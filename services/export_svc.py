"""Unity-oriented zip export + full project snapshot — paths via ``media_utils``."""

from __future__ import annotations

import io
import os
from datetime import datetime, timezone

import zipfile

from . import media_utils as mu


def _add_tree(z: zipfile.ZipFile, source_dir: str, arc_prefix: str):
    if not os.path.isdir(source_dir):
        return
    for dp, _dns, filenames in os.walk(source_dir):
        for fn in filenames:
            fp = os.path.join(dp, fn)
            rel = os.path.relpath(fp, source_dir).replace("\\", "/")
            z.write(fp, arcname=f"{arc_prefix}/{rel}".replace("//", "/"))


def unity_export_zip(version_tag: str | None = None) -> tuple[bytes, str]:
    bio = io.BytesIO()
    tag = version_tag or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    arc_base = "Assets/GameAssets"

    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as z:
        imgs = mu.images_store_dir()
        aud_base = mu.audio_store_root_dir()
        vids = mu.videos_store_dir()
        anim = mu.animations_root_dir()

        _add_tree(z, imgs, f"{arc_base}/Sprites/Imported")
        _add_tree(z, vids, f"{arc_base}/Videos/Source")
        _add_tree(z, anim, f"{arc_base}/Animations/Generated")

        if os.path.isdir(aud_base):
            for cat in os.listdir(aud_base):
                p = os.path.join(aud_base, cat)
                if os.path.isdir(p):
                    _add_tree(z, p, f"{arc_base}/Audio/{cat}")

    name = f"unity-export-{tag}.zip"
    return bio.getvalue(), name


def full_project_zip(version_tag: str | None = None) -> tuple[bytes, str]:
    bio = io.BytesIO()
    tag = version_tag or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as z:
        _add_tree(z, mu.STORAGE_ROOT, "storage")
        for rel in (mu.UPLOAD_SEG, mu.OUTPUT_SEG, mu.DATA_SEG):
            p = os.path.join(mu.BASE_DIR, rel)
            if os.path.isdir(p):
                _add_tree(z, p, rel)
        html = os.path.join(mu.BASE_DIR, "index.html")
        app_f = os.path.join(mu.BASE_DIR, "app.py")
        tmpl = os.path.join(mu.BASE_DIR, "templates")
        if os.path.isfile(html):
            z.write(html, "index_sprite_tool.html")
        if os.path.isfile(app_f):
            z.write(app_f, "app.py")
        if os.path.isdir(tmpl):
            _add_tree(z, tmpl, "templates")

    name = f"project-snapshot-{tag}.zip"
    return bio.getvalue(), name


def persist_version_manifest(tag: str) -> str:
    d = mu.DATA_DIR if os.path.isdir(mu.DATA_DIR) else os.path.join(mu.BASE_DIR, mu.DATA_SEG)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"manifest-{tag}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(datetime.now(timezone.utc).isoformat() + "\n")
    return path
