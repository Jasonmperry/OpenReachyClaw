# OpenReachyClaw

**Rosie** — a curious, sassy AI desktop robot by [PerryLabs](https://perrylabs.io), built on the [Reachy Mini](https://www.pollen-robotics.com/reachy-mini/) robot kit by Pollen Robotics & Hugging Face.

OpenReachyClaw extends Pollen's [reachy-mini-conversation-app](https://github.com/pollen-robotics/reachy_mini_conversation_app) with custom tools, a text-channel brain, and a web control panel — giving Rosie a personality that works across voice, Slack, Discord, and email.

## Features

| Feature | Description |
|---------|-------------|
| **Voice + Text Brain** | Voice via OpenAI Realtime API; text channels via Chat Completions (supports Ollama for local LLM) |
| **Madame Claudette** | Horoscope & fortune readings channeling a Cajun mystic from the Louisiana bayou |
| **Nano Banana** | AI image style transfer — take a photo and transform it with Gemini |
| **Memory** | Remembers preferences and context across a session |
| **Weather** | Current weather via OpenWeatherMap |
| **Orders** | Takes and tracks food/drink/task orders |
| **SMS & Notifications** | Sends SMS messages and push notifications |
| **Web Search** | Searches the web for answers |
| **Camera & Photos** | Takes photos and shares them to text channels |
| **PerryLabs Control Panel** | Web UI for monitoring and interacting with Rosie |

## Quick Start

### On Jetson (production)

```bash
ssh jetson@192.168.2.2
cd ~/OpenReachyClaw
./start_rosie.sh          # text brain only (Ollama, no API key needed)
./start_rosie.sh --voice  # full voice + text (needs OPENAI_API_KEY)
```

### Local Development (Mac)

```bash
# Clone and set up
git clone git@github.com:Jasonmperry/OpenReachyClaw.git
cd OpenReachyClaw
cp .env.example .env      # edit with your API keys

# Install dependencies
pip install -e .

# Run the text brain webhook (for testing tools and text responses)
python -m openreachyclaw
```

### Deploy to Jetson

```bash
./deploy.sh               # sync all code to Jetson
./deploy.sh --dry-run     # preview what would be synced
```

## Architecture

```
OpenReachyClaw/
├── openreachyclaw/
│   ├── main.py             # App entry point — voice + text threads
│   ├── text_brain.py       # Chat Completions brain for text channels
│   ├── config.py           # Environment variable helpers
│   ├── webhook.py          # FastAPI /incoming webhook
│   ├── bridges/
│   │   └── openclaw.py     # OpenClaw HTTP client
│   └── tools/              # All custom tools
│       ├── horoscope.py    # Madame Claudette fortunes
│       ├── nano_banana.py  # AI image style transfer
│       ├── remember.py     # Memory (remember + recall)
│       ├── weather.py      # OpenWeatherMap
│       ├── take_order.py   # Order management
│       ├── web_search.py   # Web search
│       ├── send_sms.py     # SMS messaging
│       ├── send_notification.py  # Push notifications
│       ├── take_photo.py   # Camera capture
│       └── notify.py       # Channel messaging
├── static/                 # PerryLabs Control Panel web UI
├── profiles/rosie/         # Personality, tools list, voice
├── deploy.sh               # Mac → Jetson rsync deployment
└── docker-compose.yml      # OpenClaw sidecar
```

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | For voice | — | OpenAI API key (voice pipeline) |
| `OPENAI_BASE_URL` | No | OpenAI | Set to `http://localhost:11434/v1` for Ollama |
| `OPENREACHYCLAW_TEXT_MODEL` | No | `gpt-4o` | Model for text brain |
| `GEMINI_API_KEY` | For nano_banana | — | Google Gemini API key |
| `OPENWEATHER_API_KEY` | For weather | — | OpenWeatherMap API key |

See `.env.example` for the full list.

## About

Built by [Jason Michael Perry](https://jasonmperry.com) at [PerryLabs](https://perrylabs.io).

Subscribe to **Thoughts on Tech & Things** — Jason's newsletter and podcast in partnership with WYPR and Baltimore Public Media — at [jasonmperry.com](https://jasonmperry.com).
