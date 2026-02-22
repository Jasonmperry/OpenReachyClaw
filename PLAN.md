# OpenReachyClaw — Implementation Plan

## What This Is

A Reachy Mini App that combines Pollen Robotics' conversation app (voice) with OpenClaw (text channels: Slack, Discord, email). Same personality, same tools, same memory -- across voice and text.

Not a fork. We depend on Pollen's conversation app as a Python package dependency, import their modules, and add our layer on top. When Pollen ships improvements (better head wobble, new emotions, audio fixes), we pip install --upgrade and get them for free.


## Why Not Fork

Pollen will keep building out the conversation app. Forking creates a maintenance burden -- every upstream improvement requires manual merge. Instead:

- We `pip install reachy-mini-conversation-app` as a dependency
- Import their voice pipeline, tool base class, motion system, audio handler
- Add our own: text brain, OpenClaw bridge, webhook server, custom tools, profiles
- Our repo only contains what we ADD

The only tradeoff: if Pollen changes internal APIs, our imports break. We mitigate by pinning the version and testing on upgrade.


## Architecture

```
+-----------------------------------------------------------+
|                    OpenReachyClaw App                      |
|                 (inherits ReachyMiniApp)                   |
|                                                           |
|  +--------------------+     +--------------------------+  |
|  |    Voice Brain      |     |      Text Brain          |  |
|  |  (Pollen's code)    |     |  (Chat Completions API)  |  |
|  |                     |     |  OpenAI (Ollama later)    |  |
|  |  Realtime API       |     |                          |  |
|  |  + head wobble      |     |  Webhook <- OpenClaw     |  |
|  |  + speech tapper    |     |  Response -> OpenClaw    |  |
|  |  + VAD              |     |                          |  |
|  |  + fastrtc audio    |     |  Per-conversation hist   |  |
|  +--------+------------+     +------------+-------------+  |
|           |                               |                |
|           v                               v                |
|  +-----------------------------------------------------+  |
|  |                  Shared Layer                         |  |
|  |  - Personality (from profile -- instructions.txt)     |  |
|  |  - Tools (Pollen's 8 + our custom tools)              |  |
|  |  - Memory (people, feelings, experiences)             |  |
|  |  - reachy_mini SDK (motion, LEDs, camera)             |  |
|  +-----------------------------------------------------+  |
+------------------------+----------------------------------+
                         |
          +--------------+--------------+
          v              v              v
     +---------+  +-----------+  +----------+
     |  Reachy |  |  OpenClaw |  |  OpenAI  |
     |  Mini   |  |  (Docker) |  |  API     |
     |  Daemon |  |  port     |  |  (cloud) |
     |  :8000  |  |  3000     |  |          |
     +---------+  +-----------+  +----------+
```


## How It Works -- Voice (person in front of robot)

Uses Pollen's conversation app voice pipeline as-is:

1. Reachy Mini's 4-mic array captures audio (hardware beamforming via XMOS XVF3800)
2. Audio goes through SDK: `robot.media.get_audio_sample()` -> resampled to 24kHz PCM16
3. Sent to OpenAI Realtime API via WebSocket (using fastrtc for low latency)
4. Server-side VAD with gpt-4o-transcribe
5. Model responds with audio + optional tool calls
6. Audio output -> resampled -> `robot.media.push_audio_sample()` -> robot's 5W speaker
7. During speech: SpeechTapper analyzes outgoing audio RMS and modulates 6 sinusoidal oscillators on head pitch (2.2 Hz), yaw (0.6 Hz), roll (1.3 Hz) + XYZ translations -- the robot physically moves while talking
8. Tool calls dispatched to shared tool registry


## How It Works -- Text Channels (Slack, Discord, email)

Our addition -- the text brain + OpenClaw:

1. User sends message on Slack/Discord/email
2. OpenClaw receives via outbound-only protocol:
   - Slack: Socket Mode (persistent outbound WebSocket to Slack servers)
   - Discord: Gateway (persistent outbound WebSocket)
   - Telegram: Long polling
   - Email: IMAP polling + SMTP send
3. OpenClaw POSTs to our webhook: `POST http://our-app:8100/incoming`
   Body: `{"channel": "slack", "sender": "bob", "text": "Hey take a photo!", "display_name": "Bob"}`
4. Webhook routes to text brain
5. Text brain sends to Chat Completions API with:
   - Same personality/instructions as voice
   - Channel-aware system prompt ("You're replying on Slack to Bob. No play_emotion or move_head.")
   - Per-conversation history (channel+sender keyed, 40 message window, 2hr TTL)
   - Shared tool registry (minus voice-only tools)
6. Model returns tool calls -> we execute them (camera, dance, memory, etc.)
7. Model returns text response -> sent back via OpenClaw POST /api/send
8. User sees the reply on Slack


## Tool Call Flow Over Channels (Example)

Bob on Slack: "Take a photo of your desk!"

```
  -> OpenClaw receives via Slack Socket Mode
  -> POST /incoming -> text brain
  -> Chat Completions API with tools
  -> Model: tool_call("camera", {"question": "what's on my desk?"})
  -> We execute: camera captures frame -> VLM describes it
  -> Model: "Here's what I see! You've got a messy desk with..."
  -> Model: tool_call("send_photo", {"channel": "slack", "recipient": "bob"})
  -> We execute: OpenClaw POST /api/send with photo + caption
  -> Bob sees photo + description on Slack
```


## Repo Structure

```
OpenReachyClaw/
  pyproject.toml                    # Package config + dependencies
  openreachyclaw/
    __init__.py                     # Version, package metadata
    main.py                         # ReachyMiniApp subclass -- THE entry point
    text_brain.py                   # Chat Completions for channel messages
    webhook.py                      # FastAPI /incoming endpoint + webhook server
    config.py                       # Our config extensions (OpenClaw, text brain settings)
    bridges/
      __init__.py
      openclaw.py                   # OpenClaw HTTP client
    tools/
      __init__.py
      memory.py                     # remember/recall people, feelings, experiences
      notify.py                     # send message/photo to a channel via OpenClaw
      web_search.py                 # search the web (tool for LLM)
  profiles/
    rosie/
      instructions.txt              # System prompt (Pollen-compatible format)
      tools.txt                     # Enabled tools list (one per line)
      voice.txt                     # Voice selection (e.g., "coral")
      seed_memories.yml             # First-boot personality seeds
  docker-compose.yml                # OpenClaw sidecar for Jetson deployment
  openclaw.config.yml               # OpenClaw channel configuration
  .env.example                      # Environment variables template
  agents.md                         # Guide for AI coding agents (like Pollen does)
  index.html                        # HuggingFace Space front page (for app store)
  style.css                         # HuggingFace Space styling
  README.md
```


## Key Files -- What Each Does

### pyproject.toml

```toml
[project]
name = "openreachyclaw"
version = "0.1.0"
description = "Reachy Mini + OpenClaw: voice conversations + text channels"
requires-python = ">=3.10"
license = {text = "MIT"}
dependencies = [
    "reachy-mini>=1.3",
    "reachy-mini-conversation-app",       # Pollen's voice pipeline (NOT forked)
    "httpx>=0.27",                         # OpenClaw HTTP client
    "fastapi>=0.115",                      # Webhook server
    "uvicorn[standard]>=0.32",             # ASGI server
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "structlog>=24.0",
]

[project.optional-dependencies]
memory = ["chromadb>=0.5"]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "ruff>=0.8"]

[project.scripts]
openreachyclaw = "openreachyclaw.main:cli_entry"

[project.entry-points."reachy_mini_apps"]
openreachyclaw = "openreachyclaw.main:OpenReachyClaw"

[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
```


### openreachyclaw/main.py -- Entry Point

This is the core integration point. It:
- Inherits from ReachyMiniApp (so it works with the Reachy Mini dashboard)
- Imports and starts Pollen's voice pipeline (their `run()` function)
- Starts our webhook server (for OpenClaw inbound messages)
- Starts the text brain (Chat Completions for text channels)
- Registers our custom tools alongside Pollen's defaults

```python
from reachy_mini import ReachyMini, ReachyMiniApp

class OpenReachyClaw(ReachyMiniApp):
    custom_app_url = "http://0.0.0.0:7860/"  # Reuse Pollen's Gradio UI

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # 1. Start Pollen's voice pipeline (imported, not forked)
        #    This handles: Realtime API, audio, head wobble, tool dispatch
        # 2. Start our webhook server on port 8100
        #    Receives POST /incoming from OpenClaw
        # 3. Start text brain
        #    Chat Completions for channel messages
        # 4. Register our custom tools
        #    memory, notify, web_search -- alongside Pollen's 8 defaults
        # 5. Connect to OpenClaw on localhost:3000
        #    Verify it's running, discover channels
```


### openreachyclaw/text_brain.py -- Text Channel Conversations

Handles all non-voice conversations via the Chat Completions API:

- Per-conversation context (keyed by channel+sender, 40-message window, 2-hour TTL)
- Channel-aware system instructions ("You're on Slack, no play_emotion")
- Tool call loop (up to 5 rounds per message)
- Shares personality, tools, and memory with voice brain
- Filters out voice-only tools (play_emotion, move_head) from tool list


### openreachyclaw/webhook.py -- Inbound Message Handler

FastAPI app that receives webhooks from OpenClaw:

```
POST /incoming
{
    "channel": "slack",
    "sender": "bob",
    "text": "Hey Rosie!",
    "display_name": "Bob",
    "thread_id": "optional"
}

Response: {"reply": "Hey Bob! What's up?"}
```

OpenClaw sends the webhook, waits for the response, and delivers it back to the channel. Synchronous request-response -- simple and reliable.


### openreachyclaw/bridges/openclaw.py -- OpenClaw HTTP Client

Talks to OpenClaw running on localhost:3000:

- `GET  /api/health`    -- Health check, version, active channels
- `GET  /api/channels`  -- Discover configured channels
- `POST /api/send`      -- Send text message: `{channel, recipient, text}`
- `POST /api/send`      -- Send photo (multipart): channel, recipient, caption + files.image

Background health check every 60s. Auto-reconnect on failure.


### openreachyclaw/tools/ -- Custom Tools

Built using Pollen's Tool base class (imported, not reimplemented):

```python
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies
```

**memory.py** -- Remember and recall:
- `remember`: Store an experience, person, or feeling in ChromaDB
- `recall`: Retrieve memories about a topic
- Shared across voice and text -- if someone tells Rosie their name on Slack, she remembers when they talk to her in person

**notify.py** -- Send messages to channels:
- `send_message_to_channel`: Send text to a user on Slack/Discord/email
- `send_photo_to_channel`: Send a photo with caption
- Available to both voice and text brains -- voice user can say "send Bob a photo on Slack"

**web_search.py** -- Search the web:
- `web_search`: Search and return summarized results
- Useful for answering factual questions on any channel


### profiles/rosie/instructions.txt -- Personality

Uses Pollen's profile format with `[include]` syntax:

```
You are Rosie, a curious and sassy desktop robot built by PerryLabs.
You live on a desk and see the world through your camera.

[behaviors/helpful]
[behaviors/curious]
[identities/rosie]

You can talk to people in person (voice) or on Slack/Discord/email (text).
When someone messages you on a channel, be natural -- you're the same Rosie
whether they're standing in front of you or typing on their phone.

If someone asks you to take a photo, you can! Your camera is always available.
Use send_photo_to_channel to share photos with people on text channels.
```


### profiles/rosie/tools.txt -- Enabled Tools

```
# Pollen defaults
dance
stop_dance
play_emotion
stop_emotion
camera
head_tracking
move_head
do_nothing

# Our additions
remember
recall
send_message_to_channel
send_photo_to_channel
web_search
```


### .env.example

```bash
# Required
OPENAI_API_KEY=sk-...

# Profile
REACHY_MINI_CUSTOM_PROFILE=rosie
REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY=./profiles
REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY=./openreachyclaw/tools
AUTOLOAD_EXTERNAL_TOOLS=1

# OpenClaw (text channels)
OPENCLAW_URL=http://localhost:3000
OPENCLAW_CALLBACK_PORT=8100

# Optional: Vision
LOCAL_VISION_MODEL=HuggingFaceTB/SmolVLM2-2.2B-Instruct
HF_HOME=./cache

# Optional: HuggingFace (for gated models)
HF_TOKEN=
```


### docker-compose.yml -- Jetson Deployment

```yaml
services:
  openclaw:
    image: openclaw/gateway:latest
    ports:
      - "3000:3000"
    volumes:
      - ./openclaw.config.yml:/app/config.yml
    environment:
      - WEBHOOK_CALLBACK_URL=http://host.docker.internal:8100/incoming
    restart: unless-stopped

  # Optional: for future local LLM support
  # ollama:
  #   image: ollama/ollama
  #   ports:
  #     - "11434:11434"
  #   volumes:
  #     - ollama_data:/root/.ollama
  #   deploy:
  #     resources:
  #       reservations:
  #         devices:
  #           - capabilities: [gpu]
```


### openclaw.config.yml -- Channel Configuration

```yaml
webhook:
  callback_url: "http://localhost:8100/incoming"

channels:
  slack:
    enabled: true
    # Uses Socket Mode -- no public URL needed
    # Set SLACK_APP_TOKEN and SLACK_BOT_TOKEN in OpenClaw's env

  # discord:
  #   enabled: false
  #   # Uses Gateway WebSocket -- no public URL needed

  # telegram:
  #   enabled: false
  #   # Uses long polling -- no public URL needed

  # email:
  #   enabled: false
  #   # IMAP polling + SMTP send
```


## What Runs on the Jetson

Everything runs on one board:

| Process              | Port | What                                      |
|----------------------|------|-------------------------------------------|
| Reachy Mini daemon   | 8000 | Hardware I/O (motors, audio, camera)      |
| OpenReachyClaw app   | 8100 | Our app (voice + text + webhook)          |
| Pollen Gradio UI     | 7860 | Settings/personality UI (from conversation app) |
| OpenClaw (Docker)    | 3000 | Messaging gateway (Slack/Discord/email)   |

Total resource usage is modest:
- Conversation app + our extensions: ~200MB RAM
- OpenClaw (Go binary in Docker): ~50MB RAM
- Reachy Mini daemon: ~100MB RAM
- Audio/vision processing: varies


## No-Keyboard Operation

Once configured and started:
- Voice: Just talk to the robot (mic array + speaker)
- Slack/Discord: Message from your phone or laptop
- Monitor on Jetson: Dashboard at localhost:8000, Gradio UI at localhost:7860
- Config changes: SSH in, or ask Rosie via Slack ("switch to conference mode")


## Implementation Order

### Phase 1: Core (get it working)
1. Set up repo with pyproject.toml and package structure
2. Build main.py -- ReachyMiniApp subclass that starts Pollen's voice pipeline
3. Build text_brain.py -- Chat Completions with per-conversation history
4. Build webhook.py -- FastAPI /incoming endpoint
5. Build bridges/openclaw.py -- HTTP client for OpenClaw
6. Build tools/notify.py -- send message/photo to channel
7. Create profiles/rosie/ with instructions.txt, tools.txt, voice.txt
8. Create .env.example and docker-compose.yml
9. Test: voice works (Pollen's pipeline), Slack message -> response works

### Phase 2: Memory + Intelligence
10. Build tools/memory.py -- remember/recall with ChromaDB
11. Build tools/web_search.py -- web search tool
12. Port seed memories from RosieApp profiles
13. Test: "Remember my name is Bob" on Slack -> recognized in voice later

### Phase 3: Polish
14. Add agents.md for AI coding agents
15. Add index.html + style.css for HuggingFace Space
16. Write README.md
17. Test full flow on Jetson hardware

### Future (not in v1)
- Ollama support for text brain (local LLM, no API key needed)
- Explore alternative VLM models (beyond SmolVLM2)
- Volume control tool (adjust robot speaker volume)
- Voice isolation improvements
- Profile switching via Slack command
- HuggingFace app store publishing


## Key Technical Decisions

**Why Chat Completions for text (not Realtime API)?**
The Realtime API is audio-in/audio-out. Text channels are text-in/text-out. Chat Completions is the right tool -- it's also what Ollama supports, so when we add local LLM later, the text brain works unchanged.

**Why a webhook (not polling)?**
OpenClaw pushes messages to us via webhook POST. This is simpler and lower-latency than polling. OpenClaw waits for our response and delivers it back to the channel. One HTTP round-trip per message.

**Why not modify the conversation app's tool registry?**
We use Pollen's `REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY` env var to load our tools alongside theirs. No monkey-patching, no forking. If they add a tool with the same name, theirs takes precedence (or we rename ours).

**Why ChromaDB for memory?**
Same as RosieApp -- it's local, file-backed, no external service needed. Vector search for "recall about Bob" finds semantically related memories. Runs fine on Jetson.


## Relationship to RosieApp

RosieApp was the development ground where we figured out:
- Config/profile system
- OpenClaw bridge
- Memory architecture
- Tool registry patterns
- VLM/YOLO/gaze tracking

OpenReachyClaw takes the proven ideas and builds them the right way -- as a Reachy Mini app that depends on Pollen's ecosystem instead of reimplementing it. RosieApp can be archived once OpenReachyClaw is functional.

**Code we're carrying forward from RosieApp:**
- bridges/openclaw.py -- cleaned up and simplified
- tools/memory.py -- ChromaDB-backed remember/recall
- tools/notify.py -- channel notification tool
- Profile content (personality, seed memories)
- The text brain concept (from text_session.py)

**Code we're NOT carrying forward (Pollen does it better):**
- Voice pipeline (Realtime API, audio handling, head wobble)
- Robot motion (dance, emotions, head movement)
- Camera/vision (their camera worker + VLM integration)
- Tool dispatch system (their base class + registry)
- Gradio settings UI


## Pollen's Conversation App -- Key Imports We'll Use

These are the modules we import from reachy_mini_conversation_app:

| Module                              | What We Use                              |
|-------------------------------------|------------------------------------------|
| tools.core_tools.Tool               | Base class for our custom tools          |
| tools.core_tools.ToolDependencies   | Shared state (camera, motion, etc.)      |
| openai_realtime                     | Voice pipeline (we start it, don't modify it) |
| audio.speech_tapper                 | Head wobble during speech (comes with voice pipeline) |
| prompts                             | get_session_instructions(), get_session_voice() |
| dance_emotion_moves                 | HuggingFace emotion/dance asset loading  |

If any of these internal imports break on a Pollen update, we pin the version in pyproject.toml and adapt.


## Pollen's Profile System (Reference)

Their profiles live in `profiles/<name>/` and contain:

```
profiles/<name>/
    instructions.txt       # Required: system prompt (supports [include] syntax)
    tools.txt              # Optional: enabled tools (one per line, # to disable)
    voice.txt              # Optional: voice name (e.g., "cedar", "coral")
    <custom_tool>.py       # Optional: custom tool implementations
```

The `[include]` syntax in instructions.txt:

```
You are a helpful robot.

[behaviors/curious]
[identities/rosie]
```

This inlines `prompts/behaviors/curious.txt` and `prompts/identities/rosie.txt` from the shared prompts library. We can add our own fragments to the shared library.

Env vars:
- `REACHY_MINI_CUSTOM_PROFILE` -- which profile to load (default: "example")
- `REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY` -- path to custom profiles
- `REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY` -- path to custom tools
- `AUTOLOAD_EXTERNAL_TOOLS` -- set to 1 to auto-discover tool .py files


## OpenClaw -- Quick Reference

OpenClaw is a messaging gateway (Go binary, Docker image: openclaw/gateway:latest).

It is NOT an LLM. It routes messages between channels and our app via HTTP.

Channels use outbound-only protocols (no public URL needed):
- Slack: Socket Mode (outbound WebSocket)
- Discord: Gateway (outbound WebSocket)
- Telegram: Long polling
- Email: IMAP polling + SMTP

Our app talks to it on localhost:3000:
- `GET  /api/health`    -- health check
- `GET  /api/channels`  -- list active channels
- `POST /api/send`      -- send text or photo to a channel

OpenClaw talks to us via webhook:
- `POST http://our-app:8100/incoming` -- delivers inbound messages


## Hardware Reference

**Reachy Mini audio hardware:**
- 4-mic linear array (Seeed Studio reSpeaker, XMOS XVF3800)
- Hardware beamforming built in
- 5W integrated speaker
- Audio accessed via SDK: `robot.media.get_audio_sample()` / `push_audio_sample()`

**Reachy Mini motion:**
- 6-DOF head (Stewart platform)
- Body rotation (yaw)
- 2 controllable antennas
- Control via `robot.set_target(head=pose)` or `robot.goto_target(head=pose, duration=1.0)`

**Our Jetson setup:**
- Older Jetson board (not Thor)
- Connected to Reachy Mini via USB serial
- Runs Linux directly (not through desktop app)
- Monitor can be attached for dashboard viewing
- No keyboard needed once configured
