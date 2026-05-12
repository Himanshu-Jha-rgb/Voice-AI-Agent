# CLAUDE.md — Voice AI Agent for Indian Schools

## Overview

Multilingual conversational voice agent for schools across India. Built on **LiveKit Agents** + **Sarvam AI** (STT/TTS/LLM). Supports 11 Indian languages with automatic detection and dynamic TTS voice switching.

## Architecture

```
Browser ──WebRTC──▶ LiveKit Cloud (BVC noise cancellation)
                        │
                        ▼
              Silero VAD (turn detection, speech start/end)
                        │
                        ▼
              Sarvam STT (saaras:v3, language="unknown")
              → auto-detects language, ~70ms latency
                        │
                        ▼
              Language detection (user_input_transcribed event)
              → stores detected language, sets MultilingualTTS.current_language
                        │
                        ▼
              Sarvam LLM (multilingual, text-based emotion)
                        │
                        ▼
              MultilingualTTS → routes to correct Sarvam TTS instance
              (lazy pool: 1 Sarvam TTS per language)
                        │
                        ▼
              Sarvam TTS (bulbul:v3, WebSocket streaming) → Browser
```

## Running the project

```bash
# Install dependencies
uv sync

# Set up API keys
cp .env.example .env   # edit with real keys

# Terminal 1 — token server (frontend auth)
uv run python server.py

# Terminal 2 — agent worker
uv run python agent.py dev

# Terminal 3 — Serve frontend (port 3000)
cd frontend && npm run dev

# Optional: test via CLI instead of browser
uv run python agent.py console
```

## Key files

| File | Purpose |
|------|---------|
| `agent.py` | Core: `MultilingualTTS` wrapper, `SchoolVoiceAgent`, `entrypoint` |
| `server.py` | FastAPI server with `/token` endpoint for LiveKit JWT |
| `config.py` | `LanguageConfig` dataclass, 11 languages, STT/TTS/VAD constants |
| `utils/prompts.py` | `SYSTEM_PROMPT` (multilingual, emotional intelligence, school context) |
| `utils/tools.py` | 5 async tool functions (`lookup_homework`, `check_attendance`, etc.) |
| `frontend/src/App.jsx` | Root component — wires Orb, StatusLabel, LanguageBar, ChatTranscript, ErrorBanner, Controls |
| `frontend/src/hooks/useVoiceAgent.js` | LiveKit connection hook — token fetch, Room lifecycle, data channel, error classification |
| `frontend/src/components/Orb.jsx` | Animated orb with 4 states (idle/listening/thinking/speaking) and SVG icons |
| `frontend/src/components/ChatTranscript.jsx` | Auto-scrolling bubble-style conversation with empty state |
| `frontend/src/components/Controls.jsx` | Connect button (with loading state), mute toggle, leave room |
| `frontend/src/components/LanguageBar.jsx` | 11 language chips with active highlight |
| `frontend/src/App.css` | Global styles, CSS custom properties, keyframe animations |
| `frontend/package.json` | Vite + React + livekit-client dependencies |
| `frontend/vite.config.js` | Vite config — React plugin, port 3000, host 0.0.0.0 |

## Frontend

React + Vite SPA. `livekit-client` is an npm dependency (no ESM CDN).

### Component tree
```
App.jsx
├── Orb.jsx + Orb.css        — 4-state animated orb (idle/listening/thinking/speaking)
├── StatusLabel.jsx          — text label synced to agent state
├── LanguageBar.jsx          — 11 language chips, highlights detected language
├── ChatTranscript.jsx       — auto-scrolling bubble list, empty placeholder state
├── ErrorBanner.jsx          — diagnostic errors with terminal commands (nullable)
└── Controls.jsx             — Connect / Leave Room / Mute toggle
```

### State management
`useVoiceAgent.js` hook encapsulates all LiveKit logic:
- Fetches token from `http://<hostname>:8000/token`
- Manages `Room` lifecycle (connect, disconnect, track subscription)
- Parses data channel messages (`{type: "transcript", role, text, language}`)
- Classifies errors into 3 categories with targeted troubleshooting messages
- Returns: `{ connected, connecting, agentState, messages, detectedLanguage, error, muted, connect, disconnect, toggleMute }`

### State flow
```
idle → listening → thinking (LLM processing) → speaking (TTS output) → listening → ...
```

### Error handling
Three distinct error states with targeted troubleshooting:
- **Token server unreachable** — shows only the `server.py` command
- **Token server error** — shows HTTP status code
- **LiveKit connection failed** — shows only the `agent.py dev` command

### Dynamic token URL
Uses `window.location.hostname` so the frontend works regardless of whether accessed via `localhost` or `0.0.0.0`.

## Core patterns

### MultilingualTTS (`agent.py:44-130`)
- Extends `livekit.agents.tts.TTS` — is a drop-in TTS for LiveKit's `Agent`
- Lazily creates one `sarvam.TTS` instance per detected language
- `current_language` property set by `SchoolVoiceAgent.on_user_turn_completed()`
- Delegates `synthesize()` and `stream()` to the correct per-language instance
- `prewarm()` is **sync** (matches base class) — calls through to each Sarvam TTS instance synchronously
- Each instance uses the speaker from `config.py` `LanguageConfig.tts_speaker`

### Language detection flow
1. STT runs with `language="unknown"` — Sarvam auto-detects
2. `user_input_transcribed` event stores detected language as `_detected_language`
3. `on_user_turn_completed(turn_ctx, *, new_message=None)` reads `_detected_language`
4. If detected language differs from current → sets `multilingual_tts.current_language`
5. Next TTS call routes to the correct voice automatically

### Turn detection
- `AgentSession(vad=silero.VAD.load())` — Silero VAD for reliable speech detection
- `TurnHandlingOptions(endpointing=EndpointingOptions(min_delay=0.07))` — 70ms endpointing tuned for fast Indian-language turn-taking
- Barge-in handled automatically by LiveKit's AgentSession
- For noisy environments: swap `MIN_ENDPOINTING_DELAY` and `MIN_SPEECH_DURATION` in `config.py` to the commented-out noisy values (300ms / 150ms)

### Emotion handling
- Sarvam TTS has **no SSML or emotion tags** (unlike Cartesia)
- Emotion conveyed through LLM word choice + Indian interjections (see `SYSTEM_PROMPT`)
- Pace/temperature can be adjusted via `tts.update_options()` per emotional context

## Adding a new language

1. Add a `LanguageConfig` entry in `config.py`
2. Pick a Sarvam Bulbul v3 speaker for that language
3. The `MultilingualTTS` pool will auto-create the TTS instance on first use

## Adding a new tool

1. Define an async function in `utils/tools.py` with `Annotated` parameters and a `ToolContext` arg
2. Register it in `SchoolVoiceAgent.__init__()` `tools=[...]` list
3. Keep tool functions fast (< 3s) for sync tools; use `asyncio.create_task()` for slow tools

## Key dependencies

- `livekit-agents[sarvam,silero]>=1.5` — LiveKit Agent framework + Sarvam plugins
- `livekit` — server SDK (token generation)
- `fastapi` + `uvicorn` — token server
- `python-dotenv` — env var loading

## Environment variables

```
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SARVAM_API_KEY=sk_xxxxxxxxxxxxxxxxxxxxxxxx
```

## Design decisions

- **TurnHandlingOptions API** — uses the new non-deprecated `turn_handling=TurnHandlingOptions(endpointing=EndpointingOptions(...))` pattern
- **Silero VAD** — separate VAD model (`vad=silero.VAD.load()`) for reliable turn detection, following LiveKit's recommended pattern
- **TTS pool, not single TTS with `update_options()`** — avoids WebSocket reconnect latency when switching languages mid-conversation
- **Sync prewarm** — `MultilingualTTS.prewarm()` is synchronous to match LiveKit's `TTS` base class signature
- **Noisy environment config** — `config.py` has commented-out overrides (300ms endpointing, 150ms min speech) for background-noise-heavy settings
- **React + Vite frontend** — componentized SPA, `livekit-client` as npm dep, fast HMR in dev, optimized production build
- **Text-based emotion** — Sarvam lacks SSML; the LLM conveys emotion through word choice and Indian interjections
- **Data messages to frontend** — agent publishes `{type: "transcript", role, text, language}` via LiveKit data channel for chat bubbles and language highlighting
- **Explicit mp3 codec** — `output_audio_codec="mp3"` set explicitly; `"wav"` is blocked because Sarvam returns raw PCM bytes instead of a valid WAV container, causing LiveKit decode crashes
- **Stale WebSocket retry** — `synthesize()` and `stream()` retry up to `TTS_WS_MAX_RETRIES` times on failure, invalidating stale TTS instances so the next attempt creates a fresh WebSocket connection
- **`target_language_code` propagation** — `update_options()` passes `target_language_code` through to the underlying `sarvam.TTS.update_options()` so the internal opts stay consistent with the wrapper's language routing
