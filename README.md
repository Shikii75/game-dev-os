# 🎮 Game Dev OS — Studio Edition

**Universal Asset Pipeline & Toolchain Workstation for 2D Action RPGs & Indie Games**

[![Render Deployment](https://img.shields.io/badge/Deploy-Render-46e3b7?logo=render&logoColor=white)](https://render.com)
[![Engine Support](https://img.shields.io/badge/Engine-Unity%206%20LTS%20(URP)-blue?logo=unity)](https://unity.com)
[![Python](https://img.shields.io/badge/Backend-Python%203.11%20%7C%20Flask-3776ab?logo=python)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 📌 Overview

**Game Dev OS** is a lightweight, high-performance developer workstation and asset pipeline designed for indie game developers building 2D action games, platformers, and RPGs. 

It provides an end-to-end bridge between raw multimedia assets (reference gameplay videos, voice acting WAV takes, character concept art) and game engines like **Unity 6 LTS (Universal Render Pipeline)**.

---

## 🚀 Core Production Suites

### 1. 🎨 Asset Generation & 2D Kinematics
* **Animation Studio:** Synthesize and configure 2D directional game sprites and transparent sprite sheets.
* **Skeletal Rigging Animator:** Interactive 2D joint rigging, pivot hierarchies, and keyframe interpolation for character sprites.
* **Batch Frame Slicer:** Automatically slices gameplay/reference footage into sequence frames with automated matting.
* **Neural Sprite BG Remover:** Integrated foreground/background extraction tool (`rembg` + OpenCV) producing clean transparent PNGs.

### 2. 🎙️ Voice & Audio Engineering
* **Voice Take Slicer:** Automated silence thresholding, waveform segmentation, and character dialogue categorization with 1-click engine export.
* **Audio Extractor:** Demux weapon slashes, impact Foley, and ambient audio loops from video files into uncompressed WAV clips.
* **Spatial Sound Repository:** Centralized sound effects library structured by environment: World Zones, Dungeons, and Boss Arenas.

### 3. ⚙️ Engine Integration & Project Controls
* **Sprint & Milestone Tracker:** Track feature deliverables, combat mechanics, enemy AI states, and QA roadmaps.
* **Unity Package Exporter:** Bundles processed spritesheets, audio takes, and metadata into import-ready folders.
* **AI Dialogue & Lore Assistant:** Contextual narrative and gameplay assistant supporting Ollama / local LLM daemons.

---

## 🛠️ Tech Stack

* **Server:** Python 3.11, Flask 3.0, Gunicorn WSGI
* **Computer Vision & Media:** OpenCV Headless, Pillow, Rembg, ImageIO / FFmpeg
* **Frontend:** Modern Vanilla CSS Design System, Responsive App Shell, Google Fonts (Inter, Plus Jakarta Sans, JetBrains Mono)
* **Deployment:** 1-Click Render Cloud Web Service, Docker, or Standalone Local Daemon

---

## ⚡ Quickstart

### Local Setup
```bash
# Clone the repository
git clone https://github.com/Shikii75/game-dev-os.git
cd game-dev-os

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Launch development server
python app.py
```
Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## 🌐 Configuration & Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `5000` | HTTP port for web server |
| `GAME_DEV_OS_HOST` | `0.0.0.0` | Host bind address |
| `UNITY_PROJECT_DIR` | `./exports/unity` | Base export folder for Unity engine assets |
| `UNITY_AUDIO_DIR` | `./exports/unity/Assets/Audio` | Destination for sliced voice takes & sound FX |
| `UNITY_FRAMES_DIR` | `./exports/unity/Assets/Animations/Frames` | Destination for processed animation frames |

---

## 📄 License
Released under the MIT License. Built for indie game development teams and solo creators.
