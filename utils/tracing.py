"""Langfuse tracing for the Voice AI Agent.

Uses Langfuse v4.x API (``start_observation`` / ``create_event`` with
``TraceContext``).  Gracefully degrades if LANGFUSE_PUBLIC_KEY /
LANGFUSE_SECRET_KEY are not set — all methods become safe no-ops.
"""

import logging
import os
from typing import Any

from langfuse import Langfuse
from langfuse.types import TraceContext

logger = logging.getLogger(__name__)

_langfuse: Langfuse | None = None


def get_langfuse() -> Langfuse:
    """Return the global Langfuse client, creating it on first call.

    When credentials are missing the client is created with
    ``tracing_enabled=False`` so every call is a safe no-op.
    """
    global _langfuse
    if _langfuse is not None:
        return _langfuse

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        logger.warning("Langfuse credentials not configured — tracing disabled")
        _langfuse = Langfuse(
            public_key="pk-placeholder",
            secret_key="sk-placeholder",
            base_url=host,
            tracing_enabled=False,
        )
    else:
        _langfuse = Langfuse(
            public_key=public_key, secret_key=secret_key, base_url=host
        )
        logger.info("Langfuse tracing enabled — host: %s", host)

    return _langfuse


class SessionTracer:
    """Wraps a single Langfuse trace for one agent session (room connection).

    Creates a deterministic trace id from the room + participant so
    reconnecting the same user produces the same trace.  All methods are
    fire-and-forget — they never raise and add negligible latency.
    """

    def __init__(self, room_name: str, participant_id: str) -> None:
        self.room_name = room_name
        self.participant_id = participant_id

        lf = get_langfuse()
        self._lf = lf
        self.trace_id = lf.create_trace_id(
            seed=f"voice-agent-{room_name}-{participant_id}"
        )
        self._ctx = TraceContext(
            trace_id=self.trace_id,
            session_id=f"{room_name}-{participant_id}",
            user_id=participant_id,
        )

        # Bootstrap the trace with a session-start event so the trace
        # appears in Langfuse even if no other events are logged.
        lf.create_event(
            trace_context=self._ctx,
            name="session.start",
            metadata={"room": room_name},
        )

    def span(self, name: str, **kwargs: Any) -> Any:
        """Start a span observation.  Call ``.end()`` on the returned span."""
        return self._lf.start_observation(
            trace_context=self._ctx,
            name=name,
            as_type="span",
            **kwargs,
        )

    def log_stt(self, transcript: str, language: str | None, is_final: bool) -> None:
        self._lf.create_event(
            trace_context=self._ctx,
            name="stt.transcript",
            input={"transcript": transcript},
            metadata={"language": language or "unknown", "is_final": is_final},
        )

    def log_llm_output(self, text: str) -> None:
        self._lf.create_event(
            trace_context=self._ctx,
            name="llm.output",
            output={"text": text[:1000]},
        )

    def log_tool_call(
        self, name: str, args: dict | None, result: str
    ) -> None:
        self._lf.create_event(
            trace_context=self._ctx,
            name="tool.call",
            input={"function": name, "arguments": args or {}},
            output={"result": result[:500]},
        )

    def log_error(self, stage: str, error: str) -> None:
        self._lf.create_event(
            trace_context=self._ctx,
            name="error",
            level="ERROR",
            metadata={"stage": stage, "error": error[:1000]},
        )

    def flush(self) -> None:
        self._lf.flush()


_current_tracer: SessionTracer | None = None


def set_current_tracer(tracer: SessionTracer | None) -> None:
    global _current_tracer
    _current_tracer = tracer


def get_current_tracer() -> SessionTracer | None:
    return _current_tracer
