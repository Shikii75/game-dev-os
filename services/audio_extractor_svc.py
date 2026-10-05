"""
Service to extract audio clips from video files using imageio-ffmpeg.
Supports PyInstaller packaged apps by locating the bundled binary at runtime.
"""

from __future__ import annotations

import os
import sys
import subprocess
from . import media_utils as mu
from .activity import hub as activity_hub

def get_ffmpeg_path() -> str:
    """
    Finds the FFmpeg executable bundled with imageio-ffmpeg or in PyInstaller _MEIPASS.
    """
    # 1. Try importing imageio_ffmpeg (standard python environment)
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.isfile(path):
            return path
    except Exception as e:
        print(f"Error getting ffmpeg path via imageio_ffmpeg: {e}", file=sys.stderr)

    # 2. Try walking _MEIPASS (PyInstaller frozen mode bundle)
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            # Check standard imageio_ffmpeg subdirectory first
            cand = os.path.join(meipass, "imageio_ffmpeg", "binaries", "ffmpeg-win64-v4.2.2.exe")
            if os.path.isfile(cand):
                return cand
            
            # General fallback search in _MEIPASS
            for root, dirs, files in os.walk(meipass):
                for f in files:
                    if f.lower() in ("ffmpeg", "ffmpeg.exe"):
                        return os.path.join(root, f)

    # 3. Fallback to system-wide path
    return "ffmpeg"


def extract_audio_segment(
    video_relative_path: str,
    start_time: float,
    end_time: float,
    slug: str,
    category: str,
    mono: bool = False
) -> dict:
    """
    Extracts a segment of audio from a video asset and saves it to storage/audio/<category>.
    Returns the metadata of the newly created WAV asset.
    """
    # 1. Resolve video source path
    video_abs_path = os.path.join(mu.videos_store_dir(), video_relative_path)
    if not os.path.isfile(video_abs_path):
        raise FileNotFoundError(f"Video file not found in storage: {video_relative_path}")

    # 2. Determine target path
    clean_slug = mu.slugify(slug or "clip")
    filename = f"{clean_slug}.wav"
    output_dir = mu.storage_bucket_abs("audio", audio_category=category)
    output_abs_path = os.path.join(output_dir, filename)

    os.makedirs(output_dir, exist_ok=True)

    # 3. Locate ffmpeg
    ffmpeg_exe = get_ffmpeg_path()
    
    # Ensure times are logical
    if start_time < 0:
        start_time = 0.0
    if end_time <= start_time:
        raise ValueError("End time must be greater than start time")

    duration = end_time - start_time
    channels = "1" if mono else "2"

    # Command parameters:
    # -y: overwrite output
    # -ss: start time (efficient seeking before input)
    # -t: duration
    # -vn: disable video recording
    # -acodec pcm_s16le: CD quality WAV format
    # -ar 44100: standard sample rate for audio
    # -ac: number of audio channels (1 = mono, 2 = stereo)
    cmd = [
        ffmpeg_exe,
        "-y",
        "-ss", f"{start_time:.3f}",
        "-t", f"{duration:.3f}",
        "-i", video_abs_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", channels,
        output_abs_path
    ]

    print(f"Executing extraction: {' '.join(cmd)}")
    
    # Run FFmpeg
    # Startupinfo stops console window popups on Windows when running electron/gui
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        startupinfo=startupinfo,
        check=False
    )

    if result.returncode != 0:
        error_msg = result.stderr or "Unknown error"
        raise RuntimeError(f"FFmpeg audio extraction failed: {error_msg}")

    if not os.path.isfile(output_abs_path):
        raise RuntimeError("FFmpeg succeeded but target file was not created.")

    # 4. Generate metadata response
    from datetime import datetime, timezone
    meta = {
        "id": clean_slug,
        "filename": filename,
        "original_video": video_relative_path,
        "kind": "audio",
        "audio_category": category,
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "url": mu.media_url_from_absolute_project_path(output_abs_path),
        "size": os.path.getsize(output_abs_path),
        "mono": mono
    }
    
    # Log to dashboard activity tracker
    activity_hub.log("audio_extraction", f"Extracted {filename} ({category}) from {video_relative_path}")
    
    return meta
