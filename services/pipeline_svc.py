"""Compatibility shim — prefer ``pipeline_controller`` for new integrations."""

from __future__ import annotations

from .pipeline_controller import run_animation_pipeline, run_full_pipeline_from_video


def pipeline_frames_then_bg(animation_id: str, interval_sec: float) -> dict:
    return run_animation_pipeline(animation_id, interval_sec, skip_bg=False)


pipeline_full_animation = run_full_pipeline_from_video

__all__ = ["pipeline_frames_then_bg", "pipeline_full_animation"]
