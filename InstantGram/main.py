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

from flask import Flask, Response, make_response, redirect, render_template_string, request, send_file, session, url_for
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

TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Login • LAN Reels</title>
  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100dvh; font-family: "Trebuchet MS", sans-serif;
      background: radial-gradient(circle at 20% 20%, #222831, #12181f 45%, #080b10);
      color: #f1f5f9; display: grid; place-items: center; padding: 2rem;
    }
    .card {
      width: min(92vw, 420px); background: rgba(17, 24, 39, 0.88);
      border: 1px solid rgba(148, 163, 184, 0.25); border-radius: 18px;
      padding: 1.5rem; box-shadow: 0 12px 30px rgba(0, 0, 0, 0.4); backdrop-filter: blur(6px);
    }
    h1 { margin: 0 0 1rem; font-size: 1.55rem; letter-spacing: 0.02em; }
    label { display: block; margin-bottom: .5rem; color: #94a3b8; font-size: .95rem; }
    input { width: 100%; border-radius: 12px; border: 1px solid #334155; background: #0f172a; color: #f8fafc; padding: .7rem .85rem; margin-bottom: .85rem; outline: none; }
    button { width: 100%; border: 0; border-radius: 12px; padding: .75rem; color: #0f172a; background: linear-gradient(130deg, #7dd3fc, #38bdf8); font-weight: 700; cursor: pointer; }
    .error { color: #fda4af; margin-top: .5rem; min-height: 1.2rem; }
  </style>
</head>
<body>
  <div class="card">
    <h1>LAN Reel Login</h1>
    <form method="post" action="/login">
      <label>Username</label><input name="username" autocomplete="username" required />
      <label>Password</label><input name="password" type="password" autocomplete="current-password" required />
      <button type="submit">Sign in</button>
      {% if error %}<div class="error">{{ error }}</div>{% endif %}
    </form>
  </div>
</body>
</html>
"""

EXPLORE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Explore</title>
  <style>
    :root { --text: #f8fafc; }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; height: 100dvh; font-family: "Trebuchet MS", sans-serif; background: linear-gradient(140deg, #020617 0%, #0f172a 35%, #111827 100%); color: var(--text); }
    body { display: grid; place-items: center; place-content: center; }
    .viewport-shell { width: min(100vw, calc(100dvh * 9 / 16)); height: min(100dvh, calc(100vw * 16 / 9)); margin: 0 auto; border-radius: 20px; overflow: hidden; border: 1px solid rgba(148, 163, 184, .25); background: rgba(15, 23, 42, .8); display: flex; flex-direction: column; }
    .topbar { padding: .75rem 1rem; background: linear-gradient(to bottom, rgba(2,6,23,.95), rgba(2,6,23,.65)); border-bottom: 1px solid rgba(148,163,184,.2); }
    .brand { font-size: 1.05rem; font-weight: 700; }
    .explore-content { flex: 1; overflow-y: auto; background: #000; }
    .explore-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 2px; }
    .explore-item { aspect-ratio: 1 / 1; background: #222; display: block; position: relative; text-decoration: none; }
    .explore-item img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .bottom-nav { height: calc(56px + env(safe-area-inset-bottom)); padding-bottom: env(safe-area-inset-bottom); border-top: 1px solid rgba(148, 163, 184, .25); display: grid; grid-template-columns: repeat(5, 1fr); background: rgba(2, 6, 23, .9); }
    .bottom-nav a { display: grid; place-items: center; text-decoration: none; color: #94a3b8; font-size: .72rem; gap: .12rem; padding: .25rem 0; }
    .bottom-nav a.active { color: #67e8f9; }
    @media (max-width: 640px) { .viewport-shell { border-radius: 0; border: none; height: 100dvh; width: 100vw; } }
  </style>
</head>
<body>
  <main class="viewport-shell">
    <header class="topbar"><div class="brand">Explore</div></header>
    <div class="explore-content">
      <div class="explore-grid">
        {% for media in items %}
        <a href="{{ url_for('explore_feed', media_id=media.id) }}" class="explore-item">
          <img src="{{ url_for('get_thumbnail', media_id=media.id, v=media.version) }}" loading="lazy" alt="Thumbnail">
        </a>
        {% endfor %}
      </div>
    </div>
    <nav class="bottom-nav">
      <a href="/feed"><span class="icon">🏠</span><span>Home</span></a>
      <a href="/explore" class="active"><span class="icon">🧭</span><span>Explore</span></a>
      <a href="/bookmarks"><span class="icon">🔖</span><span>Saved</span></a>
      <a href="/settings"><span class="icon">⚙️</span><span>Settings</span></a>
      <a href="/logout"><span class="icon">👤</span><span>ME</span></a>
    </nav>
  </main>
</body>
</html>
"""

SAVED_GRID_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Saved Media</title>
  <style>
    :root { --text: #f8fafc; }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; height: 100dvh; font-family: "Trebuchet MS", sans-serif; background: linear-gradient(140deg, #020617 0%, #0f172a 35%, #111827 100%); color: var(--text); }
    body { display: grid; place-items: center; place-content: center; }
    .viewport-shell { width: min(100vw, calc(100dvh * 9 / 16)); height: min(100dvh, calc(100vw * 16 / 9)); margin: 0 auto; border-radius: 20px; overflow: hidden; border: 1px solid rgba(148, 163, 184, .25); background: rgba(15, 23, 42, .8); display: flex; flex-direction: column; }
    .topbar { padding: .75rem 1rem; background: linear-gradient(to bottom, rgba(2,6,23,.95), rgba(2,6,23,.65)); border-bottom: 1px solid rgba(148,163,184,.2); }
    .brand { font-size: 1.05rem; font-weight: 700; }
    .explore-content { flex: 1; overflow-y: auto; background: #000; }
    .explore-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 2px; }
    .explore-item { aspect-ratio: 1 / 1; background: #222; display: block; position: relative; text-decoration: none; }
    .explore-item img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .bottom-nav { height: calc(56px + env(safe-area-inset-bottom)); padding-bottom: env(safe-area-inset-bottom); border-top: 1px solid rgba(148, 163, 184, .25); display: grid; grid-template-columns: repeat(5, 1fr); background: rgba(2, 6, 23, .9); }
    .bottom-nav a { display: grid; place-items: center; text-decoration: none; color: #94a3b8; font-size: .72rem; gap: .12rem; padding: .25rem 0; }
    .bottom-nav a.active { color: #67e8f9; }
    .empty-state { padding: 2rem; text-align: center; color: #94a3b8; }
    @media (max-width: 640px) { .viewport-shell { border-radius: 0; border: none; height: 100dvh; width: 100vw; } }
  </style>
</head>
<body>
  <main class="viewport-shell">
    <header class="topbar"><div class="brand">Saved Collection</div></header>
    <div class="explore-content">
      {% if items %}
      <div class="explore-grid">
        {% for media in items %}
        <a href="{{ url_for('bookmarks_feed', media_id=media.id) }}" class="explore-item">
          <img src="{{ url_for('get_thumbnail', media_id=media.id, v=media.version) }}" loading="lazy" alt="Thumbnail">
        </a>
        {% endfor %}
      </div>
      {% else %}
      <div class="empty-state">No saved items found.</div>
      {% endif %}
    </div>
    <nav class="bottom-nav">
      <a href="/feed"><span class="icon">🏠</span><span>Home</span></a>
      <a href="/explore"><span class="icon">🧭</span><span>Explore</span></a>
      <a href="/bookmarks" class="active"><span class="icon">🔖</span><span>Saved</span></a>
      <a href="/settings"><span class="icon">⚙️</span><span>Settings</span></a>
      <a href="/logout"><span class="icon">👤</span><span>ME</span></a>
    </nav>
  </main>
</body>
</html>
"""

SETTINGS_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Settings</title>
  <style>
    :root { --text: #f8fafc; }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; height: 100dvh; font-family: "Trebuchet MS", sans-serif; background: linear-gradient(140deg, #020617 0%, #0f172a 35%, #111827 100%); color: var(--text); }
    body { display: grid; place-items: center; place-content: center; }
    .viewport-shell { width: min(100vw, calc(100dvh * 9 / 16)); height: min(100dvh, calc(100vw * 16 / 9)); margin: 0 auto; border-radius: 20px; overflow: hidden; border: 1px solid rgba(148, 163, 184, .25); background: rgba(15, 23, 42, .8); display: flex; flex-direction: column; }
    .topbar { padding: .75rem 1rem; background: linear-gradient(to bottom, rgba(2,6,23,.95), rgba(2,6,23,.65)); border-bottom: 1px solid rgba(148,163,184,.2); }
    .settings-content { flex: 1; overflow-y: auto; padding: 1.5rem; }
    .bottom-nav { height: calc(56px + env(safe-area-inset-bottom)); padding-bottom: env(safe-area-inset-bottom); border-top: 1px solid rgba(148, 163, 184, .25); display: grid; grid-template-columns: repeat(5, 1fr); background: rgba(2, 6, 23, .9); }
    .bottom-nav a { display: grid; place-items: center; text-decoration: none; color: #94a3b8; font-size: .72rem; gap: .12rem; padding: .25rem 0; }
    .bottom-nav a.active { color: #67e8f9; }
    
    .status-card { background: rgba(255,255,255,0.05); padding: 1rem; border-radius: 12px; margin-bottom: 1.5rem; }
    .progress-bar { width: 100%; height: 10px; background: #334155; border-radius: 5px; overflow: hidden; margin-top: 8px; }
    .progress-fill { height: 100%; background: #38bdf8; }
    
    .setting-row { display: flex; justify-content: space-between; align-items: center; padding: 1rem 0; border-bottom: 1px solid rgba(255,255,255,0.1); }
    .btn-danger { background: #ef4444; color: white; border: none; padding: 0.5rem 1rem; border-radius: 6px; cursor: pointer; }
    .delete-list { margin-top: 1rem; }
    .delete-item { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; background: rgba(0,0,0,0.3); padding: 0.75rem; border-radius: 8px; }
    
    .badge { padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: bold; margin-left: auto; margin-right: 10px; }
    .bg-success { background: #22c55e; color: #fff; }
    .bg-secondary { background: #64748b; color: #fff; }
    .bg-warning { background: #eab308; color: #000; }
  </style>
</head>
<body>
  <main class="viewport-shell">
    <header class="topbar"><div class="brand">Settings</div></header>
    <div class="settings-content">
      
      <div class="status-card">
        <h3>Watch Status</h3>
        <p>Seen: {{ watched_count }} / {{ total_media }} items</p>
        <div class="progress-bar">
          <div class="progress-fill" style="width: {{ (watched_count / total_media * 100) if total_media else 0 }}%;"></div>
        </div>
        <p style="margin-top:10px; font-size: 0.9em; color:#94a3b8;">Storage taken by viewed: {{ "%.2f"|format(watched_size_gb) }} GB</p>
      </div>

      <div class="setting-row">
        <span>Hide already seen items (Home & Explore)</span>
        <form action="/settings/toggle_hide" method="POST">
            <input type="checkbox" onChange="this.form.submit()" {% if hide_watched %}checked{% endif %}>
        </form>
      </div>

      <h3 style="margin-top: 2rem;">Manage Storage (By Date)</h3>
      <div class="delete-list">
        {% for folder in folder_stats %}
        <div class="delete-item">
            <span style="font-size:0.9rem;">{{ folder.date }} ({{ folder.count }})</span>
            
            <span class="badge 
                {% if folder.tag == 'FULLY' %}bg-success
                {% elif folder.tag == 'NOT Watched' %}bg-secondary
                {% else %}bg-warning{% endif %}">
                {{ folder.tag }}
            </span>

            <form action="/settings/delete_date" method="POST" onsubmit="return confirm('Delete all media in {{ folder.date }}?');" style="margin:0;">
                <input type="hidden" name="date" value="{{ folder.date }}">
                <button type="submit" class="btn-danger">Clear</button>
            </form>
        </div>
        {% endfor %}
        {% if not folder_stats %}
        <p style="color:#94a3b8;">No media dates found.</p>
        {% endif %}
      </div>

    </div>
    <nav class="bottom-nav">
      <a href="/feed"><span class="icon">🏠</span><span>Home</span></a>
      <a href="/explore"><span class="icon">🧭</span><span>Explore</span></a>
      <a href="/bookmarks"><span class="icon">🔖</span><span>Saved</span></a>
      <a href="/settings" class="active"><span class="icon">⚙️</span><span>Settings</span></a>
      <a href="/logout"><span class="icon">👤</span><span>ME</span></a>
    </nav>
  </main>
</body>
</html>
"""

FEED_SHELL_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Media Feed</title>
  <script src="/static/js/htmx.min.js"></script>
  <style>
    :root { --text: #f8fafc; --muted: #94a3b8; --accent: #67e8f9; }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; height: 100dvh; font-family: "Trebuchet MS", sans-serif; background: linear-gradient(140deg, #020617 0%, #0f172a 35%, #111827 100%); color: var(--text); }
    body { display: grid; place-items: center; place-content: center; }
    .topbar { position: sticky; top: 0; z-index: 10; padding: .75rem 1rem; display: flex; flex-direction: column; align-items: center; gap: .25rem; background: linear-gradient(to bottom, rgba(2,6,23,.95), rgba(2,6,23,.65)); border-bottom: 1px solid rgba(148,163,184,.2); }
    .brand { font-size: 1.05rem; font-weight: 700; width: 100%; display: flex; justify-content: space-between;}
    .viewport-shell { width: min(100vw, calc(100dvh * 9 / 16)); height: min(100dvh, calc(100vw * 16 / 9)); margin: 0 auto; border-radius: 20px; overflow: hidden; border: 1px solid rgba(148, 163, 184, .25); background: rgba(15, 23, 42, .8); display: grid; grid-template-rows: auto 1fr auto; }
    .feed { overflow-y: auto; min-height: 0; scroll-snap-type: y mandatory; scroll-behavior: smooth; overscroll-behavior-y: contain; background: linear-gradient(to top, rgba(15,23,42,.9), rgba(8,14,22,.6)); display: flex; flex-direction: column; }
    #feed-items { display: contents; }
    .video-card { position: relative; flex: 0 0 100%; height: 100%; max-height: 100%; min-height: 0; scroll-snap-align: start; scroll-snap-stop: always; display: flex; align-items: stretch; padding: .85rem; }
    .player { position: relative; width: 100%; height: 100%; flex: 1; min-height: 0; border-radius: 22px; overflow: hidden; background: #000; }
    video, img.reel-image { width: 100%; height: 100%; object-fit: contain; display: block; background: #000; }
    .overlay { position: absolute; inset: auto .75rem .75rem .75rem; z-index: 3; background: linear-gradient(to top, rgba(2,6,23,.78), rgba(2,6,23,0)); border-radius: 14px; padding: .8rem; pointer-events: none; }
    .overlay * { pointer-events: auto; }
    h2 { margin: 0; font-size: 1.08rem; }
    .meta { color: var(--muted); font-size: .9rem; }
    .audio-toggle { position: absolute; left: 12px; top: 12px; z-index: 5; border: 0; border-radius: 999px; width: 2.3rem; height: 2.3rem; font-size: 1rem; color: #fff; background: rgba(2, 6, 23, .58); border: 1px solid rgba(148, 163, 184, .35); cursor: pointer; }
    .bookmark { position: absolute; right: 12px; top: 12px; z-index: 4; border: 0; border-radius: 999px; width: 2.65rem; height: 2.65rem; font-size: 1.25rem; color: #fff; background: rgba(2, 6, 23, .58); border: 1px solid rgba(148, 163, 184, .35); cursor: pointer; }
    .dl-btn { position: absolute; right: 65px; top: 12px; z-index: 4; border: 0; border-radius: 999px; width: 2.65rem; height: 2.65rem; font-size: 1.1rem; color: #fff; background: rgba(2, 6, 23, .58); border: 1px solid rgba(148, 163, 184, .35); cursor: pointer; display: flex; align-items: center; justify-content: center; text-decoration: none; }
    .bookmarked { color: #fcd34d; }
    .side-metrics { position: absolute; right: 12px; bottom: 85px; z-index: 4; display: flex; flex-direction: column; gap: 1rem; align-items: center; pointer-events: none; }
    .side-metrics .metric { display: flex; flex-direction: column; align-items: center; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.6)); }
    .side-metrics .icon { font-size: 1.6rem; margin-bottom: 0.1rem; }
    .side-metrics .text { color: #fff; font-size: 0.8rem; font-weight: bold; }
    .feed-empty { flex: 1; display: grid; place-items: center; gap: .5rem; text-align: center; color: var(--muted); }
    .load-more-sentinel { text-align: center; padding: 1rem; color: var(--muted); font-size: .9rem; flex: 0 0 auto;}
    .bottom-nav { height: calc(56px + env(safe-area-inset-bottom)); padding-bottom: env(safe-area-inset-bottom); border-top: 1px solid rgba(148, 163, 184, .25); display: grid; grid-template-columns: repeat(5, 1fr); background: rgba(2, 6, 23, .9); position: sticky; bottom: 0; }
    .bottom-nav a { display: grid; place-items: center; text-decoration: none; color: #94a3b8; font-size: .72rem; gap: .12rem; padding: .25rem 0; }
    .bottom-nav a.active { color: #67e8f9; }
    .loader { display: inline-block; width: 18px; height: 18px; border: 2px solid rgba(148,163,184,.3); border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (max-width: 640px) { .topbar { padding: .65rem .6rem; } .video-card { padding: 0; } .player { border-radius: 0; border: none; } .viewport-shell { border-radius: 0; border: none; height: 100dvh; width: 100vw; } }
  </style>
</head>
<body>
  <main class="viewport-shell">
    <header class="topbar">
      <div class="brand">
        <span>{{ feed_title | default("ReelWall") }} · {{ user }}</span>
        {% if is_explorer_feed %}
        <a href="/explore" style="color:var(--accent); font-size:0.8rem; text-decoration:none;">Back to Explore</a>
        {% elif is_bookmarks_feed %}
        <a href="/bookmarks" style="color:var(--accent); font-size:0.8rem; text-decoration:none;">Back to Grid</a>
        {% endif %}
      </div>
    </header>

    <div class="feed" id="feed" data-page="0" tabindex="-1">
      {% if items %}
        <div id="feed-items">{{ items | safe }}</div>
      {% else %}
        <div class="feed-empty"><div>No media found.</div></div>
      {% endif %}
    </div>
    <nav class="bottom-nav">
      <a href="/feed" class="{% if active_tab == 'feed' %}active{% endif %}"><span class="icon">🏠</span><span>Home</span></a>
      <a href="/explore" class="{% if active_tab == 'explore' %}active{% endif %}"><span class="icon">🧭</span><span>Explore</span></a>
      <a href="/bookmarks" class="{% if active_tab == 'bookmarks' %}active{% endif %}"><span class="icon">🔖</span><span>Saved</span></a>
      <a href="/settings" class="{% if active_tab == 'settings' %}active{% endif %}"><span class="icon">⚙️</span><span>Settings</span></a>
      <a href="/logout"><span class="icon">👤</span><span>ME</span></a>
    </nav>
  </main>

  <script>
    const userBookmarks = new Set({{ bookmarked|tojson }});
    let mediaObserver = null;
    let soundOn = localStorage.getItem('soundOn') === 'true';

    const setSoundState = (enabled) => {
      soundOn = enabled; localStorage.setItem('soundOn', enabled);
      const activeCard = document.querySelector('.video-card[aria-current="true"]');
      const activeVideo = activeCard ? activeCard.querySelector('video.reel-media') : null;
      document.querySelectorAll('video.reel-media').forEach(video => { video.muted = !enabled || (activeVideo && video !== activeVideo); });
      document.querySelectorAll('.audio-toggle').forEach(button => { button.textContent = enabled ? '🔊' : '🔇'; });
      if (activeVideo && enabled) activeVideo.play().catch(() => {});
    };

    const recordView = (mediaId) => { fetch('/api/view/' + encodeURIComponent(mediaId), { method: 'POST' }); };

    const initializeCards = () => {
      if (mediaObserver) mediaObserver.disconnect();
      mediaObserver = new IntersectionObserver((entries) => {
        const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        const topMedia = visible.length ? visible[0].target : null;
        
        entries.forEach((entry) => {
          const targetMedia = entry.target; 
          const card = targetMedia.closest('.video-card');
          const mediaId = card.getAttribute('id').replace('media-', '');
          const isVideo = targetMedia.tagName === 'VIDEO';

          if (topMedia && targetMedia === topMedia && entry.intersectionRatio > 0.5) {
            if (card.getAttribute('aria-current') !== 'true') {
              document.querySelectorAll('.video-card[aria-current="true"]').forEach((item) => item.removeAttribute('aria-current'));
              card.setAttribute('aria-current', 'true');
              if(isVideo) targetMedia.currentTime = 0; 
              recordView(mediaId);
            }
            if (isVideo) {
              targetMedia.muted = !soundOn;
              let playPromise = targetMedia.play();
              if (playPromise !== undefined) playPromise.catch(() => { 
                if (soundOn) { 
                  targetMedia.muted = true; 
                  targetMedia.play().catch(()=>{}); 
                  setSoundState(false); 
                } 
              });
            }
          } else { 
            if (isVideo) {
              targetMedia.pause(); 
              targetMedia.muted = true; 
            }
          }
        });
      }, { threshold: [0.2, 0.5, 0.8] });

      document.querySelectorAll('.reel-media').forEach((targetMedia) => { 
        if (targetMedia.tagName === 'VIDEO') targetMedia.muted = !soundOn; 
        mediaObserver.observe(targetMedia); 
      });
      setSoundState(soundOn);
    };

    const toggleSound = () => setSoundState(!soundOn);
    
    const updateBookmarkButton = (button, mediaId) => {
      const active = userBookmarks.has(mediaId);
      button.classList.toggle('bookmarked', active);
      button.textContent = active ? '★' : '☆';
    };

    document.addEventListener('click', (event) => {
      if (event.target.closest('.audio-toggle')) { toggleSound(); event.preventDefault(); return; }
      const bookmarkButton = event.target.closest('.bookmark');
      if (bookmarkButton) {
        const mediaId = bookmarkButton.dataset.mediaId;
        if (!mediaId) return;
        if (userBookmarks.has(mediaId)) userBookmarks.delete(mediaId); else userBookmarks.add(mediaId);
        updateBookmarkButton(bookmarkButton, mediaId); return;
      }
      if (event.target.closest('.player') && !event.target.closest('.dl-btn')) { toggleSound(); return; }
    });

    if (window.htmx) document.body.addEventListener('htmx:afterSettle', () => { initializeCards(); });
    initializeCards();
  </script>
</body>
</html>
"""

MEDIA_CARD_PARTIAL = """
<div class="video-card" id="media-{{ media.id }}">
  <div class="player">
    {% if media.is_video %}
    <video class="reel-media reel-video" preload="none" playsinline muted loop webkit-playsinline>
      <source src="{{ url_for('stream_media', media_id=media.id, v=media.version) }}" type="video/mp4">
    </video>
    <button class="audio-toggle" type="button">🔇</button>
    {% else %}
    <img class="reel-media reel-image" src="{{ url_for('stream_media', media_id=media.id, v=media.version) }}" loading="lazy" alt="Image Post">
    {% endif %}
    
    <button class="bookmark{% if media.id in bookmarked %} bookmarked{% endif %}" hx-post="{{ url_for('bookmark', media_id=media.id) }}" hx-swap="none" data-media-id="{{ media.id }}">{% if media.id in bookmarked %}★{% else %}☆{% endif %}</button>
    
    {% if show_download %}
    <a href="{{ url_for('stream_media', media_id=media.id, v=media.version) }}" download class="dl-btn" title="Download Media">⬇</a>
    {% endif %}

    <div class="side-metrics">
        {% if media.likes is not none %}
        <div class="metric"><span class="icon">❤️</span><span class="text">{{ media.likes | short_num }}</span></div>
        {% endif %}
        {% if media.comments is not none %}
        <div class="metric"><span class="icon">💬</span><span class="text">{{ media.comments | short_num }}</span></div>
        {% endif %}
    </div>

    <div class="overlay">
      <h2>{{ media.title }}</h2>
      <div class="meta">{{ media.description }}</div>
      <div class="meta">By {{ media.author }} • {{ media.timestamp }}</div>
    </div>
  </div>
</div>
"""

LOAD_MORE_MARKER = """<div class="load-more load-more-sentinel" hx-get="{{ load_more_url }}" hx-trigger="revealed" hx-swap="outerHTML"><span class="loader"></span> Loading more...</div>"""

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
    return no_store(make_response(render_template_string(template, **context)))

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
    rendered = [render_template_string(MEDIA_CARD_PARTIAL, media=m, bookmarked=bookmarked_ids, show_download=show_download) for m in slice_items]
    if next_offset := offset + limit < len(media_items):
        rendered.append(render_template_string(LOAD_MORE_MARKER, load_more_url=f"{base_url}?offset={offset + limit}&limit={limit}"))
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
        return render_template_string(TEMPLATE, error="Invalid credentials")
    return render_template_string(TEMPLATE, error=None)

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
    
    return render_template_string(FEED_SHELL_TEMPLATE, items=build_feed_items(0, PAGE_SIZE, bookmarks, media_items, "/feed/items"), user=user, active_tab="feed", bookmarked=list(bookmarks))

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
    return render_template_string(FEED_SHELL_TEMPLATE, items=build_feed_items(0, PAGE_SIZE, bookmarks, media_items, f"/explore_feed/items/{media_id}"), user=user, active_tab="explore", bookmarked=list(bookmarks), is_explorer_feed=True)

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
    
    return render_template_string(FEED_SHELL_TEMPLATE, items=build_feed_items(0, PAGE_SIZE, bookmarks, media_items, f"/bookmarks_feed/items/{media_id}", show_download=True), user=user, active_tab="bookmarks", feed_title="Saved Collection", bookmarked=list(bookmarks), is_bookmarks_feed=True)

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

    return render_template_string(SETTINGS_TEMPLATE, user=user, active_tab="settings", total_media=len(media_items), watched_count=len(watched_items), watched_size_gb=watched_size_gb, hide_watched=settings.get("hide_watched", False), folder_stats=folder_stats)

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

