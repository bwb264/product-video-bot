from flask import Flask, request, jsonify
import subprocess
import requests
import os
import json
import time
import logging
import jwt

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KLING_ACCESS_KEY = os.environ.get("KLING_ACCESS_KEY", "")
KLING_SECRET_KEY = os.environ.get("KLING_SECRET_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
OUTPUT_DIR = "/tmp/videos"
os.makedirs(OUTPUT_DIR, exist_ok=True)
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
def generate_kling_jwt():
    payload = {
        "iss": KLING_ACCESS_KEY,
        "exp": int(time.time()) + 1800,
        "nbf": int(time.time()) - 5
    }
    return jwt.encode(payload, KLING_SECRET_KEY, algorithm="HS256")

def create_kling_video(image_url, prompt):
    token = generate_kling_jwt()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    body = {
        "model_name": "kling-v1",
        "image_url": image_url,
        "prompt": prompt,
        "duration": "5",
        "mode": "std",
        "cfg_scale": 0.5
    }
    try:
        resp = requests.post(
            "https://api.klingai.com/v1/videos/image2video",
            headers=headers, json=body, timeout=30
        )
        data = resp.json()
        logger.info(f"Kling: {data}")
        return data.get("data", {}).get("task_id")
    except Exception as e:
        logger.error(f"Kling error: {e}")
        return None

def poll_kling_video(task_id, max_attempts=24):
    for attempt in range(max_attempts):
        try:
            token = generate_kling_jwt()
            headers = {"Authorization": f"Bearer {token}"}
            resp = requests.get(
                f"https://api.klingai.com/v1/videos/image2video/{task_id}",
                headers=headers, timeout=30
            )
            data = resp.json()
            status = data.get("data", {}).get("task_status", "")
            logger.info(f"Task {task_id}: {status}")
            if status == "succeed":
                videos = data["data"]["task_result"]["videos"]
                if videos:
                    return videos[0]["url"]
            elif status == "failed":
                return None
            time.sleep(15)
        except Exception as e:
            logger.error(f"Poll error: {e}")
            time.sleep(10)
    return None
  def generate_voice(text, output_path):
    try:
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        }
        body = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.4,
                "use_speaker_boost": True
            }
        }
        voice_id = "onwK4e9ZLuTAKqWW03F9"
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers=headers, json=body, timeout=60
        )
        if resp.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(resp.content)
            return True
        return False
    except Exception as e:
        logger.error(f"Voice error: {e}")
        return False

def download_file(url, path):
    try:
        resp = requests.get(url, timeout=120, stream=True)
        resp.raise_for_status()
        with open(path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False

def create_intro(product_name, output_path):
    safe_name = product_name.replace("'", "").replace(":", "")[:25]
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "color=c=0x0d0d0d:size=1080x1080:duration=4:rate=30",
        "-vf",
        f"drawtext=fontfile={FONT_PATH}:text='✨ {safe_name} ✨':fontsize=68:fontcolor=gold:borderw=3:bordercolor=black:x=(w-text_w)/2:y=(h/2)-60:alpha='if(lt(t,0.8),0,if(lt(t,1.8),t-0.8,1))',drawtext=fontfile={FONT_PATH}:text='اكتشف الفرق':fontsize=44:fontcolor=white:x=(w-text_w)/2:y=(h/2)+50:alpha='if(lt(t,1.5),0,if(lt(t,2.5),t-1.5,1))'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0
  def merge_videos(paths, output_path):
    list_file = output_path + "_list.txt"
    with open(list_file, "w") as f:
        for p in paths:
            f.write(f"file '{p}'\n")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy", output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.remove(list_file)
    return result.returncode == 0

def add_audio_to_video(video_path, audio_path, output_path):
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-filter_complex", "[1:a]apad,volume=1.3[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

def send_telegram_video(chat_id, video_path, caption):
    try:
        with open(video_path, "rb") as vf:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo",
                data={"chat_id": chat_id, "caption": caption,
                      "parse_mode": "Markdown", "supports_streaming": True},
                files={"video": vf}, timeout=120
            )
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

def send_telegram_message(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception:
        pass

@app.route("/process", methods=["POST"])
def process():
    data = request.get_json()
    chat_id = data.get("chat_id", "")
    image_url = data.get("image_url", "")
    product_name = data.get("product_name", "منتج رائع")
    scenes = data.get("scenes", [])
    voiceover = data.get("voiceover_script", "")
    overlay_texts = data.get("overlay_texts", [])

    job_id = f"job_{int(time.time())}"
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    send_telegram_message(chat_id, "🎬 جارٍ توليد مشاهد الفيديو... (2-3 دقائق)")

    task_ids = []
    for scene in scenes[:3]:
        tid = create_kling_video(image_url, scene.get("prompt", "cinematic product shot"))
        if tid:
            task_ids.append(tid)
            time.sleep(2)

    audio_path = os.path.join(job_dir, "voice.mp3")
    voice_ok = generate_voice(voiceover, audio_path)

    send_telegram_message(chat_id, "⏳ جارٍ معالجة الفيديو...")

    video_paths = []
    for tid in task_ids:
        url = poll_kling_video(tid)
        if url:
            vpath = os.path.join(job_dir, f"scene_{len(video_paths)}.mp4")
            if download_file(url, vpath):
                video_paths.append(vpath)

    if not video_paths:
        send_telegram_message(chat_id, "❌ حدث خطأ، حاول مرة أخرى.")
        return jsonify({"success": False}), 500

    intro_path = os.path.join(job_dir, "intro.mp4")
    if create_intro(product_name, intro_path):
        video_paths.insert(0, intro_path)

    merged_path = os.path.join(job_dir, "merged.mp4")
    merge_videos(video_paths, merged_path)

    final_path = os.path.join(job_dir, "final.mp4")
    if voice_ok and os.path.exists(audio_path):
        if not add_audio_to_video(merged_path, audio_path, final_path):
            final_path = merged_path
    else:
        final_path = merged_path

    caption = f"🎬 *{product_name}*\n\n✨ تم إنشاء الفيديو بالذكاء الاصطناعي"
    success = send_telegram_video(chat_id, final_path, caption)
    return jsonify({"success": success, "job_id": job_id})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Product Video Bot Running 🚀"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
