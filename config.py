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
TTS_MIN_BUFFER_SIZE = 50
TTS_MAX_CHUNK_LENGTH = 150
TTS_WS_MAX_RETRIES = 2  # stale WebSocket recovery attempts

# LLM
LLM_MODEL = "sarvam-30b"  # Sarvam model name (only used when provider is "sarvam")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "sarvam")  # "sarvam" or "openai"
OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL", "gpt-4o"
)  # OpenAI model (only used when provider is "openai")

# Turn detection
MIN_ENDPOINTING_DELAY = 0.07  # 70ms
MIN_SPEECH_DURATION = 0.05  # 50ms (enables fast barge-in)
MAX_CONTEXT_ITEMS = 50  # total items before summarization + trimming kicks in
SLIDING_WINDOW_TURNS = 10  # number of most-recent turns kept verbatim

# Noisy environment — uncomment these and comment the above when background noise is present
# MIN_ENDPOINTING_DELAY = 0.3   # 300ms
# MIN_SPEECH_DURATION = 0.15    # 150ms
