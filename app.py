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
    "angry": "nyxarisangry-e56db4b1",
    "annoyed": "nyxarisannoyed-1fd7f301",
    "annoyed_arms_folded": "nyxarisannoyedarmsfolded-6d8ef381",
    "cheeks_full": "nyxarischeeksfulloffoodormana-246d2ced",
    "confidently": "nyxarisconfidently-64b9a921",
    "cutely_annoyed": "nyxariscutelyannoyed-9f21f3fd",
    "cutely_thinking": "nyxariscutelythinking-08686484",
    "cutely_upset": "nyxariscutelyupset-72bf7d95",
    "excited": "nyxarisexcited-f2ab5508",
    "excited_explaining": "nyxarisexcitedarmsspreadexplaining-cb776e55",
    "explaining": "nyxarisexplaining0-c6c6f20e",
    "explaining_alt": "nyxarisexplaining1-a4a19986",
    "talking": "nyxaristalkingeyesclosed-a238b88a",
    "happy": "nyxarishappy-f4e5a565",
    "happy_to_say": "nyxarishappytosay-e0fd84be",
    "in_love": "nyxarisinlove-279c11ce",
    "neutral": "nyxarisnuetral-411247bb",
    "pissed": "nyxarispissed-7e387d67",
    "relieved": "nyxarisrelivedmp4-57352796",
    "warning": "nyxarissternorimportantwarning-534901f6",
    "thinking": "nyxaristhinking-616901a8",
    "worried_upset": "nyxarisworriedupsetthinkingmp4-bd2148fc"
}

# Randomized animation pools for natural, expressive variety
EXPLAINING_POOL = [
    "nyxarisexplaining0-c6c6f20e",
    "nyxarisexplaining1-a4a19986",
    "nyxarisexcitedarmsspreadexplaining-cb776e55",
    "nyxaristalkingeyesclosed-a238b88a",
    "nyxarisconfidently-64b9a921",
    "nyxarisconfidently0-146ef255",
]

CASUAL_TALK_POOL = [
    "nyxarishappytosay-e0fd84be",
    "nyxarishappy-f4e5a565",
    "nyxarishappythinking-bd1f19af",
    "nyxarisshrug-82e20542",
    "nyxarisnuetral-411247bb",
    "nyxarisnuetralstare-14b61402",
]

THINKING_POOL = [
    "nyxaristhinking-616901a8",
    "nyxariscutelythinking-08686484",
    "nyxarishappythinking-bd1f19af",
]

TSUNDERE_TEASE_POOL = [
    "nyxariscutelyannoyed-9f21f3fd",
    "nyxariseyesrolling-0c15d4fb",
    "nyxarisannoyedarmsfolded-6d8ef381",
    "nyxarisannoyed-1fd7f301",
    "nyxarischeeksfulloffoodormana-246d2ced",
]

EXCITED_POOL = [
    "nyxarisexcited-f2ab5508",
    "nyxarisexcitedarmsspreadexplaining-cb776e55",
    "nyxarisinfactuation-56ed8338",
]

AFFECTION_POOL = [
    "nyxarisinlove-279c11ce",
    "nyxarisinfactuation-56ed8338",
    "nyxarishappytosay-e0fd84be",
]

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
    
    text = text.replace('"', '').replace('Nyxaris:', '').strip()
    return text, emotion

def try_generate_llm_response(raw_message: str, level: str, trust: float, hp_pct: float, mana_pct: float) -> tuple[str, str] | None:
    import os
    import requests
    
    # ── Strict Chat-Template Formatting (Prevents Safety Misunderstandings & Maximizes Coherence) ──
    system_msg = (
        "You are roleplaying as Nyxaris, an anime dark goddess companion in a fantasy 2D action game.\n"
        f"Setting: Cherry Blossom Mountain ({level}). You are accompanying the player (a mortal hero) investigating the rivalry between the Strawhat and Samurai clans.\n"
        f"Game Stats: Player HP={int(hp_pct * 100)}%, Mana={int(mana_pct * 100)}%, Trust={trust:.2f}.\n"
        "Personality: Classic anime tsundere goddess — proud, sharp-tongued, dramatic, but secretly fond of and protective of the player.\n"
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
        model_name = os.environ.get("NYX_MODEL", "llama3.2:1b")
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
            "You are battered, mortal! Do not throw your life away so recklessly. Take a breath or train in the Void Surge.",
            "Your wounds are severe! Step back and gather health orbs before you collapse!",
            "Look at you, barely standing! A fallen warrior is of no use to my mission. Recover immediately!"
        ]
        resp = random.choice(responses)
        emotion = "cutely_upset"
        anim = ANIMATION_FOLDERS["cutely_upset"]
        suggested_mg = "VoidSurge"
        trust_delta = 0.04

    # 2. Low Mana Context
    elif mana_pct < 0.30 and any(k in message for k in ["mana", "spell", "mp", "magic", "empty", "cast"]):
        responses = [
            "Your mana is dangerously depleted. Refresh your arcane flow before engaging the next clan guardian.",
            "You cannot conjure spells on empty reserves! Collect mana orbs or meditate for a moment.",
            "The void essence within you runs thin. Recharging your magic is essential right now."
        ]
        resp = random.choice(responses)
        emotion = "warning"
        anim = ANIMATION_FOLDERS["warning"]
        suggested_mg = "OrbSplash"
        trust_delta = 0.03

    # 3. Minigames & Training Inquiries
    elif any(k in message for k in ["minigame", "arcade", "train", "practice", "void surge", "orb splash", "shadow runner", "skybound", "play a game"]):
        games = ["VoidSurge", "OrbSplash", "ShadowRunner", "SkyboundBox"]
        suggested_mg = random.choice(games)
        responses = [
            f"Sharpen your instincts in {suggested_mg}! Gathering void essence now will make your strikes lethal.",
            f"A true warrior trains constantly. Test your reflexes in {suggested_mg} and return stronger!",
            f"Looking to hone your arcane mastery? Step into {suggested_mg} and collect divine rewards."
        ]
        resp = random.choice(responses)
        emotion = "excited"
        anim = random.choice(EXCITED_POOL)
        trust_delta = 0.05

    # 4. Identity & Lore of Nyxaris
    elif any(k in message for k in ["who are you", "what are you", "your name", "goddess", "nyxaris", "tell me about yourself"]):
        responses = [
            "I am Nyxaris, Goddess of the Dark Multiverse. Bound across timelines to restore cosmic balance—and uncover the truth behind my followers' demise.",
            "You stand before Nyxaris. Though my mortal form is diminished in this realm, the primordial void still answers my command.",
            "I am the sovereign of shadows and forgotten realms. Together, we are going to unravel the conspiracy consuming this forest."
        ]
        resp = random.choice(responses)
        emotion = "confidently"
        anim = random.choice(["nyxarisconfidently-64b9a921", "nyxarisconfidently0-146ef255", "nyxarisexplaining0-c6c6f20e"])
        trust_delta = 0.03

    # 5. Massacre, Culprit & Followers
    elif any(k in message for k in ["who", "killer", "massacre", "follower", "followers", "culprit", "murder", "died", "who did this"]):
        responses = [
            "My followers were slaughtered in cold blood across this timeline. Clues point to a warrior hidden among the mountain clans—or something far darker impersonating them.",
            "Someone orchestrated the massacre to spark war between the Strawhat and Samurai clans. We must expose the imposter before more blood is spilled.",
            "The killer leaves a trail of deception. Investigate both dōjōs in the mountains—the evidence will lead us to the culprit."
        ]
        resp = random.choice(responses)
        emotion = "explaining"
        anim = random.choice(EXPLAINING_POOL)
        trust_delta = 0.03

    # 6. Strawhat Clan Lore
    elif any(k in message for k in ["strawhat", "dojo1", "dojo 1", "straw"]):
        responses = [
            "The Strawhat Clan claims innocence, insisting the killer is a shape-shifter in the Samurai Clan. Do not lower your guard in their dōjō.",
            "Their warriors fight with swift straw blades. Challenge their altar guardian and demand the truth about the killings.",
            "The Strawhat masters know more than they let on. Watch their movements carefully when you step past their gates."
        ]
        resp = random.choice(responses)
        emotion = "thinking"
        anim = random.choice(THINKING_POOL)

    # 7. Samurai Clan Lore
    elif any(k in message for k in ["samurai", "dojo2", "dojo 2", "master"]):
        responses = [
            "Rumors say the Samurai Clan's Master was sighted alive, despite dying two years ago... Be vigilant; things are not as they appear.",
            "The Samurai Clan blames the Strawhats, but this resurrected Master suggests dark illusions are at play.",
            "Face the Samurai Clan guardian. We must determine if their fallen Master has truly returned from the grave."
        ]
        resp = random.choice(responses)
        emotion = "warning"
        anim = ANIMATION_FOLDERS["warning"]

    # 8. Cave & Tsuchigumo Reveal
    elif any(k in message for k in ["cave", "spider", "tsuchigumo", "web"]):
        responses = [
            "The giant spiders multiplying in the regional cave serve Tsuchigumo—the true shape-shifting culprit behind the massacre!",
            "Tsuchigumo weaves webs of discord, impersonating both clans to fuel their hatred. Descend the cave and crush this beast!",
            "The bottom of the mountain cave holds the final answer. Steel yourself, mortal—Tsuchigumo will not surrender easily."
        ]
        resp = random.choice(responses)
        emotion = "pissed"
        anim = ANIMATION_FOLDERS["pissed"]
        trust_delta = 0.05

    # 9. Guidance, Navigation & "What should I do?"
    elif any(k in message for k in ["what should i do", "what now", "where do i go", "where to go", "next", "lost", "guide me", "help me", "direction", "how to"]):
        responses = [
            "Head upward through the mountain path. We must visit both Dōjō 1 (Strawhat) and Dōjō 2 (Samurai) to gather clues before entering the cave.",
            "Explore the Cherry Blossom Village and test your blade against clan warriors. When you are ready, the cave depths await.",
            "Keep advancing along the stone path. Every enemy defeated brings us closer to uncovering Tsuchigumo's nest."
        ]
        resp = random.choice(responses)
        emotion = "explaining"
        anim = random.choice(EXPLAINING_POOL)

    # 10. Affection, Flirting & Compliments
    elif any(k in message for k in ["cute", "love", "marry", "pretty", "beautiful", "like you", "kiss", "gorgeous", "waifu", "sweet"]):
        if trust > 0.65:
            responses = [
                "H-hush, mortal! A goddess does not get swayed by simple sweet-talking... Though, I suppose your company isn't entirely dreadful.",
                "Flattery from you is surprisingly pleasant... Not that I'm getting attached or anything! Keep your eyes on the road.",
                "You truly are bold to speak to a deity like that. Just make sure you stay alive so I can keep hearing it."
            ]
            resp = random.choice(responses)
            emotion = "in_love"
            anim = random.choice(AFFECTION_POOL)
            trust_delta = 0.08
        else:
            responses = [
                "Flattery will not distract me from our mission, mortal. Focus on the investigation at hand!",
                "Do not think cheap compliments will earn you divine favor so easily. Prove your worth in battle first!",
                "A goddess has no time for idle flirtation. Keep your blade sharp and your mind focused."
            ]
            resp = random.choice(responses)
            emotion = "cutely_annoyed"
            anim = random.choice(TSUNDERE_TEASE_POOL)

    # 11. Playful, Teasing, or Humorous
    elif any(k in message for k in ["tease", "annoying", "bossy", "funny", "joke", "short", "cute horn", "horns", "lazy", "food", "eat", "hungry", "baka"]):
        responses = [
            "Who are you calling bossy?! I am guiding you so you don't wander off a cliff, ungrateful mortal!",
            "Keep making remarks like that and I might just let the next spider have a nibble of your cloak!",
            "My mana reserves require constant replenishment... which totally includes delicious festival treats, obviously!"
        ]
        resp = random.choice(responses)
        emotion = "cutely_annoyed"
        anim = random.choice(TSUNDERE_TEASE_POOL)
        trust_delta = 0.03

    # 12. Gratitude, Agreement & Affirmations
    elif any(k in message for k in ["thank", "thanks", "ok", "okay", "alright", "got it", "understood", "yes", "yeah", "sure", "will do"]):
        responses = [
            "Good. As long as we understand each other, nothing in this forest can stand in our way.",
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
                "My arcane senses are tingling with anticipation. Whenever you are ready to move, I am with you.",
                "Feeling stronger by your side, mortal. Let us see what secrets this mountain still hides."
            ]
            resp = random.choice(responses)
            emotion = "happy_to_say"
            anim = random.choice(CASUAL_TALK_POOL)
            trust_delta = 0.03
        else:
            responses = [
                "My senses are focused on the investigation. Make sure your reflexes are just as sharp.",
                "I am ready when you are. Do not let your guard down for a single moment.",
                "Standing by. Speak your intent or lead the way toward our next objective."
            ]
            resp = random.choice(responses)
            emotion = "neutral"
            anim = random.choice(CASUAL_TALK_POOL)

    # 14. Greetings
    elif any(k in message for k in ["hello", "hi", "hey", "greetings", "good morning", "good evening", "yo"]):
        if hp_pct < 0.4:
            resp = "I am with you, mortal. But you look exhausted—rest a moment before charging into danger."
            emotion = "worried_upset"
            anim = ANIMATION_FOLDERS["worried_upset"]
            suggested_mg = "OrbSplash"
        elif trust > 0.6:
            responses = [
                "Greetings! It is good to see you standing tall. What shall we investigate next?",
                "Ah, there you are. I was wondering when you would seek my counsel again.",
                "Hello, companion. Ready to turn this mountain upside down?"
            ]
            resp = random.choice(responses)
            emotion = "happy_to_say"
            anim = random.choice(CASUAL_TALK_POOL)
            trust_delta = 0.03
        else:
            responses = [
                "I am with you, mortal. Speak your mind or ask for guidance on our investigation.",
                "Greetings. What observations do you have to share from your journey?",
                "I am listening. What direction shall we take?"
            ]
            resp = random.choice(responses)
            emotion = "neutral"
            anim = random.choice(CASUAL_TALK_POOL)

    # 15. Dynamic Conversational Fallback (Natural, varied, contextual)
    else:
        if "Dojo1" in level:
            responses = [
                "We are at the Strawhat Dōjō. Stay alert and watch for any hidden clues near their altar.",
                "The Strawhat warriors are sizing you up. Speak with their master or challenge their champions.",
                "Look around this dōjō carefully. The killer may have left traces of their presence."
            ]
            resp = random.choice(responses)
            emotion = "explaining"
            anim = random.choice(EXPLAINING_POOL)
        elif "Dojo2" in level:
            responses = [
                "This dōjō reeks of deception. The Master who stands before you is a false illusion!",
                "Keep your distance from the Samurai guards until we verify who is commanding them.",
                "Something is unnatural about this place. Be ready to draw your weapon at a moment's notice."
            ]
            resp = random.choice(responses)
            emotion = "thinking"
            anim = random.choice(THINKING_POOL)
        elif "Cave" in level:
            responses = [
                "We stand at the threshold of truth. Tsuchigumo awaits below in the webs. Prepare yourself for battle!",
                "The webs grow thicker here. Watch the shadows above as we descend into the lair.",
                "Tsuchigumo's venomous presence is heavy in the air. Let us cleanse this cave together!"
            ]
            resp = random.choice(responses)
            emotion = "angry"
            anim = ANIMATION_FOLDERS["angry"]
        else:
            responses = [
                "I hear you, mortal. Keep moving through the Cherry Blossom Forest—the clues we need are waiting ahead.",
                "Interesting thought. Let us press onward to the mountain dōjōs and see what we can find.",
                "Indeed. Stay vigilant and keep your blade ready. Every step brings us closer to the truth.",
                "A curious remark. Keep your focus on our quest, and let us unveil what lies in the cave."
            ]
            resp = random.choice(responses)
            emotion = "explaining"
            anim = random.choice(CASUAL_TALK_POOL + EXPLAINING_POOL)

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