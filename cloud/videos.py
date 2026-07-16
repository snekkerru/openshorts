"""Users' durable video library on R2: archive on completion, list for history,
purge after the subscription grace period.
"""
import asyncio
import os
from datetime import timedelta

from fastapi import APIRouter, Request
from sqlalchemy import select, delete

from .config import settings, VIDEO_RETENTION_GRACE_DAYS
from . import database, storage
from .models import UserVideo, Subscription
from .auth import get_current_user_required

router = APIRouter()


async def archive_job(user_id, job_id, clips, output_dir):
    """Upload a completed managed job's clips to R2 and record them for history."""
    if not settings.r2_configured or not clips:
        return
    rows = []
    for i, clip in enumerate(clips):
        video_url = clip.get("video_url") or ""
        filename = video_url.split("/")[-1]
        if not filename:
            continue
        local_path = os.path.join(output_dir, filename)
        if not os.path.exists(local_path):
            continue
        key = storage.job_key(user_id, job_id, filename)
        try:
            await asyncio.to_thread(storage.upload_file, local_path, key)
        except Exception as e:
            print(f"⚠️  R2 upload failed for {key}: {e}")
            continue
        rows.append(UserVideo(
            user_id=user_id, job_id=job_id, clip_index=i, r2_key=key,
            title=clip.get("title") or "Short",
            size_bytes=os.path.getsize(local_path),
        ))
    if rows:
        async with database.session() as s:
            async with s.begin():
                s.add_all(rows)
        print(f"☁️  Archived {len(rows)} clip(s) to R2 for user {user_id}.")


@router.get("/api/history")
async def history(request: Request):
    """List the signed-in user's saved videos with private, time-limited links."""
    user = await get_current_user_required(request)
    async with database.session() as s:
        vids = list((await s.execute(
            select(UserVideo).where(UserVideo.user_id == user.id)
            .order_by(UserVideo.created_at.desc()).limit(500)
        )).scalars())
    items = []
    for v in vids:
        safe_name = (v.title or "short").strip().replace("/", "-")[:60] + ".mp4"
        items.append({
            "id": str(v.id),
            "job_id": v.job_id,
            "clip_index": v.clip_index,
            "title": v.title,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "size_bytes": v.size_bytes,
            "view_url": storage.presigned_get(v.r2_key, expires=3600),
            "download_url": storage.presigned_get(v.r2_key, expires=3600, download_name=safe_name),
        })
    return {"videos": items}


async def purge_expired():
    """Delete R2 videos for users whose subscription ended > grace-period days ago."""
    async with database.session() as s:
        # Users with a canceled subscription past the grace period, who still have videos.
        canceled = list((await s.execute(
            select(Subscription.user_id, Subscription.last_event_at)
            .where(Subscription.status == "canceled")
        )).all())
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for user_id, last_event_at in canceled:
        if not last_event_at:
            continue
        if last_event_at + timedelta(days=VIDEO_RETENTION_GRACE_DAYS) > now:
            continue
        # Any videos left?
        async with database.session() as s:
            has = (await s.execute(
                select(UserVideo.id).where(UserVideo.user_id == user_id).limit(1)
            )).first()
        if not has:
            continue
        try:
            n = await asyncio.to_thread(storage.delete_prefix, storage.user_prefix(user_id))
            async with database.session() as s:
                async with s.begin():
                    await s.execute(delete(UserVideo).where(UserVideo.user_id == user_id))
            print(f"🗑️  Purged {n} R2 object(s) for lapsed user {user_id}.")
        except Exception as e:
            print(f"⚠️  Video purge failed for {user_id}: {e}")


_SWEEP_INTERVAL = 6 * 3600  # every 6 hours


async def _sweeper_loop():
    while True:
        try:
            await asyncio.sleep(_SWEEP_INTERVAL)
            await purge_expired()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"⚠️  Video retention sweeper error: {e}")


def start_sweeper():
    asyncio.create_task(_sweeper_loop())
