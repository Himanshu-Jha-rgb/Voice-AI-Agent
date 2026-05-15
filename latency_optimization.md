---
name: latency-optimization
description: "Latency optimization work done in May 2026 — persistent TTS sessions, language hysteresis, transcript dedup, preemptive generation, dynamic endpointing"
metadata: 
  node_type: memory
  type: project
  originSessionId: 46f28bb5-0004-45bd-b612-92e3123325c5
---

# Latency Optimization (May 2026)

Performed comprehensive latency optimization of the realtime voice pipeline. Key changes:

## Persistent TTS WebSocket sessions
- **Problem**: `_invalidate_tts()` was called on EVERY turn completion, destroying the `sarvam.TTS` instance (and its internal `ConnectionPool`), forcing a new WebSocket connection (300-600ms overhead per turn).
- **Fix**: Only invalidate the TTS instance when the language actually changes (confirmed by hysteresis). Sarvam TTS already pools WebSocket connections internally via `utils.ConnectionPool` (tts.py:468), so reuse is automatic when the instance survives.
- **Why**: WebSocket reconnect latency was the single largest contributor to per-turn latency.

## Language hysteresis
- **Problem**: Filler words ("hmm", partial syllables) triggered spurious language detection (bn-IN, ta-IN, pa-IN), causing TTS invalidation + WebSocket teardown + language thrashing.
- **Fix**: `LanguageTracker` class records each turn's detected language + transcript length. Only switches after N consecutive meaningful turns (min 5 chars, configurable via `LANG_SWITCH_MIN_CHARS` and `LANG_SWITCH_CONSECUTIVE`).
- **Why**: Prevents costly TTS reconnects from noise; stabilizes language across the conversation.

## Transcript deduplication
- **Problem**: Sarvam STT emits duplicate final transcripts for the same utterance, causing overlapping responses.
- **Fix**: `TranscriptDedup` class — hashes transcript text with MD5, ignores repeats within a sliding 2-second window (`DEDUP_WINDOW_SECONDS`). Removed the old `_final_seen_this_turn` flag + manual TTS interruption hack.
- **Why**: Cleaner than the old approach; prevents the race condition entirely at the event level.

## Preemptive generation with TTS
- **Enabled**: `PreemptiveGenerationOptions(preemptive_tts=True)` — LLM + TTS start preemptively before the turn is fully confirmed. Saves ~200-500ms per turn by overlapping compute with endpointing.
- **Why**: Reduces perceived latency because audio starts arriving sooner.

## Dynamic endpointing
- **Mode**: `"dynamic"` with `min_delay=0.07`, `max_delay=0.5`, `alpha=0.8`. The EMA-based algorithm adapts to the speaker's cadence — responsive pauses get short waits, longer thinking pauses get capped at 500ms.
- **Why**: Fixed endpointing can't adapt to different speaker patterns. Dynamic mode naturally handles Indian-language speech rhythms.

## Interruption tuning
- **`min_duration=0.3`** (down from 0.5 default) — faster barge-in detection.
- **`backchannel_boundary=(0.5, 2.0)`** (down from (1.0, 3.5)) — allows interruption sooner after agent starts speaking and leaves more room before agent ends.

## Logging optimization
- **`logger.setLevel(logging.INFO)`** (was DEBUG) — reduces hot-path overhead. Remaining debug logs in STT/TTS/transcript handlers won't be emitted at INFO level.

## Files changed
- `agent.py` — major refactor: `LanguageTracker`, `TranscriptDedup`, `MultilingualTTS` persistence, `SchoolVoiceAgent` hysteresis logic, `entrypoint` turn handling
- `config.py` — added 15 new config parameters, removed `MIN_ENDPOINTING_DELAY` and `MIN_SPEECH_DURATION`

## Target latency
- Endpointing: <200ms (down from 527-665ms)
- STT finalize: <150ms
- LLM TTFT: <700ms (down from 964-2184ms — helps by prewarming + preemptive gen)
- TTS TTFB: <250ms (down from 300-600ms — helps by persistent WebSocket pool)
- Total E2E: <1 second
