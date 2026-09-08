---
name: tv-notice
description: >-
  This skill should be used when the user asks to "show a notice on TV", "display a welcome message",
  "play a voice message on TV", "update the TV notice", "change the welcome text",
  "synthesize voice for TV", "say something on TV", "project something on the TV",
  "cycle the sound on TV", or any request to show text + play audio on an LG webOS TV.
  Make sure to use this skill whenever the user wants to send ANY text, image, or voice
  message to display on the TV screen, even if they phrase it casually.
  Always restart the browser (close then launch) after each update to ensure it displays correctly.
version: 0.2.0
---

# TV Notice — Display text + voice on LG webOS TV

Show a full-screen notice with synthesized voice on an LG webOS Smart TV.

Accepts **two separate inputs**: voice text (spoken aloud) and display text (shown on screen).

## Prerequisites

- TV is powered on and on the same WiFi network (192.168.1.x)
- Pairing key exists at `tv.key` (already configured)
- Python packages: `gtts`, `websockets`

## Quick Start

```bash
cd ~/.agents/skills/tv-notice && uv run python scripts/tv_notice.py \
    "小朋友刷完牙，可以玩拼图了，之后睡觉" \
    "小朋友刷完牙<br>可以玩拼图了<br>之后睡觉"
```

The first argument is the **voice** (spoken), the second is the **display** (shown on screen).
Use `<br>` for line breaks in the display text.

## Workflow

Run `tv_notice.py` — it handles everything in one shot:

1. Synthesizes voice MP3 via gTTS
2. Generates the notice HTML (auto-detects Chinese language for fonts/sizing)
3. Starts an HTTP server on port 8080 (reuses if already running)
4. Connects to the TV via WebSocket (`wss://192.168.1.58:3001`)
5. Closes any existing browser app
6. Launches the browser to display the notice page

```bash
cd ~/.agents/skills/tv-notice && uv run python scripts/tv_notice.py \
    "<voice_text>" \
    "<display_text>" \
    [--lang en|zh-CN] \
    [--no-loop]
```

If the TV shows a pairing prompt, accept it on the TV — the key is saved automatically.

## Auto-detection

The script automatically detects if the **display text** contains Chinese characters:

- **Chinese detected** → Sets `lang="zh"`, uses CJK fonts (Noto Sans SC, Microsoft YaHei, PingFang SC), adjusts font size based on line count
- **No Chinese** → Uses `lang="en"`, serif font (Georgia)

Font sizes adapt to line count:
- 1 line → 12em
- 2 lines → 8em
- 3+ lines → 6em

## Arguments

```
tv_notice.py <voice_text> <display_text> [options]
```

| Argument / Option | Description |
|---|---|
| `voice_text` (required) | Text to speak via voice synthesis |
| `display_text` (required) | Text to show on screen. Use `<br>` for line breaks |
| `--lang` | Voice language code (default: `en`, Chinese: `zh-CN`) |
| `--no-loop` | Play audio only once (default: loops continuously) |
| `--port` | HTTP server port (default: `8080`) |

## Examples

**Chinese voice + Chinese display (auto-detect CJK → zh fonts):**
```bash
cd ~/.agents/skills/tv-notice && uv run python scripts/tv_notice.py \
    "小朋友刷完牙，可以玩拼图了，之后睡觉" \
    "小朋友刷完牙<br>可以玩拼图了<br>之后睡觉" \
    --lang zh-CN
```

**Chinese voice + English display (auto-detect → en serif font):**
```bash
cd ~/.agents/skills/tv-notice && uv run python scripts/tv_notice.py \
    "Welcome home, Friend" \
    "Welcome Home!"
```

**English voice, single play (no loop):**
```bash
cd ~/.agents/skills/tv-notice && uv run python scripts/tv_notice.py \
    "Time for bed!" "Good Night<br>Sleep Well" --no-loop
```

**Same text for voice and display:**
```bash
cd ~/.agents/skills/tv-notice && uv run python scripts/tv_notice.py \
    "Wake up! It's time for school" \
    "Wake Up!<br>Time for School"
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Connection refused` | TV may be off. Ping `192.168.1.58` to verify. |
| Pairing prompt on TV | Accept it — the key is saved to `tv.key` automatically. |
| Audio doesn't play | TV browser may block autoplay. Tap/click on the TV screen once. |
| HTTP 404 | HTTP server may have failed to start. Check port 8080 is free. |
| `gtts` import error | Run `uv add gtts` in the tv-notice directory. |
| ModuleNotFoundError websockets | Run `uv add websockets` in the tv-notice directory. |

## Implementation Notes

- TV address: `192.168.1.58` via WiFi (interface `wlp195s0`)
- WebSocket port: `3001` (TLS) — `wss://` protocol required
- Pairing key stored in `tv.key` (copied from lgtv2 keyfile)
- Browser app ID: `com.webos.app.browser`
- HTTP server serves files from `tv-notice/` directory (port 8080)
- **Always close browser before relaunching** to ensure fresh display
