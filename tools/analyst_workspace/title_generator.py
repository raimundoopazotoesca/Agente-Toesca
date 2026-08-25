"""Small, non-analytical conversation-title capability."""
from __future__ import annotations

import re
from typing import Protocol


class TitleGenerator(Protocol):
    def generate(self, user_text: str, assistant_text: str) -> str | None: ...


class LightweightTitleGenerator:
    """Creates a bounded title locally; it never invokes the Analyst runtime."""

    _greeting = re.compile(
        r"^\s*(hola|buenas|buenos\s+(d[ií]as|tardes|noches)|c[oó]mo\s+est[aá]s|hey)\s*[!.?,]*\s*(necesito\s+ayuda)?\s*[!.?]*\s*$",
        re.IGNORECASE,
    )

    def generate(self, user_text: str, assistant_text: str) -> str | None:
        del assistant_text
        if not is_substantive_text(user_text):
            return None
        words = (user_text or "").strip().split()
        if not words:
            return None
        title = " ".join(words[:7])
        return title + "…" if len(words) > 7 else title


def is_substantive_text(text: str) -> bool:
    return bool((text or "").strip()) and not LightweightTitleGenerator._greeting.match(text or "")
