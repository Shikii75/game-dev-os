"""
Voice & Audio Slicer Service
High-performance WAV audio inspector, speech/silence detector, slice processor,
micro-fade smoother, normalizer, and dual Unity + Game Dev OS exporter.
"""

from __future__ import annotations

import os
import io
import uuid
import zipfile
import numpy as np
import scipy.io.wavfile as wavfile
from typing import List, Dict, Any, Optional

from . import media_utils as mu

# Default paths
UNITY_PROJECT_AUDIO_DIR = os.path.normpath(r"C:\Users\tyram\The Spawn of Chaos\Assets\Audio\Voice")
STORAGE_AUDIO_VOICE_DIR = os.path.normpath(os.path.join(mu.audio_store_root_dir(), "voice"))
CACHE_TEMP_DIR = os.path.normpath(os.path.join(mu.DATA_DIR, "audio_slicer_cache"))

os.makedirs(CACHE_TEMP_DIR, exist_ok=True)
os.makedirs(STORAGE_AUDIO_VOICE_DIR, exist_ok=True)
if os.path.exists(os.path.dirname(UNITY_PROJECT_AUDIO_DIR)):
    os.makedirs(UNITY_PROJECT_AUDIO_DIR, exist_ok=True)


def get_cached_file_path(file_id: str) -> str:
    """Returns absolute path to a cached uploaded WAV file."""
    return os.path.join(CACHE_TEMP_DIR, f"{file_id}.wav")


def inspect_and_cache_wav(file_storage) -> Dict[str, Any]:
    """
    Saves uploaded WAV file into cache, reads audio headers and samples,
    and returns duration, sample rate, channels, bit depth, and downsampled waveform peaks.
    """
    file_id = str(uuid.uuid4())
    save_path = get_cached_file_path(file_id)
    file_storage.save(save_path)

    try:
        sr, data = wavfile.read(save_path)
    except Exception as e:
        if os.path.exists(save_path):
            os.remove(save_path)
        raise ValueError(f"Invalid or corrupted WAV file: {e}")

    num_samples = len(data)
    channels = 1 if data.ndim == 1 else data.shape[1]
    duration_sec = num_samples / float(sr)
    dtype_name = str(data.dtype)

    # Compute downsampled waveform peaks (1200 points for smooth canvas rendering)
    target_points = 1200
    peaks = []

    if np.issubdtype(data.dtype, np.integer):
        max_int = float(np.iinfo(data.dtype).max)
        norm_data = (data[:, 0] if channels > 1 else data).astype(np.float32) / (max_int + 1e-9)
    else:
        norm_data = (data[:, 0] if channels > 1 else data).astype(np.float32)

    step = max(1, len(norm_data) // target_points)
    for i in range(0, len(norm_data), step):
        chunk = norm_data[i:i + step]
        if len(chunk) > 0:
            c_min = float(np.min(chunk))
            c_max = float(np.max(chunk))
            peaks.append({"min": round(c_min, 3), "max": round(c_max, 3)})

    return {
        "file_id": file_id,
        "filename": getattr(file_storage, "filename", "voice_recording.wav"),
        "duration": round(duration_sec, 3),
        "sample_rate": sr,
        "channels": channels,
        "bit_depth": dtype_name,
        "samples_count": num_samples,
        "peaks": peaks,
        "stream_url": f"/api/audio-slicer/stream/{file_id}"
    }


def detect_silence_regions(
    file_id: str,
    silence_thresh_db: float = -36.0,
    min_silence_sec: float = 0.28,
    min_speech_sec: float = 0.12,
    pad_sec: float = 0.05
) -> List[Dict[str, float]]:
    """
    Vectorized speech detector that identifies sound bursts separated by natural pauses.
    Returns a list of candidate slice intervals [{'start': float, 'end': float, 'duration': float}].
    """
    file_path = get_cached_file_path(file_id)
    if not os.path.isfile(file_path):
        raise FileNotFoundError("Audio file expired or not found in cache.")

    sr, data = wavfile.read(file_path)

    if data.ndim > 1:
        mono = np.mean(data, axis=1).astype(np.float32)
    else:
        mono = data.astype(np.float32)

    if np.issubdtype(data.dtype, np.integer):
        max_int = float(np.iinfo(data.dtype).max)
        norm = mono / (max_int + 1e-9)
    else:
        norm = mono

    max_val = np.max(np.abs(norm))
    if max_val > 0:
        norm = norm / max_val
    else:
        return []

    window_size = int(sr * 0.02)
    hop_size = int(sr * 0.01)
    if len(norm) < window_size:
        return [{"start": 0.0, "end": round(len(norm) / sr, 3), "duration": round(len(norm) / sr, 3)}]

    frames = np.lib.stride_tricks.sliding_window_view(norm, window_size)[::hop_size]
    rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-9)
    db = 20.0 * np.log10(rms + 1e-9)

    is_speech = db > silence_thresh_db

    regions = []
    in_speech = False
    start_frame = 0

    for i, active in enumerate(is_speech):
        if active and not in_speech:
            in_speech = True
            start_frame = i
        elif not active and in_speech:
            in_speech = False
            start_sec = max(0.0, (start_frame * hop_size) / sr - pad_sec)
            end_sec = min(len(norm) / sr, (i * hop_size + window_size) / sr + pad_sec)
            if end_sec - start_sec >= min_speech_sec:
                regions.append({"start": round(start_sec, 3), "end": round(end_sec, 3)})

    if in_speech:
        start_sec = max(0.0, (start_frame * hop_size) / sr - pad_sec)
        end_sec = len(norm) / sr
        if end_sec - start_sec >= min_speech_sec:
            regions.append({"start": round(start_sec, 3), "end": round(end_sec, 3)})

    merged = []
    for r in regions:
        if not merged:
            merged.append(r)
        else:
            prev = merged[-1]
            if r["start"] - prev["end"] < min_silence_sec:
                prev["end"] = max(prev["end"], r["end"])
            else:
                merged.append(r)

    for r in merged:
        r["duration"] = round(r["end"] - r["start"], 3)

    return merged


def slice_and_export(
    file_id: str,
    slices_data: List[Dict[str, Any]],
    apply_micro_fades: bool = True,
    normalize_volume: bool = True,
    target_peak_db: float = -0.5,
    export_to_unity: bool = True,
    export_to_storage: bool = True
) -> Dict[str, Any]:
    """
    Slices cached WAV into individual named audio files, applies 5ms anti-click micro-fades
    and optional normalization, and writes them directly into Unity and Game Dev OS storage.
    """
    file_path = get_cached_file_path(file_id)
    if not os.path.isfile(file_path):
        raise FileNotFoundError("Source audio file expired or not found.")

    sr, data = wavfile.read(file_path)
    total_samples = len(data)
    fade_samples = max(16, int(sr * 0.005)) # 5ms anti-click fade

    is_integer = np.issubdtype(data.dtype, np.integer)
    max_dtype_val = float(np.iinfo(data.dtype).max) if is_integer else 1.0
    min_dtype_val = float(np.iinfo(data.dtype).min) if is_integer else -1.0
    target_peak_linear = (10.0 ** (target_peak_db / 20.0)) * max_dtype_val

    results = []
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for idx, s in enumerate(slices_data):
            start_sec = max(0.0, float(s.get("start", 0.0)))
            end_sec = min(total_samples / float(sr), float(s.get("end", 0.0)))
            if end_sec <= start_sec:
                continue

            start_idx = int(round(start_sec * sr))
            end_idx = int(round(end_sec * sr))
            if end_idx - start_idx < 100:
                continue

            slice_data = data[start_idx:end_idx].copy()

            # Apply 5ms micro-fade in and out
            if apply_micro_fades and len(slice_data) > (fade_samples * 2):
                fade_in = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
                fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
                if slice_data.ndim == 1:
                    slice_data[:fade_samples] = (slice_data[:fade_samples].astype(np.float32) * fade_in).astype(data.dtype)
                    slice_data[-fade_samples:] = (slice_data[-fade_samples:].astype(np.float32) * fade_out).astype(data.dtype)
                else:
                    slice_data[:fade_samples, :] = (slice_data[:fade_samples, :].astype(np.float32) * fade_in[:, None]).astype(data.dtype)
                    slice_data[-fade_samples:, :] = (slice_data[-fade_samples:, :].astype(np.float32) * fade_out[:, None]).astype(data.dtype)

            # Volume Normalization
            if normalize_volume:
                cur_peak = float(np.max(np.abs(slice_data)))
                if cur_peak > 1e-4:
                    gain = target_peak_linear / cur_peak
                    normed = slice_data.astype(np.float32) * gain
                    slice_data = np.clip(normed, min_dtype_val, max_dtype_val).astype(data.dtype)

            category = mu.slugify(s.get("category", "Uncategorized"))
            label = s.get("name", "").strip() or f"clip_{idx+1:02d}"
            if not label.lower().endswith(".wav"):
                label = f"{mu.slugify(label)}.wav"
            else:
                label = f"{mu.slugify(label[:-4])}.wav"

            # 1. Write to Game Dev OS storage
            storage_path = None
            if export_to_storage:
                cat_dir = os.path.join(STORAGE_AUDIO_VOICE_DIR, category)
                os.makedirs(cat_dir, exist_ok=True)
                storage_path = os.path.join(cat_dir, label)
                wavfile.write(storage_path, sr, slice_data)

            # 2. Write directly to Unity Assets/Audio/Voice/<Category>/
            unity_path = None
            if export_to_unity:
                cat_unity_dir = os.path.join(UNITY_PROJECT_AUDIO_DIR, category)
                os.makedirs(cat_unity_dir, exist_ok=True)
                unity_path = os.path.join(cat_unity_dir, label)
                wavfile.write(unity_path, sr, slice_data)

            # 3. Add to ZIP
            slice_bytes = io.BytesIO()
            wavfile.write(slice_bytes, sr, slice_data)
            zipf.writestr(f"{category}/{label}", slice_bytes.getvalue())

            results.append({
                "index": idx + 1,
                "name": label,
                "category": category,
                "start": start_sec,
                "end": end_sec,
                "duration": round(end_sec - start_sec, 3),
                "unity_path": unity_path,
                "storage_path": storage_path,
                "stream_url": f"/media/audio/voice/{category}/{label}" if storage_path else None
            })

    # Cache the zip file for one-click browser download
    zip_id = str(uuid.uuid4())
    zip_path = os.path.join(CACHE_TEMP_DIR, f"{zip_id}.zip")
    with open(zip_path, "wb") as f:
        f.write(zip_buffer.getvalue())

    return {
        "success": True,
        "exported_count": len(results),
        "slices": results,
        "zip_url": f"/api/audio-slicer/download-zip/{zip_id}",
        "unity_folder": UNITY_PROJECT_AUDIO_DIR if export_to_unity else None,
        "storage_folder": STORAGE_AUDIO_VOICE_DIR if export_to_storage else None
    }
