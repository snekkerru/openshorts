# My Generations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a «Мои генерации» section that lists a user's AI Shorts video generations (completed history + in-progress/interrupted), backed by per-user DigitalOcean Spaces (S3) storage that survives restarts and the 1-hour disk sweep.

**Architecture:** A dependency-free `generation_history.py` holds the pure logic (metadata builder + live/S3 merge) so it's unit-testable without boto3 or FastAPI. `s3_uploader.py` gains endpoint-aware S3 I/O for a private `my-generations/{owner}/{job_id}/` prefix. `app.py` wires lifecycle hooks into the existing generation task plus list/delete endpoints. The frontend adds a nav tab, a card list, and a viewer modal.

**Tech Stack:** Python 3.11 / FastAPI / boto3 (DO Spaces via `endpoint_url`) / React 18 dashboard / pytest.

## Global Constraints

- **S3 provider is DigitalOcean Spaces** (S3-compatible). `get_s3_client()` must pass `endpoint_url` from env `AWS_S3_ENDPOINT_URL` when set; unset → unchanged AWS behavior.
- **Private history bucket** = `AWS_S3_BUCKET` (NOT the public gallery `AWS_S3_PUBLIC_BUCKET`). History is served via **presigned URLs only** (2h expiry) — never hand-built `*.amazonaws.com` URLs.
- **Per-user layout:** `my-generations/{owner}/{job_id}/{metadata.json,video.mp4,actor.png}`. `owner = await _owner_id(request) or "local"`.
- **Always recorded:** every generation writes to history regardless of the opt-in `share_to_gallery`. The existing public-gallery upload stays separate and unchanged.
- **Retention untouched:** do NOT change `JOB_RETENTION_SECONDS` or the disk sweep. Retry after 1h regenerates from the stored script.
- **Statuses:** `processing`, `completed`, `failed`, `interrupted` (S3 says `processing` but the job is absent from live `saas_jobs`).
- **Test env reality:** the pytest env lacks `boto3`; the container has `boto3` but no pytest. Keep pure logic in `generation_history.py` (stdlib only) for portable unit tests; gate S3-I/O tests with `pytest.importorskip("boto3")`. Run pure tests with the scratchpad venv; for boto3 tests, `pip install boto3` into that venv first.
- Never break generation: every history write in `app.py` is wrapped in try/except and only logs on failure.

## File Structure

```
Create:
  generation_history.py            — pure: build_meta(), merge_generations()
  tests/test_generation_history.py — pure-logic unit tests (no boto3/app import)
  tests/test_my_generations_s3.py  — s3_uploader I/O tests (importorskip boto3)
  dashboard/src/components/MyGenerationsTab.jsx — section UI + viewer modal
Modify:
  s3_uploader.py                   — endpoint_url in get_s3_client; save/list/delete history fns
  app.py                           — _history_owner, _job_belongs, lifecycle hooks, GET+DELETE endpoints
  dashboard/src/App.jsx            — nav item + render MyGenerationsTab
  dashboard/src/lib/i18n.js        — RU strings for the section
```

---

## Task 1: Endpoint-aware S3 client (DO Spaces)

**Files:**
- Modify: `s3_uploader.py:56-70` (`get_s3_client`)
- Test: `tests/test_my_generations_s3.py`

**Interfaces:**
- Produces: `get_s3_client()` unchanged signature; now honors `AWS_S3_ENDPOINT_URL`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_my_generations_s3.py
import pytest
pytest.importorskip("boto3")  # container/local only; CI env has no boto3

import s3_uploader


def test_get_s3_client_passes_endpoint_url(monkeypatch):
    captured = {}

    def fake_client(service, **kwargs):
        captured["service"] = service
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(s3_uploader.boto3, "client", fake_client)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    monkeypatch.setenv("AWS_REGION", "fra1")
    monkeypatch.setenv("AWS_S3_ENDPOINT_URL", "https://fra1.digitaloceanspaces.com")

    s3_uploader.get_s3_client()
    assert captured["kwargs"]["endpoint_url"] == "https://fra1.digitaloceanspaces.com"
    assert captured["kwargs"]["region_name"] == "fra1"


def test_get_s3_client_no_endpoint_when_unset(monkeypatch):
    captured = {}
    monkeypatch.setattr(s3_uploader.boto3, "client", lambda service, **kw: captured.update(kw) or object())
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    monkeypatch.delenv("AWS_S3_ENDPOINT_URL", raising=False)
    s3_uploader.get_s3_client()
    assert captured.get("endpoint_url") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `<venv>/bin/pip install boto3 -q && <venv>/bin/pytest tests/test_my_generations_s3.py -q`
Expected: FAIL — `endpoint_url` not present in kwargs.

- [ ] **Step 3: Implement**

Replace the client construction in `get_s3_client()`:

```python
    endpoint_url = os.environ.get('AWS_S3_ENDPOINT_URL') or None
    return boto3.client(
        's3',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        endpoint_url=endpoint_url,
        config=Config(signature_version='s3v4')
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `<venv>/bin/pytest tests/test_my_generations_s3.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add s3_uploader.py tests/test_my_generations_s3.py
git commit -m "feat(s3): honor AWS_S3_ENDPOINT_URL for DigitalOcean Spaces"
```

---

## Task 2: Pure history logic (`generation_history.py`)

**Files:**
- Create: `generation_history.py`
- Test: `tests/test_generation_history.py`

**Interfaces:**
- Produces:

```python
def build_meta(job_id: str, script: dict, video_mode: str, status: str,
               cost_estimate: dict | None = None, duration: float | int = 0,
               error: str = "") -> dict
    # Returns the metadata.json body (no timestamps — s3 layer stamps those).

def merge_generations(s3_records: list[dict], live_jobs: dict,
                      belongs: "Callable[[dict], bool]") -> list[dict]
    # s3_records: list of metadata dicts (each has job_id, status, created_at...).
    # live_jobs: the saas_jobs dict {job_id: {status, user_id, result,...}}.
    # belongs(job) -> True if the live job is the caller's.
    # Rules: live status (owned) overrides the S3 record's; an S3 'processing'
    # record whose job_id is not a live owned job becomes 'interrupted'.
    # Returns records newest-first by created_at (desc), stable.
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_generation_history.py
import generation_history as gh


def test_build_meta_pulls_script_fields():
    script = {
        "title": "T", "caption": "C", "hashtags": ["#a"],
        "full_narration": "N", "language": "ru",
        "_product_name": "P",
    }
    meta = gh.build_meta("job1", script, "premium", "processing",
                         cost_estimate={"total": 2.5}, duration=22)
    assert meta["job_id"] == "job1"
    assert meta["status"] == "processing"
    assert meta["video_mode"] == "premium"
    assert meta["title"] == "T"
    assert meta["hashtags"] == ["#a"]
    assert meta["language"] == "ru"
    assert meta["cost_estimate"] == {"total": 2.5}
    assert meta["duration"] == 22
    assert meta["product_name"] == "P"
    assert meta["error"] == ""
    # Full script is retained so Retry can regenerate faithfully (segments etc.)
    assert meta["script"] == script


def test_merge_live_status_overrides_s3():
    s3 = [{"job_id": "j1", "status": "processing", "created_at": "2026-07-24T10:00:00Z"}]
    live = {"j1": {"status": "completed", "user_id": None,
                   "result": {"video_url": "/v"}}}
    out = gh.merge_generations(s3, live, belongs=lambda job: True)
    assert out[0]["status"] == "completed"


def test_merge_marks_interrupted_when_absent_from_memory():
    s3 = [{"job_id": "j1", "status": "processing", "created_at": "2026-07-24T10:00:00Z"}]
    out = gh.merge_generations(s3, {}, belongs=lambda job: True)
    assert out[0]["status"] == "interrupted"


def test_merge_completed_s3_record_untouched():
    s3 = [{"job_id": "j1", "status": "completed", "created_at": "2026-07-24T10:00:00Z"}]
    out = gh.merge_generations(s3, {}, belongs=lambda job: True)
    assert out[0]["status"] == "completed"


def test_merge_newest_first():
    s3 = [
        {"job_id": "old", "status": "completed", "created_at": "2026-07-24T09:00:00Z"},
        {"job_id": "new", "status": "completed", "created_at": "2026-07-24T11:00:00Z"},
    ]
    out = gh.merge_generations(s3, {}, belongs=lambda job: True)
    assert [r["job_id"] for r in out] == ["new", "old"]


def test_merge_ignores_non_owned_live_job():
    # A live job that isn't the caller's must not override or appear.
    s3 = [{"job_id": "j1", "status": "processing", "created_at": "2026-07-24T10:00:00Z"}]
    live = {"j1": {"status": "completed", "user_id": "someone_else"}}
    out = gh.merge_generations(s3, live, belongs=lambda job: job.get("user_id") == "me")
    # not owned → live status ignored → S3 processing with no live owner → interrupted
    assert out[0]["status"] == "interrupted"
```

- [ ] **Step 2: Run to verify they fail**

Run: `<venv>/bin/pytest tests/test_generation_history.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'generation_history'`.

- [ ] **Step 3: Implement `generation_history.py`**

```python
"""Pure logic for the My Generations history — no boto3, no FastAPI, stdlib only,
so it unit-tests in any environment. S3 I/O lives in s3_uploader; request/owner
resolution lives in app.py."""


def build_meta(job_id, script, video_mode, status,
               cost_estimate=None, duration=0, error=""):
    return {
        "job_id": job_id,
        "status": status,
        "title": script.get("title", "Untitled"),
        "caption": script.get("caption", ""),
        "hashtags": script.get("hashtags", []),
        "full_narration": script.get("full_narration", ""),
        "language": script.get("language", "en"),
        "video_mode": video_mode,
        "duration": duration,
        "cost_estimate": cost_estimate or {},
        "product_name": script.get("_product_name", ""),
        "error": error,
        # Full original script (segments, actor_description, …) so Retry can
        # regenerate faithfully even after the disk cache is swept.
        "script": script,
    }


def merge_generations(s3_records, live_jobs, belongs):
    owned_live = {jid: j for jid, j in (live_jobs or {}).items() if belongs(j)}
    merged = []
    for rec in s3_records:
        rec = dict(rec)
        jid = rec.get("job_id")
        live = owned_live.get(jid)
        if live is not None:
            rec["status"] = live.get("status", rec.get("status"))
        elif rec.get("status") == "processing":
            rec["status"] = "interrupted"
        merged.append(rec)
    merged.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return merged
```

- [ ] **Step 4: Run to verify they pass**

Run: `<venv>/bin/pytest tests/test_generation_history.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add generation_history.py tests/test_generation_history.py
git commit -m "feat(history): pure metadata builder + live/S3 merge logic"
```

---

## Task 3: S3 history I/O (`s3_uploader.py`)

**Files:**
- Modify: `s3_uploader.py` (add three functions near `list_video_gallery`)
- Test: `tests/test_my_generations_s3.py` (extend)

**Interfaces:**
- Consumes: `get_s3_client()`, `generate_presigned_url()`, `generation_history` (unused here — meta is passed in ready).
- Produces:

```python
def save_generation_record(owner, job_id, metadata, status,
                           video_path=None, actor_image_path=None) -> bool
def list_my_generations(owner, limit=100) -> list[dict]
def delete_my_generation(owner, job_id) -> bool
```

- [ ] **Step 1: Write the failing tests (fake in-memory S3)**

```python
# append to tests/test_my_generations_s3.py
import json


class _FakeS3:
    """Minimal in-memory S3 stand-in covering the calls the history fns make."""
    def __init__(self):
        self.store = {}  # key -> bytes

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.store[Key] = Body if isinstance(Body, bytes) else Body.encode()

    def upload_file(self, filename, Bucket, Key, ExtraArgs=None):
        with open(filename, "rb") as f:
            self.store[Key] = f.read()

    def get_object(self, Bucket, Key):
        import io
        return {"Body": io.BytesIO(self.store[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.store:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://signed/{Params['Key']}"

    class _Paginator:
        def __init__(self, store): self.store = store
        def paginate(self, Bucket, Prefix):
            yield {"Contents": [{"Key": k, "LastModified": k} for k in self.store if k.startswith(Prefix)]}

    def get_paginator(self, name):
        return _FakeS3._Paginator(self.store)

    def delete_object(self, Bucket, Key):
        self.store.pop(Key, None)


def _patch_client(monkeypatch, fake):
    monkeypatch.setattr(s3_uploader, "get_s3_client", lambda: fake)
    monkeypatch.setenv("AWS_S3_BUCKET", "hist")


def test_save_and_list_roundtrip(monkeypatch, tmp_path):
    fake = _FakeS3()
    _patch_client(monkeypatch, fake)
    video = tmp_path / "v.mp4"; video.write_bytes(b"MP4")
    meta = {"job_id": "j1", "status": "processing", "title": "T"}

    assert s3_uploader.save_generation_record("local", "j1", meta, "completed",
                                              video_path=str(video)) is True
    key = "my-generations/local/j1/metadata.json"
    saved = json.loads(fake.store[key].decode())
    assert saved["status"] == "completed"
    assert saved["created_at"] and saved["updated_at"]
    assert "my-generations/local/j1/video.mp4" in fake.store

    out = s3_uploader.list_my_generations("local")
    assert len(out) == 1
    assert out[0]["job_id"] == "j1"
    assert out[0]["video_url"] == "https://signed/my-generations/local/j1/video.mp4"


def test_save_preserves_created_at(monkeypatch):
    fake = _FakeS3()
    _patch_client(monkeypatch, fake)
    s3_uploader.save_generation_record("local", "j1", {"job_id": "j1"}, "processing")
    first = json.loads(fake.store["my-generations/local/j1/metadata.json"].decode())
    s3_uploader.save_generation_record("local", "j1", {"job_id": "j1"}, "completed")
    second = json.loads(fake.store["my-generations/local/j1/metadata.json"].decode())
    assert second["created_at"] == first["created_at"]


def test_list_scoped_to_owner(monkeypatch):
    fake = _FakeS3()
    _patch_client(monkeypatch, fake)
    s3_uploader.save_generation_record("me", "j1", {"job_id": "j1"}, "completed")
    s3_uploader.save_generation_record("other", "j2", {"job_id": "j2"}, "completed")
    out = s3_uploader.list_my_generations("me")
    assert [r["job_id"] for r in out] == ["j1"]


def test_delete_removes_prefix(monkeypatch):
    fake = _FakeS3()
    _patch_client(monkeypatch, fake)
    s3_uploader.save_generation_record("local", "j1", {"job_id": "j1"}, "completed")
    assert s3_uploader.delete_my_generation("local", "j1") is True
    assert not any(k.startswith("my-generations/local/j1/") for k in fake.store)


def test_save_noop_without_client(monkeypatch):
    monkeypatch.setattr(s3_uploader, "get_s3_client", lambda: None)
    assert s3_uploader.save_generation_record("local", "j1", {}, "processing") is False
    assert s3_uploader.list_my_generations("local") == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `<venv>/bin/pytest tests/test_my_generations_s3.py -q`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement the three functions in `s3_uploader.py`**

Add after `list_video_gallery` (private bucket + presigned; note `datetime`, `json`, `logger` are already imported in this module):

```python
def _history_prefix(owner, job_id=None):
    base = f"my-generations/{owner}/"
    return f"{base}{job_id}/" if job_id else base


def save_generation_record(owner, job_id, metadata, status,
                           video_path=None, actor_image_path=None):
    """Write/overwrite the private history record for one generation."""
    import datetime
    bucket = os.environ.get('AWS_S3_BUCKET', 'my-clips-bucket')
    s3_client = get_s3_client()
    if not s3_client:
        return False
    prefix = _history_prefix(owner, job_id)
    meta_key = f"{prefix}metadata.json"
    try:
        # Preserve created_at across re-writes.
        created_at = None
        try:
            existing = s3_client.get_object(Bucket=bucket, Key=meta_key)
            created_at = json.loads(existing['Body'].read().decode()).get("created_at")
        except Exception:
            pass
        now = datetime.datetime.utcnow().isoformat() + "Z"
        record = dict(metadata)
        record["job_id"] = job_id
        record["status"] = status
        record["created_at"] = created_at or now
        record["updated_at"] = now

        if video_path and os.path.exists(video_path):
            s3_client.upload_file(video_path, bucket, f"{prefix}video.mp4",
                                  ExtraArgs={'ContentType': 'video/mp4'})
        if actor_image_path and os.path.exists(actor_image_path):
            s3_client.upload_file(actor_image_path, bucket, f"{prefix}actor.png",
                                  ExtraArgs={'ContentType': 'image/png'})

        s3_client.put_object(Bucket=bucket, Key=meta_key,
                             Body=json.dumps(record, ensure_ascii=False, indent=2).encode('utf-8'),
                             ContentType='application/json')
        return True
    except Exception as e:
        logger.error(f"save_generation_record failed for {owner}/{job_id}: {e}")
        return False


def list_my_generations(owner, limit=100):
    """List one owner's history, newest-first, with presigned video/actor URLs."""
    bucket = os.environ.get('AWS_S3_BUCKET', 'my-clips-bucket')
    s3_client = get_s3_client()
    if not s3_client:
        return []
    prefix = _history_prefix(owner)
    out = []
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        meta_objs = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                if obj['Key'].endswith('/metadata.json'):
                    meta_objs.append(obj)
        for obj in meta_objs:
            try:
                body = s3_client.get_object(Bucket=bucket, Key=obj['Key'])['Body'].read().decode()
                data = json.loads(body)
                job_prefix = obj['Key'].rsplit('metadata.json', 1)[0]
                data["video_url"] = generate_presigned_url(bucket, f"{job_prefix}video.mp4", 7200) \
                    if _object_exists(s3_client, bucket, f"{job_prefix}video.mp4") else ""
                data["actor_url"] = generate_presigned_url(bucket, f"{job_prefix}actor.png", 7200) \
                    if _object_exists(s3_client, bucket, f"{job_prefix}actor.png") else ""
                out.append(data)
                if limit and len(out) >= limit:
                    break
            except Exception as e:
                logger.error(f"read history meta {obj['Key']}: {e}")
    except Exception as e:
        logger.error(f"list_my_generations failed for {owner}: {e}")
    return out


def _object_exists(s3_client, bucket, key):
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def delete_my_generation(owner, job_id):
    bucket = os.environ.get('AWS_S3_BUCKET', 'my-clips-bucket')
    s3_client = get_s3_client()
    if not s3_client:
        return False
    prefix = _history_prefix(owner, job_id)
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                s3_client.delete_object(Bucket=bucket, Key=obj['Key'])
        return True
    except Exception as e:
        logger.error(f"delete_my_generation failed for {owner}/{job_id}: {e}")
        return False
```

Note: `list_my_generations` sorts newest-first at the app layer via `merge_generations`; here order is by S3 listing. The merge step re-sorts, so no ordering guarantee is needed from this function.

- [ ] **Step 4: Run to verify they pass**

Run: `<venv>/bin/pytest tests/test_my_generations_s3.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add s3_uploader.py tests/test_my_generations_s3.py
git commit -m "feat(s3): private per-user generation history save/list/delete"
```

---

## Task 4: Wire lifecycle hooks + endpoints (`app.py`)

**Files:**
- Modify: `app.py` — import line 25; `_history_owner`/`_job_belongs` near `_owner_id` (312-318); hooks in `run_generation` (start ~3533, completion ~3592, failure ~3638); new endpoints after `saasshorts_status` (~3662).

**Interfaces:**
- Consumes: `generation_history.build_meta/merge_generations`, `s3_uploader.save_generation_record/list_my_generations/delete_my_generation`, `_owner_id`.
- Produces: `GET /api/saasshorts/my-generations`, `DELETE /api/saasshorts/my-generations/{job_id}`.

- [ ] **Step 1: Extend imports**

`app.py:25` — add history fns:
```python
from s3_uploader import upload_job_artifacts, list_all_clips, upload_actor_to_s3, list_actor_gallery, upload_video_to_gallery, list_video_gallery, save_generation_record, list_my_generations, delete_my_generation
```
Add near the other saas imports (top of app or with `from saasshorts import`):
```python
from generation_history import build_meta, merge_generations
```

- [ ] **Step 2: Add owner/ownership helpers after `_owner_id` (app.py:318)**

```python
async def _history_owner(request):
    """Folder key for the caller's private history. Cloud → user id; self-host → 'local'."""
    return (await _owner_id(request)) or "local"


def _job_belongs_factory(request_owner):
    """Predicate for merge_generations: which live saas_jobs are the caller's.
    Self-host (BILLING off) owns all; cloud matches the stamped user_id."""
    if not BILLING_ENABLED:
        return lambda job: True
    return lambda job: job.get("user_id") == request_owner
```

- [ ] **Step 3: Record `processing` at job start**

In `saasshorts_generate`, capture `owner` once before `run_generation` is defined (it's an inner coroutine, so `owner` is captured by closure). After the `saas_jobs[job_id] = {...}` blocks (both retry and fresh paths converge before `config = {...}`), add:

```python
    owner = await _history_owner(request)
    try:
        save_generation_record(owner, job_id,
                               build_meta(job_id, req.script, req.video_mode, "processing"),
                               "processing")
    except Exception as _hist_err:
        print(f"[history] start record skipped: {_hist_err}")
```

- [ ] **Step 4: Update record on completion + failure**

In `run_generation`, in the completion branch (after `saas_jobs[job_id]["result"]` is set, ~app.py:3602), add:
```python
                try:
                    save_generation_record(
                        owner, job_id,
                        build_meta(job_id, req.script, req.video_mode, "completed",
                                   cost_estimate=result.get("cost_estimate", {}),
                                   duration=result.get("duration", 0)),
                        "completed",
                        video_path=result.get("video_path"),
                        actor_image_path=result.get("actor_image"),
                    )
                except Exception as _h:
                    log_msg(f"⚠️ History save skipped: {_h}")
```
In the failure `except` branch (~app.py:3638), add:
```python
            try:
                save_generation_record(
                    owner, job_id,
                    build_meta(job_id, req.script, req.video_mode, "failed", error=str(e)),
                    "failed")
            except Exception:
                pass
```

- [ ] **Step 5: Add list + delete endpoints after `saasshorts_status` (app.py:3662)**

```python
@app.get("/api/saasshorts/my-generations")
async def saasshorts_my_generations(request: Request):
    """List the caller's video generations (S3 history merged with live jobs)."""
    owner = await _history_owner(request)
    records = list_my_generations(owner)
    belongs = _job_belongs_factory(await _owner_id(request))
    merged = merge_generations(records, saas_jobs, belongs)
    return {"generations": merged}


@app.delete("/api/saasshorts/my-generations/{job_id}")
async def saasshorts_delete_generation(job_id: str, request: Request):
    owner = await _history_owner(request)
    ok = delete_my_generation(owner, job_id)
    # Drop from live memory too, if the caller owns it.
    if job_id in saas_jobs:
        try:
            await _assert_job_owner(request, saas_jobs[job_id])
            del saas_jobs[job_id]
        except HTTPException:
            pass
    return {"deleted": ok}
```

- [ ] **Step 6: Verify backend boots + endpoints respond**

```bash
docker restart openshorts-backend && sleep 4
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/health          # 200
curl -s http://localhost:8000/api/saasshorts/my-generations | head -c 200       # {"generations":[...]} or {"generations":[]}
```
Expected: health 200; endpoint returns a JSON object with `generations` (empty list if S3 unset — no crash).

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat(saas): record generations to history + list/delete endpoints"
```

---

## Task 5: Frontend section, cards, viewer, i18n

**Files:**
- Create: `dashboard/src/components/MyGenerationsTab.jsx`
- Modify: `dashboard/src/App.jsx` (nav item ~725-733; render ~1277); `dashboard/src/lib/i18n.js`

**Interfaces:**
- Consumes: `apiFetch` (`../lib/api`), `useI18n`. For Retry it re-posts to `/api/saasshorts/generate` with the stored script — needs `falKey`, `elevenLabsKey`, and the image-model headers, passed as props from App.jsx.

- [ ] **Step 1: Add RU strings to `lib/i18n.js`**

Add to the `RU` object:
```js
  'My Generations': 'Мои генерации',
  'No generations yet': 'Пока нет генераций',
  'Generate your first video in AI Shorts.': 'Создайте первое видео в разделе AI Shorts.',
  'in progress': 'в процессе',
  'done': 'готово',
  'error': 'ошибка',
  'interrupted': 'прервана',
  'Open': 'Открыть',
  'Download': 'Скачать',
  'Delete': 'Удалить',
  'Retry': 'Повторить',
  'Delete this generation?': 'Удалить эту генерацию?',
  'Caption': 'Описание',
  'Hashtags': 'Хэштеги',
  'Cost': 'Стоимость',
  'Close': 'Закрыть',
```

- [ ] **Step 2: Create `MyGenerationsTab.jsx`**

```jsx
import { useState, useEffect, useCallback, useRef } from 'react';
import { Loader2, Play, Download, Trash2, RefreshCw, AlertCircle, X, Copy, Check } from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useI18n } from '../contexts/I18nContext';

const STATUS_META = {
  processing:  { key: 'in progress', cls: 'badge-brass', spin: true },
  interrupted: { key: 'interrupted', cls: 'badge-warn' },
  completed:   { key: 'done',        cls: 'badge-ok' },
  failed:      { key: 'error',       cls: 'badge-danger' },
};

export default function MyGenerationsTab({ falKey, elevenLabsKey, falImageHeaders = {} }) {
  const { t } = useI18n();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [viewing, setViewing] = useState(null); // record for the viewer modal
  const timer = useRef(null);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/api/saasshorts/my-generations');
      const data = await res.json().catch(() => ({}));
      setItems(data.generations || []);
    } catch { /* keep prior list */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Poll every 5s while anything is active.
  useEffect(() => {
    const active = items.some((r) => r.status === 'processing');
    clearInterval(timer.current);
    if (active) timer.current = setInterval(load, 5000);
    return () => clearInterval(timer.current);
  }, [items, load]);

  const remove = async (jobId) => {
    if (!window.confirm(t('Delete this generation?'))) return;
    await apiFetch(`/api/saasshorts/my-generations/${jobId}`, { method: 'DELETE' });
    setItems((prev) => prev.filter((r) => r.job_id !== jobId));
  };

  const retry = async (rec) => {
    // rec.script is the full original script (segments, actor_description, …).
    await apiFetch('/api/saasshorts/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Fal-Key': falKey, 'X-ElevenLabs-Key': elevenLabsKey, ...falImageHeaders },
      body: JSON.stringify({ script: rec.script || rec, video_mode: rec.video_mode, retry_job_id: rec.job_id }),
    });
    load();
  };

  return (
    <div className="h-full overflow-y-auto custom-scrollbar p-4 sm:p-6 md:p-10 animate-fade">
      <div className="max-w-5xl mx-auto">
        <p className="eyebrow mb-1.5">03 · {t('My Generations')}</p>
        <h1 className="font-display text-2xl md:text-3xl text-ink mb-6">{t('My Generations')}</h1>

        {loading ? (
          <div className="flex items-center gap-2 text-muted text-sm"><Loader2 size={16} className="animate-spin" /> …</div>
        ) : items.length === 0 ? (
          <div className="card p-8 text-center">
            <p className="text-ink font-medium mb-1">{t('No generations yet')}</p>
            <p className="text-xs text-muted">{t('Generate your first video in AI Shorts.')}</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {items.map((rec) => {
              const s = STATUS_META[rec.status] || STATUS_META.completed;
              return (
                <div key={rec.job_id} className="card p-4 flex flex-col gap-3">
                  <div className="aspect-[9/16] rounded-input overflow-hidden bg-paper3 relative">
                    {rec.actor_url
                      ? <img src={rec.actor_url} alt="" className="w-full h-full object-cover" />
                      : <div className="w-full h-full flex items-center justify-center text-muted"><Play size={24} /></div>}
                    <span className={`absolute top-2 left-2 ${s.cls} flex items-center gap-1`}>
                      {s.spin && <Loader2 size={10} className="animate-spin" />}{t(s.key)}
                    </span>
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm text-ink truncate">{rec.title || '—'}</p>
                    <p className="readout mt-0.5">
                      {rec.created_at ? new Date(rec.created_at).toLocaleString() : ''}
                      {rec.cost_estimate?.total ? ` · $${rec.cost_estimate.total}` : ''}
                    </p>
                    {rec.status === 'failed' && rec.error && (
                      <p className="text-xs text-danger mt-1 flex items-start gap-1"><AlertCircle size={12} className="shrink-0 mt-0.5" />{rec.error}</p>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2 mt-auto">
                    {rec.status === 'completed' && rec.video_url && (
                      <>
                        <button onClick={() => setViewing(rec)} className="btn-quiet py-1.5 px-3 text-xs"><Play size={12} /> {t('Open')}</button>
                        <a href={rec.video_url} download className="btn-quiet py-1.5 px-3 text-xs"><Download size={12} /> {t('Download')}</a>
                      </>
                    )}
                    {(rec.status === 'failed' || rec.status === 'interrupted') && (
                      <button onClick={() => retry(rec)} className="btn-quiet py-1.5 px-3 text-xs"><RefreshCw size={12} /> {t('Retry')}</button>
                    )}
                    <button onClick={() => remove(rec.job_id)} className="btn-danger py-1.5 px-3 text-xs"><Trash2 size={12} /> {t('Delete')}</button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {viewing && <ViewerModal rec={viewing} onClose={() => setViewing(null)} t={t} />}
    </div>
  );
}

function ViewerModal({ rec, onClose, t }) {
  const [copied, setCopied] = useState('');
  const copy = (field, text) => { navigator.clipboard.writeText(text || ''); setCopied(field); setTimeout(() => setCopied(''), 1500); };
  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={onClose}>
      <div className="card max-w-md w-full max-h-[90vh] overflow-y-auto custom-scrollbar p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-display text-lg text-ink truncate">{rec.title}</h2>
          <button onClick={onClose} className="text-muted hover:text-ink"><X size={18} /></button>
        </div>
        <video src={rec.video_url} controls className="w-full rounded-input bg-black mb-4" />
        {rec.caption && (
          <div className="mb-3">
            <div className="flex items-center justify-between"><span className="eyebrow">{t('Caption')}</span>
              <button onClick={() => copy('cap', rec.caption)} className="btn-quiet py-1 px-2 text-xs">{copied === 'cap' ? <Check size={11} /> : <Copy size={11} />}</button></div>
            <p className="text-xs text-ink2 mt-1 leading-relaxed">{rec.caption}</p>
          </div>
        )}
        {rec.hashtags?.length > 0 && (
          <div className="mb-3">
            <div className="flex items-center justify-between"><span className="eyebrow">{t('Hashtags')}</span>
              <button onClick={() => copy('tags', rec.hashtags.join(' '))} className="btn-quiet py-1 px-2 text-xs">{copied === 'tags' ? <Check size={11} /> : <Copy size={11} />}</button></div>
            <p className="text-xs text-brass mt-1">{rec.hashtags.join(' ')}</p>
          </div>
        )}
        <div className="flex items-center justify-between text-xs text-muted">
          <span>{t('Cost')}: ${rec.cost_estimate?.total ?? '—'}</span>
          <a href={rec.video_url} download className="btn-quiet py-1.5 px-3"><Download size={12} /> {t('Download')}</a>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Wire nav + render in `App.jsx`**

Import the component near other tab imports:
```js
import MyGenerationsTab from './components/MyGenerationsTab';
```
In `navItems` (App.jsx ~726-732) add between saasshorts and settings, and renumber:
```js
      { id: 'saasshorts', ord: '01', icon: Sparkles, label: 'AI Shorts', byok: true },
      { id: 'my-generations', ord: '02', icon: History, label: 'My Generations' },
      { id: 'settings', ord: '03', icon: Settings, label: 'Settings' },
```
Update the restore whitelist added earlier (`['saasshorts', 'settings']`) to include `'my-generations'`. Render after the saasshorts block (~1277):
```jsx
          {activeTab === 'my-generations' && (
            <MyGenerationsTab
              falKey={falKey}
              elevenLabsKey={elevenLabsKey}
              falImageHeaders={{
                ...(falImageModel ? { 'X-Fal-Image-Model': falImageModel } : {}),
                ...(falImageModel === 'openai/gpt-image-2' && falImageQuality ? { 'X-Fal-Image-Quality': falImageQuality } : {}),
                ...(falImageModel === 'fal-ai/nano-banana-2' && falImageAspect ? { 'X-Fal-Image-Aspect': falImageAspect } : {}),
                ...(falImageModel === 'fal-ai/nano-banana-2' && falImageResolution ? { 'X-Fal-Image-Resolution': falImageResolution } : {}),
              }}
            />
          )}
```

- [ ] **Step 4: Lint**

Run: `docker exec openshorts-frontend npm run lint 2>&1 | tail -5`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/MyGenerationsTab.jsx dashboard/src/App.jsx dashboard/src/lib/i18n.js
git commit -m "feat(ui): My Generations section with viewer, retry and delete"
```

---

## Task 6: End-to-end verification

**Files:** none (verification only).

- [ ] **Step 1: Full backend test suite**

Run: `<venv>/bin/pytest tests/ -q`  (with boto3 installed in the venv)
Expected: all pass (existing 132 + new history tests), 2 skipped.

- [ ] **Step 2: Live smoke (needs S3 env + fal/ElevenLabs keys configured)**

- Open the app → nav shows «Мои генерации» (RU) / "My Generations" (EN) between AI Shorts and Settings.
- Empty state renders when history is empty.
- Start a generation in AI Shorts; within ~5s the item appears under «Мои генерации» as `в процессе` (processing) — confirms start-record + polling.
- On completion the card flips to `готово` with a thumbnail; **Open** plays the video from the presigned URL; **Download** saves the mp4.
- **Delete** removes the card and the S3 objects (re-list shows it gone).
- Restart the backend mid-generation, reload the section → the item shows `прервана` (interrupted) with **Retry**; Retry re-submits and it returns to processing.

- [ ] **Step 3: Confirm no regression to generation**

With S3 env UNSET, run a generation end-to-end: it must still complete (history writes are no-ops, logged, never fatal). The section shows the empty state.

---

## Self-Review Notes

- **Spec coverage:** DO Spaces endpoint (T1), per-user prefix + presigned (T3), always-record lifecycle (T4), list/delete + merge/interrupted (T2+T4), section/viewer/retry/delete/i18n (T5), graceful S3-absent degradation (T3 no-op + T6.3). All spec sections map to a task.
- **Type consistency:** `save_generation_record(owner, job_id, metadata, status, video_path, actor_image_path)`, `list_my_generations(owner, limit)`, `delete_my_generation(owner, job_id)`, `build_meta(job_id, script, video_mode, status, ...)`, `merge_generations(s3_records, live_jobs, belongs)` — identical across tasks and call sites.
- **Test env split:** pure logic (T2) runs anywhere; S3 I/O (T1, T3) uses `importorskip("boto3")` + a fake client; `app.py` is exercised via live curl (T4.6), not import, matching the repo's convention of not importing heavy modules in CI.
- **Deliberate scope limits:** no retention change, no gallery change, no migration of the 3 old on-disk videos, no social publish in the viewer — all per spec Out of Scope.
