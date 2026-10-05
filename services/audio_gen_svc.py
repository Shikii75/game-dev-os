"""Procedural WAV placeholder SFX (+ light Nyxaris-style layers)."""

from __future__ import annotations

import io
import os
import wave

import numpy as np

from . import media_utils as mu
from .activity import hub as activity_hub


def _pcm_wav(samples_i16: np.ndarray, samplerate: int = 44100) -> bytes:
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(samplerate)
        w.writeframes(samples_i16.tobytes())
    return bio.getvalue()


def nyx_ambient_wave(duration_sec: float = 1.8, glitch: float = 0.35, seed: int | None = None) -> tuple[bytes, str]:
    rng = np.random.default_rng(seed)
    sr = 44100
    n = int(sr * duration_sec)
    t = np.linspace(0, duration_sec, n, endpoint=False)

    shimmer = rng.normal(0, 0.04, size=n).astype(np.float64)
    low = np.sin(2 * np.pi * (90 + glitch * 30) * t) * 0.06
    body = shimmer + low

    glitch_mask = rng.random(n) < glitch * 0.03
    body = body.copy()
    body[glitch_mask] *= 4.8
    body = np.clip(body, -1, 1)

    pcm16 = np.clip(body * 28000, -32767, 32767).astype(np.int16)
    rid = rng.integers(0, 2**31 - 1)
    return _pcm_wav(pcm16, sr), f"nyx_amb_{rid:08x}"


def random_ui_beep(freqs=(440, 660, 880), duration_sec=0.12, seed: int | None = None) -> tuple[bytes, str]:
    rng = np.random.default_rng(seed)
    sr = 44100
    n = int(sr * duration_sec)
    freq = float(rng.choice(np.array(freqs, dtype=float)))

    ramp = np.linspace(0.0, 1.0, n)
    envelope = ramp * np.flip(ramp)
    t = np.linspace(0, duration_sec, n)
    tone = envelope * np.sin(2 * np.pi * freq * t)
    pcm = np.clip(tone * 26000, -32767, 32767).astype(np.int16)
    return _pcm_wav(pcm, sr), "ui_beep_" + mu.short_id("")[:10]


def combat_pop(seed: int | None = None) -> tuple[bytes, str]:
    rng = np.random.default_rng(seed)
    sr = 44100
    dur = 0.22
    n = int(sr * dur)
    t = np.linspace(0, dur, n)
    sweep = np.linspace(800, 60, n)
    phase = np.cumsum(2 * np.pi * sweep / sr)
    boom = np.sin(phase)
    boom *= np.exp(-8 * t)
    hiss = rng.normal(0, 0.18, size=n) * np.exp(-12 * t)
    pcm = np.clip((boom + hiss) * 22000, -32767, 32767).astype(np.int16)
    return _pcm_wav(pcm, sr), "hit_pop_" + mu.short_id("")[:8]


def slug_cat(category: str) -> str:
    return mu.slugify(category, "gen")


def save_pack(
    *,
    preset: str,
    nyx_ambient_count: int = 0,
    ui_count: int = 0,
    combat_count: int = 0,
) -> list[dict]:
    """Writes under storage/audio/generated/<preset_slug>/."""

    slug = mu.slugify(preset or "placeholder", "sfx_pack")
    out_dir = os.path.join(mu.audio_store_root_dir(), "generated", slug)
    os.makedirs(out_dir, exist_ok=True)

    manifest = []

    rng_base = hash(slug) & 0xFFFFFFFF

    idx = 0
    for _ in range(max(0, ui_count)):
        data, nid = random_ui_beep(seed=rng_base + idx)
        fname = nid + ".wav"
        _write_file(os.path.join(out_dir, fname), data)
        manifest.append({"id": nid, "file": fname, "type": "ui", "relative_dir": "generated/" + slug})
        idx += 1

    for _ in range(max(0, combat_count)):
        data, nid = combat_pop(seed=rng_base + idx)
        fname = nid + ".wav"
        _write_file(os.path.join(out_dir, fname), data)
        manifest.append({"id": nid, "file": fname, "type": "combat", "relative_dir": "generated/" + slug})
        idx += 1

    for _ in range(max(0, nyx_ambient_count)):
        data, nid = nyx_ambient_wave(seed=rng_base + idx + 997)
        fname = nid + ".wav"
        _write_file(os.path.join(out_dir, fname), data)
        manifest.append({"id": nid, "file": fname, "type": "nyx_ambient", "relative_dir": "generated/" + slug})
        idx += 1

    activity_hub.log("audio_generated", preset, {"files": len(manifest)})
    return manifest


def _write_file(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)
