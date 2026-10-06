from flask import Flask, jsonify, render_template, request, send_file, send_from_directory
import os
import uuid
import cv2
from services import media_utils as mu
from services import state_store

# 1. Initialization
mu.seed_user_workspace()
state_store.ensure_state_file()

app = Flask(
    __name__,
    template_folder=os.path.join(mu.RESOURCE_ROOT, "templates"),
    static_folder=os.path.join(mu.RESOURCE_ROOT, "static"),
)

# 2. Core Rembg Logic (Stays in main app file)
def _remove_bg(data: bytes) -> bytes:
    try:
        from rembg import remove
        from PIL import Image
        import numpy as np
        result = remove(data)
        if isinstance(result, bytes):
            return result
        if isinstance(result, Image.Image):
            img = result
        else:
            img = Image.fromarray(np.asarray(result))
        output = __import__('io').BytesIO()
        img.save(output, format="PNG")
        return output.getvalue()
    except Exception as e:
        # Fallback if rembg/onnx is memory constrained on free tier
        return data


# 3. Main Routes
@app.route("/")
@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

@app.route("/health")
@app.route("/api/status")
def api_status():
    return "Game Asset Tool API is running\n", 200, {"Content-Type": "text/plain; charset=utf-8"}

@app.route("/api/ping")
def api_ping():
    return jsonify({
        "status": "ok",
        "cwd": mu.BASE_DIR,
        "host": f"{os.environ.get('GAME_DEV_OS_HOST', '127.0.0.1')}:{os.environ.get('GAME_DEV_OS_PORT', '5000')}",
        "desktop": os.environ.get("GAME_DEV_OS_ELECTRON") == "1",
    })

@app.route("/tool")
def tool():
    return send_from_directory(mu.RESOURCE_ROOT, "index.html")

# 4. File Serving & Pipeline Endpoints
@app.route("/outputs/<path:filename>")
def serve_output(filename):
    root = os.path.normpath(mu.workspace_output_dir())
    target = os.path.normpath(os.path.join(root, filename))
    if not target.startswith(root + os.sep) and target != root:
        return jsonify({"error": "invalid path"}), 400
    if not os.path.isfile(target):
        return jsonify({"error": "not found"}), 404
    directory, fname = os.path.split(target)
    return send_from_directory(directory, fname)

@app.route("/uploads/<filename>")
def serve_upload(filename):
    return send_from_directory(mu.workspace_upload_dir(), filename)

@app.route("/remove-bg", methods=["POST"])
def remove_bg():
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "no image provided"}), 400
    file_id = str(uuid.uuid4())
    input_path = os.path.join(mu.workspace_upload_dir(), file_id + ".png")
    output_path = os.path.join(mu.workspace_output_dir(), file_id + "_clean.png")
    file.save(input_path)
    with open(input_path, "rb") as f:
        result = _remove_bg(f.read())
    with open(output_path, "wb") as f:
        f.write(result)
    state_store.bump_counter("bg_removal_runs")
    return send_file(output_path, mimetype="image/png")

@app.route("/bulk-remove", methods=["POST"])
def bulk_remove():
    files = request.files.getlist("images[]")
    if not files:
        return jsonify({"error": "no images provided"}), 400
    results = []
    for file in files:
        file_id = str(uuid.uuid4())
        input_filename = f"{file_id}.png"
        output_filename = f"{file_id}_clean.png"
        input_path = os.path.join(mu.workspace_upload_dir(), input_filename)
        output_path = os.path.join(mu.workspace_output_dir(), output_filename)
        file.save(input_path)
        with open(input_path, "rb") as f:
            result = _remove_bg(f.read())
        with open(output_path, "wb") as f:
            f.write(result)
        results.append({
            "cleaned": f"/outputs/{output_filename}",
            "original": f"/uploads/{input_filename}"
        })
    state_store.bump_counter("bg_removal_runs", len(results))
    return jsonify(results)

ANIMATION_FOLDERS = {
    "angry": "companion_dialogue_demo",
    "annoyed": "companion_dialogue_demo",
    "annoyed_arms_folded": "companion_dialogue_demo",
    "cheeks_full": "companion_dialogue_demo",
    "confidently": "companion_dialogue_demo",
    "cutely_annoyed": "companion_dialogue_demo",
    "cutely_thinking": "companion_dialogue_demo",
    "cutely_upset": "companion_dialogue_demo",
    "excited": "companion_dialogue_demo",
    "excited_explaining": "companion_dialogue_demo",
    "explaining": "companion_dialogue_demo",
    "explaining_alt": "companion_dialogue_demo",
    "talking": "companion_dialogue_demo",
    "happy": "companion_dialogue_demo",
    "happy_to_say": "companion_dialogue_demo",
    "in_love": "companion_dialogue_demo",
    "neutral": "companion_dialogue_demo",
    "pissed": "companion_dialogue_demo",
    "relieved": "companion_dialogue_demo",
    "warning": "companion_dialogue_demo",
    "thinking": "companion_dialogue_demo",
    "worried_upset": "companion_dialogue_demo"
}

# Randomized animation pools for natural, expressive variety
EXPLAINING_POOL = ["companion_dialogue_demo"]
CASUAL_TALK_POOL = ["companion_dialogue_demo"]
THINKING_POOL = ["companion_dialogue_demo"]
TSUNDERE_TEASE_POOL = ["companion_dialogue_demo"]
EXCITED_POOL = ["companion_dialogue_demo"]
AFFECTION_POOL = ["companion_dialogue_demo"]

def _parse_llm_output(text: str) -> tuple[str, str]:
    import re
    match = re.search(r"\[([a-zA-Z_]+)\]", text)
    emotion = "explaining"
    if match:
        tag = match.group(1).lower()
        valid = ["neutral", "explaining", "cutely_annoyed", "happy", "in_love", "pissed", "warning", "thinking", "excited", "worried_upset"]
        if tag in valid:
            emotion = tag
        text = re.sub(r"\[[a-zA-Z_]+\]", "", text).strip()
    
    text = text.replace('"', '').replace('Companion:', '').replace('Nyxaris:', '').strip()
    return text, emotion

def try_generate_llm_response(raw_message: str, level: str, trust: float, hp_pct: float, mana_pct: float) -> tuple[str, str] | None:
    import os
    import requests
    
    companion_name = os.environ.get("COMPANION_NAME", "Companion")
    # ── Strict Chat-Template Formatting (Prevents Safety Misunderstandings & Maximizes Coherence) ──
    system_msg = (
        f"You are roleplaying as {companion_name}, a knowledgeable companion guiding the player in an indie 2D action RPG.\n"
        f"Setting: Current Zone ({level}). You accompany the hero across dungeon chambers, wilderness trails, and boss arenas.\n"
        f"Game Stats: Player HP={int(hp_pct * 100)}%, Mana={int(mana_pct * 100)}%, Trust={trust:.2f}.\n"
        "Personality: Observant, tactical, encouraging, and protective of the player.\n"
        "Directives:\n"
        "1. Stay in character and directly address what the player says.\n"
        "2. Keep your response brief (1 to 2 natural sentences).\n"
        "3. Conclude every response with an emotion tag: [neutral], [explaining], [cutely_annoyed], [happy], [in_love], [pissed], [warning], [thinking], [excited]."
    )

    formatted_prompt = (
        f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n"
        f"{system_msg}<|eot_id|>\n"
        f"<|start_header_id|>user<|end_header_id|>\n"
        f"{raw_message}<|eot_id|>\n"
        f"<|start_header_id|>assistant<|end_header_id|>\n"
    )

    # 1. TIER 1: Online Cloud AI (Gemini REST API)
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            payload = {
                "contents": [
                    {"role": "user", "parts": [{"text": f"{system_msg}\n\nPlayer says: {raw_message}"}]}
                ],
                "generationConfig": {"maxOutputTokens": 60, "temperature": 0.75}
            }
            res = requests.post(url, json=payload, timeout=3.5)
            if res.status_code == 200:
                data = res.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text:
                    return _parse_llm_output(text)
        except Exception:
            pass

    # 2. TIER 2: Local Lightweight Ollama LLM (llama3.2:1b)
    try:
        model_name = os.environ.get("COMPANION_MODEL", os.environ.get("NYX_MODEL", "llama3.2:1b"))
        payload = {
            "model": model_name,
            "prompt": formatted_prompt,
            "stream": False,
            "keep_alive": "30m",
            "options": {
                "num_predict": 45,
                "temperature": 0.75,
                "top_p": 0.9,
                "num_thread": 4
            }
        }
        res = requests.post("http://localhost:11434/api/generate", json=payload, timeout=12.0)
        if res.status_code == 200:
            text = res.json().get("response", "").strip()
            if text:
                return _parse_llm_output(text)
    except Exception:
        pass

    return None

def get_animation_for_emotion(emotion: str) -> str:
    import random
    if emotion == "explaining":
        return random.choice(EXPLAINING_POOL)
    elif emotion in ["happy", "happy_to_say"]:
        return random.choice(CASUAL_TALK_POOL)
    elif emotion == "thinking":
        return random.choice(THINKING_POOL)
    elif emotion == "cutely_annoyed":
        return random.choice(TSUNDERE_TEASE_POOL)
    elif emotion == "excited":
        return random.choice(EXCITED_POOL)
    elif emotion == "in_love":
        return random.choice(AFFECTION_POOL)
    elif emotion in ANIMATION_FOLDERS:
        return ANIMATION_FOLDERS[emotion]
    return random.choice(CASUAL_TALK_POOL)

@app.route("/companion", methods=["POST"])
@app.route("/nyxaris", methods=["POST"])
def nyxaris_chat():
    import random
    data = request.get_json(silent=True) or {}
    raw_message = (data.get("message") or "").strip()
    message = raw_message.lower()
    level = data.get("level") or "MountainPathScene"
    trust = float(data.get("trust") or 0.5)
    hp = float(data.get("player_hp") or 100.0)
    max_hp = float(data.get("player_max_hp") or 100.0)
    mana = float(data.get("player_mana") or 100.0)
    max_mana = float(data.get("player_max_mana") or 100.0)
    
    hp_pct = max(0.0, min(1.0, hp / max(1.0, max_hp)))
    mana_pct = max(0.0, min(1.0, mana / max(1.0, max_mana)))

    suggested_mg = None
    trust_delta = 0.02

    # ── TRY INTELLIGENT AI (Gemini Online -> Local Ollama) ──
    ai_result = try_generate_llm_response(raw_message, level, trust, hp_pct, mana_pct)
    if ai_result:
        ai_resp, ai_emotion = ai_result
        anim = get_animation_for_emotion(ai_emotion)
        new_trust = max(0.0, min(1.0, trust + trust_delta))
        return jsonify({
            "response": ai_resp,
            "emotion": ai_emotion,
            "animation": anim,
            "sprite_key": ai_emotion,
            "suggested_minigame": None,
            "new_trust": new_trust,
            "engine": "llm"
        })

    # ── TIER 3: FAST HEURISTIC SYNTHESIZER FALLBACK ──
    
    # 1. Low HP Context
    if hp_pct < 0.35 and any(k in message for k in ["heal", "hurt", "hp", "health", "help", "dying", "pain", "ouch"]):
        responses = [
            "Your vitality is running low! Fall back and consume a healing flask before engaging.",
            "Take cover! Recover your health before the next wave surrounds you.",
            "Wounds like that will slow your sword arm. Rest and restore your health first!"
        ]
        resp = random.choice(responses)
        emotion = "cutely_upset"
        anim = ANIMATION_FOLDERS["cutely_upset"]
        suggested_mg = "CombatArena"
        trust_delta = 0.04

    # 2. Low Mana Context
    elif mana_pct < 0.30 and any(k in message for k in ["mana", "spell", "mp", "magic", "empty", "cast"]):
        responses = [
            "Your mana reserves are depleted. Meditate or gather mana orbs to replenish your spells.",
            "You cannot invoke skills on an empty reserve! Pace your attacks until stamina recovers.",
            "Conserve your energy—timing your abilities matters more than spamming them."
        ]
        resp = random.choice(responses)
        emotion = "warning"
        anim = ANIMATION_FOLDERS["warning"]
        suggested_mg = "SpellPractice"
        trust_delta = 0.03

    # 3. Minigames & Training Inquiries
    elif any(k in message for k in ["minigame", "arcade", "train", "practice", "arena", "trial", "play a game"]):
        games = ["CombatArena", "DungeonTrial", "SpeedRunner", "BossRush"]
        suggested_mg = random.choice(games)
        responses = [
            f"Sharpen your instincts in {suggested_mg}! Practicing your attack chains will pay off in real fights.",
            f"A true adventurer trains constantly. Test your reflexes in {suggested_mg} and return stronger!",
            f"Looking to hone your timing? Step into {suggested_mg} to practice parries and evasions."
        ]
        resp = random.choice(responses)
        emotion = "excited"
        anim = random.choice(EXCITED_POOL)
        trust_delta = 0.05

    # 4. Identity & Role of Companion
    elif any(k in message for k in ["who are you", "what are you", "your name", "companion", "tell me about yourself"]):
        responses = [
            "I am your adventuring companion! I monitor tactical openings, track our quest milestones, and back you up in battle.",
            "Think of me as your navigator and tactical guide. Together we can conquer whatever dungeon lies ahead.",
            "I'm here to travel the world by your side, uncover forgotten secrets, and make sure we both survive each expedition."
        ]
        resp = random.choice(responses)
        emotion = "confidently"
        anim = random.choice(EXPLAINING_POOL)
        trust_delta = 0.03

    # 5. World Lore & History
    elif any(k in message for k in ["lore", "history", "ruins", "world", "secret", "ancient", "mystery"]):
        responses = [
            "Ancient ruins across this region hold relics left by fallen civilizations. Careful study often reveals secret chambers.",
            "Old legends speak of sealed portals hidden deep below ground. Keep your senses tuned for magical resonances.",
            "Every territory has its own history. Exploring outposts and talking to locals will piece the story together."
        ]
        resp = random.choice(responses)
        emotion = "explaining"
        anim = random.choice(EXPLAINING_POOL)
        trust_delta = 0.03

    # 6. Guilds, Towns & Factions
    elif any(k in message for k in ["faction", "clan", "town", "village", "guild", "settlement"]):
        responses = [
            "Local settlements provide gear upgrades, restorative items, and regional bounties. Always check with merchants.",
            "Each faction holds different motives and allegiances. Pay attention to how locals treat outsiders.",
            "The town blacksmith can reinforce weapon damage if you bring along gathered crafting materials."
        ]
        resp = random.choice(responses)
        emotion = "thinking"
        anim = random.choice(THINKING_POOL)

    # 7. Bosses & Combat Tactics
    elif any(k in message for k in ["boss", "guardian", "enemy", "tactics", "strategy", "fight"]):
        responses = [
            "Every elite guardian telegraphs their heavy attacks with distinct wind-up animations. Dodge rolls are essential!",
            "Watch the boss's attack rhythm closely. Attack during the recovery frames between combo strings.",
            "Keep your distance when the boss enters an enrage phase, then strike swiftly during openings."
        ]
        resp = random.choice(responses)
        emotion = "warning"
        anim = ANIMATION_FOLDERS["warning"]

    # 8. Dungeons & Caverns
    elif any(k in message for k in ["cave", "dungeon", "depths", "crypt", "catacomb", "underground"]):
        responses = [
            "The lower chambers teem with subterranean predators and hidden floor switches. Stay light on your feet!",
            "Dungeon depths often hide locked treasure chests. Search for hidden keys or switch mechanisms.",
            "Steel yourself before venturing deeper—the further underground we go, the fiercer the encounters."
        ]
        resp = random.choice(responses)
        emotion = "warning"
        anim = ANIMATION_FOLDERS["warning"]
        trust_delta = 0.05

    # 9. Guidance, Navigation & "What should I do?"
    elif any(k in message for k in ["what should i do", "what now", "where do i go", "where to go", "next", "lost", "guide me", "help me", "direction", "how to"]):
        responses = [
            "Follow the main trail forward. Clearing regional milestones will unlock the gateway to the next zone.",
            "Check your quest log and inventory. If you're well-prepared, head toward the marked landmark ahead.",
            "Keep exploring along the stone path. Every area cleared brings new resources and stronger equipment."
        ]
        resp = random.choice(responses)
        emotion = "explaining"
        anim = random.choice(EXPLAINING_POOL)

    # 10. Affection & Compliments
    elif any(k in message for k in ["cute", "love", "marry", "pretty", "beautiful", "like you", "sweet"]):
        if trust > 0.65:
            responses = [
                "Well, aren't you sweet! I appreciate having such a dependable adventuring partner.",
                "Thank you! Having you as a companion makes all these perilous quests worthwhile.",
                "I'm glad we make such a good team. Let's make sure we both make it through to the end!"
            ]
            resp = random.choice(responses)
            emotion = "in_love"
            anim = random.choice(AFFECTION_POOL)
            trust_delta = 0.08
        else:
            responses = [
                "Flattery is nice, but keep your eyes on the road! Monsters don't wait for polite conversation.",
                "Thank you, but stay alert! Danger could be lurking around the very next corner.",
                "Focus on the mission first, traveler. We can celebrate once the area is safe."
            ]
            resp = random.choice(responses)
            emotion = "cutely_annoyed"
            anim = random.choice(TSUNDERE_TEASE_POOL)

    # 11. Playful, Teasing, or Humorous
    elif any(k in message for k in ["tease", "annoying", "bossy", "funny", "joke", "lazy", "food", "eat", "hungry"]):
        responses = [
            "Who are you calling bossy?! I'm keeping you from tumbling into spike pits, ungrateful traveler!",
            "Keep making jokes like that and I might just take a nap while you fight the next swarm!",
            "Exploring works up quite an appetite. Remind me to stop at the next campfire for snacks!"
        ]
        resp = random.choice(responses)
        emotion = "cutely_annoyed"
        anim = random.choice(TSUNDERE_TEASE_POOL)
        trust_delta = 0.03

    # 12. Gratitude, Agreement & Affirmations
    elif any(k in message for k in ["thank", "thanks", "ok", "okay", "alright", "got it", "understood", "yes", "yeah", "sure", "will do"]):
        responses = [
            "Good. As long as we understand each other, nothing in this realm can stand in our way.",
            "I expect nothing less from my companion. Let us proceed with haste.",
            "Very well. Lead onward, and strike true when the moment comes."
        ]
        resp = random.choice(responses)
        emotion = "happy_to_say"
        anim = random.choice(CASUAL_TALK_POOL)
        trust_delta = 0.02

    # 13. General Readiness & "How are you?"
    elif any(k in message for k in ["ready", "how are you", "how r u", "what's up", "whats up", "how do you feel", "are you okay", "you ready"]):
        if trust > 0.6:
            responses = [
                "I am primed for battle and eager to see what we uncover next. How are you holding up?",
                "My senses are sharp and ready. Whenever you are prepared to advance, I am right behind you.",
                "Feeling stronger by your side. Let us see what secrets this zone still holds."
            ]
            resp = random.choice(responses)
            emotion = "happy_to_say"
            anim = random.choice(CASUAL_TALK_POOL)
            trust_delta = 0.03
        else:
            responses = [
                "My senses are focused on the surroundings. Make sure your reflexes are just as sharp.",
                "I am ready when you are. Do not let your guard down for a single moment.",
                "Standing by. Speak your intent or lead the way toward our next objective."
            ]
            resp = random.choice(responses)
            emotion = "neutral"
            anim = random.choice(CASUAL_TALK_POOL)

    # 14. Greetings
    elif any(k in message for k in ["hello", "hi", "hey", "greetings", "good morning", "good evening", "yo"]):
        if hp_pct < 0.4:
            resp = "I am with you, traveler. But you look exhausted—rest a moment before charging into danger."
            emotion = "worried_upset"
            anim = ANIMATION_FOLDERS["worried_upset"]
            suggested_mg = "CombatArena"
        elif trust > 0.6:
            responses = [
                "Greetings! It is good to see you standing tall. What shall we investigate next?",
                "Ah, there you are. I was wondering when you would seek my counsel again.",
                "Hello, companion. Ready for the next adventure?"
            ]
            resp = random.choice(responses)
            emotion = "happy_to_say"
            anim = random.choice(CASUAL_TALK_POOL)
            trust_delta = 0.03
        else:
            responses = [
                "I am with you, traveler. Speak your mind or ask for guidance on our journey.",
                "Greetings. What observations do you have to share from your travels?",
                "I am listening. What direction shall we take?"
            ]
            resp = random.choice(responses)
            emotion = "neutral"
            anim = random.choice(CASUAL_TALK_POOL)

    # 15. Dynamic Conversational Fallback (Natural, varied, contextual for any action RPG)
    else:
        if "Dungeon" in level or "Cave" in level:
            responses = [
                "We stand at the threshold of the deep chambers. Prepare your weapon and watch for traps!",
                "The shadows grow thicker here. Stay alert as we descend deeper into the ruins.",
                "Hostile presence detected nearby. Let us clear this floor methodically!"
            ]
            resp = random.choice(responses)
            emotion = "angry"
            anim = ANIMATION_FOLDERS.get("angry", "neutral")
        elif "Arena" in level or "Combat" in level:
            responses = [
                "Hostiles are sizing you up. Keep your distance until you find an opening to strike.",
                "Stay light on your feet. Dodge rolls will help avoid heavy telegraphed attacks.",
                "Something dangerous approaches. Draw your weapon and hold your ground!"
            ]
            resp = random.choice(responses)
            emotion = "thinking"
            anim = random.choice(THINKING_POOL) if THINKING_POOL else "neutral"
        else:
            responses = [
                "I hear you, traveler. Let us keep moving—our next objective lies just ahead.",
                "Interesting thought. Let us press onward through the region and see what we discover.",
                "Indeed. Stay vigilant and keep your equipment ready. Every step brings us closer to the goal.",
                "A good observation. Keep your focus sharp, and let us unveil what lies in the next zone."
            ]
            resp = random.choice(responses)
            emotion = "explaining"
            anim = random.choice(CASUAL_TALK_POOL + EXPLAINING_POOL) if (CASUAL_TALK_POOL + EXPLAINING_POOL) else "neutral"

    new_trust = max(0.0, min(1.0, trust + trust_delta))
    return jsonify({
        "response": resp,
        "emotion": emotion,
        "animation": anim,
        "sprite_key": emotion,
        "suggested_minigame": suggested_mg,
        "new_trust": new_trust
    })

# 5. External Route Registration (Last step)
from routing import register_routes
register_routes(app)

if __name__ == "__main__":
    host = os.environ.get("GAME_DEV_OS_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("GAME_DEV_OS_PORT", "5000")))
    debug = os.environ.get("GAME_DEV_OS_DEBUG", "0").lower() in ("1", "true", "yes")
    app.run(host=host, port=port, debug=debug, use_reloader=False)