import asyncio
import json
import logging
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from livekit.agents import JobContext, WorkerOptions, cli, tts
from livekit.agents.llm import ChatContext, ChatMessage
from livekit.agents.voice import Agent, AgentSession
from livekit.agents.voice.turn import TurnHandlingOptions, EndpointingOptions
from livekit.plugins import sarvam, silero

from config import (
    LANGUAGE_CODE_MAP,
    DEFAULT_LANGUAGE,
    STT_MODEL,
    STT_MODE,
    STT_SAMPLE_RATE,
    LLM_MODEL,
    LLM_PROVIDER,
    OPENAI_MODEL,
    STT_HIGH_VAD_SENSITIVITY,
    STT_FLUSH_SIGNAL,
    TTS_MODEL,
    TTS_SAMPLE_RATE,
    TTS_PACE,
    TTS_TEMPERATURE,
    TTS_OUTPUT_BITRATE,
    TTS_OUTPUT_AUDIO_CODEC,
    TTS_MIN_BUFFER_SIZE,
    TTS_MAX_CHUNK_LENGTH,
    TTS_WS_MAX_RETRIES,
    MIN_ENDPOINTING_DELAY,
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
logger.setLevel(logging.DEBUG)


class MultilingualTTS(tts.TTS):
    """Routes synthesis to the correct Sarvam TTS instance per language.

    Maintains a lazily-initialized pool — one Sarvam TTS per Indian language.
    Set ``current_language`` to the BCP-47 code before synthesis and the
    wrapper delegates to the matching instance with the right voice.
    """

    def __init__(self, default_language_code: str = "hi-IN"):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=TTS_SAMPLE_RATE,
            num_channels=1,
        )
        self._default_language = default_language_code
        self._tts_instances: dict[str, sarvam.TTS] = {}
        self._current_language: str = default_language_code
        self._lock = asyncio.Lock()

    @property
    def current_language(self) -> str:
        return self._current_language

    @current_language.setter
    def current_language(self, code: str) -> None:
        if code in LANGUAGE_CODE_MAP:
            self._current_language = code
        else:
            logger.warning(f"Unknown language code '{code}', falling back to {self._default_language}")
            self._current_language = self._default_language

    def _get_or_create_tts(self, language_code: str) -> sarvam.TTS:
        if language_code not in self._tts_instances:
            lang = LANGUAGE_CODE_MAP.get(language_code, DEFAULT_LANGUAGE)
            logger.info(f"Creating Sarvam TTS for {lang.name} ({lang.code}) — speaker: {lang.tts_speaker}")
            self._tts_instances[language_code] = sarvam.TTS(
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
        return self._tts_instances[language_code]

    async def _invalidate_tts(self, language_code: str) -> None:
        """Close and remove a stale TTS instance so the next call creates a fresh one."""
        async with self._lock:
            instance = self._tts_instances.pop(language_code, None)
        if instance:
            logger.warning(f"Invalidating stale TTS instance for {language_code}")
            await instance.aclose()

    async def synthesize(self, *, text: str, conn_options=None) -> tts.ChunkedStream:
        last_exc = None
        for attempt in range(TTS_WS_MAX_RETRIES + 1):
            tts_instance = self._get_or_create_tts(self._current_language)
            try:
                return await tts_instance.synthesize(text=text, conn_options=conn_options)
            except Exception as exc:
                last_exc = exc
                logger.warning(f"TTS synthesize attempt {attempt + 1} failed: {exc}")
                await self._invalidate_tts(self._current_language)
        raise last_exc  # type: ignore[misc]

    def stream(self, *, conn_options=None) -> tts.SynthesizeStream:
        last_exc = None
        for attempt in range(TTS_WS_MAX_RETRIES + 1):
            tts_instance = self._get_or_create_tts(self._current_language)
            try:
                return tts_instance.stream(conn_options=conn_options)
            except Exception as exc:
                last_exc = exc
                logger.warning(f"TTS stream attempt {attempt + 1} failed: {exc}")
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._invalidate_tts(self._current_language))
                except RuntimeError:
                    self._tts_instances.pop(self._current_language, None)
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
        async with self._lock:
            tts_instance = self._get_or_create_tts(self._current_language)
            kwargs: dict = {}
            if target_language_code:
                kwargs["target_language_code"] = target_language_code
            if speaker:
                kwargs["speaker"] = speaker
            if pace is not None:
                kwargs["pace"] = pace
            if temperature is not None:
                kwargs["temperature"] = temperature
            if kwargs:
                await tts_instance.update_options(**kwargs)

    def prewarm(self) -> None:
        default_tts = self._get_or_create_tts(self._default_language)
        default_tts.prewarm()

    async def aclose(self) -> None:
        for instance in self._tts_instances.values():
            await instance.aclose()
        self._tts_instances.clear()


# Per-session storage for the last detected language (set from STT events)
_detected_language: Optional[str] = None
# Flag to detect multiple final transcripts in a single turn (VAD splitting)
_final_seen_this_turn: bool = False


class SchoolVoiceAgent(Agent):
    def __init__(self) -> None:
        self._multilingual_tts = MultilingualTTS(default_language_code="hi-IN")
        self._rolling_summary: Optional[str] = None
        self._summary_in_progress: bool = False

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

    async def on_user_turn_completed(self, turn_ctx, *, new_message=None) -> None:
        global _detected_language, _final_seen_this_turn
        logger.info(f"Turn completed — detected language: {_detected_language}")

        # Determine the target language for the next response
        target_language = self._multilingual_tts.current_language
        if _detected_language and _detected_language in LANGUAGE_CODE_MAP:
            target_language = _detected_language
            if _detected_language != self._multilingual_tts.current_language:
                lang = LANGUAGE_CODE_MAP[_detected_language]
                logger.info(f"Language switch: {self._multilingual_tts.current_language} → {_detected_language} ({lang.name})")

        # Reset per-turn globals
        _detected_language = None
        _final_seen_this_turn = False

        # Invalidate the old TTS instance so its stale WebSocket stops producing audio
        old_language = self._multilingual_tts.current_language
        await self._multilingual_tts._invalidate_tts(old_language)
        self._multilingual_tts.current_language = target_language

        # Two-layer chat context assembly
        items = self._chat_ctx.items
        if len(items) > MAX_CONTEXT_ITEMS:
            system_item = items[0]

            # Keep the last SLIDING_WINDOW_TURNS user+assistant pairs verbatim
            keep_count = SLIDING_WINDOW_TURNS * 2
            recent_items = items[-keep_count:] if len(items) > keep_count else items[1:]
            old_items = items[1:-keep_count] if len(items) - 1 > keep_count else []

            new_items = [system_item]

            # Layer 1: Rolling summary (compressed older conversation)
            if self._rolling_summary:
                new_items.append(
                    ChatMessage(role="system", text=f"## Earlier conversation\n{self._rolling_summary}")
                )

            # Layer 2: Recent turns verbatim (sliding window)
            new_items.extend(recent_items)

            await self.update_chat_ctx(ChatContext(new_items))
            logger.info(
                f"Two-layer context: summary={bool(self._rolling_summary)}, "
                f"recent_turns={len(recent_items) // 2}"
            )

            # Kick off async summarization of the dropped items
            if old_items and not self._summary_in_progress:
                self._summary_in_progress = True
                asyncio.create_task(self._generate_rolling_summary(old_items))

    async def _generate_rolling_summary(self, old_items: list) -> None:
        """Asynchronously produce a summary of dropped context items."""
        try:
            summary = await summarize_conversation(old_items, LLM_PROVIDER)
            if summary:
                self._rolling_summary = summary
                logger.info(f"Rolling summary updated ({len(summary)} chars)")
        except Exception as e:
            logger.warning(f"Rolling summary generation failed: {e}")
        finally:
            self._summary_in_progress = False


async def entrypoint(ctx: JobContext) -> None:
    logger.info(f"User connected to room: {ctx.room.name}")

    agent = SchoolVoiceAgent()

    session = AgentSession(
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            endpointing=EndpointingOptions(min_delay=MIN_ENDPOINTING_DELAY),
        ),
    )

    @session.on("user_input_transcribed")
    def _on_stt(ev):
        global _detected_language, _final_seen_this_turn
        transcript = getattr(ev, "transcript", "")
        language = getattr(ev, "language", None)
        is_final = getattr(ev, "is_final", False)

        logger.debug(f"STT event — transcript: '{transcript}', language: {language}, is_final: {is_final}")

        # Store language for TTS switching (only first detection per turn wins)
        global _detected_language
        if language and _detected_language is None:
            _detected_language = language

        # Send transcript to frontend
        if transcript and is_final:
            # If the VAD split a single user utterance into multiple final
            # transcripts, each triggers its own LLM response + TTS — two AI
            # voices play simultaneously.  Interrupt the in-progress TTS so
            # only the latest response reaches the user's ear.
            if _final_seen_this_turn:
                logger.warning(
                    "Multiple final transcripts in one turn — interrupting TTS "
                    "to prevent overlapping voices"
                )
                tts = agent._multilingual_tts
                asyncio.create_task(tts._invalidate_tts(tts.current_language))
            _final_seen_this_turn = True

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
        logger.info("Agent speech created")

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
                logger.info(f"Agent response: '{text[:100]}...'")
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
        logger.info(f"User state changed: {ev.old_state} → {ev.new_state}")

    @session.on("agent_state_changed")
    def _on_agent_state(ev):
        logger.info(f"Agent state changed: {ev.old_state} → {ev.new_state}")

    @session.on("error")
    def _on_error(ev):
        logger.error(f"Agent session error: {ev}")

    await session.start(
        agent=agent,
        room=ctx.room,
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
