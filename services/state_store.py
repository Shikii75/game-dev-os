"""Persistent JSON game state (pipeline metrics + companion interaction + styles)."""

from __future__ import annotations

import json
import os
import threading
import uuid
from copy import deepcopy
from pathlib import Path

from .media_utils import DATA_DIR, STATE_PATH, slugify


DEFAULT_STATE = {
    "counts": {
        "asset_uploads": 0,
        "animations_processed": 0,
        "audio_uploads": 0,
        "bg_removal_runs": 0,
        "pipeline_runs": 0,
        "companion_chats": 0,
        "companion_dev_calls": 0,
    },
    "companion": {"trust": 0.5, "interaction_count": 0, "phase": "calm"},
    "styles": [],
    "interaction_log_sample": [],
}


_lock = threading.Lock()


def ensure_state_file():
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    if not Path(STATE_PATH).exists():
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_STATE, f, indent=2)


def load_state() -> dict:
    ensure_state_file()
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    merged = deepcopy(DEFAULT_STATE)
    merged.update(data)
    if "counts" in data:
        merged["counts"] = {**DEFAULT_STATE["counts"], **data["counts"]}
    if "companion" in data:
        merged["companion"] = {**DEFAULT_STATE["companion"], **data["companion"]}
    return merged


def save_state(data: dict) -> None:
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, STATE_PATH)


def bump_counter(key: str, amount: int = 1):
    with _lock:
        s = load_state()
        s["counts"][key] = s["counts"].get(key, 0) + amount
        save_state(s)


def companion_update_after_chat(evolution_prompt_suffix: str = "") -> tuple[float, str, str]:
    """Advance companion interaction trust/phase slightly; returns (trust, phase, suffix)."""
    with _lock:
        s = load_state()
        comp = s.setdefault("companion", {"trust": 0.5, "interaction_count": 0, "phase": "calm"})
        trust = float(comp.get("trust", 0.5))
        comp["interaction_count"] = comp.get("interaction_count", 0) + 1
        trust = min(1.0, trust + 0.02)
        comp["trust"] = trust
        if trust < 0.35:
            phase = "reserved"
        elif trust < 0.70:
            phase = "neutral"
        else:
            phase = "friendly"
        comp["phase"] = phase
        save_state(s)
        return trust, phase, evolution_prompt_suffix


nyxaris_update_after_chat = companion_update_after_chat


def append_interaction_preview(text: str, max_keep: int = 30):
    with _lock:
        s = load_state()
        samp = s.setdefault("interaction_log_sample", [])
        samp.append(text[:500])
        s["interaction_log_sample"] = samp[-max_keep:]
        save_state(s)


def get_style_presets() -> list:
    return load_state().get("styles", [])


def upsert_style(name: str, tags: list, rules: str) -> dict:
    with _lock:
        s = load_state()
        styles = s.setdefault("styles", [])
        sid = slugify(name, "style")
        for st in styles:
            if st.get("name") == name or st.get("id") == sid:
                st["tags"] = tags
                st["rules"] = rules
                save_state(s)
                return st
        entry = {"id": sid or "style-" + uuid.uuid4().hex[:8], "name": name, "tags": tags, "rules": rules}
        styles.append(entry)
        save_state(s)
        return entry
