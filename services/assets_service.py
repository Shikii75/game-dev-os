"""Typed asset uploads and listing — paths and URLs via ``media_utils`` only."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from werkzeug.utils import secure_filename

from . import media_utils as mu
from . import state_store
from .activity import hub as activity_hub


ALLOWED_KIND = frozenset({"image", "audio", "video"})


def storage_dir_for(kind: str, audio_category: str | None = None) -> str:
    return mu.storage_bucket_abs(kind, audio_category=audio_category)


def rel_to_media_url(abs_path: str) -> str:
    return mu.media_url_from_absolute_project_path(abs_path)


def save_uploaded_file(kind: str, file_storage, slug: str | None, audio_category: str | None) -> dict:
    if kind not in ALLOWED_KIND:
        raise ValueError("invalid kind")

    base = mu.storage_bucket_abs(kind, audio_category=audio_category if kind == "audio" else None)
    orig_name = secure_filename(file_storage.filename or "file.bin")
    ext = os.path.splitext(orig_name)[1].lower()

    sid = mu.slugify(slug or mu.short_id(kind[:1]))
    uniq = mu.short_id("")[:8]
    logical_id = f"{sid}-{uniq}"
    filename = logical_id + (ext if ext else ".bin")
    dst = os.path.join(base, filename)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    file_storage.save(dst)
    meta = {
        "id": logical_id,
        "filename": filename,
        "original_name": orig_name,
        "kind": kind,
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "url": mu.media_url_from_absolute_project_path(dst),
        "audio_category": audio_category if kind == "audio" else None,
    }
    state_store.bump_counter("asset_uploads")
    if kind == "audio":
        state_store.bump_counter("audio_uploads")
    activity_hub.log("asset_upload", f"{kind}: {filename}")
    return {"absolute_path": dst, **meta}


def _walk_files(root: str):
    entries = []
    if not os.path.isdir(root):
        return entries

    for dirpath, _dirs, files in os.walk(root):
        for fn in sorted(files):
            full = os.path.join(dirpath, fn)
            if not os.path.isfile(full):
                continue
            segments = os.path.relpath(full, root).replace("\\", "/")
            entries.append({
                "name": fn,
                "path": segments,
                "url": mu.media_url_from_absolute_project_path(full),
                "size": os.path.getsize(full),
            })
    return entries


def list_images() -> list[dict]:
    return _walk_files(mu.images_store_dir())


def list_audios():
    grouped = {}
    audio_root = mu.audio_store_root_dir()
    if not os.path.isdir(audio_root):
        return grouped
    for cat in sorted(os.listdir(audio_root)):
        cp = os.path.join(audio_root, cat)
        if os.path.isdir(cp):
            grouped[cat] = _walk_files(cp)
    return grouped


def list_videos() -> list[dict]:
    return _walk_files(mu.videos_store_dir())


def list_animations() -> list[dict]:
    root = mu.animations_root_dir()
    if not os.path.isdir(root):
        return []
    rows = []
    for aid in os.listdir(root):
        ap = mu.animation_bundle_dir(aid)
        if not os.path.isdir(ap):
            continue
        meta_path = mu.animation_metadata_path(aid)
        meta = {}
        if os.path.isfile(meta_path):
            try:
                import json
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
        rp = mu.animation_raw_dir(aid)
        cp = mu.animation_clean_dir(aid)
        raw_n = sum(1 for n in os.listdir(rp) if n.endswith(".png")) if os.path.isdir(rp) else 0
        clean_n = sum(1 for n in os.listdir(cp) if n.endswith(".png")) if os.path.isdir(cp) else 0

        mtime = os.path.getmtime(ap)
        rows.append({
            "id": aid,
            "slug": meta.get("slug"),
            "frame_interval": meta.get("frame_interval_sec"),
            "raw_frames": raw_n if raw_n else meta.get("raw_frame_count"),
            "clean_frames": clean_n if clean_n else meta.get("clean_frame_count"),
            "player_url": f"/animations/{aid}/play",
            "preview_pattern": meta.get("frame_pattern"),
            "mtime": mtime,
        })
    rows.sort(key=lambda x: x["mtime"], reverse=True)
    return rows
