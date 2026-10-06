"""Aggregate completion snapshot for dashboards."""

from __future__ import annotations

from . import state_store
from .animation_svc import scan_storage_usage
from .assets_service import list_animations, list_audios, list_images, list_videos


def _ratio(actual: float, goal: float) -> float:
    if goal <= 0:
        return 0.0
    return min(1.0, actual / goal)


def snapshot() -> dict:
    cnt = state_store.load_state().get("counts", {})
    stor = scan_storage_usage()

    img_n = len(list_images())
    vid_n = len(list_videos())
    anim_roster = len(list_animations())

    buckets = list_audios()
    aud_total = sum(len(v) for v in buckets.values())

    chats = cnt.get("companion_chats", 0)
    pipes = cnt.get("pipeline_runs", 0)
    removals = cnt.get("bg_removal_runs", 0)

    goals = {"assets": max(35, img_n + aud_total + 5), "animations": max(10, anim_roster + 3), "lore_engagement": 80}
    pct_assets = _ratio(img_n + aud_total * 2 + vid_n * 4, goals["assets"]) * 0.42
    pct_animations = min(1.0, _ratio(max(anim_roster, pipes), goals["animations"]) + _ratio(removals, removals + 420) * 0.15) * 0.42
    pct_companion = min(1.0, chats / goals["lore_engagement"]) * 0.16

    overall = min(100, round(100 * (pct_assets + pct_animations + pct_companion)))

    return {
        "overall_percent_estimate": overall,
        "milestones_goals": goals,
        "counts": cnt,
        "present": {
            "images_indexed": img_n,
            "audio_indexed": aud_total,
            "videos_indexed": vid_n,
            "animations_indexed": anim_roster,
        },
        "storage": stor,
    }
