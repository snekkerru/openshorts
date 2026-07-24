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
