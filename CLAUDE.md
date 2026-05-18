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
              TranscriptDedup (text hash + time window — drop repeated finals)
                        │
                        ▼
              LanguageTracker (REAL hysteresis: 3 consecutive turns, ≥15 chars)
              → NO websocket teardown during pending state
                        │
                        ▼
              LLM (Sarvam / OpenAI / Groq — configurable via LLM_PROVIDER)
              + Langfuse tracing (per-turn spans, LLM generation, TTS, STT)
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

# Terminal 1 — token server (serves API + built frontend)
uv run python server.py

# Terminal 2 — agent worker
uv run python agent.py dev

# Terminal 3 — Serve frontend dev (port 3000, proxies /token to :8000)
cd frontend && npm run dev

# Optional: test via CLI instead of browser
uv run python agent.py console
```

## Docker / Hugging Face Spaces

`Dockerfile` is a multi-stage build for HF Spaces deployment:
1. **Stage 1** (`node:20-slim`): installs npm deps, runs `npm run build`
2. **Stage 2** (`uv:python3.12-bookworm-slim`): installs ffmpeg + curl, `uv sync --frozen`, copies built frontend

Exposes port 7860. Startup runs both `agent.py start` (background) and `uvicorn server:app` on port 7860.

## Key files

| File | Purpose |
|------|---------|
| `agent.py` | Core: `WSState`, `FillerFilter`, `LanguageTracker`, `TranscriptDedup`, `TTSSessionManager`, `RaceFreeSynthesizeStream`, `MultilingualTTS`, `SchoolVoiceAgent`, `entrypoint` |
| `server.py` | FastAPI: GET/POST `/token` (LiveKit JWT), SPA static file serving |
| `config.py` | `LanguageConfig` dataclass, 11 languages, STT/TTS/LLM/endpointing/hysteresis/filler constants |
| `pyproject.toml` | Python deps: `livekit-agents[sarvam,silero]`, `langfuse`, `fastapi`, etc. |
| `utils/prompts.py` | `SYSTEM_PROMPT` (voice-optimised, ~2000 chars) + `GREETING_INSTRUCTIONS` |
| `utils/tools.py` | 5 `@function_tool` functions (currently commented out in agent) + Langfuse span helpers |
| `utils/summarize.py` | Rolling conversation summarization (Sarvam or OpenAI) |
| `utils/tracing.py` | `SessionTracer` class (unused — agent.py uses Langfuse directly) |
| `Dockerfile` | Multi-stage build: Node 20 frontend builder + UV Python 3.12, designed for HF Spaces |
| `frontend/src/App.tsx` | Root — `AgentSessionProvider` + `AgentUI` (visualizer, language bar, chat, controls) |
| `frontend/src/main.tsx` | React 19 entrypoint |
| `frontend/src/hooks/useTranscripts.ts` | LiveKit data channel listener — parses `{type:"transcript"}` messages |
| `frontend/src/components/LanguageBar.tsx` | 11 language chips with active highlight |
| `frontend/src/components/agents-ui/` | Agent UI components (session provider, control bar, chat transcript, audio visualizer, etc.) |
| `frontend/src/components/ai-elements/` | AI conversation/message primitives |
| `frontend/src/components/ui/` | shadcn/ui base components (button, toggle, tooltip, select, separator) |
| `frontend/src/lib/utils.ts` | `cn()` utility (clsx + tailwind-merge) |
| `frontend/package.json` | React 19, Vite 8, Tailwind v4, `@livekit/components-react`, shadcn, motion, lucide |
| `frontend/vite.config.js` | Vite + React + Tailwind plugin, `@` alias, port 3000, `/token` proxy to :8000 |
| `frontend/tsconfig.json` | TypeScript config with `@/` path alias |
| `frontend/components.json` | shadcn/ui configuration |

## Frontend

React 19 + TypeScript + Vite 8 SPA. Uses Tailwind CSS v4, shadcn/ui (Radix UI primitives), and `@livekit/components-react` for LiveKit integration.

### Component tree
```
App.tsx
└── AgentSessionProvider          — wraps SessionProvider + RoomAudioRenderer
    └── AgentUI
        ├── AgentAudioVisualizerBar — animated audio visualizer synced to agent state
        ├── LanguageBar.tsx         — 11 language chips, highlights detected language
        ├── AgentChatTranscript     — auto-scrolling conversation bubbles
        ├── AgentControlBar         — mic toggle, leave room
        └── StartAudioButton        — browser audio unlock prompt
```

### State management
- `useSession(tokenSource)` from `@livekit/components-react` — manages Room lifecycle via `TokenSource.endpoint('/token')`
- `useAgent()` — provides agent state (idle/listening/thinking/speaking)
- `useTranscripts.ts` — listens to LiveKit `DataReceived` events, parses `{type:"transcript", role, text, language}` messages, returns `{messages, detectedLanguage, reset}`
- Vite dev server proxies `/token` to `http://localhost:8000` so no CORS issues

### Key dependencies
- `@livekit/components-react` — `SessionProvider`, `useSession`, `useAgent`, `useRoomContext`, `RoomAudioRenderer`
- `livekit-client` — `TokenSource`, `RoomEvent`
- `motion` — animations
- `lucide-react` — icons
- `streamdown` + `@streamdown/*` — markdown rendering in chat
- `ai` — AI SDK utilities
- `radix-ui` + `shadcn` — UI primitives
- `tailwind-merge` + `class-variance-authority` + `clsx` — styling utilities
- `use-stick-to-bottom` — auto-scroll behavior

## Core patterns

### TTS Session Manager (`agent.py:TTSSessionManager`)
Centralized owner of all TTS websocket lifecycle. Design invariants:
- ONE `sarvam.TTS` instance per language (lazily created, persistent for session lifetime)
- Sarvam's internal `ConnectionPool` keeps websockets alive across turns
- Websockets are **never** closed between turns — only on confirmed language switch or shutdown
- `async Lock` serializes all state transitions; `threading.Lock` protects singleton creation
- `warm()` evicts stale pool entries and prewarms connections
- Background tasks tracked via `_bg_tasks` set, drained before shutdown

### MultilingualTTS (`agent.py:MultilingualTTS`)
- Extends `livekit.agents.tts.TTS` — drop-in TTS for LiveKit's `Agent`
- Thin adapter over `TTSSessionManager` — delegates all lifecycle decisions
- `synthesize()` → returns Sarvam `ChunkedStream` (HTTP POST, no websocket race risk)
- `stream()` → returns `RaceFreeSynthesizeStream` wrapper with race-free `aclose()`
- Both retry up to `TTS_WS_MAX_RETRIES` times on transient failures

### RaceFreeSynthesizeStream (`agent.py:RaceFreeSynthesizeStream`)
Wraps Sarvam's `SynthesizeStream` to prevent the `aiohttp` "Cannot write to closing transport" crash:
1. **State machine** (`WSState`: DISCONNECTED → CONNECTING → CONNECTED → CLOSING → CLOSED)
2. `aclose()` acquires `_close_lock`, sets CLOSING, **drains in-flight writes** (250ms), then closes
3. Duplicate close calls are no-ops (idempotent via state check)
4. Transport-close errors during teardown are caught and suppressed
5. The underlying websocket stays alive in Sarvam's `ConnectionPool` for the next turn
6. Langfuse TTS span with TTFB tracking on first audio chunk

### TranscriptDedup (`agent.py:TranscriptDedup`)
Deduplicates final transcript events via MD5 text hashing + configurable time window. Prevents repeated STT finals from triggering duplicate LLM/TTS cycles.

### Language detection flow (with REAL hysteresis)
1. STT runs with `language="unknown"` — Sarvam auto-detects
2. `user_input_transcribed` event stores detected language as `_detected_language`
3. `on_user_turn_completed` checks `FillerFilter.is_filler(transcript)` — **filler → skip entirely**
4. `TranscriptDedup.is_duplicate(transcript)` — **duplicate → skip**
5. `LanguageTracker.record_turn()` records the detection (fillers record as "no decision")
6. `LanguageTracker.should_switch()` requires **3 consecutive meaningful turns** (≥15 chars) in the same new language
7. Until hysteresis confirms: keep current TTS websocket warm, no teardown
8. Single-turn language mismatches: respond in detected language but **keep old TTS instance alive**

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
- `EndpointingOptions(mode="dynamic", min_delay=0.05, max_delay=0.15)` — 50ms floor, 150ms cap
- `alpha=0.6` — responsive EMA for fast adaptation to speaker cadence
- `InterruptionOptions(min_duration=0.2)` — 200ms barge-in threshold
- `PreemptiveGenerationOptions(enabled=True, preemptive_tts=True)` — start TTS as soon as LLM produces first tokens
- Backchannel boundary: 300ms start, 1.5s end — suppresses spurious interruptions near speech boundaries
- For noisy environments: swap constants in `config.py` to the commented-out noisy values

### Context management (two-layer)
When `MAX_CONTEXT_ITEMS` (50) is exceeded:
1. System prompt + rolling summary (if available) + most recent `SLIDING_WINDOW_TURNS` (10) kept verbatim
2. Older items asynchronously summarized via `utils/summarize.py` (Sarvam or OpenAI)
3. Summary injected as a system message — agent retains full conversation context

### LLM provider flexibility
- `LLM_PROVIDER` env var selects: `"sarvam"` (default), `"openai"`, or `"groq"`
- Sarvam: native `sarvam.LLM(model="sarvam-30b")`
- OpenAI: `livekit.plugins.openai.LLM(model="gpt-4o-mini")`
- Groq: OpenAI-compatible endpoint at `api.groq.com/openai/v1` with `llama-3.3-70b-versatile`

### Langfuse observability
- Per-session trace with root span (`voice-session`)
- Per-turn spans (`user-turn`) with detected language, transcript length, final TTS language
- STT spans with transcript + language metadata
- LLM generation spans with TTFT, token count, char count, elapsed time
- TTS spans with TTFB tracking
- Tool call spans with duration + success/error
- Events: language-switch (temporary vs hysteresis-confirmed), interruption start/resume/cancel

### Emotion handling
- Sarvam TTS has **no SSML or emotion tags** (unlike Cartesia)
- Emotion conveyed through LLM word choice + Indian interjections (see `SYSTEM_PROMPT`)
- Pace/temperature adjustable via `tts.update_options()` per emotional context

## Adding a new language

1. Add a `LanguageConfig` entry in `config.py`
2. Pick a Sarvam Bulbul v3 speaker for that language
3. The `MultilingualTTS` pool will auto-create the TTS instance on first use

## Adding a new tool

1. Define an async function in `utils/tools.py` with `@function_tool` decorator and `Annotated` parameters
2. Register it in `SchoolVoiceAgent.__init__()` `tools=[...]` list
3. Keep tool functions fast (< 3s) for sync tools; use `asyncio.create_task()` for slow tools
4. Langfuse tool call spans are automatically created via `_get_tool_span()` / `_end_tool_span()`

## Key dependencies

### Python (`pyproject.toml`)
- `livekit-agents[sarvam,silero]>=1.5` — LiveKit Agent framework + Sarvam/Silero plugins
- `livekit` — server SDK (token generation)
- `fastapi` + `uvicorn[standard]` — token server + SPA serving
- `python-dotenv` — env var loading
- `langfuse>=4.0` — observability (traces, spans, generations)
- `numpy` — audio processing

### Frontend (`package.json`)
- `react` + `react-dom` v19 — UI framework
- `vite` v8 + `@vitejs/plugin-react` — build tool
- `tailwindcss` v4 + `@tailwindcss/vite` — styling
- `@livekit/components-react` — LiveKit React hooks + components
- `livekit-client` — WebRTC client
- `shadcn` + `radix-ui` — UI component primitives
- `motion` — animations
- `lucide-react` — icons
- `streamdown` + `@streamdown/*` — markdown rendering
- `ai` — AI SDK utilities
- `tailwind-merge` + `class-variance-authority` + `clsx` — styling utilities
- `use-stick-to-bottom` — auto-scroll

## Environment variables

```
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SARVAM_API_KEY=sk_xxxxxxxxxxxxxxxxxxxxxxxx
LLM_PROVIDER=sarvam              # "sarvam", "openai", or "groq"
OPENAI_API_KEY=sk-...            # only if LLM_PROVIDER=openai
OPENAI_MODEL=gpt-4o-mini         # only if LLM_PROVIDER=openai
GROQ_API_KEY=gsk_...             # only if LLM_PROVIDER=groq
GROQ_MODEL=llama-3.3-70b-versatile  # only if LLM_PROVIDER=groq
LANGFUSE_PUBLIC_KEY=pk-lf-...    # optional: Langfuse observability
LANGFUSE_SECRET_KEY=sk-lf-...    # optional: Langfuse observability
LANGFUSE_HOST=https://cloud.langfuse.com  # optional
```

## Design decisions

- **Centralized websocket ownership** — `TTSSessionManager` is the sole owner of all TTS websocket lifecycle. No scattered `ws.close()` calls. All state transitions serialized via `asyncio.Lock` (async) + `threading.Lock` (sync singleton creation).
- **Persistent websocket pool** — Sarvam's internal `ConnectionPool` keeps websockets alive indefinitely (1h rotation). Websockets are NEVER closed between turns — only on confirmed language switch or process shutdown.
- **Race-free stream wrapper** — `RaceFreeSynthesizeStream` wraps Sarvam's `SynthesizeStream` with a `WSState` state machine. `aclose()` drains in-flight writes (250ms) before touching the websocket, preventing the "Cannot write to closing transport" aiohttp crash.
- **Real hysteresis (not fake)** — `LanguageTracker` requires 3 consecutive meaningful turns (≥15 chars) in the same language before switching TTS websockets. Fillers and short utterances break the streak. No websocket teardown during pending state.
- **Filler suppression** — Utterances matching 30+ filler patterns or shorter than 4 characters are dropped entirely: no LLM, no TTS, no state transition. Eliminates spurious "Hmm" → full pipeline activation.
- **Transcript deduplication** — `TranscriptDedup` uses MD5 hashing + time window to prevent repeated STT finals from triggering duplicate LLM/TTS cycles.
- **Two-layer context** — Rolling summarization of older turns (async, background) + sliding window of recent turns. Maintains long conversation context without unbounded growth.
- **Multi-provider LLM** — `LLM_PROVIDER` env var switches between Sarvam, OpenAI, and Groq without code changes. Groq uses OpenAI-compatible API.
- **Langfuse observability** — Full tracing: session → turn → STT/LLM/TTS spans + tool calls + language-switch events. TTFT and TTFB tracked per generation.
- **TurnHandlingOptions API** — uses the new non-deprecated `turn_handling=TurnHandlingOptions(endpointing=EndpointingOptions(...))` pattern with preemptive generation enabled.
- **Silero VAD** — separate VAD model (`vad=silero.VAD.load()`) for reliable turn detection, following LiveKit's recommended pattern.
- **Aggressive endpointing** — `min_delay=50ms`, `max_delay=150ms`, `alpha=0.6`, `mode="dynamic"` — tuned for fast Indian-language turn-taking with minimal silence gaps.
- **Preemptive TTS** — TTS starts as soon as LLM produces first tokens, reducing time-to-first-audio.
- **TTS pool, not single TTS with `update_options()`** — avoids WebSocket reconnect latency when switching languages mid-conversation. One persistent `sarvam.TTS` per language.
- **Sync prewarm** — `MultilingualTTS.prewarm()` is synchronous to match LiveKit's `TTS` base class signature. Hot languages (hi-IN, en-IN) prewarmed on agent entry.
- **Noisy environment config** — `config.py` has commented-out overrides (300ms endpointing, 600ms max) for background-noise-heavy settings.
- **React 19 + TypeScript + Tailwind v4 frontend** — `@livekit/components-react` provides session/agent hooks, shadcn/ui for consistent component styling, `TokenSource.endpoint('/token')` for auth.
- **SPA static serving** — `server.py` serves built frontend from `frontend/dist/` with SPA fallback (404 → index.html). Vite dev proxies `/token` to backend.
- **Text-based emotion** — Sarvam lacks SSML; the LLM conveys emotion through word choice and Indian interjections.
- **Data messages to frontend** — agent publishes `{type: "transcript", role, text, language}` via LiveKit data channel for chat bubbles and language highlighting.
- **Explicit mp3 codec** — `output_audio_codec="mp3"` set explicitly; `"wav"` is blocked because Sarvam returns raw PCM bytes instead of a valid WAV container, causing LiveKit decode crashes.
- **Stale WebSocket retry** — `synthesize()` and `stream()` retry up to `TTS_WS_MAX_RETRIES` times on failure. ConnectionPool handles stale connection recovery internally.
- **`target_language_code` propagation** — `update_options()` passes `target_language_code` through to the underlying `sarvam.TTS.update_options()` so the internal opts stay consistent with the wrapper's language routing.
