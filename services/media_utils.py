"""
Single module for filesystem layout under the game workspace.

Handles path resolution, /media URL generation, and storage bucket mapping.

Packaged desktop builds:
  - RESOURCE_ROOT: bundled templates/static (PyInstaller _MEIPASS)
  - BASE_DIR / DATA_DIR: user-writable AppData (GAME_DEV_OS_DATA_DIR)
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import uuid

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> str:
    if _frozen():
        return getattr(sys, "_MEIPASS", _PKG_ROOT)
    return os.environ.get("GAME_DEV_OS_RESOURCE_DIR", _PKG_ROOT)


def data_root() -> str:
    env = os.environ.get("GAME_DEV_OS_DATA_DIR")
    if env:
        return os.path.normpath(env)
    return _PKG_ROOT


RESOURCE_ROOT = resource_root()
BASE_DIR = data_root()

STORAGE_SEG = "storage"
UPLOAD_SEG = "uploads"
OUTPUT_SEG = "outputs"
DATA_SEG = "data"

STORAGE_ROOT = os.path.join(BASE_DIR, STORAGE_SEG)
DATA_DIR = os.path.join(BASE_DIR, DATA_SEG)
STATE_PATH = os.path.join(DATA_DIR, "game_state.json")

IMAGES_BUCKET = "images"
AUDIO_BUCKET = "audio"
VIDEOS_BUCKET = "videos"
ANIMATIONS_BUCKET = "animations"

# Legacy string segments used by app routes (/uploads, /outputs)
UPLOAD = UPLOAD_SEG
OUTPUT = OUTPUT_SEG

_SLUG_SAFE = re.compile(r"[^a-z0-9_-]+")


def slugify(text: str, fallback: str = "asset") -> str:
    s = text.strip().lower().replace(" ", "-")
    s = _SLUG_SAFE.sub("-", s).strip("-")
    return s[:64] if s else fallback


def short_id(prefix: str = "") -> str:
    u = uuid.uuid4().hex[:10]
    return f"{prefix}{u}" if prefix else u


def seed_user_workspace() -> None:
    """Create writable folders (and default state) under BASE_DIR / AppData."""
    ensure_dirs()
    if not os.path.isfile(STATE_PATH):
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as wf:
            wf.write("{}\n")

    bundled_storage = os.path.join(RESOURCE_ROOT, STORAGE_SEG)
    if os.path.isdir(bundled_storage):
        for bucket in (IMAGES_BUCKET, AUDIO_BUCKET, VIDEOS_BUCKET, ANIMATIONS_BUCKET):
            src = os.path.join(bundled_storage, bucket)
            dst = os.path.join(STORAGE_ROOT, bucket)
            if os.path.isdir(src) and not os.path.isdir(dst):
                shutil.copytree(src, dst, dirs_exist_ok=True)


def ensure_dirs() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(images_store_dir(), exist_ok=True)
    os.makedirs(audio_store_root_dir(), exist_ok=True)
    os.makedirs(videos_store_dir(), exist_ok=True)
    os.makedirs(animations_root_dir(), exist_ok=True)
    os.makedirs(workspace_upload_dir(), exist_ok=True)
    os.makedirs(workspace_output_dir(), exist_ok=True)


def workspace_upload_dir() -> str:
    return os.path.join(BASE_DIR, UPLOAD_SEG)


def workspace_output_dir() -> str:
    return os.path.join(BASE_DIR, OUTPUT_SEG)


def images_store_dir() -> str:
    return os.path.join(STORAGE_ROOT, IMAGES_BUCKET)


def audio_store_root_dir() -> str:
    return os.path.join(STORAGE_ROOT, AUDIO_BUCKET)


def videos_store_dir() -> str:
    return os.path.join(STORAGE_ROOT, VIDEOS_BUCKET)


def animations_root_dir() -> str:
    return os.path.join(STORAGE_ROOT, ANIMATIONS_BUCKET)


def storage_bucket_abs(kind: str, *, audio_category: str | None = None) -> str:
    """Typed asset directory under storage (creates audio category folder when needed)."""
    if kind == "image":
        return images_store_dir()
    if kind == "audio":
        cat = slugify(audio_category or "misc", "misc")
        base = os.path.join(audio_store_root_dir(), cat)
        os.makedirs(base, exist_ok=True)
        return base
    if kind == "video":
        return videos_store_dir()
    raise ValueError("unknown storage kind")


def animation_bundle_dir(animation_id: str) -> str:
    return os.path.join(animations_root_dir(), animation_id)


def animation_raw_dir(animation_id: str) -> str:
    return os.path.join(animation_bundle_dir(animation_id), "raw")


def animation_clean_dir(animation_id: str) -> str:
    return os.path.join(animation_bundle_dir(animation_id), "clean")


def animation_metadata_path(animation_id: str) -> str:
    return os.path.join(animation_bundle_dir(animation_id), "metadata.json")


def animation_subdir(animation_id: str, name: str) -> str:
    return os.path.join(animation_bundle_dir(animation_id), name)


def animation_bundle_child(animation_id: str, *names: str) -> str:
    return os.path.join(animation_bundle_dir(animation_id), *names)


def bundle_exists(animation_id: str) -> bool:
    return os.path.isdir(animation_bundle_dir(animation_id))


# --- Resolution under STORAGE_ROOT (security-checked) ---


def resolve_existing_file_under_storage(rel_under_media: str) -> str | None:
    """
    Map URL segment after /media/ to an absolute file path if it exists.
    rel_under_media examples: images/foo.png, animations/id/raw/frame_001.png
    """
    parts = [
        p
        for p in rel_under_media.strip("/").replace("\\", "/").split("/")
        if p and p not in (".", "..")
    ]
    if not parts:
        return None
    cand = os.path.normpath(os.path.join(STORAGE_ROOT, *parts))
    root_ns = os.path.normpath(STORAGE_ROOT)
    if cand.lower() == root_ns.lower():
        return None
    if not cand.lower().startswith(root_ns.lower() + os.sep):
        return None
    return cand if os.path.isfile(cand) else None


def safe_media_path(rel: str) -> str | None:
    """Join rel to STORAGE_ROOT; return None if path escapes or not a file."""
    return resolve_existing_file_under_storage(rel)


def storage_relative_from_absolute(abs_path: str) -> str | None:
    abs_path = os.path.normpath(os.path.abspath(abs_path))
    root = os.path.normpath(os.path.abspath(STORAGE_ROOT))
    if not abs_path.startswith(root + os.sep):
        return None
    return abs_path[len(root) + 1 :].replace("\\", "/")


def media_relative_path(abs_path: str) -> str | None:
    """Alias for storage-relative POSIX path under STORAGE_ROOT."""
    return storage_relative_from_absolute(abs_path)


# --- URL helpers (/media/...) ---


def media_url_from_absolute_project_path(abs_path: str) -> str:
    """
    Build /media/... for anything under BASE_DIR (storage subtree drops `storage/` prefix).
    Matches prior assets_service behavior for catalog URLs.
    """
    rel = os.path.relpath(abs_path, BASE_DIR).replace("\\", "/")
    parts = rel.split("/")
    if parts and parts[0] == STORAGE_SEG:
        return "/media/" + "/".join(parts[1:])
    return "/media/" + "/".join(parts)


def media_url_from_storage_relative(storage_rel: str) -> str:
    storage_rel = storage_rel.strip("/").replace("\\", "/")
    return "/media/" + storage_rel


def natural_sort_key(s: str) -> list:
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]


def frame_urls_for_bundle(animation_id: str, cleaned: bool) -> list[str]:
    folder = animation_clean_dir(animation_id) if cleaned else animation_raw_dir(animation_id)
    urls: list[str] = []
    if not os.path.isdir(folder):
        return urls
    for n in sorted(os.listdir(folder), key=natural_sort_key):
        if not n.endswith(".png"):
            continue
        rel = "/".join(["animations", animation_id, "clean" if cleaned else "raw", n])
        urls.append(media_url_from_storage_relative(rel))
    return urls
