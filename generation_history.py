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
