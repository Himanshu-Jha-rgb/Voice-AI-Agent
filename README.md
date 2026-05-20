---
title: Voice AI Agent
emoji: 🎙️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Voice AI Agent for Indian Schools

A conversational voice agent for schools across India. Supports **11 Indian languages** with **automatic detection**, tuned for **low latency**, **classroom noise**, and **natural interruptions**.

Built on [LiveKit Agents](https://github.com/livekit/agents) + [Sarvam AI](https://sarvam.ai) (STT, TTS, LLM) with configurable LLM providers (Sarvam, OpenAI, Groq) and production-grade tracing via [Langfuse v4](https://langfuse.com).

## Architecture

```mermaid
graph TD
    classDef frontend fill:#3b82f6,stroke:#1e3a8a,stroke-width:2px,color:white;
    classDef server fill:#10b981,stroke:#047857,stroke-width:2px,color:white;
    classDef livekit fill:#f59e0b,stroke:#b45309,stroke-width:2px,color:white;
    classDef agent fill:#8b5cf6,stroke:#4c1d95,stroke-width:2px,color:white;
    classDef ext fill:#64748b,stroke:#334155,stroke-width:2px,color:white;

    subgraph Client [Client Side]
        UI[React/TS/Vite Frontend]:::frontend
    end

    subgraph Backend [Backend Infrastructure]
        TokenServer[FastAPI Token Server]:::server
        LiveKitCloud[LiveKit Cloud / WebRTC Router]:::livekit
    end

    subgraph Worker [Agent Worker Node]
        VoiceAgent[LiveKit Python Agent]:::agent

        subgraph Pipeline [Voice Processing Pipeline]
            VAD[Silero VAD: Turn Detection]:::agent
            STT[Sarvam STT: Speech-to-Text & Lang Detect]:::agent
            Dedup[Transcript Dedup + Filler Filter]:::agent
            Hysteresis[Language Hysteresis Tracker]:::agent
            LLM[LLM Generation]:::agent
            TTS[Sarvam TTS: Multi-lang Streaming]:::agent
            Tools[School Operations Tools]:::agent
        end
    end

    subgraph Externals [External Services]
        Langfuse[Langfuse: Observability & Tracing]:::ext
    end

    UI -- "1. Request Token (/token)" --> TokenServer
    TokenServer -- "2. Return LiveKit JWT" --> UI

    UI <== "3. WebRTC (Audio In/Out)\nData Channel (Transcripts)" ==> LiveKitCloud
    LiveKitCloud <== "4. WebRTC\nData Channel" ==> VoiceAgent

    VoiceAgent --> |Audio stream| VAD
    VAD --> |Speech endpoints| STT
    STT --> |Transcript + Language| Dedup
    Dedup --> |Clean transcript| Hysteresis
    Hysteresis --> |Language decision| LLM
    LLM --> |Tool Call| Tools
    Tools -.-> |Tool Result| LLM
    LLM --> |Text chunks| TTS
    TTS --> |Synthesized Audio| VoiceAgent

    VoiceAgent -. "Traces & Spans\n(TTFT, TTFB, latency)" .-> Langfuse
```

### Component Breakdown

1. **Client Side**: React 19 + TypeScript + Vite SPA using `@livekit/components-react`. Fetches a token via `TokenSource.endpoint('/token')` and connects to LiveKit Cloud. Renders audio visualizer, chat transcript, and language chips from data channel messages.
2. **Backend Infrastructure**: FastAPI Token Server issues secure LiveKit JWTs (GET + POST endpoints). Serves built frontend as SPA with fallback routing. LiveKit Cloud acts as the WebRTC SFU and provides BVC noise cancellation.
3. **Agent Worker Node**: Core orchestration layer. Silero VAD for endpointing, Sarvam STT for speech-to-text and language detection, configurable LLM for responses, and Sarvam TTS with persistent per-language WebSocket pools. Includes filler suppression, transcript deduplication, language hysteresis, and rolling conversation summarization.
4. **External Services**: Langfuse captures hierarchical telemetry — session traces, per-turn spans, STT/LLM/TTS observability (TTFT, TTFB), tool call latency, language switch events, and interruption tracking.

### Latency budget

| Stage | Time |
|---|---|
| Browser to LiveKit | 20-40ms |
| Sarvam STT | ~70ms |
| Endpointing delay | 50-150ms |
| LLM first token | 150-400ms (varies by provider) |
| Sarvam TTS (first byte) | 100-200ms |
| LiveKit to Browser | 20-40ms |
| **Total** | **~400-860ms** |

## Quick start

### Prerequisites

- Python 3.10+
- Node.js 20+
- [LiveKit Cloud](https://cloud.livekit.io) account (free)
- [Sarvam AI](https://dashboard.sarvam.ai) API key
- [Langfuse](https://langfuse.com) account (optional, free tier for observability)

### Setup

```bash
cd Voice-AI-Agent

# Install Python dependencies
uv sync

# Install frontend dependencies
cd frontend && npm install && cd ..

# Configure API keys
cp .env.example .env
# Edit .env with your keys
```

### Run

Three terminals needed:

```bash
# Terminal 1 — Token server + API (port 8000)
uv run python server.py

# Terminal 2 — Agent worker
uv run python agent.py dev

# Terminal 3 — Frontend dev server (port 3000, proxies /token to :8000)
cd frontend && npm run dev
```

Open `http://localhost:3000` and click **Connect**. The agent greets you in Hindi and auto-detects your language as you speak.

### CLI testing (no browser)

```bash
uv run python agent.py console
```

### Docker / Hugging Face Spaces

The included `Dockerfile` builds a self-contained image for HF Spaces deployment:

```bash
docker build -t voice-ai-agent .
docker run -p 7860:7860 --env-file .env voice-ai-agent
```

Runs both the agent worker and token server on port 7860, serving the built frontend as a SPA.

## Supported languages

| Language | Code | Speaker | Region |
|---|---|---|---|
| Hindi | `hi-IN` | shubh | North |
| Tamil | `ta-IN` | shubh | South |
| Telugu | `te-IN` | shubh | South |
| Kannada | `kn-IN` | shubh | South |
| Malayalam | `ml-IN` | shubh | South |
| Marathi | `mr-IN` | shubh | West |
| Gujarati | `gu-IN` | shubh | West |
| Bengali | `bn-IN` | shubh | East |
| Odia | `od-IN` | shubh | East |
| Punjabi | `pa-IN` | shubh | North |
| English | `en-IN` | shubh | Pan-India |

All languages use the `shubh` speaker from Sarvam Bulbul v3.

## How language auto-detection works

1. Sarvam STT runs with `language="unknown"` — it auto-detects the spoken language
2. `user_input_transcribed` event stores the detected language code
3. `FillerFilter` drops filler utterances ("hmm", "uh", "ji") — no LLM/TTS triggered
4. `TranscriptDedup` prevents repeated STT finals from duplicate processing
5. `LanguageTracker` applies **real hysteresis**: requires 3 consecutive meaningful turns (>=15 chars) in the same new language before switching TTS
6. Until hysteresis confirms: current TTS websocket stays warm — no teardown
7. Single-turn language mismatches: respond in detected language but keep old TTS instance alive
8. Transcripts are published to the frontend via LiveKit data channel for real-time chat display

## LLM Providers

The agent supports three LLM providers, selected via the `LLM_PROVIDER` environment variable:

| Provider | Model | Setup |
|---|---|---|
| `sarvam` (default) | `sarvam-30b` | Just needs `SARVAM_API_KEY` |
| `openai` | `gpt-4o-mini` | Set `OPENAI_API_KEY` |
| `groq` | `llama-3.3-70b-versatile` | Set `GROQ_API_KEY` |

## Frontend

React 19 + TypeScript + Vite 8 SPA. Uses Tailwind CSS v4, shadcn/ui (Radix UI primitives), and `@livekit/components-react`.

- **Audio visualizer** — animated bar visualizer synced to agent state (connecting/listening/thinking/speaking)
- **Chat transcript** — bubble-style conversation with user and agent messages, auto-scroll, streaming markdown rendering
- **Language chips** — all 11 languages shown; detected language highlights in green
- **Control bar** — microphone toggle, leave room button
- **Start audio button** — browser autoplay unlock prompt

### Build

```bash
cd frontend
npm run dev     # development on http://localhost:3000
npm run build   # production build to frontend/dist/
npm run lint    # ESLint
```

The Vite dev server proxies `/token` to `http://localhost:8000` so no CORS issues in development. In production, `server.py` serves the built frontend from `frontend/dist/` with SPA fallback routing.

## Project structure

```
Voice-AI-Agent/
├── agent.py              # WSState, FillerFilter, LanguageTracker, TranscriptDedup,
│                         #   TTSSessionManager, RaceFreeSynthesizeStream,
│                         #   MultilingualTTS, SchoolVoiceAgent, entrypoint
├── server.py             # FastAPI: GET/POST /token + SPA static file serving
├── config.py             # LanguageConfig, 11 languages, all constants
├── pyproject.toml        # Python dependencies (uv)
├── Dockerfile            # Multi-stage build for HF Spaces
├── .env.example          # API keys template
├── CLAUDE.md             # Claude Code agent context
├── utils/
│   ├── prompts.py        # System prompt (voice-optimised, ~2000 chars)
│   ├── tools.py          # School tools with Langfuse tracing
│   └── summarize.py      # Rolling conversation summarization
└── frontend/
    ├── src/
    │   ├── App.tsx                          # Root — AgentSessionProvider + AgentUI
    │   ├── main.tsx                         # React 19 entrypoint
    │   ├── index.css                        # Tailwind CSS v4 import
    │   ├── hooks/
    │   │   ├── useTranscripts.ts            # LiveKit data channel listener
    │   │   └── agents-ui/                   # Audio visualizer + control bar hooks
    │   ├── components/
    │   │   ├── LanguageBar.tsx              # 11 language chips
    │   │   ├── agents-ui/                   # LiveKit agent UI components
    │   │   │   ├── agent-session-provider.tsx
    │   │   │   ├── agent-control-bar.tsx
    │   │   │   ├── agent-chat-transcript.tsx
    │   │   │   ├── agent-audio-visualizer-bar.tsx
    │   │   │   └── start-audio-button.tsx
    │   │   ├── ai-elements/                 # AI conversation/message primitives
    │   │   └── ui/                          # shadcn/ui base components
    │   └── lib/
    │       └── utils.ts                     # cn() utility (clsx + tailwind-merge)
    ├── package.json
    ├── vite.config.js
    ├── tsconfig.json
    ├── components.json                      # shadcn/ui config
    └── index.html
```

## Key optimizations

- **Silero VAD** — dedicated voice activity detection following LiveKit's recommended pattern
- **Dynamic endpointing** — `min_delay=50ms`, `max_delay=150ms`, `alpha=0.6` — aggressive tuning for fast Indian-language turn-taking
- **Preemptive TTS** — starts synthesis as soon as LLM produces first tokens, reducing time-to-first-audio
- **TTS connection pooling** — one persistent WebSocket per language, never closed between turns, no reconnect on language switch
- **Filler suppression** — 27 filler patterns filtered out before LLM/TTS pipeline activation
- **Transcript deduplication** — MD5 hashing + time window prevents repeated STT finals from duplicate processing
- **Language hysteresis** — 3 consecutive meaningful turns required before switching TTS, eliminates flip-flopping
- **Two-layer context** — rolling summarization of older turns + sliding window of recent turns for long conversations
- **BVC noise cancellation** — LiveKit server-side removes keyboard, fan, background voices
- **200ms barge-in** — `min_duration=0.2` enables natural interruption with backchannel boundary suppression
- **Langfuse observability** — hierarchical tracing: session, turns, STT, LLM (TTFT), TTS (TTFB), tool calls, language switches, interruptions
- **Multi-provider LLM** — switch between Sarvam, OpenAI, and Groq via environment variable
- **Noisy environment fallback** — `config.py` has commented-out overrides for background-noise-heavy settings

## Design notes

- Sarvam TTS has **no SSML/emotion tags** — emotion is conveyed through word choice and Indian interjections in the system prompt
- Each language gets its own persistent `sarvam.TTS` instance managed by `TTSSessionManager` — no scattered `ws.close()` calls
- `RaceFreeSynthesizeStream` wraps Sarvam's stream with a `WSState` state machine and drain-before-close to prevent aiohttp transport crashes
- Turn detection uses `TurnHandlingOptions(endpointing=EndpointingOptions(...))` — the non-deprecated API with preemptive generation enabled
- Tools are currently commented out — uncomment in `SchoolVoiceAgent.__init__()` and replace stubs with real school database integrations
- For noisy environments like crowded classrooms, swap `config.py` to the commented-out noisy values (300ms/600ms endpointing)
