import asyncio
import logging
import time
from typing import Annotated
from contextvars import ContextVar

from livekit.agents.llm import function_tool
from langfuse import Langfuse

logger = logging.getLogger(__name__)

langfuse_client = Langfuse()
active_turn_span_var = ContextVar("active_turn_span", default=None)

def _get_tool_span(name, args):
    ctx = active_turn_span_var.get()
    if ctx:
        return langfuse_client.start_observation(
            name="tool-call",
            trace_context={"trace_id": ctx["trace_id"], "parent_span_id": ctx["span_id"]},
            metadata={"tool_name": name, "arguments": args}
        )
    return None

def _end_tool_span(span, start_time, success, error=None):
    if span:
        meta = {"duration_ms": (time.perf_counter() - start_time) * 1000, "success": success}
        if error:
            meta["error"] = error
        span.update(metadata=meta)
        span.end()


@function_tool
async def lookup_homework(
    student_name: Annotated[str, "Name of the student"],
    subject: Annotated[str, "Subject to look up homework for"],
) -> str:
    """Look up pending homework for a student in a given subject."""
    start = time.perf_counter()
    span = _get_tool_span("lookup_homework", {"student_name": student_name, "subject": subject})
    logger.info(f"Homework lookup: student={student_name}, subject={subject}")
    try:
        await asyncio.sleep(0.5)
        res = f"Homework for {student_name} in {subject}: Complete exercises 1-5 from Chapter 3. Due tomorrow."
        _end_tool_span(span, start, True)
        return res
    except Exception as e:
        _end_tool_span(span, start, False, str(e))
        raise


@function_tool
async def check_attendance(
    student_name: Annotated[str, "Name of the student"],
    date: Annotated[str, "Date in YYYY-MM-DD format"],
) -> str:
    """Check attendance record for a student on a given date."""
    start = time.perf_counter()
    span = _get_tool_span("check_attendance", {"student_name": student_name, "date": date})
    logger.info(f"Attendance check: student={student_name}, date={date}")
    try:
        await asyncio.sleep(0.3)
        res = f"{student_name} was present on {date}."
        _end_tool_span(span, start, True)
        return res
    except Exception as e:
        _end_tool_span(span, start, False, str(e))
        raise


@function_tool
async def get_school_timetable(
    grade: Annotated[str, "Grade/class (e.g., '8th', '10th')"],
) -> str:
    """Get the weekly timetable for a specific grade."""
    start = time.perf_counter()
    span = _get_tool_span("get_school_timetable", {"grade": grade})
    logger.info(f"Timetable request: grade={grade}")
    try:
        await asyncio.sleep(0.3)
        res = f"Timetable for Grade {grade}: Monday — Math, Science, English. Tuesday — Hindi, Social Studies, Math. Wednesday — Science, English, Computer Lab."
        _end_tool_span(span, start, True)
        return res
    except Exception as e:
        _end_tool_span(span, start, False, str(e))
        raise


@function_tool
async def search_knowledge_base(
    query: Annotated[str, "The question or topic to search for"],
) -> str:
    """Search the school knowledge base for educational content on a topic."""
    start = time.perf_counter()
    span = _get_tool_span("search_knowledge_base", {"query": query})
    logger.info(f"Knowledge search: {query}")
    try:
        await asyncio.sleep(1.0)
        res = f"Found information about '{query}': This topic is covered in Chapter 4 of the textbook. Key concepts include definitions, examples, and practice problems."
        _end_tool_span(span, start, True)
        return res
    except Exception as e:
        _end_tool_span(span, start, False, str(e))
        raise


@function_tool
async def explain_with_example(
    topic: Annotated[str, "Topic to explain"],
    language: Annotated[str, "Language to explain in (e.g., hi-IN, ta-IN)"],
) -> str:
    """Generate a simple, age-appropriate explanation of a topic with a real-world example."""
    start = time.perf_counter()
    span = _get_tool_span("explain_with_example", {"topic": topic, "language": language})
    logger.info(f"Explain request: topic={topic}, lang={language}")
    try:
        await asyncio.sleep(0.8)
        res = f"Let me explain '{topic}' with a simple example using everyday situations that students can relate to."
        _end_tool_span(span, start, True)
        return res
    except Exception as e:
        _end_tool_span(span, start, False, str(e))
        raise

