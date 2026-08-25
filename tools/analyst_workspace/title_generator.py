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
    _filler_words = {
        "a", "al", "analizar", "como", "cómo", "con", "compara", "comparar", "cuál", "cual",
        "de", "del", "el", "en", "es", "fue", "ha", "la", "las", "lo", "los", "me", "necesito",
        "evolucionado", "evolución", "para", "por", "puedes", "que", "qué", "quiero", "se", "un", "una", "y",
    }

    def generate(self, user_text: str, assistant_text: str) -> str | None:
        del assistant_text
        if not is_substantive_text(user_text):
            return None
        words = re.findall(r"[\wÁÉÍÓÚÜÑáéíóúüñ%.-]+", user_text or "", flags=re.UNICODE)
        meaningful = [word for word in words if word.casefold() not in self._filler_words]
        if not meaningful:
            return None
        if len(meaningful) < 3:
            meaningful.insert(0, "Análisis")
        else:
            meaningful[0] = meaningful[0][:1].upper() + meaningful[0][1:]
        return " ".join(meaningful[:7])


def is_substantive_text(text: str) -> bool:
    return bool((text or "").strip()) and not LightweightTitleGenerator._greeting.match(text or "")
