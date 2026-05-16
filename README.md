# Voice AI Agent for Indian Schools

A conversational voice agent for schools across India. Supports **11 Indian languages** with **automatic detection**, tuned for **low latency**, **classroom noise**, and **natural interruptions**.

Built on [LiveKit Agents](https://github.com/livekit/agents) + [Sarvam AI](https://sarvam.ai) (STT, TTS) + [Groq/Llama-3](https://groq.com) (LLM) and features production-grade tracing via [Langfuse v4](https://langfuse.com).

## Architecture

```
Browser ──WebRTC──▶ LiveKit Cloud (BVC noise cancellation)
                        │
     ┌──────────────────▼─────────────────────┐       ┌────────────────────┐
     │            Voice AI Agent               │       │                    │
     │                                         │       │  Langfuse v4       │
     │  Silero VAD (turn detection)            │       │   - LLM TTFT       │
     │    reliable speech start/end detection  │──────▶│   - TTS TTFB       │
     │                                         │       │   - Tool tracing   │
     │  Sarvam STT (Saaras v3)                 │       │   - Latency logs   │
     │    language="unknown" → auto-detect     │       │                    │
     │    flush_signal for secondary VAD       │       └────────────────────┘
     │                                         │
     │  Language detection                     │
     │    stores language from STT event       │
     │    routes to correct TTS voice          │
     │                                         │
     │  LLM (Groq Llama-3 or Sarvam-30b)       │
     │    multilingual responses               │
     │    text-based emotional expression      │
     │    tool calling (homework, attendance)  │
     │                                         │
     │  MultilingualTTS (Sarvam Bulbul v3)     │
     │    11 TTS instances, 1 per language     │
     │    WebSocket streaming, 24000 Hz        │
     │    ──Data channel──▶ Frontend chat      │
     └─────────────────────────────────────────┘
```

### Latency budget

| Stage | Time |
|---|---|
| Browser → LiveKit | 20-40ms |
| Sarvam STT | ~70ms |
| Endpointing delay | 70ms |
| Groq LLM (Llama-3) | **150-250ms** |
| Sarvam TTS (first byte) | 100-200ms |
| LiveKit → Browser | 20-40ms |
| **Total** | **~430-670ms** |

## Quick start

### Prerequisites

- Python 3.10+
- [LiveKit Cloud](https://cloud.livekit.io) account (free)
- [Sarvam AI](https://dashboard.sarvam.ai) API key
- [Groq](https://console.groq.com) API key (free, for Llama-3 LLM)
- [Langfuse](https://langfuse.com) API key (free, for observability)

### Setup

```bash
cd Voice-AI-Agent

# Install dependencies
uv sync

# Configure API keys
cp .env.example .env
# Edit .env with your keys
```

### Run

Three terminals needed:

```bash
# Terminal 1 — Token server (port 8000)
uv run python server.py

# Terminal 2 — Agent worker
uv run python agent.py dev

# Terminal 3 — Serve frontend (port 3000)
cd frontend && npm run dev
```

Open `http://localhost:3000` and click **Connect**. The agent greets you in Hindi and auto-detects your language as you speak.

### CLI testing (no browser)

```bash
uv run python agent.py console
```

## Supported languages

| Language | Code | Speaker | Region |
|---|---|---|---|
| Hindi | `hi-IN` | simran | North |
| Tamil | `ta-IN` | kavitha | South |
| Telugu | `te-IN` | rupali | South |
| Kannada | `kn-IN` | neha | South |
| Malayalam | `ml-IN` | priya | South |
| Marathi | `mr-IN` | shreya | West |
| Gujarati | `gu-IN` | pooja | West |
| Bengali | `bn-IN` | ishita | East |
| Odia | `od-IN` | suhani | East |
| Punjabi | `pa-IN` | tanya | North |
| English | `en-IN` | aditya | Pan-India |

## How language auto-detection works

1. Sarvam STT runs with `language="unknown"` — it auto-detects the spoken language
2. `user_input_transcribed` event stores the detected language code
3. `on_user_turn_completed(turn_ctx, *, new_message=None)` reads the stored language and switches TTS if needed
4. `MultilingualTTS.current_language` is updated — the TTS wrapper routes to the correct per-language Sarvam instance
5. Each language has its own pre-initialized TTS instance with the right voice — no WebSocket reconnect latency on switch
6. Transcripts are published to the frontend via LiveKit data channel for real-time chat display

## Frontend

React + Vite SPA — `livekit-client` installed via npm. ESM CDN no longer required.

- **Animated orb** — reflects agent state: blue pulse when listening, violet spin when thinking, green glow when speaking
- **Chat transcript** — bubble-style conversation with user (blue) and agent (dark) messages, auto-scroll, fed by agent data messages
- **Language chips** — all 11 languages shown; detected language highlights in green
- **Error banner** — intelligent diagnostics: distinguishes token server unreachable vs LiveKit connection failed
- **Mute toggle** — round mic button that calls `setMicrophoneEnabled()` on the LiveKit participant
- **Dynamic hostname** — token URL uses `window.location.hostname` so it works via `localhost` or `0.0.0.0`

```bash
cd frontend
npm install
npm run dev     # starts on http://localhost:3000
```

For production:

```bash
cd frontend
npm run build   # outputs to frontend/dist/
```

## Project structure

```
Voice-AI-Agent/
├── agent.py              # MultilingualTTS + SchoolVoiceAgent + entrypoint
├── server.py             # FastAPI token server (/token endpoint)
├── config.py             # Language config, voice mappings, STT/TTS constants
├── pyproject.toml        # Dependencies (uv)
├── .env.example          # API keys template
├── CLAUDE.md             # Claude Code agent context
├── utils/
│   ├── prompts.py        # System prompt (multilingual, emotional intelligence)
│   └── tools.py          # School tools (homework, attendance, timetable, etc.)
├── frontend/
│   ├── src/
│   │   ├── App.jsx                 # Root component, wires all pieces
│   │   ├── App.css                 # Global styles, CSS custom properties, animations
│   │   ├── main.jsx                # React entry point
│   │   ├── components/
│   │   │   ├── Orb.jsx / Orb.css   # Animated orb — idle/listening/thinking/speaking
│   │   │   ├── StatusLabel.jsx     # "Listening...", "Thinking...", "Speaking..."
│   │   │   ├── LanguageBar.jsx     # 11 language chips with active highlight
│   │   │   ├── ChatTranscript.jsx  # Scrollable bubble-style conversation
│   │   │   ├── ErrorBanner.jsx     # Diagnostic error messages
│   │   │   └── Controls.jsx        # Connect / Leave Room / Mute toggle
│   │   └── hooks/
│   │       └── useVoiceAgent.js    # LiveKit connection, state machine, data channel
│   ├── index.html                  # Vite HTML entry
│   ├── package.json
│   └── vite.config.js
└── README.md
```

## Key optimizations

- **Silero VAD** — dedicated voice activity detection following LiveKit's recommended pattern for reliable turn detection
- **70ms endpointing** — `EndpointingOptions(min_delay=0.07)` via `TurnHandlingOptions` vs typical 200-300ms
- **TTS connection pooling** — one WebSocket per language, pre-warmed synchronously, no reconnect on language switch
- **BVC noise cancellation** — LiveKit server-side removes keyboard, fan, background voices
- **50ms barge-in** — `min_speech_duration=0.05` enables instant interruption when user starts speaking
- **Groq LLM Backend** — Llama-3 evaluates tools and streams first token in under 200ms, completely eliminating OpenAI tool-calling overhead
- **Langfuse Observability** — OpenTelemetry-based hierarchical tracing of conversation turns, LLM TTFT, TTS TTFB, and tool latency
- **Noisy environment fallback** — `config.py` has commented-out overrides (300ms/150ms) when background noise is present
- **React + Vite** — componentized frontend with `livekit-client` as npm dependency, fast HMR in dev

## Design notes

- Sarvam TTS has **no SSML/emotion tags** — emotion is conveyed through word choice and Indian interjections in the system prompt
- Each language gets its own `sarvam.TTS` instance (not a single instance with `update_options()`) — avoids WebSocket reconnect overhead
- Turn detection uses `TurnHandlingOptions(endpointing=EndpointingOptions(min_delay=0.07))` — the new non-deprecated API replacing `min_endpointing_delay`
- For noisy environments like crowded classrooms, swap `config.py` to the commented-out noisy values
- Tools are stubs returning mock data — replace with real school database/SIS integrations
# Voice-AI-Agent
