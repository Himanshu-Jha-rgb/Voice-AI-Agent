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
              FillerFilter (suppress "hmm", "uh", etc. — no LLM/TTS)
                        │
                        ▼
              LanguageTracker (REAL hysteresis: 3 consecutive turns, ≥15 chars)
              → NO websocket teardown during pending state
                        │
                        ▼
              Sarvam LLM (multilingual, text-based emotion)
                        │
                        ▼
              MultilingualTTS → TTSSessionManager → Sarvam TTS instance
              (persistent pool: 1 TTS per language, websockets NEVER closed per-turn)
                        │
                        ▼
              RaceFreeSynthesizeStream (WSState machine, drain-before-close)
                        │
                        ▼
              Sarvam TTS (bulbul:v3, persistent WebSocket) → Browser
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
| `agent.py` | Core: `WSState` enum, `FillerFilter`, `LanguageTracker`, `TTSSessionManager`, `RaceFreeSynthesizeStream`, `MultilingualTTS`, `SchoolVoiceAgent`, `entrypoint` |
| `server.py` | FastAPI server with `/token` endpoint for LiveKit JWT |
| `config.py` | `LanguageConfig` dataclass, 11 languages, STT/TTS/VAD constants, filler patterns, hysteresis thresholds |
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

### TTS Session Manager (`agent.py:TTSSessionManager`)
Centralized owner of all TTS websocket lifecycle. Design invariants:
- ONE `sarvam.TTS` instance per language (lazily created, persistent for session lifetime)
- Sarvam's internal `ConnectionPool` keeps websockets alive across turns
- Websockets are **never** closed between turns — only on confirmed language switch or shutdown
- `async Lock` serializes all state transitions (create, invalidate, close)
- `invalidate_language()` called **only** when hysteresis confirms a language switch

### MultilingualTTS (`agent.py:MultilingualTTS`)
- Extends `livekit.agents.tts.TTS` — drop-in TTS for LiveKit's `Agent`
- Thin adapter over `TTSSessionManager` — delegates all lifecycle decisions
- `synthesize()` → returns Sarvam `ChunkedStream` (HTTP POST, no websocket race risk)
- `stream()` → returns `RaceFreeSynthesizeStream` wrapper with race-free `aclose()`

### RaceFreeSynthesizeStream (`agent.py:RaceFreeSynthesizeStream`)
Wraps Sarvam's `SynthesizeStream` to prevent the `aiohttp` "Cannot write to closing transport" crash:
1. **State machine** (`WSState`: DISCONNECTED → CONNECTING → CONNECTED → CLOSING → CLOSED)
2. `aclose()` acquires `_close_lock`, sets CLOSING, **drains in-flight writes** (100ms), then closes
3. Duplicate close calls are no-ops (idempotent via state check)
4. Transport-close errors during teardown are caught and suppressed
5. The underlying websocket stays alive in Sarvam's `ConnectionPool` for the next turn

### Language detection flow (with REAL hysteresis)
1. STT runs with `language="unknown"` — Sarvam auto-detects
2. `user_input_transcribed` event stores detected language as `_detected_language`
3. `on_user_turn_completed` checks `FillerFilter.is_filler(transcript)` — **filler → skip entirely**
4. `LanguageTracker.record_turn()` records the detection (fillers record as "no decision")
5. `LanguageTracker.should_switch()` requires **3 consecutive meaningful turns** (≥15 chars) in the same new language
6. Until hysteresis confirms: keep current TTS websocket warm, no teardown
7. Single-turn language mismatches: respond in detected language but **keep old TTS instance alive**

### Filler suppression
- `FillerFilter.is_filler()` checks: length < 4, exact match against 30+ filler patterns, or single/dual-word very-short utterances
- When filler detected: **no LLM generation, no TTS, no state transition, no language recording**
- Patterns include: hmm, uh, okay, haan, ji, kya, nahi, achha, theek hai, etc.

### LanguageTracker (real hysteresis)
- `LANG_SWITCH_MIN_CHARS = 15` — transcript must be ≥15 characters to count as meaningful
- `LANG_SWITCH_CONSECUTIVE = 3` — same candidate language required for 3 consecutive meaningful turns
- Short/filler utterances recorded as "no decision" (breaks any in-progress streak)
- Flip-flopping languages (en→ta→en) never triggers a switch

### Turn detection
- `AgentSession(vad=silero.VAD.load())` — Silero VAD for reliable speech detection
- `EndpointingOptions(min_delay=0.05, max_delay=0.25)` — 50ms floor, 250ms cap (aggressive conversational tuning)
- `alpha=0.7` — more responsive EMA for faster adaptation to speaker cadence
- `InterruptionOptions(min_duration=0.2)` — 200ms barge-in threshold
- For noisy environments: swap constants in `config.py` to the commented-out noisy values

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

- **Centralized websocket ownership** — `TTSSessionManager` is the sole owner of all TTS websocket lifecycle. No scattered `ws.close()` calls. All state transitions serialized via `asyncio.Lock`.
- **Persistent websocket pool** — Sarvam's internal `ConnectionPool` keeps websockets alive indefinitely (1h rotation). Websockets are NEVER closed between turns — only on confirmed language switch or process shutdown.
- **Race-free stream wrapper** — `RaceFreeSynthesizeStream` wraps Sarvam's `SynthesizeStream` with a `WSState` state machine. `aclose()` drains in-flight writes (100ms) before touching the websocket, preventing the "Cannot write to closing transport" aiohttp crash.
- **Real hysteresis (not fake)** — `LanguageTracker` requires 3 consecutive meaningful turns (≥15 chars) in the same language before switching TTS websockets. Fillers and short utterances break the streak. No websocket teardown during pending state.
- **Filler suppression** — Utterances matching 30+ filler patterns or shorter than 4 characters are dropped entirely: no LLM, no TTS, no state transition. Eliminates spurious "Hmm" → full pipeline activation.
- **TurnHandlingOptions API** — uses the new non-deprecated `turn_handling=TurnHandlingOptions(endpointing=EndpointingOptions(...))` pattern
- **Silero VAD** — separate VAD model (`vad=silero.VAD.load()`) for reliable turn detection, following LiveKit's recommended pattern
- **Aggressive endpointing** — `min_delay=50ms`, `max_delay=250ms`, `alpha=0.7` — tuned for fast Indian-language turn-taking with minimal silence gaps
- **TTS pool, not single TTS with `update_options()`** — avoids WebSocket reconnect latency when switching languages mid-conversation. One persistent `sarvam.TTS` per language.
- **Sync prewarm** — `MultilingualTTS.prewarm()` is synchronous to match LiveKit's `TTS` base class signature
- **Noisy environment config** — `config.py` has commented-out overrides (300ms endpointing, 600ms max) for background-noise-heavy settings
- **React + Vite frontend** — componentized SPA, `livekit-client` as npm dep, fast HMR in dev, optimized production build
- **Text-based emotion** — Sarvam lacks SSML; the LLM conveys emotion through word choice and Indian interjections
- **Data messages to frontend** — agent publishes `{type: "transcript", role, text, language}` via LiveKit data channel for chat bubbles and language highlighting
- **Explicit mp3 codec** — `output_audio_codec="mp3"` set explicitly; `"wav"` is blocked because Sarvam returns raw PCM bytes instead of a valid WAV container, causing LiveKit decode crashes
- **Stale WebSocket retry** — `synthesize()` and `stream()` retry up to `TTS_WS_MAX_RETRIES` times on failure, invalidating stale TTS instances so the next attempt creates a fresh WebSocket connection
- **`target_language_code` propagation** — `update_options()` passes `target_language_code` through to the underlying `sarvam.TTS.update_options()` so the internal opts stay consistent with the wrapper's language routing
