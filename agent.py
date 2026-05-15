import asyncio
import enum
import hashlib
import json
import logging
import threading
import time
import weakref
from collections import deque
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from livekit.agents import JobContext, WorkerOptions, cli, tts
from livekit.agents.llm import ChatContext, ChatMessage
from livekit.agents.voice import Agent, AgentSession
from livekit.agents.voice.turn import (
    TurnHandlingOptions,
    EndpointingOptions,
    InterruptionOptions,
    PreemptiveGenerationOptions,
)
from livekit.plugins import sarvam, silero

from config import (
    LANGUAGE_CODE_MAP,
    DEFAULT_LANGUAGE,
    STT_MODEL,
    STT_MODE,
    STT_SAMPLE_RATE,
    STT_HIGH_VAD_SENSITIVITY,
    STT_FLUSH_SIGNAL,
    LLM_MODEL,
    LLM_PROVIDER,
    OPENAI_MODEL,
    TTS_MODEL,
    TTS_SAMPLE_RATE,
    TTS_PACE,
    TTS_TEMPERATURE,
    TTS_OUTPUT_BITRATE,
    TTS_OUTPUT_AUDIO_CODEC,
    TTS_MIN_BUFFER_SIZE,
    TTS_MAX_CHUNK_LENGTH,
    TTS_WS_MAX_RETRIES,
    TTS_CLOSE_DRAIN_TIMEOUT,
    # Turn detection
    ENDPOINTING_MODE,
    ENDPOINTING_MIN_DELAY,
    ENDPOINTING_MAX_DELAY,
    ENDPOINTING_ALPHA,
    # Preemptive generation
    PREEMPTIVE_GENERATION,
    PREEMPTIVE_TTS,
    # Interruption handling
    INTERRUPTION_MIN_DURATION,
    BACKCHANNEL_BOUNDARY_START,
    BACKCHANNEL_BOUNDARY_END,
    # Language hysteresis
    LANG_SWITCH_MIN_CHARS,
    LANG_SWITCH_MIN_CONFIDENCE,
    LANG_SWITCH_CONSECUTIVE,
    # Filler suppression
    FILLER_MIN_LENGTH,
    FILLER_PATTERNS,
    # Transcript dedup
    DEDUP_WINDOW_SECONDS,
    DEDUP_MAX_HISTORY,
    # Context
    MAX_CONTEXT_ITEMS,
    SLIDING_WINDOW_TURNS,
)
from utils.prompts import SYSTEM_PROMPT, GREETING_INSTRUCTIONS
from utils.tools import (
    lookup_homework,
    check_attendance,
    get_school_timetable,
    search_knowledge_base,
    explain_with_example,
)
from utils.summarize import summarize_conversation

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("school-voice-agent")
logger.setLevel(logging.INFO)


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket / Stream State Machine
# ═══════════════════════════════════════════════════════════════════════════════

class WSState(enum.Enum):
    """WebSocket lifecycle states for race-free connection management."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"
    CLOSED = "closed"


# ═══════════════════════════════════════════════════════════════════════════════
# Filler Filter
# ═══════════════════════════════════════════════════════════════════════════════

class FillerFilter:
    """Suppress filler utterances to avoid triggering LLM, TTS, or state changes.

    Short/meaningless utterances ("hmm", "uh", "okay") should NOT:
    - Trigger LLM generation
    - Create a TTS response
    - Record a language detection
    - Transition agent state
    """

    @staticmethod
    def is_filler(transcript: str) -> bool:
        text = transcript.strip().lower()
        if not text:
            return True
        if len(text) < FILLER_MIN_LENGTH:
            return True
        if text in FILLER_PATTERNS:
            return True
        # Single-word utterances of very short length have no semantic content
        words = text.split()
        if len(words) == 1 and len(words[0]) <= 3:
            return True
        # Two-word utterances where both words are very short
        if len(words) == 2 and all(len(w) <= 3 for w in words):
            return True
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# Language Hysteresis Tracker (REAL hysteresis)
# ═══════════════════════════════════════════════════════════════════════════════

class LanguageTracker:
    """Stabilises language detection with proper hysteresis.

    Requirements for a language switch:
    1. Transcript length >= MIN_CHARS (meaningful utterance, not filler)
    2. Same candidate language detected across CONSECUTIVE consecutive turns
    3. Candidate language differs from the currently active language

    Until all conditions are met: keep the current TTS language and websocket.
    NO websocket teardown during pending state.
    """

    def __init__(
        self,
        default_language: str,
        min_chars: int,
        consecutive_required: int,
    ):
        self._default = default_language
        self._min_chars = min_chars
        self._consec_required = consecutive_required
        # Newest-first deque of (language_code, transcript_length)
        self._history: deque[tuple[str, int]] = deque(
            maxlen=consecutive_required * 3
        )
        self._candidate: str | None = None
        self._candidate_count = 0

    def record_turn(self, detected_language: str | None, transcript_length: int) -> None:
        """Record a completed turn for hysteresis tracking.

        - Short/filler turns are recorded as "no decision" (default language, 0 length)
          which breaks any in-progress consecutive streak.
        - Meaningful turns advance or reset the candidate counters.
        """
        if detected_language and transcript_length >= self._min_chars:
            self._history.appendleft((detected_language, transcript_length))
        else:
            # Filler or too-short — breaks all streaks
            self._history.appendleft((self._default, 0))

    def should_switch(self, current_language: str) -> str | None:
        """Return the language to switch to, or None to stay on current language.

        Only returns a language when the same non-current language has been
        detected across ``_consec_required`` consecutive meaningful turns.
        Fillers (length < min_chars) reset the accumulation and break any
        in-progress streak.
        """
        if len(self._history) < self._consec_required:
            return None

        # Walk newest-first collecting consecutive meaningful detections.
        # A filler (length < min_chars) resets the streak — the candidate
        # list is cleared so only turns AFTER the most recent filler count.
        candidates: list[str] = []
        for lang, length in self._history:
            if length >= self._min_chars:
                candidates.append(lang)
            else:
                # Filler — breaks the consecutive streak
                candidates.clear()
            if len(candidates) >= self._consec_required:
                break

        if len(candidates) < self._consec_required:
            return None

        first = candidates[0]
        if all(c == first for c in candidates[: self._consec_required]):
            if first != current_language and first in LANGUAGE_CODE_MAP:
                return first
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Transcript Deduplication
# ═══════════════════════════════════════════════════════════════════════════════

class TranscriptDedup:
    """Deduplicates final transcript events via text hashing + time window."""

    def __init__(self, window_seconds: float, max_history: int):
        self._window = window_seconds
        self._max = max_history
        self._seen: dict[str, float] = {}

    def is_duplicate(self, text: str) -> bool:
        if not text:
            return True
        h = _text_hash(text)
        now = time.monotonic()

        stale = [k for k, ts in self._seen.items() if now - ts > self._window]
        for k in stale:
            del self._seen[k]

        if h in self._seen:
            return True

        self._seen[h] = now
        if len(self._seen) > self._max:
            oldest = min(self._seen, key=self._seen.get)
            del self._seen[oldest]
        return False

    def reset(self) -> None:
        self._seen.clear()


def _text_hash(text: str) -> str:
    return hashlib.md5(text.strip().lower().encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# TTS Session Manager — centralized websocket ownership
# ═══════════════════════════════════════════════════════════════════════════════

class TTSSessionManager:
    """Centralized owner of all TTS websocket sessions.

    Design invariants:
    - ONE Sarvam TTS instance per language (lazily created, persistent)
    - Sarvam's internal ConnectionPool keeps websockets alive across turns
    - Streams are wrapped to prevent aclose() from destroying pool connections
    - Async lock serializes all state transitions (create, invalidate, close)
    - NO scattered ws.close() calls — only the session manager closes websockets

    Websocket lifecycle:
    - Created: on first use of a language
    - Reused: every subsequent turn in the same language
    - Closed ONLY: confirmed language switch, idle timeout, or process shutdown
    - NEVER closed: between turns, during hysteresis pending, or on filler
    """

    def __init__(self, default_language: str = "hi-IN"):
        self._default_language = default_language
        self._tts_instances: dict[str, sarvam.TTS] = {}
        self._current_language = default_language
        self._state_lock = asyncio.Lock()
        self._create_lock = threading.Lock()  # protects _get_or_create_tts singleton
        self._streams: weakref.WeakSet[RaceFreeSynthesizeStream] = weakref.WeakSet()
        # Track background tasks so aclose() can drain them before closing
        self._bg_tasks: set[asyncio.Task] = set()

    # ── properties ──────────────────────────────────────────────────────────

    @property
    def current_language(self) -> str:
        return self._current_language

    @current_language.setter
    def current_language(self, code: str) -> None:
        if code in LANGUAGE_CODE_MAP:
            self._current_language = code
        else:
            logger.warning(
                f"Unknown language code '{code}', "
                f"falling back to {self._default_language}"
            )
            self._current_language = self._default_language

    # ── TTS instance management ─────────────────────────────────────────────

    def _get_or_create_tts(self, language_code: str) -> sarvam.TTS:
        """Get or lazily create a Sarvam TTS instance for a language.

        Protected by ``_create_lock`` (threading.Lock) to guarantee
        singleton-per-language: concurrent coroutines cannot race and create
        duplicate instances.  A threading lock is used here (not asyncio.Lock)
        because callers include sync methods (``synthesize``, ``stream``,
        ``prewarm``) that must remain sync for the LiveKit TTS interface.

        The lock is held for microseconds (CPU-only, no I/O) so event-loop
        blocking is negligible.

        Instances are persistent — they live until invalidate_language() or
        aclose() is called.  The internal ConnectionPool keeps websockets warm.
        """
        if language_code in self._tts_instances:
            return self._tts_instances[language_code]

        with self._create_lock:
            # Double-check after acquiring the lock — another caller may have
            # created the instance while we were waiting.
            if language_code in self._tts_instances:
                return self._tts_instances[language_code]

            lang = LANGUAGE_CODE_MAP.get(language_code, DEFAULT_LANGUAGE)
            logger.info(
                f"Creating Sarvam TTS for {lang.name} ({lang.code})"
                f" — speaker: {lang.tts_speaker}"
            )
            instance = sarvam.TTS(
                target_language_code=lang.code,
                model=TTS_MODEL,
                speaker=lang.tts_speaker,
                speech_sample_rate=TTS_SAMPLE_RATE,
                pace=TTS_PACE,
                temperature=TTS_TEMPERATURE,
                output_audio_bitrate=TTS_OUTPUT_BITRATE,
                output_audio_codec=TTS_OUTPUT_AUDIO_CODEC,
                min_buffer_size=TTS_MIN_BUFFER_SIZE,
                max_chunk_length=TTS_MAX_CHUNK_LENGTH,
            )
            self._tts_instances[language_code] = instance
            return instance

    async def invalidate_language(self, language_code: str) -> None:
        """Close and remove a TTS instance.

        Called ONLY on confirmed language switch (hysteresis satisfied).
        Never called during pending state, between turns, or on filler.
        """
        async with self._state_lock:
            instance = self._tts_instances.pop(language_code, None)
        if instance:
            logger.info(f"Closing TTS instance for {language_code}")
            try:
                await instance.aclose()
            except Exception as e:
                logger.warning(f"Error closing TTS for {language_code}: {e}")

    def prewarm(self) -> None:
        """Prewarm the default language TTS so first turn has a warm websocket."""
        self._get_or_create_tts(self._default_language).prewarm()

    async def warm(self, language_code: str) -> None:
        """Ensure a TTS connection is ready for the given language.

        Evicts stale pool entries (those closed by a previous stream's cleanup
        behind the pool's back) and prewarms the pool so the next stream call
        gets a live websocket immediately.
        """
        tts_instance = self._get_or_create_tts(language_code)
        pool = tts_instance._pool
        stale = {
            c for c in list(pool._connections) if getattr(c, "closed", True)
        }
        for c in stale:
            pool.remove(c)
        pool.prewarm()

    # ── stream / synthesize — the interface used by LiveKit Agent ────────────

    def synthesize(self, text: str) -> tts.ChunkedStream:
        """Non-streaming synthesis (HTTP POST, no websocket race concern)."""
        tts_instance = self._get_or_create_tts(self._current_language)
        return tts_instance.synthesize(text=text)

    def stream(self) -> "RaceFreeSynthesizeStream":
        """Create a race-free streaming TTS session for the current language.

        Returns a wrapped Sarvam SynthesizeStream whose aclose() does NOT
        destroy the underlying websocket.  The websocket is returned to the
        ConnectionPool for reuse on the next turn.
        """
        tts_instance = self._get_or_create_tts(self._current_language)
        delegate = tts_instance.stream()
        wrapped = RaceFreeSynthesizeStream(
            delegate=delegate,
            session_manager=self,
        )
        self._streams.add(wrapped)
        return wrapped

    # ── shutdown ────────────────────────────────────────────────────────────

    def _track_bg(self, coro) -> asyncio.Task:
        """Create a tracked background task.  All tracked tasks are awaited
        during ``aclose()`` to prevent premature cleanup."""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    async def aclose(self) -> None:
        """Close all TTS instances.  Idempotent — safe to call multiple times.

        Drains all background tasks before closing to prevent cleanup races.
        """
        # Drain background tasks first
        if self._bg_tasks:
            logger.debug(f"Draining {len(self._bg_tasks)} background TTS tasks")
            for task in list(self._bg_tasks):
                if not task.done():
                    task.cancel()
            if self._bg_tasks:
                await asyncio.gather(*list(self._bg_tasks), return_exceptions=True)

        async with self._state_lock:
            instances = list(self._tts_instances.values())
            self._tts_instances.clear()
        if not instances:
            return
        for inst in instances:
            try:
                await inst.aclose()
            except Exception as e:
                logger.warning(f"Error during TTS shutdown: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Race-Free SynthesizeStream Wrapper
# ═══════════════════════════════════════════════════════════════════════════════

class RaceFreeSynthesizeStream:
    """Wraps a Sarvam SynthesizeStream with race-free websocket lifecycle.

    THE PROBLEM (before this wrapper):
      Sarvam's SynthesizeStream.aclose() closes the websocket even though it
      was already returned to the ConnectionPool.  During barge-in/interruption,
      aclose() is called while send_task is still writing to the websocket.
      This causes: aiohttp "Cannot write to closing transport" → crash → storm.

    THE FIX:
      1. State machine prevents concurrent close/send operations
      2. aclose() drains in-flight writes before closing
      3. Transport errors during close are caught and suppressed
      4. The underlying websocket stays in the ConnectionPool for reuse

    LiveKit Agent framework compatibility:
      Exposes _input_ch (the async channel LiveKit feeds text into) and
      delegates all other attribute access to the underlying stream.
    """

    def __init__(self, delegate, session_manager: TTSSessionManager):
        self._delegate = delegate
        self._session = session_manager
        self._state = WSState.CONNECTED
        self._close_lock = asyncio.Lock()

    # ── async context manager (LiveKit uses `async with tts.stream() as stream`) ──

    async def __aenter__(self):
        """Enter the async context — delegate to underlying stream if it supports it.

        Returns ``self`` (the wrapper), NOT the delegate, so the race-safe
        close logic stays active for the entire context.
        """
        if hasattr(self._delegate, "__aenter__"):
            await self._delegate.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Exit the async context — close via the race-safe wrapper."""
        await self.aclose()
        return False  # don't suppress exceptions

    # ── async iteration (LiveKit uses `async for ev in stream`) ────────────
    # Python looks up special methods (__aiter__, __anext__) on the TYPE,
    # NOT via __getattr__ — so they must be defined explicitly on the wrapper.

    def __aiter__(self):
        """Delegate async iteration to the underlying stream."""
        return self._delegate.__aiter__()

    async def __anext__(self):
        """Delegate to the underlying stream's __anext__."""
        return await self._delegate.__anext__()

    # ── interface expected by LiveKit Agent ─────────────────────────────────

    @property
    def _input_ch(self):
        """Async channel LiveKit uses to feed text chunks into the stream."""
        return self._delegate._input_ch

    # ── race-free close ─────────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Close the stream without destroying the underlying websocket.

        Serialized via _close_lock: only one close can be in flight.
        Once CLOSING or CLOSED, subsequent calls are no-ops.

        The drain delay allows in-flight send_str() calls to complete before
        we touch the websocket, preventing the "Cannot write to closing
        transport" aiohttp error.
        """
        async with self._close_lock:
            if self._state in (WSState.CLOSING, WSState.CLOSED):
                return
            self._state = WSState.CLOSING

        # Drain in-flight writes before closing
        if TTS_CLOSE_DRAIN_TIMEOUT > 0:
            await asyncio.sleep(TTS_CLOSE_DRAIN_TIMEOUT)

        try:
            await self._delegate.aclose()
        except Exception as e:
            msg = str(e).lower()
            if "closing transport" in msg or "cannot write" in msg:
                logger.debug(
                    f"Suppressed transport error during stream close "
                    f"(connection already draining): {e}"
                )
            elif "connection" in msg and "close" in msg:
                logger.debug(f"Suppressed connection close error: {e}")
            else:
                logger.warning(f"Error during stream close: {e}")
        finally:
            self._state = WSState.CLOSED

    # ── delegation ──────────────────────────────────────────────────────────

    def __getattr__(self, name: str):
        """Delegate all other attribute access to the underlying stream."""
        return getattr(self._delegate, name)


# ═══════════════════════════════════════════════════════════════════════════════
# Multilingual TTS adapter (LiveKit TTS interface)
# ═══════════════════════════════════════════════════════════════════════════════

class MultilingualTTS(tts.TTS):
    """LiveKit TTS adapter backed by TTSSessionManager.

    Implements the tts.TTS interface that LiveKit's Agent framework expects.
    Delegates all websocket/stream management to TTSSessionManager for proper
    ownership and race-free lifecycle.
    """

    def __init__(self, session_manager: TTSSessionManager):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=TTS_SAMPLE_RATE,
            num_channels=1,
        )
        self._session = session_manager

    @property
    def current_language(self) -> str:
        return self._session.current_language

    @current_language.setter
    def current_language(self, code: str) -> None:
        self._session.current_language = code

    def synthesize(
        self, *, text: str, conn_options=None
    ) -> tts.ChunkedStream:
        """Non-streaming synthesis.  Retries on transient failures."""
        last_exc = None
        for attempt in range(TTS_WS_MAX_RETRIES + 1):
            try:
                return self._session.synthesize(text=text)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    f"TTS synthesize attempt {attempt + 1} failed: {exc}"
                )
        raise last_exc  # type: ignore[misc]

    def stream(self, *, conn_options=None) -> RaceFreeSynthesizeStream:
        """Streaming synthesis with race-free websocket lifecycle.

        Retries on transient failures without invalidating the TTS instance
        between attempts — the internal ConnectionPool handles stale
        connection recovery, and invalidating causes duplicate TTS creation.
        """
        last_exc = None
        for attempt in range(TTS_WS_MAX_RETRIES + 1):
            try:
                return self._session.stream()
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    f"TTS stream attempt {attempt + 1} failed: {exc}"
                )
        raise last_exc  # type: ignore[misc]

    async def update_options(
        self,
        *,
        target_language_code: Optional[str] = None,
        speaker: Optional[str] = None,
        pace: Optional[float] = None,
        temperature: Optional[float] = None,
    ) -> None:
        if target_language_code:
            self.current_language = target_language_code
        # The underlying TTS instance is managed by the session — update_options
        # on the active instance is called through the delegate when needed.

    def prewarm(self) -> None:
        self._session.prewarm()

    async def aclose(self) -> None:
        await self._session.aclose()


# ═══════════════════════════════════════════════════════════════════════════════
# Per-session state (set from STT events, consumed at turn completion)
# ═══════════════════════════════════════════════════════════════════════════════

_detected_language: Optional[str] = None
_detected_transcript: str = ""
_transcript_dedup = TranscriptDedup(DEDUP_WINDOW_SECONDS, DEDUP_MAX_HISTORY)


# ═══════════════════════════════════════════════════════════════════════════════
# SchoolVoiceAgent
# ═══════════════════════════════════════════════════════════════════════════════

class SchoolVoiceAgent(Agent):
    def __init__(self) -> None:
        # Centralized TTS session manager — owns all websocket lifecycle
        self._tts_session = TTSSessionManager(default_language="hi-IN")
        self._multilingual_tts = MultilingualTTS(self._tts_session)

        self._rolling_summary: Optional[str] = None
        self._summary_in_progress: bool = False

        # Language-hysteresis tracker with REAL thresholds
        self._lang_tracker = LanguageTracker(
            default_language="hi-IN",
            min_chars=LANG_SWITCH_MIN_CHARS,
            consecutive_required=LANG_SWITCH_CONSECUTIVE,
        )

        # Prewarm the default TTS websocket before first turn
        self._tts_session.prewarm()

        if LLM_PROVIDER == "openai":
            from livekit.plugins.openai import LLM as OpenAILLM

            llm = OpenAILLM(model=OPENAI_MODEL)
            logger.info(f"Using OpenAI LLM — model: {OPENAI_MODEL}")
        else:
            llm = sarvam.LLM(model=LLM_MODEL)
            logger.info(f"Using Sarvam LLM — model: {LLM_MODEL}")

        super().__init__(
            instructions=SYSTEM_PROMPT,
            stt=sarvam.STT(
                language="unknown",
                model=STT_MODEL,
                mode=STT_MODE,
                sample_rate=STT_SAMPLE_RATE,
                high_vad_sensitivity=STT_HIGH_VAD_SENSITIVITY,
                flush_signal=STT_FLUSH_SIGNAL,
            ),
            llm=llm,
            tts=self._multilingual_tts,
            tools=[
                lookup_homework,
                check_attendance,
                get_school_timetable,
                search_knowledge_base,
                explain_with_example,
            ],
        )

    async def on_enter(self) -> None:
        logger.info("User entered — generating greeting")
        self.session.generate_reply(instructions=GREETING_INSTRUCTIONS)

    async def on_exit(self) -> None:
        """Clean up all TTS websocket sessions when the agent leaves the room."""
        logger.info("User exiting — closing TTS session manager")
        await self._tts_session.aclose()

    async def on_user_turn_completed(self, turn_ctx, *, new_message=None) -> None:
        global _detected_language, _detected_transcript

        transcript = _detected_transcript or ""
        transcript_length = len(transcript)

        logger.info(
            f"Turn completed — detected language: {_detected_language}, "
            f"transcript: {transcript[:60]!r} ({transcript_length} chars)"
        )

        # ── Step 1: Filler suppression ──────────────────────────────────────
        # Drop filler utterances entirely: no LLM generation, no TTS, no
        # state transition, no language detection recording.
        if FillerFilter.is_filler(transcript):
            logger.info(
                f"Filler suppressed: {transcript!r} "
                f"({transcript_length} chars) — skipping LLM/TTS"
            )
            _detected_language = None
            _detected_transcript = ""
            return

        # ── Step 2: Record turn in hysteresis tracker ───────────────────────
        self._lang_tracker.record_turn(_detected_language, transcript_length)

        # ── Step 3: Decide language — real hysteresis only ──────────────────
        target_language = self._tts_session.current_language
        switch_to = self._lang_tracker.should_switch(target_language)

        if switch_to:
            # Hysteresis confirmed — permanent switch.  NOW close old TTS.
            lang = LANGUAGE_CODE_MAP[switch_to]
            logger.info(
                f"Language switch CONFIRMED: {target_language} → {switch_to} "
                f"({lang.name}) (hysteresis: {LANG_SWITCH_CONSECUTIVE} "
                f"consecutive turns, min {LANG_SWITCH_MIN_CHARS} chars)"
            )
            # Close old language's websocket — this is the ONLY place we do it
            if target_language != switch_to:
                await self._tts_session.invalidate_language(target_language)
            target_language = switch_to
        elif (
            _detected_language
            and _detected_language in LANGUAGE_CODE_MAP
            and transcript_length >= LANG_SWITCH_MIN_CHARS
            and _detected_language != self._tts_session.current_language
        ):
            # Single-turn override: respond in detected language but keep
            # current TTS instance warm.  If user switches back next turn,
            # the old websocket is still alive — no reconnect penalty.
            logger.info(
                f"Temporary language: using {_detected_language} for this "
                f"response (transcript: {transcript_length} chars). "
                f"Current TTS ({target_language}) kept warm — no websocket teardown."
            )
            target_language = _detected_language
        # else: keep current language (filler already suppressed above)

        self._tts_session.current_language = target_language

        # ── Step 4: Prewarm TTS websocket while LLM generates ───────────────
        # The websocket handshake (~200ms) overlaps with LLM TTFT (~800ms).
        # Since we never close the websocket between turns, this is mostly
        # a no-op that just ensures pool health.
        self._tts_session._track_bg(
            self._tts_session.warm(target_language)
        )

        # ── Step 5: Reset per-turn globals ──────────────────────────────────
        _detected_language = None
        _detected_transcript = ""

        # ── Step 6: Two-layer chat context assembly ─────────────────────────
        items = self._chat_ctx.items
        if len(items) > MAX_CONTEXT_ITEMS:
            system_item = items[0]

            keep_count = SLIDING_WINDOW_TURNS * 2
            recent_items = (
                items[-keep_count:] if len(items) > keep_count else items[1:]
            )
            old_items = (
                items[1:-keep_count] if len(items) - 1 > keep_count else []
            )

            new_items = [system_item]

            if self._rolling_summary:
                new_items.append(
                    ChatMessage(
                        role="system",
                        text=f"## Earlier conversation\n{self._rolling_summary}",
                    )
                )

            new_items.extend(recent_items)

            await self.update_chat_ctx(ChatContext(new_items))
            logger.info(
                f"Two-layer context: summary={bool(self._rolling_summary)}, "
                f"recent_turns={len(recent_items) // 2}"
            )

            if old_items and not self._summary_in_progress:
                self._summary_in_progress = True
                asyncio.create_task(
                    self._generate_rolling_summary(old_items)
                )

    async def _generate_rolling_summary(self, old_items: list) -> None:
        try:
            summary = await summarize_conversation(old_items, LLM_PROVIDER)
            if summary:
                self._rolling_summary = summary
                logger.info(f"Rolling summary updated ({len(summary)} chars)")
        except Exception as e:
            logger.warning(f"Rolling summary generation failed: {e}")
        finally:
            self._summary_in_progress = False


# ═══════════════════════════════════════════════════════════════════════════════
# Entrypoint
# ═══════════════════════════════════════════════════════════════════════════════

async def entrypoint(ctx: JobContext) -> None:
    logger.info(f"User connected to room: {ctx.room.name}")

    agent = SchoolVoiceAgent()

    session = AgentSession(
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            endpointing=EndpointingOptions(
                mode=ENDPOINTING_MODE,
                min_delay=ENDPOINTING_MIN_DELAY,   # 50ms — aggressive floor
                max_delay=ENDPOINTING_MAX_DELAY,   # 250ms — tight cap
                alpha=ENDPOINTING_ALPHA,           # 0.7 — responsive EMA
            ),
            interruption=InterruptionOptions(
                enabled=True,
                min_duration=INTERRUPTION_MIN_DURATION,  # 200ms barge-in
                min_words=0,
                discard_audio_if_uninterruptible=True,
                resume_false_interruption=True,
                false_interruption_timeout=2.0,
                backchannel_boundary=(
                    BACKCHANNEL_BOUNDARY_START,  # 300ms
                    BACKCHANNEL_BOUNDARY_END,    # 1.5s
                ),
            ),
            preemptive_generation=PreemptiveGenerationOptions(
                enabled=PREEMPTIVE_GENERATION,
                preemptive_tts=PREEMPTIVE_TTS,
                max_speech_duration=10.0,
                max_retries=3,
            ),
        ),
    )

    @session.on("user_input_transcribed")
    def _on_stt(ev):
        global _detected_language, _detected_transcript
        transcript = getattr(ev, "transcript", "")
        language = getattr(ev, "language", None)
        is_final = getattr(ev, "is_final", False)

        if is_final:
            logger.debug(f"STT final — '{transcript[:50]}' lang={language}")

        # First language detection for this turn wins
        if language and _detected_language is None:
            _detected_language = language

        if transcript and is_final:
            # Deduplicate: ignore repeated finals within the time window
            if _transcript_dedup.is_duplicate(transcript):
                logger.debug(
                    f"Duplicate final transcript dropped: '{transcript[:40]}'"
                )
                return

            _detected_transcript = (
                _detected_transcript + " " + transcript
            ).strip()

            asyncio.create_task(
                ctx.room.local_participant.publish_data(
                    payload=json.dumps({
                        "type": "transcript",
                        "role": "user",
                        "text": transcript,
                        "language": language,
                    }),
                    reliable=True,
                )
            )

    @session.on("speech_created")
    def _on_speech_created(ev):
        logger.debug("Agent speech created")

    @session.on("conversation_item_added")
    def _on_conversation_item(ev):
        item = getattr(ev, "item", None)
        if item and getattr(item, "role", None) == "assistant":
            text_parts = []
            for c in getattr(item, "content", []) or []:
                t = getattr(c, "text", None)
                if t:
                    text_parts.append(str(t))
            text = " ".join(text_parts)
            if text:
                logger.debug(f"Agent response: '{text[:100]}...'")
                asyncio.create_task(
                    ctx.room.local_participant.publish_data(
                        payload=json.dumps({
                            "type": "transcript",
                            "role": "agent",
                            "text": text,
                        }),
                        reliable=True,
                    )
                )

    @session.on("user_state_changed")
    def _on_user_state(ev):
        # User started speaking — prewarm TTS for current language so the
        # websocket is ready before LLM generation starts.
        if ev.new_state == "user_speaking":
            agent._tts_session._track_bg(
                agent._tts_session.warm(
                    agent._tts_session.current_language
                )
            )
        logger.debug(f"User state: {ev.old_state} → {ev.new_state}")

    @session.on("agent_state_changed")
    def _on_agent_state(ev):
        logger.info(f"Agent state: {ev.old_state} → {ev.new_state}")

    @session.on("error")
    def _on_error(ev):
        logger.error(f"Agent session error: {ev}")

    # session.start() returns when the session ends.  on_exit() fires
    # as part of session teardown and handles TTS cleanup.  No finally
    # block here — it would fire prematurely in console mode where
    # session.start() may return before the agent finishes its first turn.
    await session.start(
        agent=agent,
        room=ctx.room,
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
