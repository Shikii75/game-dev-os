"""Per-animation folders, metadata JSON, BG batch — paths via ``media_utils`` only."""

from __future__ import annotations

import base64
import json
import os
import shutil
from datetime import datetime, timezone

from . import media_utils as mu
from . import state_store
from .activity import hub as activity_hub
from .bg_remove_svc import remove_png_to_path
from .video_frames import extract_frames, reorganize_existing_frames


def animation_dir(animation_id: str) -> str:
    return mu.animation_bundle_dir(animation_id)


def write_metadata(animation_id: str, payload: dict) -> None:
    path = mu.animation_metadata_path(animation_id)
    merged = payload.copy()
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)


def read_metadata(animation_id: str) -> dict | None:
    p = mu.animation_metadata_path(animation_id)
    if not os.path.isfile(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def create_animation_bundle(slug: str, label: str | None = None) -> str:
    aid = mu.slugify(slug or "anim", "anim") + "-" + mu.short_id("")[:8]
    os.makedirs(mu.animation_raw_dir(aid), exist_ok=False)
    os.makedirs(mu.animation_clean_dir(aid), exist_ok=True)

    meta = {
        "id": aid,
        "slug": mu.slugify(slug, "animation"),
        "label": label or mu.slugify(slug, "animation"),
        "video_source": None,
        "frame_interval_sec": None,
        "extract_stats": {},
        "raw_frame_count": 0,
        "clean_frame_count": 0,
        "frame_pattern": "frame_%03d.png",
    }
    write_metadata(aid, meta)
    activity_hub.log("animation_create", aid)
    return aid


def copy_video_into_animation(animation_id: str, video_abs_path: str) -> str:
    ext = os.path.splitext(video_abs_path)[1] or ".mp4"
    dest = mu.animation_subdir(animation_id, f"source{ext}")
    shutil.copy2(video_abs_path, dest)
    meta = read_metadata(animation_id) or {}
    meta["video_source"] = os.path.basename(dest)
    meta["video_relpath"] = "source" + ext
    write_metadata(animation_id, meta)
    return dest


def find_source_video(animation_id: str) -> str | None:
    root = mu.animation_bundle_dir(animation_id)
    try:
        names = os.listdir(root)
    except OSError:
        return None
    for name in sorted(names):
        low = name.lower()
        if low.startswith("source.") and os.path.isfile(mu.animation_bundle_child(animation_id, name)):
            return mu.animation_bundle_child(animation_id, name)
    return None


def run_extract(animation_id: str, interval_sec: float) -> dict:
    raw_dir = mu.animation_raw_dir(animation_id)
    os.makedirs(raw_dir, exist_ok=True)

    vid = find_source_video(animation_id)
    if not vid:
        raise FileNotFoundError("No source video in animation bundle")

    stats = extract_frames(vid, raw_dir, interval_sec)
    reorganize_existing_frames(raw_dir, "frame")
    pngs = [n for n in os.listdir(raw_dir) if n.endswith(".png")]
    meta = read_metadata(animation_id) or {}
    meta["extract_stats"] = stats
    meta["raw_frame_count"] = len(pngs)
    meta["frame_interval_sec"] = interval_sec
    write_metadata(animation_id, meta)
    activity_hub.log("frames_extract", animation_id, {"frames": len(pngs)})
    state_store.bump_counter("animations_processed")
    return stats | {"saved": len(pngs), "folder": animation_id}


def batch_remove_bg(animation_id: str, method: str = "rembg") -> dict:
    raw_dir = mu.animation_raw_dir(animation_id)
    clean_dir = mu.animation_clean_dir(animation_id)
    os.makedirs(clean_dir, exist_ok=True)
    pngs = sorted((n for n in os.listdir(raw_dir) if n.lower().endswith(".png")), key=mu.natural_sort_key)

    cleaned = []
    for name in pngs:
        inp = mu.animation_bundle_child(animation_id, "raw", name)
        out = mu.animation_bundle_child(animation_id, "clean", name)
        remove_png_to_path(inp, out, method=method)
        cleaned.append(name)

    meta = read_metadata(animation_id) or {}
    meta["clean_frame_count"] = len(cleaned)
    meta["bg_removal_method"] = method
    write_metadata(animation_id, meta)
    state_store.bump_counter("bg_removal_runs", len(cleaned))
    activity_hub.log("bg_batch", animation_id, {"cleaned": len(cleaned), "method": method})
    return {"processed": len(cleaned), "names": cleaned}


def ingest_video_into_new_animation(video_path: str, slug: str, interval_sec: float) -> tuple[str, dict]:
    aid = create_animation_bundle(slug)
    copy_video_into_animation(aid, video_path)
    ex = run_extract(aid, interval_sec)
    return aid, {"animation_id": aid, "extract": ex}


def list_frame_urls(animation_id: str, cleaned: bool) -> tuple[list[str], dict]:
    meta = read_metadata(animation_id)
    urls = mu.frame_urls_for_bundle(animation_id, cleaned)
    return urls, meta or {}


def _decode_png_data_url(image_data_url: str) -> bytes:
    payload = image_data_url.strip()
    if "," in payload:
        payload = payload.split(",", 1)[1]
    return base64.b64decode(payload)


def _frame_name_for_index(animation_id: str, frame_index: int, folder: str) -> str:
    root = mu.animation_clean_dir(animation_id) if folder == "clean" else mu.animation_raw_dir(animation_id)
    if os.path.isdir(root):
        names = sorted((n for n in os.listdir(root) if n.lower().endswith(".png")), key=mu.natural_sort_key)
        if 0 <= frame_index < len(names):
            return names[frame_index]
    return f"frame_{frame_index + 1:03d}.png"


def save_edited_frame(
    animation_id: str,
    *,
    frame_index: int,
    image_data_url: str,
    filename: str | None = None,
    folder: str = "clean",
) -> dict:
    """Write edited PNG to ``outputs/<animation_id>/`` and the bundle folder."""
    if folder not in ("raw", "clean"):
        raise ValueError("folder must be raw or clean")

    name = filename or _frame_name_for_index(animation_id, frame_index, folder)
    png_bytes = _decode_png_data_url(image_data_url)

    out_dir = os.path.join(mu.workspace_output_dir(), animation_id)
    os.makedirs(out_dir, exist_ok=True)
    output_abs = os.path.join(out_dir, name)
    with open(output_abs, "wb") as wf:
        wf.write(png_bytes)

    storage_dir = mu.animation_raw_dir(animation_id) if folder == "raw" else mu.animation_clean_dir(animation_id)
    os.makedirs(storage_dir, exist_ok=True)
    storage_abs = os.path.join(storage_dir, name)
    with open(storage_abs, "wb") as wf:
        wf.write(png_bytes)

    activity_hub.log("frame_save", animation_id, {"frame": name, "folder": folder})
    return {
        "filename": name,
        "frame_index": frame_index,
        "folder": folder,
        "output_path": output_abs,
        "output_url": f"/outputs/{animation_id}/{name}",
        "storage_path": storage_abs,
    }


def save_edited_frames_batch(
    animation_id: str,
    frames: list[dict],
    *,
    folder: str = "clean",
) -> dict:
    saved = []
    for item in frames:
        idx = int(item.get("frame_index", item.get("index", 0)))
        image = item.get("image") or item.get("data_url")
        if not image:
            continue
        saved.append(
            save_edited_frame(
                animation_id,
                frame_index=idx,
                image_data_url=image,
                filename=item.get("filename"),
                folder=folder,
            )
        )
    return {"saved": len(saved), "frames": saved, "folder": folder}


def scan_storage_usage() -> dict:
    def size_tree(root: str) -> tuple[int, int]:
        if not os.path.isdir(root):
            return 0, 0
        total = 0
        count = 0
        for dp, _, filenames in os.walk(root):
            for fn in filenames:
                p = os.path.join(dp, fn)
                if os.path.isfile(p):
                    total += os.path.getsize(p)
                    count += 1
        return total, count

    sb, sf = size_tree(mu.STORAGE_ROOT)
    ub, _ = size_tree(mu.workspace_upload_dir())
    ob, _ = size_tree(mu.workspace_output_dir())
    anim_root = mu.animations_root_dir()
    anim_cnt = (
        sum(1 for n in os.listdir(anim_root) if os.path.isdir(mu.animation_bundle_dir(n)))
        if os.path.isdir(anim_root)
        else 0
    )

    return {
        "storage_bytes": sb,
        "storage_files": sf,
        "upload_bytes": ub,
        "output_bytes": ob,
        "animation_bundles": anim_cnt,
    }


def generate_unity_meta(sheet_path: str, slices: list[dict], width: int, height: int) -> None:
    meta_path = sheet_path + ".meta"
    import uuid
    meta_guid = uuid.uuid4().hex
    meta_content = f"""fileFormatVersion: 2
guid: {meta_guid}
TextureImporter:
  internalIDToNameTable: []
  externalObjects: {{}}
  serializedVersion: 13
  mipmaps:
    mipMapMode: 0
    enableMipMap: 0
    sRGBTexture: 1
    linearTexture: 0
    fadeOut: 0
    borderMipMap: 0
    mipMapsPreserveCoverage: 0
    alphaTestReferenceValue: 0.5
    mipMapFadeDistanceStart: 1
    mipMapFadeDistanceEnd: 3
  bumpmap:
    convertToNormalMap: 0
    externalNormalMap: 0
    heightScale: 0.25
    normalMapFilter: 0
  isReadable: 0
  streamingMipmaps: 0
  streamingMipmapsPriority: 0
  vTOnly: 0
  ignorePngAlpha: 0
  grayScaleAsAlpha: 0
  singleChannelComponent: 0
  imageSheet: {{}}
  textureFormat: -1
  maxTextureSize: 2048
  textureSettings:
    serializedVersion: 2
    filterMode: 0
    aniso: 1
    mipBias: 0
    wrapU: 1
    wrapV: 1
    wrapW: 1
  nPOTScale: 0
  lightmap: 0
  compressionQuality: 50
  spriteMode: 2
  spriteExtrude: 1
  spriteMeshType: 1
  alignment: 0
  spritePivot: {{x: 0.5, y: 0.5}}
  spritePixelsToUnits: 100
  spriteBorder: {{x: 0, y: 0, z: 0, w: 0}}
  spriteGenerateFallbackPhysicsShape: 1
  alphaUsage: 1
  alphaIsTransparency: 1
  spriteTessellationDetail: -1
  dirty: 0
  spriteSheet:
    serializedVersion: 2
    sprites:
"""
    for i, s in enumerate(slices):
        sprite_guid = uuid.uuid4().hex
        meta_content += f"""      - serializedVersion: 2
        name: {s['name']}
        rect:
          serializedVersion: 2
          x: {s['x']}
          y: {s['y']}
          width: {s['width']}
          height: {s['height']}
        alignment: 0
        pivot: {{x: 0.5, y: 0.5}}
        border: {{x: 0, y: 0, z: 0, w: 0}}
        outline: []
        physicsShape: []
        tessellationDetail: 0
        bones: []
        spriteID: {sprite_guid[:16]}-{sprite_guid[16:]}
        internalID: {21300000 + i * 2}
"""
    
    meta_content += """    outline: []
    physicsShape: []
    bones: []
    spriteID: 
    internalID: 0
  spritePackingTag: 
  pSDRemoveMatte: 0
  pSDShowGrid: 0
  pSDRemoveMatteSetting: 0
  pSDKeepAlphaSetting: 0
  pSDAlphaToleranceSetting: 0
  pSDTransparentPaddingSetting: 0
  pSDColorFormatSetting: 0
  pSDLayerSettings: []
  userData: 
  assetBundleName: 
  assetBundleVariant: 
"""
    with open(meta_path, "w", encoding="utf-8") as wf:
        wf.write(meta_content)


def pack_sprite_sheet(animation_id: str, folder: str = "clean") -> dict:
    import math
    from PIL import Image

    source_dir = mu.animation_clean_dir(animation_id) if folder == "clean" else mu.animation_raw_dir(animation_id)
    if not os.path.isdir(source_dir):
        raise FileNotFoundError(f"Folder {folder} not found in bundle {animation_id}")

    frame_names = sorted((n for n in os.listdir(source_dir) if n.lower().endswith(".png")), key=mu.natural_sort_key)
    if not frame_names:
        raise ValueError("No PNG frames found to pack")

    frames = []
    max_w = 0
    max_h = 0
    for name in frame_names:
        img_path = os.path.join(source_dir, name)
        img = Image.open(img_path)
        frames.append((name, img))
        max_w = max(max_w, img.width)
        max_h = max(max_h, img.height)

    count = len(frames)
    cols = int(math.ceil(math.sqrt(count)))
    rows = int(math.ceil(count / cols))

    sheet_w = cols * max_w
    sheet_h = rows * max_h
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))

    slices = []
    for i, (name, img) in enumerate(frames):
        c = i % cols
        r = i // cols
        x = c * max_w
        y = r * max_h
        sheet.paste(img, (x, y))

        y_unity = sheet_h - (r + 1) * max_h
        slices.append({
            "name": os.path.splitext(name)[0],
            "x": x,
            "y": y_unity,
            "width": max_w,
            "height": max_h
        })

    output_dir = os.path.join(mu.workspace_output_dir(), animation_id)
    os.makedirs(output_dir, exist_ok=True)
    sheet_name = f"{animation_id}_spritesheet.png"
    output_path = os.path.join(output_dir, sheet_name)
    sheet.save(output_path, "PNG")

    unity_base_frames = os.environ.get(
        "UNITY_FRAMES_DIR",
        os.path.join(mu.BASE_DIR, "exports", "unity", "Assets", "Animations", "Frames")
    )
    unity_frames_dir = os.path.join(unity_base_frames, animation_id)
    os.makedirs(unity_frames_dir, exist_ok=True)
    unity_sheet_path = os.path.join(unity_frames_dir, sheet_name)
    shutil.copy2(output_path, unity_sheet_path)

    generate_unity_meta(unity_sheet_path, slices, sheet_w, sheet_h)

    for _, img in frames:
        img.close()

    return {
        "filename": sheet_name,
        "columns": cols,
        "rows": rows,
        "frame_width": max_w,
        "frame_height": max_h,
        "total_width": sheet_w,
        "total_height": sheet_h,
        "output_url": f"/outputs/{animation_id}/{sheet_name}",
        "unity_path": unity_sheet_path
    }
