import logging
import os
from typing import Optional

logger = logging.getLogger("school-voice-agent")

_SUMMARIZATION_PROMPT = (
    "Summarise the following conversation turns in 2-3 sentences. "
    "Keep every important fact: the user's role (student/parent/teacher), "
    "grade/class, board, subject, topic being discussed, problems solved, "
    "and any personal details the user shared. "
    "This summary will be fed back to the AI so it remembers the full context."
)


def _format_items_as_text(items: list) -> str:
    """Convert a list of ChatMessage items to flat text for summarization."""
    lines = []
    for item in items:
        role = getattr(item, "role", "unknown")
        text = ""
        content = getattr(item, "content", None)
        if isinstance(content, list):
            for part in content:
                t = getattr(part, "text", None)
                if t:
                    text += str(t) + " "
        elif isinstance(content, str):
            text = content
        else:
            text = str(getattr(item, "text", "") or "")
        text = text.strip()
        if text:
            label = {"user": "User", "assistant": "Assistant", "system": "Context"}.get(role, "Context")
            lines.append(f"{label}: {text[:200]}")
    return "\n".join(lines)


async def summarize_conversation(items: list, llm_provider: str = "sarvam") -> Optional[str]:
    """Produce a 2-3 sentence summary of older conversation items.

    Returns ``None`` if summarization fails or isn't available — the caller
    should gracefully degrade to the sliding-window-only fallback.
    """
    text = _format_items_as_text(items)
    if not text.strip():
        return None

    logger.info(f"Generating rolling summary from {len(items)} items ({len(text)} chars)")

    try:
        if llm_provider == "openai":
            return await _summarize_openai(text)
        else:
            return await _summarize_sarvam(text)
    except Exception as e:
        logger.warning(f"Rolling summary failed: {e}")
        return None


async def _summarize_openai(text: str) -> Optional[str]:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.warning("openai package not available for summarization")
        return None

    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _SUMMARIZATION_PROMPT},
            {"role": "user", "content": text},
        ],
        max_tokens=300,
        temperature=0.3,
    )
    summary = response.choices[0].message.content
    logger.debug(f"OpenAI summary ({len(summary)} chars): {summary[:120]}...")
    return summary


async def _summarize_sarvam(text: str) -> Optional[str]:
    """Use Sarvam AI's chat API for summarization."""
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        logger.warning("SARVAM_API_KEY not set — cannot use Sarvam for summarization")
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.sarvam.ai/chat/completions",
                headers={
                    "API-Key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "model": "sarvam-30b",
                    "messages": [
                        {"role": "system", "content": _SUMMARIZATION_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    "max_tokens": 300,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            summary = data["choices"][0]["message"]["content"]
            logger.debug(f"Sarvam summary ({len(summary)} chars): {summary[:120]}...")
            return summary
    except ImportError:
        logger.warning("httpx not available — cannot call Sarvam API for summarization")
        return None
    except Exception as e:
        logger.warning(f"Sarvam summarization failed: {e}")
        return None
