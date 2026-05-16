import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageConfig:
    code: str  # BCP-47 language code
    name: str  # Human-readable name
    tts_speaker: str  # Default Sarvam Bulbul v3 speaker
    region: str  # Indian region


SUPPORTED_LANGUAGES: list[LanguageConfig] = [
    LanguageConfig("hi-IN", "Hindi", "shubh", "North"),
    LanguageConfig("ta-IN", "Tamil", "shubh", "South"),
    LanguageConfig("te-IN", "Telugu", "shubh", "South"),
    LanguageConfig("kn-IN", "Kannada", "shubh", "South"),
    LanguageConfig("ml-IN", "Malayalam", "shubh", "South"),
    LanguageConfig("mr-IN", "Marathi", "shubh", "West"),
    LanguageConfig("gu-IN", "Gujarati", "shubh", "West"),
    LanguageConfig("bn-IN", "Bengali", "shubh", "East"),
    LanguageConfig("od-IN", "Odia", "shubh", "East"),
    LanguageConfig("pa-IN", "Punjabi", "shubh", "North"),
    LanguageConfig("en-IN", "English", "shubh", "Pan-India"),
]

LANGUAGE_CODE_MAP: dict[str, LanguageConfig] = {
    lang.code: lang for lang in SUPPORTED_LANGUAGES
}
DEFAULT_LANGUAGE = LANGUAGE_CODE_MAP["hi-IN"]

# STT
STT_MODEL = "saaras:v3"
STT_MODE = "transcribe"
STT_SAMPLE_RATE = 16000
STT_HIGH_VAD_SENSITIVITY = True
STT_FLUSH_SIGNAL = True

# TTS
TTS_MODEL = "bulbul:v3"
TTS_SAMPLE_RATE = 24000
TTS_PACE = 1.0
TTS_TEMPERATURE = 0.6
TTS_OUTPUT_BITRATE = "128k"
TTS_OUTPUT_AUDIO_CODEC = (
    "mp3"  # "wav" is broken: Sarvam returns raw PCM, not a WAV container
)
TTS_MIN_BUFFER_SIZE = (
    30  # chars before TTS starts — aggressive for fast first audio (was 50)
)
TTS_MAX_CHUNK_LENGTH = 150
TTS_WS_MAX_RETRIES = 2  # stale WebSocket recovery attempts

# LLM
LLM_MODEL = "sarvam-30b"  # Sarvam model name (only used when provider is "sarvam")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "sarvam")  # "sarvam", "openai", or "groq"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # OpenAI model
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")  # Groq model

# ── Turn detection (aggressive conversational tuning) ─────────────────────────

ENDPOINTING_MODE = "dynamic"  # "fixed" or "dynamic" — dynamic adapts to speaker cadence
ENDPOINTING_MIN_DELAY = 0.05  # 50ms minimum silence before end-of-turn (was 70ms)
ENDPOINTING_MAX_DELAY = 0.15  # 150ms cap — faster turn finalization (was 250ms)
ENDPOINTING_ALPHA = 0.6  # EMA coefficient — more responsive to current speech (was 0.7)

# ── Preemptive generation ────────────────────────────────────────────────────
PREEMPTIVE_GENERATION = True
PREEMPTIVE_TTS = True  # start TTS as soon as LLM produces first tokens

# ── Interruption handling ────────────────────────────────────────────────────
INTERRUPTION_MIN_DURATION = (
    0.2  # 200ms minimum speech to register interruption (was 300ms)
)
BACKCHANNEL_BOUNDARY_START = (
    0.3  # suppress interruptions 300ms after agent starts (was 500ms)
)
BACKCHANNEL_BOUNDARY_END = (
    1.5  # suppress interruptions 1.5s before agent ends (was 2.0s)
)

# ── Language hysteresis (REAL — not fake) ─────────────────────────────────────
# Requires the same language across N consecutive *meaningful* turns before
# switching TTS websocket.  Short/filler transcripts are completely ignored.
LANG_SWITCH_MIN_CHARS = (
    15  # ignore language switch if transcript < 15 characters (was 5)
)
LANG_SWITCH_MIN_CONFIDENCE = 0.8  # reserved for future STT confidence field
LANG_SWITCH_CONSECUTIVE = 3  # require same language for 3 consecutive turns (was 2)

# ── Filler suppression ────────────────────────────────────────────────────────
# Utterances matching these patterns or shorter than FILLER_MIN_LENGTH are
# dropped entirely — no LLM generation, no TTS, no state transition.
FILLER_MIN_LENGTH = 4  # transcript shorter than this is always suppressed
FILLER_PATTERNS: set[str] = {
    "hmm",
    "umm",
    "uh",
    "ah",
    "eh",
    "oh",
    "er",
    "haan",
    "hmm hmm",
    "umm hmm",
    "okay",
    "ok",
    "hmm okay",
    "okay okay",
    "achha",
    "acha",
    "theek",
    "theek hai",
    "haan ji",
    "ji haan",
    "ji",
    "nahi",
    "nahin",
    "na",
    "kya",
    "kyaa",
    "huh",
    "huh?",
    "what?",
    "what",
}

# ── Transcript deduplication ─────────────────────────────────────────────────
DEDUP_WINDOW_SECONDS = 2.0  # ignore repeated final transcripts within this window
DEDUP_MAX_HISTORY = 20  # max recent transcript hashes to track

# ── Context management ───────────────────────────────────────────────────────
MAX_CONTEXT_ITEMS = 50  # total items before summarization + trimming kicks in
SLIDING_WINDOW_TURNS = 10  # number of most-recent turns kept verbatim

# ── TTS session management ───────────────────────────────────────────────────
# Persistent websockets: Sarvam ConnectionPool keeps websockets alive across
# turns.  We NEVER close them per-turn — only on confirmed language switch
# or process shutdown.
TTS_POOL_MAX_SESSION_DURATION = 3600  # 1 hour per websocket before rotation
TTS_CLOSE_DRAIN_TIMEOUT = 0.25  # seconds to drain in-flight writes before close

# Noisy environment — uncomment these and comment the above when background noise is present
# ENDPOINTING_MIN_DELAY = 0.3   # 300ms
# ENDPOINTING_MAX_DELAY = 0.6   # 600ms
# ENDPOINTING_ALPHA = 0.9
# BACKCHANNEL_BOUNDARY_START = 1.0
# BACKCHANNEL_BOUNDARY_END = 3.5
# LANG_SWITCH_MIN_CHARS = 25
# LANG_SWITCH_CONSECUTIVE = 4
