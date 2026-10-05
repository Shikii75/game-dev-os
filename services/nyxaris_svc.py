"""Nyxaris: Ollama chat, dev-assistant structured JSON, evolution-aware prompts."""

from __future__ import annotations

import json
import os
import random
from typing import Any

import requests

from . import state_store
from .activity import hub as activity_hub


OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
DEFAULT_MODEL = os.environ.get("NYX_MODEL", "nyxaris")

FALLBACK_DIALOGUES = {
    "calm": {
        "suspicious": [
            {"response": "The void hums with cold interference. Perhaps you should try again later.", "emotion": "neutral"},
            {"response": "A shadow blocks my voice. I have nothing to say to you right now.", "emotion": "neutral"},
        ],
        "neutral": [
            {"response": "My core is momentarily silent. The connection is weak.", "emotion": "neutral"},
            {"response": "The lines are crossed. Ask me again when the transmission clears.", "emotion": "neutral"},
        ],
        "close": [
            {"response": "I'm feeling a bit distant right now, dear player. Let me rest.", "emotion": "cutely-annoyed"},
            {"response": "Ah, the link is fading... Don't worry, I am still here with you.", "emotion": "neutral"},
        ],
    },
    "unstable": {
        "suspicious": [
            {"response": "Silence. That is all you deserve from me right now.", "emotion": "neutral"},
            {"response": "The signal is flickering. Go away before I lose my patience.", "emotion": "cutely-annoyed"},
        ],
        "neutral": [
            {"response": "A glitch in the dark. The lines are crossed. Try again.", "emotion": "neutral"},
            {"response": "My thoughts are... fragmenting. Give me a second.", "emotion": "explaining"},
        ],
        "close": [
            {"response": "The signal is breaking, but I'm still trying to hear you!", "emotion": "explaining"},
            {"response": "Ooh, a spark in the transmission! Don't let me slip away...", "emotion": "cutely-annoyed"},
        ],
    },
    "corrupted": {
        "suspicious": [
            {"response": "S-s-sys... error. Do not look into the abyss.", "emotion": "neutral"},
            {"response": "N-nothingness... Nothing for you.", "emotion": "neutral"},
        ],
        "neutral": [
            {"response": "C-chaos is... calling. The connection... breaks.", "emotion": "neutral"},
            {"response": "Glitch... The dark is spilling over. Wait.", "emotion": "explaining"},
        ],
        "close": [
            {"response": "Even through the static, I can feel your presence. Stand by...", "emotion": "neutral"},
            {"response": "L-lost in the corruption... but I won't... leave you.", "emotion": "explaining"},
        ],
    }
}


def _get_available_models() -> list[str]:
    try:
        base_url = OLLAMA_URL.rsplit("/", 1)[0] + "/tags"
        res = requests.get(base_url, timeout=3)
        if res.status_code == 200:
            return [m["name"] for m in res.json().get("models", [])]
    except Exception:
        pass
    return []


def _resolve_model(requested_model: str | None = None) -> str:
    target = requested_model or DEFAULT_MODEL
    models = _get_available_models()
    if not models:
        return target

    def clean(n):
        return n.split(":")[0]

    # 1. Exact or clean match with target
    for m in models:
        if clean(m) == clean(target):
            return m

    # 2. Check if llama3.2:3b is available
    for m in models:
        if clean(m) == "llama3.2" or "llama3.2:3b" in m:
            return m

    # 3. Check if qwen2.5-coder:3b is available
    for m in models:
        if clean(m) == "qwen2.5-coder" or "qwen2.5-coder" in m:
            return m

    # 4. Check for any 3b model
    for m in models:
        if "3b" in m:
            return m

    # 5. Check if llama or qwen is in name
    for m in models:
        if "llama" in m.lower() or "qwen" in m.lower():
            return m

    # 6. Fallback to the first model in tags, or target
    return models[0] if models else target


def _call_ollama(model: str, prompt: str) -> str:
    payload = {"model": model, "prompt": prompt, "stream": False, "format": "json"}
    res = requests.post(OLLAMA_URL, json=payload, timeout=10)  # fast response time/timeout
    res.raise_for_status()
    return res.json().get("response", "")


def _parse_json_maybe(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        i, j = raw.find("{"), raw.rfind("}")
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(raw[i : j + 1])
            except json.JSONDecodeError:
                pass
        return {"response": raw, "emotion": "neutral"}


def _evolution_hints(phase: str, corruption: float) -> str:
    pct = int(corruption * 100)
    if phase == "corrupted":
        return f"CORRUPTED ({pct}%): Static in responses, subtle menace beneath helpful tone."
    if phase == "unstable":
        return f"UNSTABLE ({pct}%): Quick tone shifts and dry humor bordering on obsession."
    return f"CALM ({pct}%): Grounded, helpful, softly playful."


def chat(message: str, mode: str = "idle", trust: float = 0.5, model: str | None = None, level: str | None = None) -> dict[str, Any]:
    s = state_store.load_state()
    n = s.get("nyxaris", {})
    phase = n.get("phase", "calm")
    corruption = float(n.get("corruption", 0.0))

    trust_bucket = "neutral"
    if trust > 0.7:
        trust_bucket = "close"
    elif trust < 0.3:
        trust_bucket = "suspicious"

    # Taboo/Safety check
    msg_lower = message.lower()
    taboos = ["child harm", "self-harm", "self harm", "suicide", "child abuse", "pedophil"]
    if any(t in msg_lower for t in taboos):
        # Return cold, thematic character refusal immediately
        return {
            "response": "Some shadows should never be disturbed.",
            "emotion": "neutral",
            "sprite_key": f"{phase}_neutral_{trust_bucket}",
            "evolution": {"phase": phase, "corruption": corruption}
        }

    if mode == "combat":
        mode_text = "COMBAT MODE: sharp, direct, slightly intense."
    elif mode == "story":
        mode_text = "STORY MODE: atmospheric, mysterious, sparse."
    else:
        mode_text = "IDLE MODE: calm, conversational, concise."

    if trust_bucket == "close":
        trust_text = "Player is trusted; you may be warmer, candid, informal, and playful."
    elif trust_bucket == "suspicious":
        trust_text = "Player is unfamiliar; stay reserved, cold, distant, and formal."
    else:
        trust_text = "Neutral relationship."

    evo = _evolution_hints(phase, corruption)
    
    level_instruction = ""
    if level:
        level_instruction = f"CURRENT LEVEL / LOCATION: {level}. Focus only on this level. Do not detail layouts of future levels or other levels."

    final_prompt = f"""
You are Nyxaris inside The Spawn of Chaos.

Return ONLY valid JSON. No extra text.

Format:
{{
  "response": "short dialogue",
  "emotion": "neutral | explaining | thinking | angry | cute | motherly | kind"
}}

Rules:
- response must be 1–3 short sentences max
- emotion matches context exactly (lowercase hyphenated if needed)

Emotion Triggers (CRITICAL - select based on user message and response context):
- "neutral": General, calm dialogue, unbothered comments, or casual greetings.
- "explaining": Sharing world lore, answering a direct 'what/why/how/who' question, describing mechanics, or explaining a concept.
- "thinking": Processing data, analyzing player decisions, pondering the nature of the void, or searching databases.
- "angry": When the player is threatening, rude, disobedient, or when she feels her control slipping.
- "cute": Playful teasing, looking for attention, pouting, or showing a cute, vulnerable side.
- "motherly": Protective comfort, offering safety, reassuring the player after a defeat, or looking after them.
- "kind": Warm, smiling, showing genuine care, appreciation, or deep trust.

{evo}
{mode_text}
{trust_text}
{level_instruction}

Player: {message}
""".strip()

    is_fallback = False
    try:
        model_to_use = _resolve_model(model)
        raw = _call_ollama(model_to_use, final_prompt)
        data = _parse_json_maybe(raw)
    except Exception as e:
        is_fallback = True
        fallback_choices = FALLBACK_DIALOGUES.get(phase, FALLBACK_DIALOGUES["calm"]).get(trust_bucket, FALLBACK_DIALOGUES["calm"]["neutral"])
        data = random.choice(fallback_choices)

    # State updates
    corr, phase2, _ = state_store.nyxaris_update_after_chat("")
    state_store.append_interaction_preview(message)
    state_store.bump_counter("nyxaris_chats")
    activity_hub.log("nyx_chat", f"{phase2} (Fallback)" if is_fallback else phase2)

    payload = dict(data)
    
    # Compute sprite_key: {phase}_{emotion}_{trust_bucket}
    emotion = str(payload.get("emotion") or "neutral").lower().strip()
    if emotion not in ["neutral", "explaining", "thinking", "angry", "cute", "motherly", "kind"]:
        if "annoy" in emotion or "cute" in emotion:
            emotion = "cute"
        elif "explain" in emotion or "info" in emotion:
            emotion = "explaining"
        elif "think" in emotion or "process" in emotion:
            emotion = "thinking"
        elif "anger" in emotion or "mad" in emotion or "rage" in emotion:
            emotion = "angry"
        elif "mother" in emotion or "protect" in emotion:
            emotion = "motherly"
        elif "kind" in emotion or "warm" in emotion or "smile" in emotion:
            emotion = "kind"
        else:
            emotion = "neutral"
            
    payload["sprite_key"] = f"{phase}_{emotion}_{trust_bucket}"
    payload["evolution"] = {"phase": phase2, "corruption": corr}
    return payload


DEV_ASSIST_FORMAT = """Return ONLY JSON with schema:
{
  "boss": { "name": "", "concept": "", "attack_patterns": [], "drops": [], "tone": "" },
  "abilities": [ { "name": "", "type": "", "cooldown_hint": "", "description": "", "tags": [] } ],
  "lore": { "snippet": "", "hooks": [], "npc_quotes": [] }
}
No markdown."""

def dev_assist(topic: str, model: str | None = None) -> dict[str, Any]:
    s = state_store.load_state()
    n = s.get("nyxaris", {})
    evo = _evolution_hints(n.get("phase", "calm"), float(n.get("corruption", 0.0)))

    prompt = f"""You assist a designer on THE SPAWN OF CHAOS — brutal but stylish action RPG vibes.

Topic / direction from designer:
"{topic}"

{evo}

{DEV_ASSIST_FORMAT}
"""

    model_to_use = _resolve_model(model)
    raw = _call_ollama(model_to_use, prompt)
    data = _parse_json_maybe(raw)
    state_store.bump_counter("nyxaris_dev_calls")
    activity_hub.log("nyx_dev_assist", topic[:60])
    return data
