#!/usr/bin/env python3
"""
tv_notice.py — Display a notice with voice on LG webOS TV.

Usage:
    tv_notice "小朋友刷完牙，可以玩拼图了，之后睡觉" "小朋友刷完牙<br>可以玩拼图了<br>之后睡觉"
    tv_notice "Welcome home!" "Welcome Home"
    tv_notice "Wake up!" "Time to<br>wake up!" --no-loop
"""

import argparse
import asyncio
import json
import os
import socket
import sys
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread

try:
    from gtts import gTTS
except ImportError:
    gTTS = None

# ── Constants ──────────────────────────────────────────────────────────
TV_IP = "192.168.1.58"
TV_PORT = 3001
DEFAULT_HTTP_PORT = 8080
KEY_FILE = Path(__file__).resolve().parent.parent / "tv.key"
PROJECT_DIR = KEY_FILE.parent

# ── HTML template ──────────────────────────────────────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="{lang_attr}">
<head>
<meta charset="utf-8">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  background: #0a0a2e;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  font-family: {font_family};
  overflow: hidden;
}}
.notice {{
  text-align: center;
  color: #fff;
  opacity: 0;
  animation: fadeIn 2s ease-in 0.5s forwards;
  padding: 1.5em;
}}
.notice h1 {{
  font-size: {font_size};
  font-weight: 400;
  letter-spacing: 0.05em;
  line-height: 1.4;
  background: linear-gradient(135deg, #fff 0%, #a8c0ff 50%, #fbc2eb 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}}
@keyframes fadeIn {{ to {{ opacity: 1; }} }}
</style>
</head>
<body>
  <div class="notice">
    <h1>{display_text}</h1>
  </div>
  <audio autoplay{loop_attr}>
    <source src="notice.mp3" type="audio/mpeg">
  </audio>
</body>
</html>"""


# ── HTTP Server ────────────────────────────────────────────────────────

_server = None


class _DirHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory or str(PROJECT_DIR), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def log_error(self, fmt, *args):
        pass


def get_local_ip():
    """Get the primary local IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def ensure_server(port: int = DEFAULT_HTTP_PORT):
    """Start HTTP server if not already running."""
    global _server
    if _server:
        return

    handler = lambda *args, **kw: _DirHandler(*args, directory=str(PROJECT_DIR), **kw)
    _server = HTTPServer(("0.0.0.0", port), handler)
    thread = Thread(target=_server.serve_forever, daemon=True)
    thread.start()

    local_ip = get_local_ip()
    for _ in range(20):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect((local_ip, port))
            s.close()
            return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)

    print("Warning: server may not have started")


def server_url(port: int = DEFAULT_HTTP_PORT):
    return f"http://{get_local_ip()}:{port}/"


# ── Helpers ────────────────────────────────────────────────────────────

def has_cjk(text: str) -> bool:
    """Detect if text contains CJK characters."""
    return any("\u4e00" <= c <= "\u9fff" for c in text)


def line_count(text: str) -> int:
    """Count display lines (split by <br>)."""
    return text.count("<br>") + 1


# ── Voice Synthesis ────────────────────────────────────────────────────

def synthesize_voice(text: str, lang: str, output: Path):
    """Generate MP3 voice file using gTTS."""
    if gTTS is None:
        print("Error: gtts not installed. Run: uv add gtts")
        sys.exit(1)

    if not text.strip():
        return

    tts = gTTS(text, lang=lang, slow=False)
    tts.save(str(output))
    print(f"🔊 Voice saved: {output}")


# ── HTML Generation ───────────────────────────────────────────────────

def generate_html(display_text: str, loop: bool, output: Path):
    """Generate the notice HTML page."""
    cjk = has_cjk(display_text)
    lines = line_count(display_text)

    if cjk:
        lang_attr = "zh"
        font_family = '"Noto Sans SC", "Microsoft YaHei", "PingFang SC", sans-serif'
        if lines <= 1:
            font_size = "12em"
        elif lines <= 2:
            font_size = "8em"
        else:
            font_size = "6em"
    else:
        lang_attr = "en"
        font_family = "Georgia, serif"
        if lines <= 1:
            font_size = "12em"
        elif lines <= 2:
            font_size = "8em"
        else:
            font_size = "6em"

    loop_attr = " loop" if loop else ""

    html = HTML_TEMPLATE.format(
        lang_attr=lang_attr,
        display_text=display_text,
        font_family=font_family,
        font_size=font_size,
        loop_attr=loop_attr,
    )

    output.write_text(html, encoding="utf-8")
    print(f"📄 HTML written: {output}")
    print(f"   Language: {'中文' if cjk else 'English'}, Font size: {font_size}, Loop: {loop}")


# ── TV WebSocket Protocol ──────────────────────────────────────────────

class WebOSTV:
    """Connect to and control an LG webOS TV via WebSocket."""

    def __init__(self, host: str, port: int, key: str | None = None):
        self.host = host
        self.port = port
        self.key = key
        self.ws = None
        self._pending = {}
        self._counter = 0

    async def connect(self):
        import ssl

        import websockets

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        uri = f"wss://{self.host}:{self.port}/"
        self.ws = await websockets.connect(uri, ssl=ssl_ctx, open_timeout=10)
        print(f"✅ WebSocket connected to {uri}")

        hello = json.loads(await self.ws.recv())
        print(f"TV hello: id={hello.get('id')}")

        reg = {
            "id": "register_0",
            "type": "register",
            "payload": {
                "forcePairing": False,
                "pairingType": "PROMPT",
                "manifest": {
                    "manifestVersion": 1,
                    "appVersion": "1.1",
                    "signed": {
                        "created": "20140509",
                        "appId": "com.lge.test",
                        "vendorId": "com.lge",
                        "localizedAppNames": {"": "LG Remote App"},
                        "localizedVendorNames": {"": "LG Electronics"},
                        "permissions": [
                            "LAUNCH", "CLOSE", "CONTROL_AUDIO", "CONTROL_POWER",
                            "READ_RUNNING_APPS", "READ_INSTALLED_APPS",
                            "CONTROL_INPUT_TEXT", "CONTROL_MOUSE_AND_KEYBOARD",
                            "READ_NOTIFICATIONS", "SEARCH", "WRITE_SETTINGS",
                            "WRITE_NOTIFICATION_TOAST", "CONTROL_TV_STANBY",
                            "CONTROL_TV_POWER", "CONTROL_WOL",
                        ],
                        "serial": "2f930e2d2cfe083771f68e4fe7bb07",
                    },
                    "permissions": [
                        "LAUNCH", "LAUNCH_WEBAPP", "APP_TO_APP", "CLOSE",
                        "CONTROL_AUDIO", "CONTROL_DISPLAY", "CONTROL_POWER",
                        "CONTROL_INPUT_JOYSTICK", "CONTROL_INPUT_MEDIA_PLAYBACK",
                        "CONTROL_INPUT_TV", "CONTROL_POWER_STATE",
                        "READ_INSTALLED_APPS", "READ_RUNNING_APPS",
                        "READ_SETTINGS", "READ_TV_CURRENT_TIME",
                        "WRITE_NOTIFICATION_TOAST", "CONTROL_TV_STANBY",
                        "CONTROL_TV_POWER", "CONTROL_WOL",
                    ],
                    "signatures": [
                        {
                            "signatureVersion": 1,
                            "signature": "eyJhbGdvcml0aG0iOiJSU0EtU0hBMjU2Iiwia2V5SWQiOiJ0ZXN0LXNpZ25pbmctY2VydCIsInNpZ25hdHVyZVZlcnNpb24iOjF9.hrVRgjCwXVvE2OOSpDZ58hR+59aFNwYDyjQgKk3auukd7pcegmE2CzPCa0bJ0ZsRAcKkCTJrWo5iDzNhMBWRyaMOv5zWSrthlf7G128qvIlpMT0YNY+n/FaOHE73uLrS/g7swl3/qH/BGFG2Hu4RlL48eb3lLKqTt2xKHdCs6Cd4RMfJPYnzgvI4BNrFUKsjkcu+WD4OO2A27Pq1n50cMchmcaXadJhGrOqH5YmHdOCj5NSHzJYrsW0HPlpuAx/ECMeIZYDh6RMqaFM2DXzdKX9NmmyqzJ3o/0lkk/N97gfVRLW5hA29yeAwaCViZNCP8iC9aO0q9fQojoa7NQnAtw==",
                        }
                    ],
                },
            },
        }
        if self.key:
            reg["payload"]["client-key"] = self.key

        await self.ws.send(json.dumps(reg))
        resp = json.loads(await self.ws.recv())
        print(f"Register response: {resp.get('type')}")

        if resp.get("type") == "response" and resp.get("payload", {}).get("returnValue"):
            new_key = resp["payload"].get("client-key")
            if new_key and new_key != self.key:
                self.key = new_key
                KEY_FILE.write_text(new_key)
                print(f"🔑 Key saved to {KEY_FILE}")
            return True
        elif resp.get("type") == "error" or resp.get("payload", {}).get("errorCode") == 401:
            print("❌ Pairing rejected. Check TV for prompt!")
            return False
        return False

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def request(self, uri: str, payload: dict | None = None) -> dict:
        cid = self._cid()
        msg = {
            "id": cid,
            "type": "request",
            "uri": uri,
            "payload": payload or {},
        }
        await self.ws.send(json.dumps(msg))
        while True:
            resp = json.loads(await self.ws.recv())
            if resp.get("id") == cid:
                return resp.get("payload", {})
            # Handle unsubscribe responses etc.

    def _cid(self):
        self._counter += 1
        return f"client_{self._counter:04x}"


async def tv_main(
    voice_text: str,
    display_text: str,
    lang: str,
    loop: bool,
    port: int,
):
    """Main workflow: generate assets, serve, connect TV, launch."""
    dir_path = PROJECT_DIR
    dir_path.mkdir(parents=True, exist_ok=True)

    # 1. Generate voice
    print(f"\n{'='*50}")
    print(f"📢 Voice: \"{voice_text}\" (lang={lang})")
    synthesize_voice(voice_text, lang, dir_path / "notice.mp3")

    # 2. Generate HTML
    print(f"📄 Display: \"{display_text}\"")
    generate_html(display_text, loop, dir_path / "notice.html")

    # 3. Start HTTP server
    url = f"{server_url(port)}notice.html"
    print(f"🌐 Serving at: {url}")
    ensure_server(port)

    # 4. Connect to TV and launch
    key = None
    if KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()

    tv = WebOSTV(TV_IP, TV_PORT, key)
    if not await tv.connect():
        print("⏳ Waiting 15s for user to accept pairing...")
        await asyncio.sleep(15)
        if not await tv.connect():
            print("❌ Failed to connect to TV.")
            sys.exit(1)

    # 5. Close any existing browser
    browser_id = "com.webos.app.browser"
    close_result = await tv.request("ssap://system.launcher/close", {"id": browser_id})
    print(f"Close browser: {close_result.get('returnValue', False)}")

    await asyncio.sleep(0.5)

    # 6. Launch browser with the notice page
    launch_result = await tv.request(
        "ssap://system.launcher/launch",
        {
            "id": browser_id,
            "params": {"target": url},
        },
    )
    print(f"Launch browser: {launch_result.get('returnValue', False)}")

    if launch_result.get("returnValue"):
        print(f"\n✅ Notice displayed on TV!")
    else:
        print(f"\n⚠️  Launch result: {json.dumps(launch_result)}")

    await tv.close()


def main():
    parser = argparse.ArgumentParser(
        description="Display a notice with voice on LG webOS TV."
    )
    parser.add_argument("voice_text", help="Text to speak (voice synthesis)")
    parser.add_argument(
        "display_text",
        help=(
            "Text to display on screen. "
            "Use <br> for line breaks. "
            "Auto-detects Chinese to set proper font/size."
        ),
    )
    parser.add_argument(
        "--lang",
        default="en",
        help="Voice language code (en, zh-CN, etc.) (default: en)",
    )
    parser.add_argument(
        "--no-loop",
        action="store_true",
        help="Play audio only once (default: loop)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_HTTP_PORT,
        help=f"HTTP server port (default: {DEFAULT_HTTP_PORT})",
    )

    args = parser.parse_args()

    asyncio.run(
        tv_main(
            voice_text=args.voice_text,
            display_text=args.display_text,
            lang=args.lang,
            loop=not args.no_loop,
            port=args.port,
        )
    )


if __name__ == "__main__":
    main()
