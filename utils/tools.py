import asyncio
import logging
from typing import Annotated

from livekit.agents.llm import function_tool

logger = logging.getLogger(__name__)


@function_tool
async def lookup_homework(
    student_name: Annotated[str, "Name of the student"],
    subject: Annotated[str, "Subject to look up homework for"],
) -> str:
    """Look up pending homework for a student in a given subject."""
    logger.info(f"Homework lookup: student={student_name}, subject={subject}")
    await asyncio.sleep(0.5)
    return f"Homework for {student_name} in {subject}: Complete exercises 1-5 from Chapter 3. Due tomorrow."


@function_tool
async def check_attendance(
    student_name: Annotated[str, "Name of the student"],
    date: Annotated[str, "Date in YYYY-MM-DD format"],
) -> str:
    """Check attendance record for a student on a given date."""
    logger.info(f"Attendance check: student={student_name}, date={date}")
    await asyncio.sleep(0.3)
    return f"{student_name} was present on {date}."


@function_tool
async def get_school_timetable(
    grade: Annotated[str, "Grade/class (e.g., '8th', '10th')"],
) -> str:
    """Get the weekly timetable for a specific grade."""
    logger.info(f"Timetable request: grade={grade}")
    await asyncio.sleep(0.3)
    return f"Timetable for Grade {grade}: Monday — Math, Science, English. Tuesday — Hindi, Social Studies, Math. Wednesday — Science, English, Computer Lab."


@function_tool
async def search_knowledge_base(
    query: Annotated[str, "The question or topic to search for"],
) -> str:
    """Search the school knowledge base for educational content on a topic."""
    logger.info(f"Knowledge search: {query}")
    await asyncio.sleep(1.0)
    return f"Found information about '{query}': This topic is covered in Chapter 4 of the textbook. Key concepts include definitions, examples, and practice problems."


@function_tool
async def explain_with_example(
    topic: Annotated[str, "Topic to explain"],
    language: Annotated[str, "Language to explain in (e.g., hi-IN, ta-IN)"],
) -> str:
    """Generate a simple, age-appropriate explanation of a topic with a real-world example."""
    logger.info(f"Explain request: topic={topic}, lang={language}")
    await asyncio.sleep(0.8)
    return f"Let me explain '{topic}' with a simple example using everyday situations that students can relate to."
