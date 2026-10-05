"""Backward-compatible exports — prefer ``services.media_utils`` for new code."""

from __future__ import annotations

from .media_utils import (
    BASE_DIR,
    DATA_DIR,
    RESOURCE_ROOT,
    OUTPUT,
    STATE_PATH,
    STORAGE_ROOT,
    UPLOAD,
    animations_root_dir,
    animation_bundle_dir,
    audio_store_root_dir,
    ensure_dirs,
    seed_user_workspace,
    images_store_dir,
    media_relative_path,
    safe_media_path,
    short_id,
    slugify,
    videos_store_dir,
)

ANIMATIONS = animations_root_dir()
IMAGES_STORE = images_store_dir()
AUDIO_STORE = audio_store_root_dir()
VIDEOS_STORE = videos_store_dir()
