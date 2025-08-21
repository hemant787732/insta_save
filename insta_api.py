import os
import re
import threading
from uuid import uuid4
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO
from dotenv import load_dotenv
import yt_dlp

# Load .env if present
load_dotenv()

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
COOKIES_FILE = os.getenv("COOKIES_FILE") or None
FFMPEG_PATH = os.getenv("FFMPEG_PATH") or None
ALLOW_IMAGES = (os.getenv("ALLOW_IMAGES", "yes").lower() == "yes")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5000"))

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

jobs = {}  # in-memory job store: job_id -> dict

ANSI_RE = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')

def clean_percent(s):
    if not s:
        return 0.0
    try:
        return float(re.sub(r'[^\d.]','', ANSI_RE.sub('', str(s) ) ) or 0.0)
    except:
        return 0.0

def progress_hook_factory(job_id):
    def hook(d):
        try:
            job = jobs.get(job_id)
            if not job:
                return
            status = d.get('status')
            if status == 'downloading':
                pct = d.get('_percent_str') or '0%'
                pct_val = clean_percent(pct)
                job.update({
                    'status': 'downloading',
                    'progress': f"{pct_val:.2f}%",
                    'speed': d.get('_speed_str', ''),
                    'eta': d.get('_eta_str', '')
                })
                socketio.emit('progress', {'job_id': job_id, **job})
            elif status == 'finished':
                job.update({'status': 'processing', 'progress': '100%'})
                socketio.emit('progress', {'job_id': job_id, **job})
        except Exception as e:
            job = jobs.get(job_id, {})
            job['status'] = 'error'
            job['error'] = str(e)
            socketio.emit('progress', {'job_id': job_id, **job})
    return hook

def build_ydl_opts(job_id):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outtmpl = os.path.join(DOWNLOAD_DIR, f"%(uploader)s__%(id)s__{timestamp}.%(ext)s")
    opts = {
        'outtmpl': outtmpl,
        'noplaylist': True,
        'progress_hooks': [progress_hook_factory(job_id)],
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': False,
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'concurrent_fragment_downloads': 4,
        'retries': 10,
        'fragment_retries': 10,
    }
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE
    if FFMPEG_PATH:
        opts['ffmpeg_location'] = FFMPEG_PATH
    if not ALLOW_IMAGES:
        opts['postprocessors'] = [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4'
        }]
    return opts

def do_download(job_id, url):
    job = jobs[job_id]
    job['status'] = 'starting'
    socketio.emit('progress', {'job_id': job_id, **job})
    opts = build_ydl_opts(job_id)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            base, _ = os.path.splitext(filename)
            final = None
            for ext in ('.mp4', '.mkv', '.mov', '.webm', '.jpg', '.jpeg', '.png'):
                candidate = base + ext
                if os.path.exists(candidate):
                    final = candidate
                    break
            if not final and os.path.exists(filename):
                final = filename
            if not final:
                job['status'] = 'error'
                job['error'] = 'Download finished but file not found'
                socketio.emit('progress', {'job_id': job_id, **job})
                return
            safe_name = re.sub(r'[^A-Za-z0-9\-\._\(\) ]+', '_', os.path.basename(final))
            safe_path = os.path.join(DOWNLOAD_DIR, safe_name)
            if final != safe_path:
                try:
                    os.replace(final, safe_path)
                    final = safe_path
                except Exception:
                    pass
            job['status'] = 'done'
            job['progress'] = '100%'
            job['file_path'] = os.path.relpath(final, DOWNLOAD_DIR)
            socketio.emit('progress', {'job_id': job_id, **job})
    except Exception as e:
        job['status'] = 'error'
        job['error'] = str(e)
        socketio.emit('progress', {'job_id': job_id, **job})

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/api/download', methods=['POST'])
def api_download():
    body = request.get_json(silent=True) or request.form or {}
    url = (body.get('url') or '').strip()
    if not url or 'instagram.com' not in url:
        return jsonify({'ok': False, 'error': 'Please provide a valid Instagram URL'}), 400
    job_id = uuid4().hex
    jobs[job_id] = {
        'status': 'queued',
        'progress': '0%',
        'speed': '',
        'eta': '',
        'file_path': None,
        'error': None
    }
    socketio.start_background_task(do_download, job_id, url)
    return jsonify({'ok': True, 'job_id': job_id})

@app.route('/api/status/<job_id>', methods=['GET'])
def api_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'ok': False, 'error': 'Job not found'}), 404
    return jsonify({'ok': True, 'job': job})

@app.route('/files/<path:filename>', methods=['GET'])
def serve_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)

if __name__ == '__main__':
    print('Starting Insta downloader on', HOST, PORT)
    socketio.run(app, host=HOST, port=PORT)
