# B-roll Source Selection + Pre-Generation Timeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user, per b-roll slot, choose AI generation (editable prompt), their own image (Ken Burns), or their own video (no Ken Burns, optional audio mix), and show a video-editor-style timeline on the pre-generation review screen.

**Architecture:** Extend b-roll script segments with optional fields (`broll_source`, `broll_asset_url`, `broll_mute_audio`). The whole `script` dict already flows to `POST /api/saasshorts/generate`, so new fields reach the backend for free. Backend branches per slot in `generate_full_video` Step 4 and mixes audio in `composite_video`. A new `POST /api/saasshorts/broll-upload` stores user assets. Frontend adds a timeline + per-slot editor on step 2. Follows the repo's testing style: pure helpers are TDD'd; FFmpeg/endpoints/React are verified via lint + manual runs.

**Tech Stack:** Python 3.11, FastAPI, FFmpeg (subprocess), fal.ai, React 18 + Vite + Tailwind, pytest.

## Global Constraints

- New segment fields are OPTIONAL and backward-compatible: a segment missing `broll_source` is treated as `"ai"`. Old all-AI scripts must render byte-for-byte unchanged.
- `broll_source` ∈ `{"ai", "image", "video"}`; default `"ai"`.
- `broll_mute_audio` default `true`. `true` = voiceover only. `false` = **mix** clip audio TOGETHER WITH voiceover (both audible). Applies to `video` slots only.
- The slot window (`start`/`end`) is authoritative and manually editable. Windows must be non-overlapping and increasing.
- Only `broll_source=="ai"` slots incur fal/Kling b-roll cost; user assets are free.
- Uploaded assets: images ≤ 25 MB, videos ≤ 100 MB. Stored under `OUTPUT_DIR/broll_uploads/`.
- Out of scope: adding/removing slots, generating an image preview from the prompt, changing the "1 vs 2 inserts" LLM behavior.
- Run backend tests with `python -m pytest`. Run frontend lint with `cd dashboard && npm run lint` (strict, `--max-warnings 0`).

---

### Task 1: Per-slot classification helper (`classify_broll_slot`)

Pure function that turns a raw script segment into a normalized slot decision. This is the single source of truth every backend branch reads.

**Files:**
- Modify: `saasshorts.py` (add function near the other b-roll helpers, above `generate_broll` at line 1010)
- Test: `tests/test_broll_slots.py` (create)

**Interfaces:**
- Produces: `classify_broll_slot(seg: dict) -> dict` returning
  `{"source": "ai"|"image"|"video", "asset_path": str|None, "audio_mode": "voiceover"|"mix", "prompt": str|None}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_broll_slots.py
from saasshorts import classify_broll_slot


def _seg(**kw):
    base = {"visual": "broll", "broll_prompt": "a cat", "start": 5, "end": 9}
    base.update(kw)
    return base


class TestClassifyBrollSlot:
    def test_missing_source_defaults_to_ai(self):
        r = classify_broll_slot(_seg())
        assert r["source"] == "ai"
        assert r["prompt"] == "a cat"
        assert r["asset_path"] is None
        assert r["audio_mode"] == "voiceover"

    def test_invalid_source_falls_back_to_ai(self):
        assert classify_broll_slot(_seg(broll_source="banana"))["source"] == "ai"

    def test_image_source_uses_asset_path(self):
        r = classify_broll_slot(_seg(broll_source="image", broll_asset_path="/x/y.png"))
        assert r["source"] == "image"
        assert r["asset_path"] == "/x/y.png"
        assert r["audio_mode"] == "voiceover"  # images never mix

    def test_image_without_asset_falls_back_to_ai(self):
        # No usable file -> don't silently render nothing; fall back to AI.
        assert classify_broll_slot(_seg(broll_source="image", broll_asset_path=None))["source"] == "ai"

    def test_video_mute_true_is_voiceover(self):
        r = classify_broll_slot(_seg(broll_source="video", broll_asset_path="/x/y.mp4", broll_mute_audio=True))
        assert r["source"] == "video"
        assert r["audio_mode"] == "voiceover"

    def test_video_mute_false_is_mix(self):
        r = classify_broll_slot(_seg(broll_source="video", broll_asset_path="/x/y.mp4", broll_mute_audio=False))
        assert r["audio_mode"] == "mix"

    def test_video_mute_defaults_true(self):
        r = classify_broll_slot(_seg(broll_source="video", broll_asset_path="/x/y.mp4"))
        assert r["audio_mode"] == "voiceover"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_broll_slots.py -v`
Expected: FAIL with `ImportError: cannot import name 'classify_broll_slot'`

- [ ] **Step 3: Write minimal implementation**

```python
# saasshorts.py — add above generate_broll (line ~1010)
def classify_broll_slot(seg: dict) -> dict:
    """Normalize a b-roll script segment into a slot decision.

    Returns source ("ai"|"image"|"video"), the local asset_path (image/video
    only), audio_mode ("voiceover"|"mix"), and the prompt (ai only). Unknown
    sources, or image/video slots missing a usable asset_path, fall back to AI.
    """
    source = seg.get("broll_source") or "ai"
    asset_path = seg.get("broll_asset_path")
    if source not in ("ai", "image", "video"):
        source = "ai"
    if source in ("image", "video") and not asset_path:
        source = "ai"

    if source == "video":
        # mute default True -> voiceover only; False -> mix clip audio in too.
        mute = seg.get("broll_mute_audio", True)
        audio_mode = "voiceover" if mute else "mix"
    else:
        audio_mode = "voiceover"

    return {
        "source": source,
        "asset_path": asset_path if source in ("image", "video") else None,
        "audio_mode": audio_mode,
        "prompt": seg.get("broll_prompt") if source == "ai" else None,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_broll_slots.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add saasshorts.py tests/test_broll_slots.py
git commit -m "feat(saas): classify_broll_slot helper for per-slot b-roll source"
```

---

### Task 2: Extract Ken Burns command builder + image source path

Split `generate_broll` so the Ken Burns FFmpeg stage is reusable for a user-supplied image (skipping fal generation). TDD the pure command builder; the file-producing wrappers are verified by the existing pipeline.

**Files:**
- Modify: `saasshorts.py:1010-1076` (`generate_broll`)
- Test: `tests/test_broll_slots.py` (append)

**Interfaces:**
- Consumes: `resolve_image_model`, `_build_image_input`, `_fal_run`, `video_encode_args`, `DELIVERY` (existing).
- Produces:
  - `build_ken_burns_cmd(img_path: str, output_path: str, dur_secs: int) -> list[str]` — pure FFmpeg arg list.
  - `ken_burns_clip(img_path: str, output_path: str, dur_secs: int) -> str` — runs the cmd, returns output_path.
  - `generate_broll(prompt, fal_key, output_path, duration="5", image_model=None, image_opts=None) -> str` — unchanged signature; now fetches the fal image then calls `ken_burns_clip`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_broll_slots.py — append
from saasshorts import build_ken_burns_cmd


class TestKenBurnsCmd:
    def test_cmd_loops_image_and_sets_duration(self):
        cmd = build_ken_burns_cmd("/tmp/in.png", "/tmp/out.mp4", 5)
        assert cmd[0] == "ffmpeg"
        assert "-loop" in cmd and "1" in cmd
        assert "/tmp/in.png" in cmd
        assert cmd[-1] == "/tmp/out.mp4"
        # duration honored
        i = cmd.index("-t")
        assert cmd[i + 1] == "5"

    def test_cmd_contains_zoompan_ken_burns(self):
        cmd = build_ken_burns_cmd("/tmp/in.png", "/tmp/out.mp4", 4)
        vf = cmd[cmd.index("-vf") + 1]
        assert "zoompan" in vf
        assert "s=1080x1920" in vf
        # 4s * 30fps = 120 frames drives the zoom denominator
        assert "120" in vf
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_broll_slots.py::TestKenBurnsCmd -v`
Expected: FAIL with `ImportError: cannot import name 'build_ken_burns_cmd'`

- [ ] **Step 3: Refactor `generate_broll` and add the two helpers**

Replace `saasshorts.py:1010-1076` with:

```python
def build_ken_burns_cmd(img_path: str, output_path: str, dur_secs: int) -> list:
    """Build the FFmpeg command that turns a still image into a Ken Burns clip."""
    fps = 30
    total_frames = dur_secs * fps
    zoompan_filter = (
        f"scale=2160:3840,"
        f"zoompan=z='1+0.15*on/{total_frames}':"
        f"x='iw/2-(iw/zoom/2)+10*on/{total_frames}':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:s=1080x1920:fps={fps},"
        f"setsar=1"
    )
    return [
        "ffmpeg", "-y",
        "-loop", "1", "-i", img_path,
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-vf", zoompan_filter,
        "-t", str(dur_secs),
        "-map", "0:v", "-map", "1:a",
        *video_encode_args(DELIVERY),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]


def ken_burns_clip(img_path: str, output_path: str, dur_secs: int) -> str:
    """Render a Ken Burns clip from an existing image file."""
    subprocess.run(build_ken_burns_cmd(img_path, output_path, dur_secs), check=True, capture_output=True)
    print(f"[SaaSShorts] ✅ B-roll (Ken Burns): {output_path}")
    return output_path


def generate_broll(
    prompt: str, fal_key: str, output_path: str, duration: str = "5", image_model: str = None, image_opts: dict = None
) -> str:
    """Generate b-roll: a still image (fal.ai) + Ken Burns zoom via FFmpeg."""
    model_id = resolve_image_model(image_model)
    print(f"[SaaSShorts] 🎬 Generating b-roll image ({model_id}) + Ken Burns effect...")

    dur_secs = int(duration)
    img_path = output_path.replace(".mp4", "_img.png")

    broll_prompt = f"{prompt}. Cinematic, shallow depth of field, professional photography."
    result = _fal_run(
        model_id,
        _build_image_input(model_id, broll_prompt, image_opts),
        fal_key,
        timeout=300,
    )

    images = result.get("images") or result.get("output", [])
    if not images:
        raise Exception(f"No images in b-roll result: {list(result.keys())}")
    img_url = images[0]["url"] if isinstance(images[0], dict) else images[0]

    with httpx.Client(timeout=60.0) as client:
        img_resp = client.get(img_url)
        with open(img_path, "wb") as f:
            f.write(img_resp.content)

    ken_burns_clip(img_path, output_path, dur_secs)

    if os.path.exists(img_path):
        os.remove(img_path)
    return output_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_broll_slots.py -v`
Expected: PASS (all TestClassifyBrollSlot + TestKenBurnsCmd)

- [ ] **Step 5: Commit**

```bash
git add saasshorts.py tests/test_broll_slots.py
git commit -m "refactor(saas): extract ken_burns_clip so user images reuse the effect"
```

---

### Task 3: Video slot preparation helper (`prepare_broll_video`)

Copy/normalize a user video into the slot path, guaranteeing an audio stream exists so `composite_video` can safely reference `[idx:a]` in both voiceover and mix modes. TDD the pure command builder.

**Files:**
- Modify: `saasshorts.py` (add near `ken_burns_clip`)
- Test: `tests/test_broll_slots.py` (append)

**Interfaces:**
- Produces:
  - `_has_audio_stream(path: str) -> bool` — ffprobe check for an audio stream.
  - `build_prepare_video_cmd(src_path: str, output_path: str, has_audio: bool) -> list[str]` — pure builder; maps real audio when present, else a silent `anullsrc` track.
  - `prepare_broll_video(src_path: str, output_path: str) -> str` — probes then runs it, returns output_path.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_broll_slots.py — append
from saasshorts import build_prepare_video_cmd


class TestPrepareVideoCmd:
    def test_silent_fallback_when_source_has_no_audio(self):
        cmd = build_prepare_video_cmd("/tmp/in.mp4", "/tmp/slot.mp4", has_audio=False)
        assert cmd[0] == "ffmpeg"
        assert "/tmp/in.mp4" in cmd
        assert cmd[-1] == "/tmp/slot.mp4"
        # a silent anullsrc input guarantees an audio stream even if src has none
        assert "anullsrc=r=44100:cl=stereo" in cmd
        assert "1:a" in cmd          # audio mapped from the silent source
        assert "-shortest" in cmd

    def test_uses_real_audio_when_present(self):
        cmd = build_prepare_video_cmd("/tmp/in.mp4", "/tmp/slot.mp4", has_audio=True)
        assert "anullsrc=r=44100:cl=stereo" not in cmd
        assert "0:a" in cmd          # audio mapped from the real input
        assert "0:v" in cmd
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_broll_slots.py::TestPrepareVideoCmd -v`
Expected: FAIL with `ImportError: cannot import name 'build_prepare_video_cmd'`

- [ ] **Step 3: Write the implementation**

FFmpeg cannot conditionally pick "real audio else silent" via `-map` alone, so probe once and branch the map list.

```python
# saasshorts.py — add after ken_burns_clip
def _has_audio_stream(path: str) -> bool:
    """True if the media file has at least one audio stream (ffprobe)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", path],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        return bool(out)
    except Exception:
        return False


def build_prepare_video_cmd(src_path: str, output_path: str, has_audio: bool) -> list:
    """Normalize a user b-roll video, guaranteeing a mappable audio stream.

    Maps the real audio when present; otherwise adds a silent anullsrc track so
    the compositor's atrim/amix never fails on an audioless clip.
    """
    cmd = ["ffmpeg", "-y", "-i", src_path]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += [
        "-map", "0:v",
        "-map", ("0:a" if has_audio else "1:a"),
        *video_encode_args(DELIVERY),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]
    return cmd


def prepare_broll_video(src_path: str, output_path: str) -> str:
    """Normalize a user-supplied b-roll video into the slot clip path."""
    cmd = build_prepare_video_cmd(src_path, output_path, _has_audio_stream(src_path))
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"[SaaSShorts] ✅ B-roll (user video): {output_path}")
    return output_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_broll_slots.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add saasshorts.py tests/test_broll_slots.py
git commit -m "feat(saas): prepare_broll_video guarantees an audio stream for user clips"
```

---

### Task 4: Branch Step 4 of `generate_full_video` per slot

Wire the three sources into the generation loop, carrying `audio_mode` onto each runtime clip dict.

**Files:**
- Modify: `saasshorts.py:1447-1494` (Step 4 b-roll generation)
- Verify: no unit test (subprocess/fal); regression via Task 5 filter test + manual run.

**Interfaces:**
- Consumes: `classify_broll_slot`, `ken_burns_clip`, `prepare_broll_video`, `generate_broll`.
- Produces: `broll_clips` items now shaped `{"path", "start", "end", "audio_mode"}`.

- [ ] **Step 1: Rewrite Step 4**

Replace the body at `saasshorts.py:1447-1494` with:

```python
    # ── Step 4: Generate/prepare b-roll clips (per-slot source) ──
    broll_segments = [
        seg for seg in script.get("segments", [])
        if seg.get("visual") == "broll" and (
            seg.get("broll_prompt") or seg.get("broll_asset_path")
        )
    ]

    broll_clips = []
    if broll_segments:
        to_build = []
        for i, seg in enumerate(broll_segments):
            slot = classify_broll_slot(seg)
            broll_path = os.path.join(output_dir, f"{title_slug}_broll_{i}.mp4")
            if _exists(broll_path):
                broll_clips.append({
                    "path": broll_path, "start": seg["start"], "end": seg["end"],
                    "audio_mode": slot["audio_mode"],
                })
                log(f"  ✅ B-roll {i} cached, skipping.")
            else:
                to_build.append((i, seg, slot, broll_path))

        if to_build:
            log(f"[4/6] Preparing {len(to_build)} b-roll clip(s)...")
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {}
                for i, seg, slot, broll_path in to_build:
                    if slot["source"] == "image":
                        fut = executor.submit(ken_burns_clip, slot["asset_path"], broll_path,
                                              int(seg["end"] - seg["start"]) or 5)
                    elif slot["source"] == "video":
                        fut = executor.submit(prepare_broll_video, slot["asset_path"], broll_path)
                    else:
                        fut = executor.submit(generate_broll, slot["prompt"], fal_key, broll_path,
                                              "5", image_model, image_opts)
                    futures[fut] = {"seg": seg, "slot": slot, "path": broll_path}

                for fut in as_completed(futures):
                    info = futures[fut]
                    try:
                        path = fut.result()
                        broll_clips.append({
                            "path": path, "start": info["seg"]["start"], "end": info["seg"]["end"],
                            "audio_mode": info["slot"]["audio_mode"],
                        })
                        log(f"  ✅ B-roll clip ready: {os.path.basename(path)}")
                    except Exception as e:
                        log(f"  ⚠️ B-roll failed (skipping): {e}")
        else:
            log("[4/6] ✅ All b-roll cached, skipping.")
    else:
        log("[4/6] No b-roll segments in script, skipping.")
```

- [ ] **Step 2: Sanity-check import/parse**

Run: `python -c "import saasshorts"`
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add saasshorts.py
git commit -m "feat(saas): branch b-roll Step 4 across ai/image/video sources"
```

---

### Task 5: Extract composite filter builder + audio mix

Extract the `filter_complex` string assembly into a pure, testable function and add the `amix` path for `audio_mode=="mix"`.

**Files:**
- Modify: `saasshorts.py:1209-1340` (`composite_video`)
- Test: `tests/test_broll_slots.py` (append)

**Interfaces:**
- Consumes: runtime `broll_clips` with `audio_mode`.
- Produces: `build_composite_filter(segments: list, sub_filter: str) -> str`, where each segment is
  `{"type": "th", "start", "end"}` or `{"type": "broll", "index": int, "start", "end", "duration", "audio_mode"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_broll_slots.py — append
from saasshorts import build_composite_filter


def _th(j_start, j_end):
    return {"type": "th", "start": j_start, "end": j_end}


def _broll(index, start, end, audio_mode):
    return {"type": "broll", "index": index, "start": start, "end": end,
            "duration": end - start, "audio_mode": audio_mode}


class TestCompositeFilter:
    def test_voiceover_broll_uses_talking_head_audio_only(self):
        segs = [_th(0, 5), _broll(0, 5, 9, "voiceover"), _th(9, 12)]
        f = build_composite_filter(segs, "ass='subs.ass'")
        # b-roll video from input 1, audio from talking head [0:a], no amix
        assert "[1:v]trim=start=0:end=4.000" in f
        assert "[0:a]atrim=start=5.000:end=9.000" in f
        assert "amix" not in f
        assert "concat=n=3:v=1:a=1[outv][outa]" in f
        assert "[outv]ass='subs.ass'[finalv]" in f

    def test_mix_broll_amixes_clip_and_voiceover(self):
        segs = [_th(0, 5), _broll(0, 5, 9, "mix"), _th(9, 12)]
        f = build_composite_filter(segs, "ass='subs.ass'")
        # both the clip audio [1:a] and the voiceover [0:a] feed an amix
        assert "amix=inputs=2" in f
        assert "[1:a]atrim=start=0:end=4.000" in f
        assert "[0:a]atrim=start=5.000:end=9.000" in f
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_broll_slots.py::TestCompositeFilter -v`
Expected: FAIL with `ImportError: cannot import name 'build_composite_filter'`

- [ ] **Step 3: Add `build_composite_filter` and call it from `composite_video`**

Add this function above `composite_video` (before `saasshorts.py:1209`):

```python
def build_composite_filter(segments: list, sub_filter: str) -> str:
    """Assemble the FFmpeg filter_complex for the talking-head + b-roll timeline.

    Talking-head segments trim [0:v]/[0:a]. Voiceover b-roll segments take the
    clip video [idx:v] but keep [0:a]. Mix b-roll segments amix the clip audio
    [idx:a] together with the voiceover [0:a] so both are audible.
    """
    norm = ("scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1")
    filter_parts = []
    concat_parts = []

    for j, seg in enumerate(segments):
        if seg["type"] == "th":
            filter_parts.append(
                f"[0:v]trim=start={seg['start']:.3f}:end={seg['end']:.3f},setpts=PTS-STARTPTS,{norm}[tv{j}]")
            filter_parts.append(
                f"[0:a]atrim=start={seg['start']:.3f}:end={seg['end']:.3f},asetpts=PTS-STARTPTS[ta{j}]")
            concat_parts.append(f"[tv{j}][ta{j}]")
        else:
            idx = seg["index"] + 1
            dur = seg["duration"]
            filter_parts.append(
                f"[{idx}:v]trim=start=0:end={dur:.3f},setpts=PTS-STARTPTS,{norm}[bv{j}]")
            if seg.get("audio_mode") == "mix":
                filter_parts.append(
                    f"[0:a]atrim=start={seg['start']:.3f}:end={seg['end']:.3f},asetpts=PTS-STARTPTS[voa{j}]")
                filter_parts.append(
                    f"[{idx}:a]atrim=start=0:end={dur:.3f},asetpts=PTS-STARTPTS[cla{j}]")
                filter_parts.append(
                    f"[voa{j}][cla{j}]amix=inputs=2:duration=first:dropout_transition=0,dynaudnorm[ba{j}]")
            else:
                filter_parts.append(
                    f"[0:a]atrim=start={seg['start']:.3f}:end={seg['end']:.3f},asetpts=PTS-STARTPTS[ba{j}]")
            concat_parts.append(f"[bv{j}][ba{j}]")

    n = len(segments)
    filter_parts.append(f"{''.join(concat_parts)}concat=n={n}:v=1:a=1[outv][outa]")
    filter_parts.append(f"[outv]{sub_filter}[finalv]")
    return ";".join(filter_parts)
```

Then in `composite_video`, carry `audio_mode` onto the built broll segment (in the loop at `saasshorts.py:1264-1280` add `"audio_mode": clip.get("audio_mode", "voiceover")` to the appended broll dict) and replace the inline `filter_parts`/`concat_parts` assembly (`saasshorts.py:1290-1324`) with:

```python
    filter_str = build_composite_filter(segments, sub_filter)
```

Leave the `inputs` list, `cmd`, and `subprocess.run` below it unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_broll_slots.py -v`
Expected: PASS (all classes)

- [ ] **Step 5: Commit**

```bash
git add saasshorts.py tests/test_broll_slots.py
git commit -m "feat(saas): composite audio mix for user-video b-roll slots"
```

---

### Task 6: Cost counts AI slots only

**Files:**
- Modify: `saasshorts.py:1508-1535` (cost estimate)
- Test: `tests/test_broll_slots.py` (append)

**Interfaces:**
- Produces: `count_ai_broll(broll_clips: list, segments: list) -> int` — number of rendered clips whose slot source is AI.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_broll_slots.py — append
from saasshorts import count_ai_broll


class TestCountAiBroll:
    def test_counts_only_ai_rendered_clips(self):
        segments = [
            {"visual": "broll", "broll_prompt": "x", "start": 5, "end": 9, "broll_source": "ai"},
            {"visual": "broll", "broll_prompt": "y", "start": 16, "end": 21,
             "broll_source": "video", "broll_asset_path": "/a.mp4"},
        ]
        broll_clips = [{"path": "/b0.mp4"}, {"path": "/b1.mp4"}]  # both rendered
        assert count_ai_broll(broll_clips, segments) == 1

    def test_zero_when_all_user_assets(self):
        segments = [{"visual": "broll", "start": 5, "end": 9, "broll_source": "image",
                     "broll_asset_path": "/a.png"}]
        assert count_ai_broll([{"path": "/b0.mp4"}], segments) == 1 - 1  # == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_broll_slots.py::TestCountAiBroll -v`
Expected: FAIL with `ImportError: cannot import name 'count_ai_broll'`

- [ ] **Step 3: Implement and wire into the cost block**

Add near `classify_broll_slot`:

```python
def count_ai_broll(broll_clips: list, segments: list) -> int:
    """How many rendered b-roll clips came from AI generation (billable)."""
    ai_slots = sum(
        1 for seg in segments
        if seg.get("visual") == "broll" and (seg.get("broll_prompt") or seg.get("broll_asset_path"))
        and classify_broll_slot(seg)["source"] == "ai"
    )
    return min(len(broll_clips), ai_slots)
```

In the cost block (`saasshorts.py:1508-1535`) compute once before the branches:

```python
    ai_broll_n = count_ai_broll(broll_clips, script.get("segments", []))
```

and replace each `len(broll_clips)` inside the `broll_flux` / `broll_kling` cost lines with `ai_broll_n`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_broll_slots.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add saasshorts.py tests/test_broll_slots.py
git commit -m "feat(saas): bill only AI b-roll slots, not user-supplied assets"
```

---

### Task 7: `broll-upload` endpoint + generate resolves asset urls

**Files:**
- Modify: `app.py` (add endpoint after `saasshorts_actor_upload` ~line 3145; resolve urls in `saasshorts_generate` near the `selected_actor_url` block `app.py:3575-3597`)
- Test: `tests/test_broll_upload.py` (create)

**Interfaces:**
- Consumes: `_safe_under`, `OUTPUT_DIR`, `require_managed_entitlement` (existing).
- Produces:
  - `validate_broll_upload(content_type: str, size: int) -> tuple[str, str]` in `app.py` — returns `(kind, ext)` for a valid upload, raises `HTTPException` otherwise. `kind` ∈ `{"image","video"}`.
  - `POST /api/saasshorts/broll-upload` returning `{"url": "/videos/broll_uploads/{name}", "kind": kind}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_broll_upload.py
import pytest
from fastapi import HTTPException

from app import validate_broll_upload


class TestValidateBrollUpload:
    def test_accepts_image(self):
        assert validate_broll_upload("image/png", 1_000_000) == ("image", "png")

    def test_accepts_video(self):
        assert validate_broll_upload("video/mp4", 5_000_000) == ("video", "mp4")

    def test_rejects_other_types(self):
        with pytest.raises(HTTPException) as e:
            validate_broll_upload("application/pdf", 100)
        assert e.value.status_code == 400

    def test_rejects_oversize_image(self):
        with pytest.raises(HTTPException) as e:
            validate_broll_upload("image/png", 26 * 1024 * 1024)
        assert e.value.status_code == 413

    def test_rejects_oversize_video(self):
        with pytest.raises(HTTPException) as e:
            validate_broll_upload("video/mp4", 101 * 1024 * 1024)
        assert e.value.status_code == 413
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_broll_upload.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate_broll_upload'`

- [ ] **Step 3: Implement helper + endpoint + url resolution**

Add the pure validator near the other SaaSShorts helpers in `app.py`:

```python
BROLL_IMAGE_MAX_BYTES = 25 * 1024 * 1024
BROLL_VIDEO_MAX_BYTES = 100 * 1024 * 1024
_BROLL_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
              "video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm"}


def validate_broll_upload(content_type: str, size: int):
    """Validate a b-roll upload's type and size; return (kind, ext) or raise."""
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        kind, cap = "image", BROLL_IMAGE_MAX_BYTES
    elif ct.startswith("video/"):
        kind, cap = "video", BROLL_VIDEO_MAX_BYTES
    else:
        raise HTTPException(status_code=400, detail="File must be an image or video")
    if size > cap:
        raise HTTPException(status_code=413, detail=f"{kind.title()} too large")
    ext = _BROLL_EXT.get(ct, "png" if kind == "image" else "mp4")
    return kind, ext
```

Add the endpoint after `saasshorts_actor_upload`:

```python
@app.post("/api/saasshorts/broll-upload")
async def saasshorts_broll_upload(request: Request, file: UploadFile = File(...)):
    """Upload a custom b-roll image or video (stored locally only)."""
    await require_managed_entitlement(request)
    cap = BROLL_VIDEO_MAX_BYTES  # read up to the larger cap; validate exact size after
    content = await file.read(cap + 1)
    kind, ext = validate_broll_upload(file.content_type, len(content))
    if len(content) < 1000:
        raise HTTPException(status_code=400, detail="File too small to be valid")

    upload_id = uuid.uuid4().hex[:8]
    upload_dir = os.path.join(OUTPUT_DIR, "broll_uploads")
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"broll_{upload_id}.{ext}"
    with open(os.path.join(upload_dir, filename), "wb") as f:
        f.write(content)
    return {"url": f"/videos/broll_uploads/{filename}", "kind": kind}
```

In `saasshorts_generate`, after the `selected_actor_url` resolution (`app.py:3575-3597`) and before building `config`, resolve each segment's asset url to a safe local path:

```python
    # Resolve user b-roll asset urls -> safe local paths on each segment.
    for seg in req.script.get("segments", []) or []:
        asset_url = seg.get("broll_asset_url")
        if asset_url:
            src = _safe_under(OUTPUT_DIR, asset_url.replace("/videos/", "").lstrip("/"))
            if src and os.path.exists(src):
                seg["broll_asset_path"] = src
            else:
                # Missing/invalid asset -> drop to AI so classify_broll_slot falls back.
                seg.pop("broll_asset_path", None)
                seg["broll_source"] = "ai"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_broll_upload.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_broll_upload.py
git commit -m "feat(saas): b-roll upload endpoint + resolve asset urls to local paths"
```

---

### Task 8: Frontend — timeline component (variant B)

Single video track of butt-jointed blocks (head/b-roll, colored by type) + a voiceover track, on step 2.

**Files:**
- Create: `dashboard/src/components/BrollTimeline.jsx`
- Modify: `dashboard/src/components/SaaShortsTab.jsx` (render `<BrollTimeline>` on step 2, near the cost block; pass the selected script + a click handler)
- Modify: `dashboard/src/lib/i18n.js` (timeline + source labels)

**Interfaces:**
- Consumes: `script` (the selected script object with `segments`, `duration_seconds`), `onSlotClick(segIndex)`.
- Produces: `BrollTimeline` default export.

- [ ] **Step 1: Create the component**

```jsx
// dashboard/src/components/BrollTimeline.jsx
import React from 'react';

const KIND = {
  th:    { cls: 'bg-zinc-600 border-zinc-500 text-zinc-100', label: '🗣' },
  ai:    { cls: 'bg-violet-600 border-violet-400 text-white', label: 'AI' },
  image: { cls: 'bg-sky-600 border-sky-400 text-white', label: '📷' },
  video: { cls: 'bg-amber-500 border-amber-300 text-black', label: '🎬' },
};

function slotKind(seg) {
  if (seg.visual !== 'broll') return 'th';
  const s = seg.broll_source || 'ai';
  return ['ai', 'image', 'video'].includes(s) ? s : 'ai';
}

export default function BrollTimeline({ script, onSlotClick, t = (x) => x }) {
  const segments = script?.segments || [];
  const total = script?.duration_seconds
    || segments.reduce((m, s) => Math.max(m, s.end || 0), 0) || 1;

  return (
    <div className="rounded-xl border border-rule bg-black/40 p-3">
      <div className="flex text-[10px] text-muted mb-1 pl-14">
        {[0, 0.25, 0.5, 0.75, 1].map((f, i) => (
          <span key={i} className="flex-1">{Math.round(total * f)}s</span>
        ))}
      </div>
      <div className="flex items-stretch mb-1.5">
        <div className="w-14 shrink-0 text-[10px] text-muted uppercase flex items-center justify-end pr-2">
          {t('Video')}
        </div>
        <div className="flex-1 flex gap-[3px] h-9">
          {segments.map((seg, i) => {
            const kind = slotKind(seg);
            const meta = KIND[kind];
            const grow = Math.max(0.5, (seg.end - seg.start));
            const clickable = seg.visual === 'broll';
            return (
              <button
                key={i}
                type="button"
                disabled={!clickable}
                onClick={() => clickable && onSlotClick(i)}
                style={{ flexGrow: grow, flexBasis: 0 }}
                className={`rounded-md border text-[10px] font-semibold flex flex-col items-center justify-center overflow-hidden px-1 ${meta.cls} ${clickable ? 'cursor-pointer hover:brightness-110' : 'cursor-default'}`}
                title={seg.type || kind}
              >
                <span>{meta.label}</span>
                <span className="text-[8px] font-normal opacity-80 truncate max-w-full">{seg.type}</span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex items-stretch">
        <div className="w-14 shrink-0 text-[10px] text-muted uppercase flex items-center justify-end pr-2">
          {t('Voice')}
        </div>
        <div className="flex-1 h-6 rounded-md border border-slate-600 bg-slate-800 text-[9px] text-sky-300 flex items-center justify-center">
          🔊 {t('Voiceover — continuous')}
        </div>
      </div>
      <div className="flex gap-3 flex-wrap text-[10px] text-muted mt-2 pl-14">
        <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-zinc-600 mr-1 align-[-1px]" />{t('Head')}</span>
        <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-violet-600 mr-1 align-[-1px]" />{t('AI b-roll')}</span>
        <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-sky-600 mr-1 align-[-1px]" />{t('My photo')}</span>
        <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-amber-500 mr-1 align-[-1px]" />{t('My video')}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Render it on step 2**

In `SaaShortsTab.jsx`, import at top: `import BrollTimeline from './BrollTimeline';`
Inside the `{step === 2 && scripts[selectedScript] && (` block (around `SaaShortsTab.jsx:927`), add near the cost area:

```jsx
<BrollTimeline
  script={scripts[selectedScript]}
  t={t}
  onSlotClick={(segIdx) => setActiveSlot({ scriptIdx: selectedScript, segIdx })}
/>
```

Add state near the other `useState` hooks (around `SaaShortsTab.jsx:300`): `const [activeSlot, setActiveSlot] = useState(null);`

- [ ] **Step 3: Add i18n keys**

In `dashboard/src/lib/i18n.js`, add to each language map the keys used above: `'Video'`, `'Voice'`, `'Voiceover — continuous'`, `'Head'`, `'AI b-roll'`, `'My photo'`, `'My video'` (English passthrough is fine as the base; add Russian/Spanish translations following the file's existing structure).

- [ ] **Step 4: Verify lint/build**

Run: `cd dashboard && npm run lint`
Expected: no errors (0 warnings).

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/BrollTimeline.jsx dashboard/src/components/SaaShortsTab.jsx dashboard/src/lib/i18n.js
git commit -m "feat(ui): b-roll timeline on the pre-generation review screen"
```

---

### Task 9: Frontend — per-slot editor panel + upload

Clicking a b-roll block opens a panel to pick source, edit prompt or upload a file, toggle video audio, and edit the window.

**Files:**
- Create: `dashboard/src/components/BrollSlotEditor.jsx`
- Modify: `dashboard/src/components/SaaShortsTab.jsx` (render the panel when `activeSlot` set; write edits into `scripts`)
- Modify: `dashboard/src/lib/i18n.js` (editor labels)

**Interfaces:**
- Consumes: `segment` (the b-roll segment), `apiFetch`, `falImageHeaders`, `onChange(patch)`, `onClose()`.
- Produces: `BrollSlotEditor` default export.

- [ ] **Step 1: Create the editor**

```jsx
// dashboard/src/components/BrollSlotEditor.jsx
import React, { useState } from 'react';

export default function BrollSlotEditor({ segment, apiFetch, onChange, onClose, t = (x) => x }) {
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState('');
  const source = segment.broll_source || 'ai';
  const mute = segment.broll_mute_audio !== false; // default true

  const upload = async (file) => {
    if (!file) return;
    setUploading(true); setErr('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await apiFetch('/api/saasshorts/broll-upload', { method: 'POST', body: fd });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Upload failed'); }
      const data = await res.json();
      onChange({ broll_source: data.kind, broll_asset_url: data.url });
    } catch (e) { setErr(e.message); }
    setUploading(false);
  };

  return (
    <div className="rounded-xl border border-rule bg-paper p-4 mt-2 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-ink">{t('B-roll slot')} · {segment.type}</h4>
        <button type="button" onClick={onClose} className="text-xs text-muted hover:text-ink">✕</button>
      </div>

      <div className="flex gap-2 text-xs">
        {[['ai', t('AI')], ['image', t('My photo')], ['video', t('My video')]].map(([val, label]) => (
          <label key={val} className={`px-3 py-1.5 rounded-input border cursor-pointer ${source === val ? 'border-accent text-ink' : 'border-rule text-muted'}`}>
            <input type="radio" className="hidden" name="broll_source" checked={source === val}
              onChange={() => onChange({ broll_source: val })} />
            {label}
          </label>
        ))}
      </div>

      {source === 'ai' && (
        <textarea
          className="w-full text-xs bg-black/30 border border-rule rounded-input p-2 text-ink2"
          rows={3}
          value={segment.broll_prompt || ''}
          onChange={(e) => onChange({ broll_prompt: e.target.value })}
          placeholder={t('Describe the b-roll visual...')}
        />
      )}

      {(source === 'image' || source === 'video') && (
        <div className="space-y-2">
          <input type="file" accept={source === 'image' ? 'image/*' : 'video/*'}
            disabled={uploading}
            onChange={(e) => upload(e.target.files?.[0])}
            className="block text-xs text-muted" />
          {uploading && <p className="text-xs text-muted">{t('Uploading...')}</p>}
          {segment.broll_asset_url && !uploading && (
            <p className="text-xs text-emerald-400 truncate">✓ {segment.broll_asset_url.split('/').pop()}</p>
          )}
          {err && <p className="text-xs text-red-400">{err}</p>}
        </div>
      )}

      {source === 'video' && (
        <label className="flex items-center gap-2 text-xs text-ink2">
          <input type="checkbox" checked={mute}
            onChange={(e) => onChange({ broll_mute_audio: e.target.checked })} />
          {t('Mute video audio (keep voiceover only)')}
        </label>
      )}

      <div className="flex gap-2 items-center text-xs text-muted">
        <label>{t('Start')}
          <input type="number" step="0.5" value={segment.start}
            onChange={(e) => onChange({ start: parseFloat(e.target.value) })}
            className="w-16 ml-1 bg-black/30 border border-rule rounded-input px-1 text-ink2" />
        </label>
        <label>{t('End')}
          <input type="number" step="0.5" value={segment.end}
            onChange={(e) => onChange({ end: parseFloat(e.target.value) })}
            className="w-16 ml-1 bg-black/30 border border-rule rounded-input px-1 text-ink2" />
        </label>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire into `SaaShortsTab.jsx`**

Import: `import BrollSlotEditor from './BrollSlotEditor';`

Add a patch helper near the other handlers (around `SaaShortsTab.jsx:307`):

```jsx
const patchSegment = (scriptIdx, segIdx, patch) => {
  setScripts((prev) => prev.map((s, i) => {
    if (i !== scriptIdx) return s;
    const segments = s.segments.map((seg, j) => (j === segIdx ? { ...seg, ...patch } : seg));
    return { ...s, segments };
  }));
};
```

Render below `<BrollTimeline>` in the step-2 block:

```jsx
{activeSlot && scripts[activeSlot.scriptIdx]?.segments[activeSlot.segIdx] && (
  <BrollSlotEditor
    segment={scripts[activeSlot.scriptIdx].segments[activeSlot.segIdx]}
    apiFetch={apiFetch}
    t={t}
    onChange={(patch) => patchSegment(activeSlot.scriptIdx, activeSlot.segIdx, patch)}
    onClose={() => setActiveSlot(null)}
  />
)}
```

Persist to cache after edits by calling the existing `saveCache(...)` inside `patchSegment` if the surrounding code caches scripts (mirror `handleSaveScriptEdit` at `SaaShortsTab.jsx:314-320`).

- [ ] **Step 3: Confirm generate already sends new fields**

No change needed — `handleGenerate` (`SaaShortsTab.jsx:346`) spreads `scripts[selectedScript]`, so `broll_source`, `broll_asset_url`, `broll_mute_audio`, edited `broll_prompt`, and `start`/`end` all serialize into the POST body. Verify by reading the function; do not modify.

- [ ] **Step 4: Add i18n keys + verify lint**

Add keys: `'B-roll slot'`, `'AI'`, `'My photo'`, `'My video'`, `'Describe the b-roll visual...'`, `'Uploading...'`, `'Mute video audio (keep voiceover only)'`, `'Start'`, `'End'` to `i18n.js`.

Run: `cd dashboard && npm run lint`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/BrollSlotEditor.jsx dashboard/src/components/SaaShortsTab.jsx dashboard/src/lib/i18n.js
git commit -m "feat(ui): per-slot b-roll editor (source, prompt, upload, audio, window)"
```

---

### Task 10: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Backend tests green**

Run: `python -m pytest tests/test_broll_slots.py tests/test_broll_upload.py -v`
Expected: all PASS.

- [ ] **Step 2: Full suite (regression)**

Run: `python -m pytest -q`
Expected: no new failures vs. baseline.

- [ ] **Step 3: Frontend lint**

Run: `cd dashboard && npm run lint`
Expected: 0 warnings/errors.

- [ ] **Step 4: Manual smoke (documented, run by user)**

1. `docker compose up --build`; open the SaaSShorts tab; analyze a product → get scripts.
2. On step 2, confirm the timeline shows the talking-head + b-roll blocks and a voice track.
3. Slot 1 → AI, edit the prompt. Slot 2 → upload a short video, uncheck "Mute video audio". Generate.
4. Confirm: the render cuts to the video in slot 2; both the voiceover AND the clip audio are audible there; slot 1 shows the AI Ken Burns image; cost reflects one AI b-roll.
5. Second run: slot with an uploaded photo (Ken Burns applied); a video slot with mute ON (voiceover only). Confirm.
6. Regression: a script left fully default (all AI) renders exactly as before.

- [ ] **Step 5: Finalize**

Use superpowers:finishing-a-development-branch to open a PR or merge.

---

## Self-Review

**Spec coverage:**
- Per-slot source (ai/image/video) → Tasks 1, 4. ✓
- Editable prompt → Task 9 (textarea; already serialized). ✓
- User image + Ken Burns → Tasks 2, 4. ✓
- User video, no Ken Burns → Tasks 3, 4. ✓
- Per-slot audio mix (both audible) → Tasks 1, 5. ✓
- Manual window start/end → Task 9. ✓
- Timeline variant B → Task 8. ✓
- Upload endpoint (image+video, caps) → Task 7. ✓
- url→path resolution → Task 7. ✓
- Cost = AI slots only → Task 6. ✓
- Backward compat (missing source = ai) → Task 1 + Task 4 filter. ✓
- Out-of-scope items excluded. ✓

**Type consistency:** `classify_broll_slot` returns `source/asset_path/audio_mode/prompt`, consumed consistently in Tasks 4/6. Runtime clip dict `{path,start,end,audio_mode}` produced in Task 4, consumed in Task 5's `composite_video` segment build. `build_composite_filter(segments, sub_filter)` signature matches Task 5 test. `validate_broll_upload(content_type,size)->(kind,ext)` consistent across Task 7. Segment fields `broll_source/broll_asset_url/broll_asset_path/broll_mute_audio` used consistently frontend↔backend. ✓

**Placeholders:** none. Task 3 now ships the probe-based (`_has_audio_stream` + `has_audio` arg) implementation as its primary code, with matching tests for both audio-present and audioless branches.
