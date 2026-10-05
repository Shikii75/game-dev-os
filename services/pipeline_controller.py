"""
Unified pipeline entry points for Electron/desktop wrappers.

Delegates to animation_svc for implementation; orchestrates jobs + counters here.
"""

from __future__ import annotations

from . import animation_svc
from . import state_store
from .activity import hub as activity_hub


def run_video_extract(animation_id: str, interval_sec: float) -> dict:
    """OpenCV extract ordered frames into ``raw/``."""
    return animation_svc.run_extract(animation_id, interval_sec)


def run_bg_cleanup(animation_id: str, method: str = "rembg") -> dict:
    """Batch background removal ``raw/*.png`` → ``clean/``."""
    return animation_svc.batch_remove_bg(animation_id, method)


def run_animation_pipeline(animation_id: str, interval_sec: float, *, skip_bg: bool = False, method: str = "rembg") -> dict:
    """Extract frames, then optionally batch-remove backgrounds."""
    extract = animation_svc.run_extract(animation_id, interval_sec)
    if skip_bg:
        state_store.bump_counter("pipeline_runs")
        activity_hub.log("pipeline_animation_chain", animation_id, {"skip_bg": True})
        return {"extract": extract, "bg_batch": {"skipped": True}}

    bg = animation_svc.batch_remove_bg(animation_id, method)
    state_store.bump_counter("pipeline_runs")
    activity_hub.log("pipeline_animation_chain", animation_id, {"method": method})
    return {"extract": extract, "bg_batch": bg}


def run_full_pipeline_from_video(
    video_abs_path: str,
    slug: str,
    interval_sec: float,
    *,
    skip_bg: bool = False,
    method: str = "rembg",
) -> dict:
    """New bundle + extract (+ optional BG batch) from an on-disk video file."""
    job = activity_hub.job_start(f"pipeline:{slug}")
    try:
        aid, step1 = animation_svc.ingest_video_into_new_animation(video_abs_path, slug, interval_sec)
        if skip_bg:
            state_store.bump_counter("pipeline_runs")
            activity_hub.job_done(job)
            return {"animation_id": aid, **step1, "bg_batch": {"skipped": True}}

        bg = animation_svc.batch_remove_bg(aid, method)
        state_store.bump_counter("pipeline_runs")
        activity_hub.log("pipeline_complete", aid, {"method": method})
        activity_hub.job_done(job)
        return {"animation_id": aid, **step1, "bg_batch": bg}
    except Exception as e:
        activity_hub.job_fail(job, str(e))
        raise
