from pyrogram import Client
from colorama import Fore, init
from pathlib import Path
import threading
import re
import json
import sys
import os
import time

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "TID/TID-config.json"

init()

print("Follow the instructions to setup your telegram account.")
print(Fore.RED)
print("This code will Generate a file called Instant.session")
print("Make sure you have set the api_id and api_hash in the TID/TID-config.json")
print("Make sure  to set  the download_directory  var in the TID/TID-config.json \nto where your browser saves downloade file")


try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
except FileNotFoundError:
    print(Fore.RED + f"❌ config.json not found at {CONFIG_PATH}")
    sys.exit(1)
except json.JSONDecodeError as exc:
    print(f"❌ config.json is invalid JSON: {exc}")
    sys.exit(1)

API_ID   = cfg.get("api_id", 0)
API_HASH = cfg.get("api_hash", "")

if not API_ID or not API_HASH or API_ID == 12345678:
    print("❌ Set a real api_id / api_hash in config.json")
    sys.exit(1)

print(Fore.RESET)

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

def terminate_on_login_confirmation():
    while True:
        if os.path.exists(BASE_DIR/"Instant.session-journal"):
            print(Fore.GREEN+"Setup was successful!"+Fore.RESET)
            os._exit(0)
        time.sleep(3)

threading.Thread(target=terminate_on_login_confirmation,args=()).start()
PROXY = _detect_proxy()

app = Client("Instant", api_id=API_ID, api_hash=API_HASH, proxy=PROXY)
app.run()