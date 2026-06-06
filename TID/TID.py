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

API_ID   = cfg.get("api_id", 0)
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

DOWNLOAD_DIR  = BASE_DIR/"../InstantGram/media/Downloaded"
BAR_LEN       = 16
REPLY_TIMEOUT = 40                    
INSTA_DIR     = Path(cfg.get("download_directory", ""))      
INSTA_TARGET  = "@instasavegrambot"        

app = Client("Instant", api_id=API_ID, api_hash=API_HASH, proxy=PROXY)

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


class Progress:
    """Throttled progress bar. Edits a TG message, or prints to the console
    when console=True (no message to edit)."""

    def __init__(self, client, chat_id, msg_id, label, fname, console=False):
        self.c       = client
        self.cid     = chat_id
        self.mid     = msg_id
        self.label   = label
        self.fname   = fname[:50]
        self.console = console
        self._last   = 0.0

    async def __call__(self, cur: int, total: int):
        now = time.time()
        gap = 0.5 if self.console else 2
        # always let the final 100% frame through
        if total and cur < total and now - self._last < gap:
            return
        self._last = now

        pct = (cur / total * 100) if total else 0.0
        bar = make_bar(pct)

        if self.console:
            mb     = cur / 1_048_576
            tot_mb = total / 1_048_576 if total else 0.0
            print(f"\r  {bar} {pct:5.1f}%  {mb:6.2f}/{tot_mb:6.2f} MB  "
                  f"{self.fname}", end="", flush=True)
            if total and cur >= total:
                print()        # newline once finished
            return
        text = f"{self.label}\n{bar} {pct:5.1f}%\n📁 {self.fname}"
        try:
            await self.c.edit_message_text(self.cid, self.mid, text)
        except (FloodWait, MessageNotModified, MessageIdInvalid):
            pass


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
async def grab_to_disk(client: Client, target: str, line: str):
    """Send one line to the bot and download the media it replies with."""
    print(f"\n🔗 Link: {line}")

    try:
        peer = await client.get_chat(target)
        peer_id = peer.id
    except Exception as exc:
        print(f"❌ Couldn't resolve {target}: {exc}")
        return
    if peer_id in _pending:
        print("⚠️ Already waiting on a reply from that chat.")
        return

    loop = asyncio.get_event_loop()
    fut  = loop.create_future()
    _pending[peer_id] = fut          # arm BEFORE sending

    reply = None
    try:
        # Capture the sent message object so we can delete it later
        sent_msg = await client.send_message(peer_id, line)
        print(f"📤 Sent. Waiting up to {REPLY_TIMEOUT}s for a reply…")

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

            print(f"    ↪ interim reply: {got.text or '(no text)'}")
            fut = loop.create_future()
            _pending[peer_id] = fut
    finally:
        _pending.pop(peer_id, None)

    if reply is None:
        print("⌛ No media reply received in time.")
        return

    media, kind = media_of(reply)
    fname = getattr(media, "file_name", None)
    if not fname:
        ext = "mp4" if kind in ("video", "animation", "video_note") else "bin"
        fname = f"{kind}_{int(time.time())}.{ext}"

    DOWNLOAD_DIR.mkdir(exist_ok=True)
    dest = DOWNLOAD_DIR / fname
    print(f"🐱 Found a {kind}. Downloading…")

    prog = Progress(client, 0, None, "", fname, console=True)
    try:
        saved = await client.download_media(reply, file_name=str(dest), progress=prog)
        
        # Clean up the bot chat by deleting your request and its video response
        await client.delete_messages(peer_id, [sent_msg.id, reply.id])
    except Exception as exc:
        print(f"❌ Download failed: {exc}")
        return
    
    size = Path(saved).stat().st_size if saved else 0
    print(f"✅ Saved → {saved}  ({size/1_048_576:.2f} MB)")


async def download_worker(client: Client):
    if not INSTA_DIR.exists():
        print(f"❌ Folder not found: {INSTA_DIR}")
        return

    for file in INSTA_DIR.iterdir():
        if not file.is_file() or "Insta-post" not in file.name:
            continue
        print(f"\n📄 Reading {file.name}")
        with open(file, "r", encoding="utf-8") as f:
            for raw in f:
                link = raw.strip()
                if not link:
                    continue
                await grab_to_disk(client, INSTA_TARGET, link)
        
        # Removed text file safely after closing the reader handle
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
                print("✅ Pass done — sleeping 5s\n")
                await asyncio.sleep(5)

            except Exception as e:
                print(f"exception caught {e}")
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await app.stop()


def init():
    
        app.run(main())
    
# init()