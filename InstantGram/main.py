import json
import os
import random
import time
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime
from functools import wraps
from pathlib import Path
from datetime import datetime
import shutil

from flask import Flask, Response, make_response, redirect, render_template, render_template_string, request, send_file, session, url_for
from werkzeug.utils import safe_join
import logging

import threading

# log = logging.getLogger('werkzeug')
# log.setLevel(logging.ERROR)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = 55 * 1024 * 1024

BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = BASE_DIR / "media"
if not os.path.exists(MEDIA_DIR): os.mkdir(MEDIA_DIR)
USERS_JSON = BASE_DIR / "users.json"
BOOKMARKS_JSON = BASE_DIR / "bookmarks.json"
HISTORY_JSON = BASE_DIR / "history.json"
SETTINGS_JSON = BASE_DIR / "settings.json"
MAX_MEDIA_SIZE_BYTES = 50 * 1024 * 1024
PAGE_SIZE = 7 
IMAGE_EXTENSIONS = {'.jpg', '.jpeg'}
VIDEO_EXTENSIONS = {'.mp4'}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

EXPLORE_TEMPLATE = "explore.html"
SAVED_GRID_TEMPLATE = "saved.html"

_MEDIA_CACHE = []
_MEDIA_CACHE_TIME = 0
CACHE_TTL_SECONDS = 60 

def format_number(num):
    try:
        num = int(num)
        if num >= 1000000: return f"{num/1000000:.1f}M"
        if num >= 1000: return f"{num/1000:.1f}K"
        return str(num)
    except Exception:
        return str(num)

app.jinja_env.filters['short_num'] = format_number


def _timestamp_from_file(path_obj: Path) -> str:
    stat = path_obj.stat()
    ts = getattr(stat, "st_birthtime", stat.st_mtime)
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")

def _load_json(path: Path, fallback):
    if not path.exists():
        path.write_text(json.dumps(fallback, indent=2), encoding="utf-8")
        return fallback
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return fallback

def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

def no_store(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

def render_no_store_template(template, **context):
    return no_store(make_response(render_template(template, **context)))

def resolve_media_path(media_id):
    target = safe_join(str(MEDIA_DIR), media_id)
    if target:
        path = Path(target)
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
            return path

    # Old browser pages can point at media that was moved between folders.
    filename = Path(media_id).name
    suffix = Path(filename).suffix.lower()
    if not filename or suffix not in MEDIA_EXTENSIONS:
        return None

    matches = sorted(
        p for p in MEDIA_DIR.rglob(filename)
        if p.is_file() and p.suffix.lower() == suffix
    )
    return matches[0] if matches else None

def send_cached_file(path, cache_seconds=3600):
    response = send_file(path, conditional=True)
    response.headers["Cache-Control"] = f"public, max-age={cache_seconds}"
    return response

def generate_thumbnail(video_path, thumb_path):
    cmd = ['ffmpeg', '-i', str(video_path), '-ss', '00:00:00.500', '-vframes', '1', str(thumb_path), '-y']
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def thumbnail_placeholder(label="No Thumb"):
    svg_placeholder = f'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="100%" height="100%" fill="#222"/><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="#555" font-family="sans-serif">{label}</text></svg>'
    return no_store(Response(svg_placeholder, mimetype='image/svg+xml'))

def ensure_seed_files():
    _load_json(USERS_JSON, {"users": [{"username": "admin", "password": "password", "dir": "default"}]})
    _load_json(BOOKMARKS_JSON, {})
    _load_json(HISTORY_JSON, {})
    _load_json(SETTINGS_JSON, {})

def parse_metadata(file_path):
    """Checks for companion JSON metadata file for likes & comments."""
    meta_file = file_path.with_suffix('.json')
    if not meta_file.exists():
        meta_file = file_path.with_name(file_path.stem + '.info.json')
        if not meta_file.exists():
            return None, None
    try:
        with open(meta_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            likes = data.get('like_count') or data.get('likes')
            if likes is None and 'edge_media_preview_like' in data:
                likes = data['edge_media_preview_like'].get('count')
                
            comments = data.get('comment_count') or data.get('comments')
            if comments is None and 'edge_media_to_comment' in data:
                comments = data['edge_media_to_comment'].get('count')
                
            return likes, comments
    except Exception:
        return None, None

def scan_media():
    media_list = []
    if not MEDIA_DIR.exists(): MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Expecting: MEDIA_DIR/DATE(ex 2026-22-4)/(Videos)/*********.(mp4|jpg)
    for file in MEDIA_DIR.rglob("*"):
        if not file.is_file() or file.suffix.lower() not in MEDIA_EXTENSIONS: continue
        file_stat = file.stat()
        if file_stat.st_size > MAX_MEDIA_SIZE_BYTES: continue
        
        rel_parts = file.relative_to(MEDIA_DIR).parts
        folder_date = rel_parts[0] if len(rel_parts) > 0 else "Unknown"
        category = rel_parts[1] if len(rel_parts) > 1 else "Unknown"
        
        is_video = file.suffix.lower() in VIDEO_EXTENSIONS
        
        # PREVENT VIDEO THUMBNAILS FROM BECOMING POSTS:
        # If it's a JPG, it MUST be inside the "Posts" folder to be recognized.
        if not is_video and category != "Posts":
            continue
            
        media_id = "/".join(rel_parts)
        likes, comments = parse_metadata(file)
        
        media_list.append({
            "id": media_id,
            "date": folder_date,
            "filename": file.name,
            "title": "Post" if not is_video else "Video", 
            "description": "", 
            "author": category,
            "timestamp": _timestamp_from_file(file),
            "size": file_stat.st_size,
            "version": f"{file_stat.st_mtime_ns}-{file_stat.st_size}",
            "is_video": is_video,
            "likes": likes,
            "comments": comments
        })
    return media_list

def startup_generate_thumbnails():
    """Scans all videos and generates missing thumbnails before the server starts."""
    print("Scanning for missing thumbnails...")
    media_items = scan_media()
    generated_count = 0
    for m in media_items:
        if not m["is_video"]: 
            continue # Images don't need generated thumbnails
            
        video_path = MEDIA_DIR / m["id"]
        thumb_path = video_path.with_suffix('.jpg')
        
        if not thumb_path.exists():
            print(f"Generating missing thumbnail for {m['filename']}...")
            try:
                generate_thumbnail(video_path, thumb_path)
                generated_count += 1
            except Exception as e:
                print(f"Failed to generate thumbnail for {m['filename']}: {e}")
    print(f"Thumbnail scan complete. Generated {generated_count} new thumbnails.")

def get_media_index(force=False):
    global _MEDIA_CACHE, _MEDIA_CACHE_TIME
    if not force and _MEDIA_CACHE and (time.time() - _MEDIA_CACHE_TIME < CACHE_TTL_SECONDS):
        return _MEDIA_CACHE
    _MEDIA_CACHE = scan_media()
    _MEDIA_CACHE_TIME = time.time()
    return _MEDIA_CACHE

def get_current_user(): return session.get("user")

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not get_current_user(): return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def build_feed_items(offset, limit, bookmarked_ids, media_items, base_url, show_download=False):
    slice_items = media_items[offset : offset + limit]
    rendered = [render_template("media_card_partial.html", media=m, bookmarked=bookmarked_ids, show_download=show_download) for m in slice_items]
    if next_offset := offset + limit < len(media_items):
        rendered.append(render_template("load_more_marker.html", load_more_url=f"{base_url}?offset={offset + limit}&limit={limit}"))
    return "\n".join(rendered)

def filter_watched(user, media_items):
    settings = _load_json(SETTINGS_JSON, {})
    hide_watched = settings.get(user, {}).get("hide_watched", False)
    if hide_watched:
        history = _load_json(HISTORY_JSON, {}).get(user, {})
        return [m for m in media_items if m["id"] not in history]
    return media_items

@app.route("/")
def index():
    return redirect(url_for("feed")) if get_current_user() else redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        users = {u.get("username"): u for u in _load_json(USERS_JSON, {"users": []}).get("users", [])}
        user = request.form.get("username", "")
        if user in users and users[user]["password"] == request.form.get("password", ""):
            session["user"] = user
            return redirect(url_for("feed"))
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html", error=None)

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/feed")
@login_required
def feed():
    user = get_current_user()
    bookmarks = set(_load_json(BOOKMARKS_JSON, {}).get(user, []))
    history = _load_json(HISTORY_JSON, {}).get(user, {})
    
    all_media = get_media_index()
    filtered = filter_watched(user, all_media)
    
    media_items = sorted(filtered, key=lambda m: history.get(m["id"], 0) + random.uniform(0, history.get(m["id"], 0) + 1))
    
    return render_template("feed.html", items=build_feed_items(0, PAGE_SIZE, bookmarks, media_items, "/feed/items"), user=user, active_tab="feed", bookmarked=list(bookmarks))

@app.route("/feed/items")
@login_required
def feed_items():
    user = get_current_user()
    offset, limit = int(request.args.get("offset", 0)), int(request.args.get("limit", PAGE_SIZE))
    history = _load_json(HISTORY_JSON, {}).get(user, {})
    media_items = sorted(filter_watched(user, get_media_index()), key=lambda m: history.get(m["id"], 0) + random.uniform(0, history.get(m["id"], 0) + 1))
    return Response(build_feed_items(offset, limit, set(_load_json(BOOKMARKS_JSON, {}).get(user, [])), media_items, "/feed/items"))

@app.route("/explore")
@login_required
def explore():
    media_items = filter_watched(get_current_user(), list(get_media_index(force=True)))
    random.shuffle(media_items)
    return render_no_store_template(EXPLORE_TEMPLATE, items=media_items)

@app.route("/explore_feed/<path:media_id>")
@login_required
def explore_feed(media_id):
    user = get_current_user()
    bookmarks = set(_load_json(BOOKMARKS_JSON, {}).get(user, []))
    media_items = filter_watched(user, list(get_media_index()))
    start = next((m for m in media_items if m["id"] == media_id), None)
    if start: media_items.remove(start); random.shuffle(media_items); media_items.insert(0, start)
    return render_template("feed.html", items=build_feed_items(0, PAGE_SIZE, bookmarks, media_items, f"/explore_feed/items/{media_id}"), user=user, active_tab="explore", bookmarked=list(bookmarks), is_explorer_feed=True)

@app.route("/explore_feed/items/<path:media_id>")
@login_required
def explore_feed_items(media_id):
    user = get_current_user()
    offset, limit = int(request.args.get("offset", 0)), int(request.args.get("limit", PAGE_SIZE))
    media_items = filter_watched(user, list(get_media_index()))
    start = next((m for m in media_items if m["id"] == media_id), None)
    if start: media_items.remove(start); random.shuffle(media_items); media_items.insert(0, start)
    return Response(build_feed_items(offset, limit, set(_load_json(BOOKMARKS_JSON, {}).get(user, [])), media_items, f"/explore_feed/items/{media_id}"))

@app.route("/bookmarks")
@login_required
def bookmarks_view():
    user = get_current_user()
    bookmarks = set(_load_json(BOOKMARKS_JSON, {}).get(user, []))
    media_items = [m for m in get_media_index() if m["id"] in bookmarks]
    return render_no_store_template(SAVED_GRID_TEMPLATE, items=media_items)

@app.route("/bookmarks_feed/<path:media_id>")
@login_required
def bookmarks_feed(media_id):
    user = get_current_user()
    bookmarks = set(_load_json(BOOKMARKS_JSON, {}).get(user, []))
    media_items = [m for m in get_media_index() if m["id"] in bookmarks]
    
    start = next((m for m in media_items if m["id"] == media_id), None)
    if start: media_items.remove(start); media_items.insert(0, start)
    
    return render_template("feed.html", items=build_feed_items(0, PAGE_SIZE, bookmarks, media_items, f"/bookmarks_feed/items/{media_id}", show_download=True), user=user, active_tab="bookmarks", feed_title="Saved Collection", bookmarked=list(bookmarks), is_bookmarks_feed=True)

@app.route("/bookmarks_feed/items/<path:media_id>")
@login_required
def bookmarks_feed_items(media_id):
    user = get_current_user()
    offset, limit = int(request.args.get("offset", 0)), int(request.args.get("limit", PAGE_SIZE))
    bookmarks = set(_load_json(BOOKMARKS_JSON, {}).get(user, []))
    media_items = [m for m in get_media_index() if m["id"] in bookmarks]
    
    start = next((m for m in media_items if m["id"] == media_id), None)
    if start: media_items.remove(start); media_items.insert(0, start)
    
    return Response(build_feed_items(offset, limit, bookmarks, media_items, f"/bookmarks_feed/items/{media_id}", show_download=True))

@app.route("/bookmark/<path:media_id>", methods=["POST"])
@login_required
def bookmark(media_id):
    user = get_current_user()
    b_data = _load_json(BOOKMARKS_JSON, {})
    user_set = set(b_data.get(user, []))
    if media_id in user_set: user_set.discard(media_id)
    else: user_set.add(media_id)
    b_data[user] = sorted(user_set)
    save_json(BOOKMARKS_JSON, b_data)
    return Response(status=204)

@app.route("/api/view/<path:media_id>", methods=["POST"])
@login_required
def record_view(media_id):
    user = get_current_user()
    history = _load_json(HISTORY_JSON, {})
    if user not in history: history[user] = {}
    history[user][media_id] = history[user].get(media_id, 0) + 1
    save_json(HISTORY_JSON, history)
    return Response(status=204)

@app.route("/settings")
@login_required
def settings_view():
    user = get_current_user()
    media_items = get_media_index()
    history = _load_json(HISTORY_JSON, {}).get(user, {})
    settings = _load_json(SETTINGS_JSON, {}).get(user, {})
    
    watched_items = [m for m in media_items if m["id"] in history]
    watched_size_gb = sum(m.get("size", 0) for m in watched_items) / (1024**3)
    
    by_date = defaultdict(list)
    for m in media_items: 
        by_date[m["date"]].append(m)
        
    folder_stats = []
    for date, items in by_date.items():
        total = len(items)
        watched = sum(1 for m in items if m["id"] in history)
        if watched == total:
            tag = "FULLY"
        elif watched == 0:
            tag = "NOT Watched"
        else:
            tag = f"%{int((watched/total)*100)}"
            
        folder_stats.append({"date": date, "count": total, "tag": tag})
        
    folder_stats.sort(key=lambda x: x["date"], reverse=True)

    return render_template("settings.html", user=user, active_tab="settings", total_media=len(media_items), watched_count=len(watched_items), watched_size_gb=watched_size_gb, hide_watched=settings.get("hide_watched", False), folder_stats=folder_stats)

@app.route("/settings/toggle_hide", methods=["POST"])
@login_required
def toggle_hide():
    user = get_current_user()
    settings = _load_json(SETTINGS_JSON, {})
    if user not in settings: settings[user] = {}
    settings[user]["hide_watched"] = not settings[user].get("hide_watched", False)
    save_json(SETTINGS_JSON, settings)
    return redirect(url_for("settings_view"))

@app.route("/settings/delete_date", methods=["POST"])
@login_required
def delete_date():
    target_date = request.form.get("date")
    if target_date:
        folder_path = MEDIA_DIR / target_date
        if folder_path.exists() and folder_path.is_dir():
            shutil.rmtree(folder_path, ignore_errors=True)
            get_media_index(force=True)
    return redirect(url_for("settings_view"))

@app.route("/media/<path:media_id>")
def stream_media(media_id):
    media_path = resolve_media_path(media_id)
    if not media_path:
        get_media_index(force=True)
        return "Not found", 404
    return send_cached_file(media_path)

@app.route("/thumbnail/<path:media_id>")
def get_thumbnail(media_id):
    media_path = resolve_media_path(media_id)
    if not media_path:
        get_media_index(force=True)
        return thumbnail_placeholder("Missing")
        
    # If the media is an image, it serves as its own thumbnail
    if media_path.suffix.lower() in IMAGE_EXTENSIONS:
        return send_cached_file(media_path)
        
    thumb_path = media_path.with_suffix('.jpg')
    
    if not thumb_path.exists():
        try:
            generate_thumbnail(media_path, thumb_path)
        except Exception:
            pass
            
    if thumb_path.exists():
        return send_cached_file(thumb_path)
        
    return thumbnail_placeholder()

stop_event = threading.Event()

def download_handler():
    while not stop_event.is_set():
        if not os.path.exists(MEDIA_DIR / "Downloaded"):
          os.mkdir(MEDIA_DIR / "Downloaded")
          
        files = os.listdir(MEDIA_DIR / "Downloaded")
        if files:
            for file in files:
                if not file.endswith("mp4"):
                    break
                try:
                    now = datetime.now()
                    formatted = now.strftime("%m_%d_%Y")
                    os.makedirs(BASE_DIR / f"media/{formatted}", exist_ok=True)
                    print("found a new downloaded file:", file)
                    shutil.move(
                        BASE_DIR / f"media/Downloaded/{file}",
                        BASE_DIR / f"media/{formatted}/{file}",
                    )
                except Exception as e:
                    print("exception:", e)
                stop_event.wait(1)   # interruptible sleep
                startup_generate_thumbnails()
              
        else:
            stop_event.wait(30)      # interruptible sleep
        
    print("Download handler terminated!")

downloadh = threading.Thread(target=download_handler, daemon = True)
downloadh.start()
