from __future__ import annotations
import os
import shutil
from flask import Response, abort, jsonify, render_template, request, send_from_directory, send_file

# Local service imports
from services import media_utils as mu

UNITY_DEFAULT_EXPORT = os.environ.get("UNITY_PROJECT_DIR", os.path.join(mu.BASE_DIR, "exports", "unity"))
UNITY_FRAMES_EXPORT = os.environ.get("UNITY_FRAMES_DIR", os.path.join(UNITY_DEFAULT_EXPORT, "Assets", "Animations", "Frames"))
UNITY_AUDIO_EXPORT = os.environ.get("UNITY_AUDIO_DIR", os.path.join(UNITY_DEFAULT_EXPORT, "Assets", "Audio"))
UNITY_SCENES_EXPORT = os.environ.get("UNITY_SCENES_DIR", os.path.join(UNITY_DEFAULT_EXPORT, "Assets", "Scenes"))

from services.animation_svc import (
    copy_video_into_animation, create_animation_bundle, list_frame_urls,
    save_edited_frame, save_edited_frames_batch
)
from services.assets_service import (
    ALLOWED_KIND, save_uploaded_file as svc_save_asset,
    list_audios as svc_list_audios, list_images as svc_list_images,
    list_animations as svc_list_animations, list_videos as svc_list_videos
)
from services.audio_gen_svc import save_pack as generate_audio_pack
from services.export_svc import full_project_zip, unity_export_zip
from services.nyxaris_svc import chat as nyx_chat_fn, dev_assist as nyx_dev_assist
from services.pipeline_controller import (
    run_animation_pipeline, run_bg_cleanup, run_full_pipeline_from_video, run_video_extract
)
from services.progress_view import snapshot as progress_snapshot
from services.video_frames import reorganize_existing_frames
from services import ai_animation_gen_svc as ai_anim_svc
from services import audio_slicer_svc as slicer_svc

def register_routes(app) -> None:
    """Mounts routes after Flask app is initialized."""

    @app.route("/media/<path:rel>")
    def serve_media(rel: str):
        full = mu.resolve_existing_file_under_storage(rel)
        if not full:
            abort(404)
        dn, fn = os.path.split(full)
        return send_from_directory(dn, fn)


    @app.route("/api/pipeline/full", methods=["POST"])
    @app.route("/video-to-frames", methods=["POST"])
    def api_video_to_frames():
        """Handles video upload and extraction using the pipeline controller."""
        if 'video' not in request.files:
            return jsonify({"error": "no video provided"}), 400

        video_file = request.files['video']
        filename = video_file.filename or "video"
        slug, ext = os.path.splitext(filename)
        slug = slug or "video"
        ext = ext or ".mp4"

        temp_video_path = os.path.join(mu.workspace_upload_dir(), f"{mu.short_id('vid')}{ext}")
        video_file.save(temp_video_path)

        try:
            interval_sec = float(request.form.get("interval", "0.1"))
        except ValueError:
            return jsonify({"error": "invalid interval"}), 400

        skip_bg = request.form.get("skip_bg", "").lower() in ("true", "1", "yes")
        method = request.form.get("method", "rembg")

        try:
            result = run_full_pipeline_from_video(temp_video_path, slug, interval_sec, skip_bg=skip_bg, method=method)
            animation_id = result.get("animation_id")
            if not animation_id:
                raise RuntimeError("No animation bundle created")

            # Export cleaned frames to Unity folder (subfolder per animation ID)
            unity_frames_dir = os.path.join(UNITY_FRAMES_EXPORT, animation_id)
            os.makedirs(unity_frames_dir, exist_ok=True)

            cleaned_dir = mu.animation_clean_dir(animation_id)
            frame_files = []
            for fname in sorted(os.listdir(cleaned_dir), key=mu.natural_sort_key):
                if fname.endswith(".png"):
                    src = os.path.join(cleaned_dir, fname)
                    dst = os.path.join(unity_frames_dir, fname)
                    shutil.copy2(src, dst)
                    frame_files.append(fname)

            cleaned_urls = mu.frame_urls_for_bundle(animation_id, cleaned=True)
            raw_urls = mu.frame_urls_for_bundle(animation_id, cleaned=False)
            frames = []
            for i, c_url in enumerate(cleaned_urls):
                r_url = raw_urls[i] if i < len(raw_urls) else c_url
                frames.append({
                    "cleaned": c_url,
                    "original": r_url
                })
            return jsonify({"animation_id": animation_id, "frames": frames, "exported_count": len(frame_files), "unity_path": unity_frames_dir})
        except Exception as e:
            print(f"Pipeline error: {str(e)}")
            return jsonify({"error": f"Video processing failed: {str(e)}"}), 500


    @app.route("/api/animations/<anim_id>/extract", methods=["POST"])
    def api_extract_frames(anim_id: str):
        if not mu.bundle_exists(anim_id):
            abort(404)
        data = request.get_json(force=True, silent=True) or {}
        try:
            interval_sec = float(data.get("interval_sec", data.get("interval", 0.2)))
        except ValueError:
            return jsonify({"error": "invalid interval"}), 400
        try:
            res = run_video_extract(anim_id, interval_sec)
            return jsonify(res)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/animations/<anim_id>/bg-batch", methods=["POST"])
    def api_bg_batch(anim_id: str):
        if not mu.bundle_exists(anim_id):
            abort(404)
        data = request.get_json(force=True, silent=True) or {}
        method = data.get("method", request.args.get("method", "rembg"))
        try:
            res = run_bg_cleanup(anim_id, method=method)
            return jsonify(res)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/pipeline/frame-bg", methods=["POST"])
    def api_frame_bg_pipeline():
        data = request.get_json(force=True, silent=True) or {}
        anim_id = data.get("animation_id")
        method = data.get("method", "rembg")
        try:
            interval_sec = float(data.get("interval_sec", 0.2))
        except ValueError:
            return jsonify({"error": "invalid interval"}), 400
        if not anim_id or not mu.bundle_exists(anim_id):
            return jsonify({"error": "invalid animation_id"}), 400
        try:
            res = run_animation_pipeline(anim_id, interval_sec, method=method)
            return jsonify(res)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/animations/<anim_id>/attach-video", methods=["POST"])
    def api_attach_video(anim_id: str):
        if not mu.bundle_exists(anim_id):
            abort(404)
        if 'video' not in request.files:
            return jsonify({"error": "no video provided"}), 400
        video_file = request.files['video']
        filename = video_file.filename or "video.mp4"
        ext = os.path.splitext(filename)[1] or ".mp4"
        temp_video_path = os.path.join(mu.workspace_upload_dir(), f"temp_attach_{anim_id}{ext}")
        video_file.save(temp_video_path)
        try:
            from services.animation_svc import copy_video_into_animation
            dest = copy_video_into_animation(anim_id, temp_video_path)
            if os.path.isfile(temp_video_path):
                os.remove(temp_video_path)
            return jsonify({"status": "attached", "path": dest})
        except Exception as e:
            return jsonify({"error": str(e)}), 400


    @app.route("/assets")
    def page_assets():
        return render_template("assets.html")

    @app.route("/animations")
    def page_animations():
        return render_template("animations.html")

    @app.route("/ai-animator")
    def page_ai_animator():
        return render_template("ai_animator.html")

    @app.route("/tracker")
    def page_tracker():
        return render_template("tracker.html")

    @app.route("/api/tracker/progress", methods=["GET", "POST"])
    def api_tracker_progress():
        root = os.path.abspath(os.path.dirname(__file__))
        state_file = os.path.join(root, "progress.json")

        def load_state():
            if os.path.isfile(state_file):
                try:
                    import json
                    with open(state_file, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
            default = {
                "categories": [
                    {"id": "character", "title": "🎭 Character & Animation", "tasks": [
                        {"id": "character-1", "label": "Polish protagonist idle animation", "completed": False},
                        {"id": "character-2", "label": "Polish attack combo animation set", "completed": False},
                        {"id": "character-3", "label": "Add dodge / dash animation with i-frames", "completed": False}
                    ]},
                    {"id": "npc", "title": "🧠 NPC & Dialogue System", "tasks": [
                        {"id": "npc-1", "label": "Create world NPCs for quests and guidance", "completed": False},
                        {"id": "npc-2", "label": "Implement interactive dialogue branching system", "completed": False},
                        {"id": "npc-3", "label": "Add story hints and narrative trigger cues", "completed": False}
                    ]},
                    {"id": "ui", "title": "🖥️ UI SYSTEMS", "tasks": [
                        {"id": "ui-1", "label": "Pause menu & settings UI", "completed": False},
                        {"id": "ui-2", "label": "Health bar & stamina gauges (player + enemies)", "completed": False},
                        {"id": "ui-3", "label": "Merchant shop and inventory UI", "completed": False}
                    ]},
                    {"id": "world", "title": "🏯 WORLD BUILDING", "tasks": [
                        {"id": "world-1", "label": "Starter village / safe hub environment", "completed": False},
                        {"id": "world-2", "label": "Pathway and exploration routes to Dungeon 1", "completed": False},
                        {"id": "world-3", "label": "Primary dungeon interior & room layouts", "completed": False},
                        {"id": "world-4", "label": "Secondary challenge zone & gauntlets", "completed": False},
                        {"id": "world-5", "label": "Vertical platforming & hazard zone section", "completed": False},
                        {"id": "world-6", "label": "Final boss chamber arena architecture", "completed": False}
                    ]},
                    {"id": "combat", "title": "⚔️ COMBAT SYSTEM", "tasks": [
                        {"id": "combat-1", "label": "Core combat moveset (basic + heavy attacks)", "completed": False},
                        {"id": "combat-2", "label": "Dynamic enemy wave spawner implementation", "completed": False},
                        {"id": "combat-3", "label": "Enemy mob variants (melee, ranged, heavy)", "completed": False},
                        {"id": "combat-4", "label": "Multi-phase boss fight encounter logic", "completed": False}
                    ]},
                    {"id": "shop", "title": "🛒 SHOP SYSTEM", "tasks": [
                        {"id": "shop-1", "label": "In-game merchant NPC shop system", "completed": False},
                        {"id": "shop-2", "label": "Currency and transaction exchange logic", "completed": False},
                        {"id": "shop-3", "label": "Consumables: Health potions & stamina draughts", "completed": False},
                        {"id": "shop-4", "label": "Gear upgrades: Weapon tiers and stat modifiers", "completed": False}
                    ]},
                    {"id": "audio", "title": "🔊 AUDIO & POLISH", "tasks": [
                        {"id": "audio-1", "label": "Exploration soundtrack & ambient loops", "completed": False},
                        {"id": "audio-2", "label": "Dynamic combat music system", "completed": False},
                        {"id": "audio-3", "label": "Sound effects suite (swings, impacts, UI)", "completed": False}
                    ]},
                    {"id": "movement", "title": "🌍 MOVEMENT SYSTEM", "tasks": [
                        {"id": "movement-1", "label": "Ledge grab and dynamic climbing", "completed": False},
                        {"id": "movement-2", "label": "Locomotion blend trees & smooth turning", "completed": False},
                        {"id": "movement-3", "label": "Jump physics, gravity curves, and coyote time", "completed": False}
                    ]}
                ]
            }
            with open(state_file, "w", encoding="utf-8") as f:
                import json
                json.dump(default, f, indent=2)
            return default

        def save_state(payload):
            import json
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

        if request.method == 'GET':
            return jsonify(load_state())

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Invalid payload"}), 400
        save_state(data)
        return jsonify({"status": "saved"})

    @app.route("/api/tracker/reset", methods=["POST"])
    def api_tracker_reset():
        root = os.path.abspath(os.path.dirname(__file__))
        state_file = os.path.join(root, "progress.json")
        if os.path.isfile(state_file):
            os.remove(state_file)
        return jsonify({"status": "reset"})

    # --- Added routes to fix missing page rendering and API endpoints ---

    @app.route("/audio-hub")
    def page_audio_hub():
        return render_template("audio.html")

    @app.route("/audio-extractor")
    def page_audio_extractor():
        return render_template("audio_extractor.html")

    @app.route("/api/audio/extract-from-video", methods=["POST"])
    def api_extract_audio_from_video():
        data = request.get_json(force=True, silent=True) or {}
        video_path = data.get("video_path")
        try:
            start_time = float(data.get("start_time", 0.0))
            end_time = float(data.get("end_time", 0.0))
        except (ValueError, TypeError):
            return jsonify({"error": "invalid start_time or end_time"}), 400
        
        slug = data.get("slug")
        category = data.get("category", "misc")
        mono = bool(data.get("mono", False))
        
        if not video_path:
            return jsonify({"error": "video_path is required"}), 400
        if not slug:
            return jsonify({"error": "slug/filename is required"}), 400
            
        try:
            from services.audio_extractor_svc import extract_audio_segment
            meta = extract_audio_segment(
                video_relative_path=video_path,
                start_time=start_time,
                end_time=end_time,
                slug=slug,
                category=category,
                mono=mono
            )
            return jsonify(meta)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/images")
    def page_images():
        return render_template("images.html")

    @app.route("/styles")
    def page_styles():
        from services.state_store import get_style_presets
        return render_template("styles.html", presets=get_style_presets())

    @app.route("/status-board")
    def page_status_board():
        return render_template("status.html", snapshot=progress_snapshot())

    @app.route("/script-setup")
    def page_script_setup():
        return render_template("script_setup.html")

    @app.route("/prompt-planner")
    def page_prompt_planner():
        return render_template("prompts.html")

    @app.route("/api/assets/import-unity", methods=["POST"])
    def api_import_unity():
        category = request.form.get("category")
        asset_type = request.form.get("asset_type")
        file = request.files.get("file")
        relative_path = request.form.get("relative_path")
        
        if not category or not asset_type:
            return jsonify({"error": "category and asset_type are required"}), 400
            
        if not file and not relative_path:
            return jsonify({"error": "either file or relative_path is required"}), 400
            
        if asset_type not in ("art", "animation", "audio"):
            return jsonify({"error": "asset_type must be either 'art', 'animation', or 'audio'"}), 400
            
        from werkzeug.utils import secure_filename
        safe_category = secure_filename(category)
        
        if asset_type == "audio":
            unity_base = UNITY_AUDIO_EXPORT
            dest_dir = os.path.join(unity_base, safe_category)
        else:
            unity_base = UNITY_SCENES_EXPORT
            target_subfolder = "art" if asset_type == "art" else "animations"
            dest_dir = os.path.join(unity_base, target_subfolder, safe_category)
            
        os.makedirs(dest_dir, exist_ok=True)
        
        if relative_path:
            src_path = mu.resolve_existing_file_under_storage(relative_path)
            if not src_path or not os.path.isfile(src_path):
                return jsonify({"error": f"source file not found: {relative_path}"}), 404
            filename = os.path.basename(src_path)
            dest_path = os.path.join(dest_dir, filename)
        else:
            filename = secure_filename(file.filename)
            dest_path = os.path.join(dest_dir, filename)
            
        try:
            if relative_path:
                shutil.copy2(src_path, dest_path)
            else:
                file.save(dest_path)
            
            # Auto unzip if it is a zip archive
            if filename.endswith(".zip") and asset_type != "audio":
                import zipfile
                extract_dir = os.path.splitext(dest_path)[0]
                os.makedirs(extract_dir, exist_ok=True)
                with zipfile.ZipFile(dest_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
                print(f"Auto-extracted zip package to: {extract_dir}")
                
            return jsonify({
                "status": "success",
                "message": f"Successfully imported {filename} to Unity folder: {os.path.basename(unity_base)}/{safe_category}",
                "path": dest_path
            })
        except Exception as e:
            return jsonify({"error": f"Import failed: {str(e)}"}), 500

    @app.route("/companion-chat")
    @app.route("/nyxaris-chat")
    def page_nyxaris_chat():
        return render_template("nyxaris.html")

    @app.route("/animations/<anim_id>/play")
    def page_play_animation(anim_id: str):
        if not mu.bundle_exists(anim_id):
            abort(404)
        cleaned = request.args.get("mode") != "raw"
        urls, _ = list_frame_urls(anim_id, cleaned=cleaned)
        return render_template("animation_player.html", anim_id=anim_id, frame_urls_json=urls)

    @app.route("/api/assets/upload", methods=["POST"])
    def api_upload_asset():
        kind = request.form.get("kind")
        slug = request.form.get("slug")
        audio_category = request.form.get("audio_category")
        file = request.files.get("file")
        if not kind or not file:
            return jsonify({"error": "kind and file are required"}), 400
        try:
            res = svc_save_asset(kind, file, slug, audio_category)
            return jsonify(res)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/audio/generate", methods=["POST"])
    def api_generate_audio():
        data = request.get_json(force=True, silent=True) or {}
        preset = data.get("preset", "generated")
        nyx_ambient = int(data.get("nyx_ambient", 0))
        ui = int(data.get("ui", 0))
        combat = int(data.get("combat", 0))
        try:
            res = generate_audio_pack(preset=preset, nyx_ambient_count=nyx_ambient, ui_count=ui, combat_count=combat)
            return jsonify(res)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/media/list/images")
    def api_list_images():
        return jsonify(svc_list_images())

    @app.route("/api/media/list/videos")
    def api_list_videos():
        return jsonify(svc_list_videos())

    @app.route("/api/animations")
    @app.route("/api/media/list/animations")
    def api_list_animations():
        return jsonify(svc_list_animations())

    @app.route("/api/media/list/audio")
    def api_list_audio():
        return jsonify(svc_list_audios())

    @app.route("/api/styles", methods=["POST"])
    def api_save_style():
        data = request.get_json(force=True, silent=True) or {}
        name = data.get("name")
        tags = data.get("tags") or []
        rules = data.get("rules") or ""
        if not name:
            return jsonify({"error": "name required"}), 400
        from services.state_store import upsert_style
        res = upsert_style(name, tags, rules)
        return jsonify(res)

    @app.route("/api/system/summary")
    def api_system_summary():
        snap = progress_snapshot()
        from services.activity import hub as activity_hub
        snap["recent_activity"] = activity_hub.recent()
        snap["active_jobs"] = activity_hub.active_jobs()
        return jsonify(snap)

    @app.route("/companion", methods=["POST"])
    @app.route("/nyxaris", methods=["POST"])
    def api_nyxaris_chat():
        data = request.get_json(force=True, silent=True) or {}
        message = data.get("message")
        if not message:
            return jsonify({"error": "No message provided"}), 400
        mode = data.get("mode", "idle")
        try:
            trust = float(data.get("trust", 0.5))
        except (ValueError, TypeError):
            trust = 0.5
        level = data.get("level")
        model = data.get("model")
        res = nyx_chat_fn(message, mode, trust, model=model, level=level)
        return jsonify(res)

    @app.route("/api/companion/dev-assist", methods=["POST"])
    @app.route("/api/nyxaris/dev-assist", methods=["POST"])
    def api_nyxaris_dev_assist():
        data = request.get_json(force=True, silent=True) or {}
        topic = data.get("topic")
        if not topic:
            return jsonify({"error": "No topic provided"}), 400
        res = nyx_dev_assist(topic)
        return jsonify(res)

    @app.route("/api/animation/<anim_id>/frames")
    def api_get_animation_frames(anim_id: str):
        if not mu.bundle_exists(anim_id):
            abort(404)
        raw_urls, _ = list_frame_urls(anim_id, cleaned=False)
        clean_urls, _ = list_frame_urls(anim_id, cleaned=True)
        return jsonify({"raw": raw_urls, "clean": clean_urls})

    @app.route("/api/animations/<anim_id>/save-frame", methods=["POST"])
    def api_save_frame(anim_id: str):
        if not mu.bundle_exists(anim_id):
            abort(404)
        data = request.get_json(force=True, silent=True) or {}
        frame_index = data.get("frame_index")
        image = data.get("image")
        filename = data.get("filename")
        folder = data.get("folder", "clean")
        if frame_index is None or not image:
            return jsonify({"error": "frame_index and image required"}), 400
        try:
            result = save_edited_frame(anim_id, frame_index=int(frame_index), image_data_url=image, filename=filename, folder=folder)
            # Copy all clean frames of this animation to Unity folder (subfolder per animation ID)
            if folder == "clean":
                unity_frames_dir = os.path.join(UNITY_FRAMES_EXPORT, anim_id)
                os.makedirs(unity_frames_dir, exist_ok=True)
                cleaned_dir = mu.animation_clean_dir(anim_id)
                if os.path.isdir(cleaned_dir):
                    for fname in sorted(os.listdir(cleaned_dir), key=mu.natural_sort_key):
                        if fname.endswith(".png"):
                            shutil.copy2(os.path.join(cleaned_dir, fname), os.path.join(unity_frames_dir, fname))
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(result)

    @app.route("/api/animations/<anim_id>/save-frames", methods=["POST"])
    def api_save_frames_batch(anim_id: str):
        if not mu.bundle_exists(anim_id):
            abort(404)
        data = request.get_json(force=True, silent=True) or {}
        frames = data.get("frames") or []
        if not frames:
            return jsonify({"error": "frames array required"}), 400
        folder = data.get("folder", "clean")
        if folder not in ("raw", "clean"):
            return jsonify({"error": "folder must be raw or clean"}), 400
        try:
            result = save_edited_frames_batch(anim_id, frames, folder=folder)
            # Copy all clean frames of this animation to Unity folder (subfolder per animation ID)
            if folder == "clean":
                unity_frames_dir = os.path.join(UNITY_FRAMES_EXPORT, anim_id)
                os.makedirs(unity_frames_dir, exist_ok=True)
                cleaned_dir = mu.animation_clean_dir(anim_id)
                if os.path.isdir(cleaned_dir):
                    for fname in sorted(os.listdir(cleaned_dir), key=mu.natural_sort_key):
                        if fname.endswith(".png"):
                            shutil.copy2(os.path.join(cleaned_dir, fname), os.path.join(unity_frames_dir, fname))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(result)

    @app.route("/export/unity")
    def api_export_unity():
        data_bytes, name = unity_export_zip()
        return Response(
            data_bytes,
            mimetype="application/zip",
            headers={"Content-Disposition": f"attachment; filename={name}"}
        )

    @app.route("/export/full")
    def api_export_full():
        data_bytes, name = full_project_zip()
        return Response(
            data_bytes,
            mimetype="application/zip",
            headers={"Content-Disposition": f"attachment; filename={name}"}
        )

    @app.route("/api/animations/<anim_id>/pack", methods=["POST"])
    def api_pack_animation(anim_id: str):
        if not mu.bundle_exists(anim_id):
            abort(404)
        data = request.get_json(force=True, silent=True) or {}
        folder = data.get("folder", "clean")
        if folder not in ("raw", "clean"):
            return jsonify({"error": "folder must be raw or clean"}), 400
        try:
            from services.animation_svc import pack_sprite_sheet
            res = pack_sprite_sheet(anim_id, folder=folder)
            return jsonify(res)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/skeletal-animator")
    @app.route("/animations/skeletal")
    def page_skeletal_animator():
        return render_template("skeletal_animator.html")

    @app.route("/character-builder")
    def page_character_builder():
        return render_template("character_builder.html")

    @app.route("/api/companion/status")
    @app.route("/api/nyxaris/status")
    def api_nyxaris_status():
        import requests
        try:
            res = requests.get("http://localhost:11434/api/tags", timeout=3)
            if res.status_code == 200:
                models = res.json().get("models", [])
                model_names = [m.get("name") for m in models]
                has_nyxaris = any("nyxaris" in name.lower() for name in model_names)
                return jsonify({
                    "ollama_running": True,
                    "has_nyxaris": has_nyxaris,
                    "models": model_names
                })
        except Exception:
            pass
        return jsonify({
            "ollama_running": False,
            "has_nyxaris": False,
            "models": []
        })

    @app.route("/api/companion/pull", methods=["POST"])
    @app.route("/api/nyxaris/pull", methods=["POST"])
    def api_nyxaris_pull():
        import requests
        def pull_model():
            try:
                requests.post("http://localhost:11434/api/pull", json={"name": "nyxaris"}, timeout=300)
            except Exception:
                pass
        import threading
        threading.Thread(target=pull_model).start()
        return jsonify({"status": "started", "message": "Pulling 'nyxaris' model from Ollama in background."})

    @app.route("/api/ai-animation/providers")
    def api_ai_animation_providers():
        return jsonify(ai_anim_svc.get_provider_status())

    @app.route("/api/ai-animation/generate", methods=["POST"])
    def api_ai_animation_generate():
        prompt = request.form.get("prompt") or request.json.get("prompt") if request.is_json else request.form.get("prompt", "idle motion")
        motion_type = request.form.get("motion_type", "idle")
        frame_count = int(request.form.get("frame_count", "8"))
        columns = int(request.form.get("columns", "4"))
        remove_bg = request.form.get("remove_bg", "true").lower() in ("true", "1", "yes")
        provider = request.form.get("provider", "auto")

        source_img_path = None
        if "source_image" in request.files:
            file = request.files["source_image"]
            if file and file.filename:
                fn = f"{mu.short_id('src')}_{file.filename}"
                source_img_path = os.path.join(mu.workspace_upload_dir(), fn)
                file.save(source_img_path)

        try:
            res = ai_anim_svc.create_ai_animation_bundle(
                prompt=prompt,
                motion_type=motion_type,
                source_img_path=source_img_path,
                frame_count=frame_count,
                columns=columns,
                remove_bg=remove_bg,
                provider=provider
            )
            return jsonify({"status": "success", "result": res})
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 400

    @app.route("/api/ai-animation/pack-spritesheet", methods=["POST"])
    def api_ai_animation_pack():
        data = request.get_json(silent=True) or {}
        image_urls = data.get("image_urls", [])
        cols = int(data.get("columns", 4))
        
        if not image_urls:
            return jsonify({"error": "No image URLs provided"}), 400

        # Resolve image file paths from URLs
        local_paths = []
        for url in image_urls:
            if url.startswith("/media/"):
                rel = url.replace("/media/", "", 1)
                full = mu.resolve_existing_file_under_storage(rel)
                if full:
                    local_paths.append(full)
            elif url.startswith("/outputs/"):
                fname = os.path.basename(url)
                full = os.path.join(mu.workspace_output_dir(), fname)
                if os.path.exists(full):
                    local_paths.append(full)
            elif url.startswith("/uploads/"):
                fname = os.path.basename(url)
                full = os.path.join(mu.workspace_upload_dir(), fname)
                if os.path.exists(full):
                    local_paths.append(full)

        if not local_paths:
            return jsonify({"error": "Could not resolve image paths"}), 400

        out_name = f"packed_{mu.short_id('sheet')}.png"
        out_path = os.path.join(mu.workspace_output_dir(), out_name)

        try:
            pack_info = ai_anim_svc.pack_sprite_sheet(local_paths, out_path, cols=cols)
            return jsonify({
                "status": "success",
                "sprite_sheet_url": f"/outputs/{out_name}",
                "pack_info": pack_info
            })
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 400

    # ── Voice & Audio Slicer Studio ──────────────────────────────────────────
    @app.route("/audio-slicer")
    def page_audio_slicer():
        return render_template("audio_slicer.html")

    @app.route("/api/audio-slicer/upload", methods=["POST"])
    def api_audio_slicer_upload():
        file = request.files.get("file")
        if not file:
            return jsonify({"error": "No audio file provided"}), 400
        try:
            meta = slicer_svc.inspect_and_cache_wav(file)
            return jsonify({"status": "success", "data": meta})
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 400

    @app.route("/api/audio-slicer/stream/<file_id>")
    def api_audio_slicer_stream(file_id: str):
        wav_path = slicer_svc.get_cached_file_path(file_id)
        if not os.path.isfile(wav_path):
            abort(404)
        return send_file(wav_path, mimetype="audio/wav")

    @app.route("/api/audio-slicer/detect-silence", methods=["POST"])
    def api_audio_slicer_detect_silence():
        data = request.get_json() or {}
        file_id = data.get("file_id")
        if not file_id:
            return jsonify({"error": "file_id is required"}), 400
        try:
            silence_thresh_db = float(data.get("silence_thresh_db", -36.0))
            min_silence_sec = float(data.get("min_silence_sec", 0.28))
            min_speech_sec = float(data.get("min_speech_sec", 0.12))
            regions = slicer_svc.detect_silence_regions(
                file_id=file_id,
                silence_thresh_db=silence_thresh_db,
                min_silence_sec=min_silence_sec,
                min_speech_sec=min_speech_sec
            )
            return jsonify({"status": "success", "regions": regions})
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 400

    @app.route("/api/audio-slicer/export", methods=["POST"])
    def api_audio_slicer_export():
        data = request.get_json() or {}
        file_id = data.get("file_id")
        slices = data.get("slices", [])
        if not file_id or not slices:
            return jsonify({"error": "file_id and slices list are required"}), 400
        try:
            apply_micro_fades = bool(data.get("apply_micro_fades", True))
            normalize_volume = bool(data.get("normalize_volume", True))
            export_to_unity = bool(data.get("export_to_unity", True))
            export_to_storage = bool(data.get("export_to_storage", True))

            res = slicer_svc.slice_and_export(
                file_id=file_id,
                slices_data=slices,
                apply_micro_fades=apply_micro_fades,
                normalize_volume=normalize_volume,
                export_to_unity=export_to_unity,
                export_to_storage=export_to_storage
            )
            return jsonify(res)
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 400

    @app.route("/api/audio-slicer/download-zip/<zip_id>")
    def api_audio_slicer_download_zip(zip_id: str):
        zip_path = os.path.join(slicer_svc.CACHE_TEMP_DIR, f"{zip_id}.zip")
        if not os.path.isfile(zip_path):
            abort(404)
        return send_file(zip_path, as_attachment=True, download_name="voice_slices.zip")
