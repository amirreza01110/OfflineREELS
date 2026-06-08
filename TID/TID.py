import asyncio
import json
import re
import sys
import time
from pathlib import Path
import os


from pyrogram import Client, filters
from pyrogram.errors import FloodWait, MessageNotModified, MessageIdInvalid

# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "TID-config.json"

try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
except FileNotFoundError:
    print(f"❌ config.json not found at {CONFIG_PATH}")
    sys.exit(1)
except json.JSONDecodeError as exc:
    print(f"❌ config.json is invalid JSON: {exc}")
    sys.exit(1)

API_ID = cfg.get("api_id", 0)
API_HASH = cfg.get("api_hash", "")

if not API_ID or not API_HASH or API_ID == 12345678:
    print("❌ Set a real api_id / api_hash in config.json")
    sys.exit(1)


def _detect_proxy():
    """Return a Pyrogram proxy dict from config, or from system env vars."""
    p = cfg.get("proxy")
    if isinstance(p, dict) and p.get("hostname"):
        return p

    import urllib.request
    sys_proxies = urllib.request.getproxies()
    url = sys_proxies.get("https") or sys_proxies.get("http")
    if not url:
        return None

    m = re.match(r"(?:(\w+)://)?(?:([^:@]+):([^@]+)@)?([^:]+):(\d+)", url)
    if not m:
        return None

    scheme, user, pw, host, port = m.groups()
    proxy = {
        "scheme": scheme or "http",
        "hostname": host,
        "port": int(port),
    }
    if user and pw:
        proxy["username"] = user
        proxy["password"] = pw
    return proxy


PROXY = _detect_proxy()

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

DOWNLOAD_DIR = BASE_DIR / "../InstantGram/media/Downloaded"
BAR_LEN = 16
REPLY_TIMEOUT = 40
INSTA_DIR = Path(cfg.get("download_directory", ""))


INSTA_TARGETS = ["@instasavegrambot","@VoiceShazamBot"]

app = Client("Instant", api_id=API_ID, api_hash=API_HASH, proxy=PROXY, workers=8)

# chat_id -> asyncio.Future awaiting that chat's next reply
_pending = {}

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def make_bar(percent: float) -> str:
    filled = int(percent / 100 * BAR_LEN)
    filled = max(0, min(BAR_LEN, filled))
    return "▰" * filled + "▱" * (BAR_LEN - filled)


def media_of(message):
    """Return (media_obj, kind) for a downloadable message, else (None, None)."""
    if message.video:
        return message.video, "video"
    if message.document:
        return message.document, "document"
    if message.animation:
        return message.animation, "animation"
    if message.video_note:
        return message.video_note, "video_note"
    return None, None


class ConsoleProgressManager:
    """Render concurrent download progress in a fixed target order."""

    def __init__(self, targets):
        self.targets = list(targets)
        self.lines = {target: "" for target in self.targets}
        self.printed_lines = 0
        self.lock = asyncio.Lock()

    def _label(self, target):
        idx = self.targets.index(target) + 1
        return f"[{idx}] {target}"

    async def reset(self, active_targets):
        async with self.lock:
            self.lines = {
                target: f"{self._label(target):<26} waiting"
                for target in active_targets
            }
            await self._render_locked(active_targets)

    async def set_status(self, active_targets, target, status):
        async with self.lock:
            self.lines[target] = f"{self._label(target):<26} {status}"
            await self._render_locked(active_targets)

    async def update_progress(self, active_targets, target, fname, cur, total):
        pct = (cur / total * 100) if total else 0.0
        bar = make_bar(pct)
        mb = cur / 1_048_576
        tot_mb = total / 1_048_576 if total else 0.0
        short_name = fname[:32]

        async with self.lock:
            self.lines[target] = (
                f"{self._label(target):<26} {bar} {pct:5.1f}%  "
                f"{mb:6.2f}/{tot_mb:6.2f} MB  {short_name}"
            )
            await self._render_locked(active_targets)

    async def _render_locked(self, active_targets):
        if self.printed_lines:
            sys.stdout.write(f"\x1b[{self.printed_lines}F")

        for target in active_targets:
            sys.stdout.write("\x1b[2K")
            sys.stdout.write(self.lines.get(target, f"{self._label(target):<26} waiting"))
            sys.stdout.write("\n")

        sys.stdout.flush()
        self.printed_lines = len(active_targets)

    async def finish_batch(self):
        async with self.lock:
            self.printed_lines = 0
            sys.stdout.write("\n")
            sys.stdout.flush()


class Progress:
    """Throttled console progress callback bound to one bot slot."""

    def __init__(self, manager, active_targets, target, fname):
        self.manager = manager
        self.active_targets = active_targets
        self.target = target
        self.fname = fname
        self._last = 0.0

    async def __call__(self, cur: int, total: int):
        now = time.time()
        if total and cur < total and now - self._last < 0.5:
            return
        self._last = now
        await self.manager.update_progress(self.active_targets, self.target, self.fname, cur, total)


# ─────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────

@app.on_message(filters.incoming, group=1)
async def reply_watcher(client: Client, message):
    """Resolve a pending future when the awaited chat replies."""
    fut = _pending.get(message.chat.id)
    if fut and not fut.done():
        fut.set_result(message)


# ─────────────────────────────────────────────────────────────
# Batch worker (scans INSTA_DIR for "Insta-post" files)
# ─────────────────────────────────────────────────────────────
async def grab_to_disk(client: Client, target: str, line: str, manager: ConsoleProgressManager, active_targets):
    """Send one line to one bot and download the media it replies with."""
    sent_msg = None
    reply = None

    try:
        peer = await client.get_chat(target)
        peer_id = peer.id
    except Exception as exc:
        await manager.set_status(active_targets, target, f"resolve failed: {exc}")
        return

    if peer_id in _pending:
        await manager.set_status(active_targets, target, "already waiting on this bot")
        return

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    _pending[peer_id] = fut

    try:
        await manager.set_status(active_targets, target, f"sending {line[:40]}")
        sent_msg = await client.send_message(peer_id, line)
        await manager.set_status(active_targets, target, "waiting for media reply")

        deadline = time.time() + REPLY_TIMEOUT
        while time.time() < deadline:
            try:
                remaining = max(1, deadline - time.time())
                got = await asyncio.wait_for(fut, timeout=remaining)
            except asyncio.TimeoutError:
                break

            media, kind = media_of(got)
            if media:
                reply = got
                break

            fut = loop.create_future()
            _pending[peer_id] = fut

    finally:
        _pending.pop(peer_id, None)

    if reply is None:
        await manager.set_status(active_targets, target, "timeout: no media reply")
        return

    media, kind = media_of(reply)
    fname = getattr(media, "file_name", None)
    if not fname:
        ext = "mp4" if kind in ("video", "animation", "video_note") else "bin"
        fname = f"{kind}_{int(time.time())}.{ext}"

    DOWNLOAD_DIR.mkdir(exist_ok=True)
    dest = DOWNLOAD_DIR / fname

    prog = Progress(manager, active_targets, target, fname)

    try:
        saved = await client.download_media(reply, file_name=str(dest), progress=prog.__call__)

        if sent_msg is not None:
            await client.delete_messages(peer_id, [sent_msg.id, reply.id])

    except Exception as exc:
        await manager.set_status(active_targets, target, f"download failed: {exc}")
        return

    size = Path(saved).stat().st_size if saved else 0
    await manager.set_status(
        active_targets,
        target,
        f"done: {Path(saved).name} ({size / 1_048_576:.2f} MB)"
    )


def chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


async def download_worker(client: Client):
    if not INSTA_DIR.exists():
        print(f"❌ Folder not found: {INSTA_DIR}")
        return

    if not INSTA_TARGETS:
        print("❌ INSTA_TARGETS is empty.")
        return

    manager = ConsoleProgressManager(INSTA_TARGETS)

    for file in INSTA_DIR.iterdir():
        if not file.is_file() or "Insta-post" not in file.name:
            continue

        print(f"\n📄 Reading {file.name}")

        with open(file, "r", encoding="utf-8") as f:
            links = [raw.strip() for raw in f if raw.strip()]

        for batch in chunked(links, len(INSTA_TARGETS)):
            active_targets = INSTA_TARGETS[:len(batch)]
            await manager.reset(active_targets)

            tasks = [
                grab_to_disk(client, target, link, manager, active_targets)
                for target, link in zip(active_targets, batch)
            ]
            await asyncio.gather(*tasks)
            await manager.finish_batch()

        try:
            os.remove(file)
            print(f"🗑️ Removed source file: {file.name}")
        except Exception as exc:
            print(f"⚠️ Could not delete file {file.name}: {exc}")


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────
async def main():
    proxy_tag = " via proxy" if PROXY else ""
    print(f"🔐 Logging in{proxy_tag}…\n")

    await app.start()

    me = await app.get_me()
    uname = f"@{me.username}" if me.username else me.first_name
    print(f"👋 Connected as {uname}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Batch worker running — Ctrl+C to stop")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    try:
        while True:
            try:
                await download_worker(app)
                print("✅ All links in the *-Insta-post.txt files were downloaded — sleeping 5s\n")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"exception caught {e}")
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await app.stop()


def init():
    app.run(main())