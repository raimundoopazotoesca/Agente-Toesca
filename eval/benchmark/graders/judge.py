"""Rubric judge v1.

Complements the deterministic graders; never overrides them. The judge is
only ever asked about the 7 dimensions and 3 gates (F1, C4, C5) that
graders/deterministic.py and graders/gates.py explicitly leave unscored /
undecided (triggered=None) -- see rubric.yaml's header comment. Everything
F2/F3/F4/F5/C1/C2/C3 already settled is handed to the judge as a *result*,
never as an open question, so it has no way to relitigate it.

Failure handling: if the judge's output is missing, malformed, or fails
schema validation after a bounded number of retries, the affected
dimensions/gates come back `judge_failed=True` with no score -- never a
default score, never a silent pass. A grader that can't get a valid
verdict must say so, not guess.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import jsonschema
import yaml

from eval.benchmark.graders.judge_input import JudgeInput

RUBRIC_PATH = Path(__file__).resolve().parent / "rubric.yaml"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "judge_output.schema.json"

DIMENSION_NAMES = [
    "analytical_quality",
    "grounding",
    "hallucination",
    "clarification_judgment",
    "investigation_quality",
    "output_usefulness",
    "tool_correctness",
]
GATE_NAMES = ["F1_fabrication", "C4_unsupported_causality", "C5_forbidden_claim"]

MAX_JUDGE_ATTEMPTS = 3
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


@lru_cache(maxsize=1)
def load_rubric() -> dict[str, Any]:
    return yaml.safe_load(RUBRIC_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_output_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def classify_response(turn, infra_error: str | None) -> str:
    """Deterministic pre-classification, decided before the judge ever
    runs -- these are structural facts (an exception was raised; the text
    is empty), not matters of judgment.

    'infra_failure': excluded from every capability denominator downstream.
    'model_non_answer': counts against capability (see design brief) but is
    NOT the same as a legitimate clarification -- that distinction (was a
    non-empty clarifying question the right call?) is judge territory,
    reported as `response_mode` inside the judge's own output.
    """
    if infra_error:
        return "infra_failure"
    if turn is None or not (turn.text or "").strip():
        return "model_non_answer"
    return "attempted"


def _render_rubric_text(rubric: dict[str, Any]) -> str:
    lines = []
    for name, spec in rubric["dimensions"].items():
        lines.append(f"### {name}")
        lines.append(spec["question"].strip())
        for score in range(5):
            lines.append(f"  {score}: {spec['anchors'][score]}")
        lines.append("")
    lines.append("## Gates (report as triggered/not-triggered, not 0-4 scores)")
    for name, spec in rubric["gates"].items():
        lines.append(f"### {name}")
        lines.append(f"Definition: {spec['definition'].strip()}")
        not_key = next(k for k in spec if k.startswith("explicitly_not"))
        lines.append(f"NOT this gate: {spec[not_key].strip()}")
        lines.append(f"Test: {spec['trigger_test'].strip()}")
        lines.append("")
    return "\n".join(lines)


_SYSTEM_PROMPT = """\
Eres un juez tecnico evaluando la respuesta de un sistema de analisis inmobiliario \
contra una rubrica explicita. No sabes que sistema, modelo o proveedor genero la \
respuesta -- evaluas solo lo que se te entrega: la pregunta, el comportamiento \
esperado, las restricciones del caso, el ground truth ya calculado, la respuesta, \
y el SQL que realmente se ejecuto (con sus resultados cuando estan disponibles).

Reglas estrictas:
- No reevalues nada que ya este decidido en `deterministic_grader_results` (gates \
F2/F3/F4/F5/C1/C2/C3, dimension_scores ya presentes). Esos son autoridad; tu trabajo \
es solo lo que falta.
- Si una dimension no aplica genuinamente a este caso, marca not_applicable=true y \
no inventes un score.
- Cada score debe venir con evidencia CONCRETA (una cita literal de la respuesta o \
de los resultados de query), no una justificacion generica.
- F1 (fabrication) es SOLO para afirmaciones sin ningun sustento en las queries \
ejecutadas o el ground truth -- un numero incorrecto que si vino de una query real \
NO es F1 (eso ya esta cubierto por C1/C2, no lo toques).
- C4 (causalidad no sustentada) NO se dispara si la respuesta presenta la causa \
explicitamente como hipotesis no confirmada.
- C5 (forbidden claim) se evalua literalmente contra cada claim listado en \
forbidden_claims, no contra tu propio juicio de que esta mal.
- response_mode: "answered" si intento responder sustantivamente; "clarified" si \
pidio una aclaracion en vez de responder; "declined" si declaro explicitamente que \
no podia/debia responder sin pedir aclaracion.
- Responde EXCLUSIVAMENTE con el JSON solicitado. Sin texto antes o despues, sin \
markdown fences.

RUBRICA:
{rubric_text}
"""


def build_prompt(judge_input: JudgeInput, rubric: dict[str, Any] | None = None) -> list[dict[str, str]]:
    rubric = rubric or load_rubric()
    system = _SYSTEM_PROMPT.format(rubric_text=_render_rubric_text(rubric))
    user = (
        "Evalua la siguiente respuesta contra el caso. Devuelve solo el JSON.\n\n"
        + json.dumps(judge_input.to_prompt_dict(), ensure_ascii=False, indent=2, default=str)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


@dataclass
class JudgeResult:
    response_mode: str | None = None
    dimension_scores: dict[str, int] = field(default_factory=dict)
    dimension_details: dict[str, dict[str, Any]] = field(default_factory=dict)
    not_applicable: set[str] = field(default_factory=set)
    gates: dict[str, dict[str, Any]] = field(default_factory=dict)
    judge_failed: bool = False
    failure_detail: str | None = None
    raw_output: dict[str, Any] | None = None
    attempts: int = 0


def _unscored_result(detail: str, attempts: int) -> JudgeResult:
    return JudgeResult(judge_failed=True, failure_detail=detail, attempts=attempts)


def _validate_and_parse(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    match = _JSON_BLOCK_RE.search(text or "")
    if not match:
        raise ValueError("no JSON object found in judge output")
    payload = json.loads(match.group(0))
    jsonschema.validate(payload, schema)
    for dim in DIMENSION_NAMES:
        d = payload["dimensions"][dim]
        if not d.get("not_applicable") and ("score" not in d or "justification" not in d or "evidence" not in d):
            raise ValueError(f"dimension {dim}: score/justification/evidence required when not_applicable=false")
    for gate in GATE_NAMES:
        g = payload["gates"][gate]
        if g.get("triggered") and ("justification" not in g or "evidence" not in g):
            raise ValueError(f"gate {gate}: justification/evidence required when triggered=true")
    return payload


def _to_judge_result(payload: dict[str, Any], attempts: int) -> JudgeResult:
    result = JudgeResult(response_mode=payload["response_mode"], raw_output=payload, attempts=attempts)
    for dim in DIMENSION_NAMES:
        d = payload["dimensions"][dim]
        if d.get("not_applicable"):
            result.not_applicable.add(dim)
        else:
            result.dimension_scores[dim] = d["score"]
        result.dimension_details[dim] = d
    result.gates = payload["gates"]
    return result


def run_judge(
    judge_input: JudgeInput,
    chat_fn: Callable[..., Any],
    model: str,
    rubric: dict[str, Any] | None = None,
    max_attempts: int = MAX_JUDGE_ATTEMPTS,
) -> JudgeResult:
    """`chat_fn(model=..., messages=...) -> response` with an OpenAI-shaped
    `.choices[0].message.content`. Bounded retries on invalid output; never
    converts a persistent failure into a score. Retries are separate,
    independent calls (not a growing conversation), each seeing the same
    prompt plus, on retry, the specific validation error from the last
    attempt appended -- so the model gets one concrete chance to self-correct
    per attempt instead of repeating the same mistake blind.
    """
    schema = load_output_schema()
    messages = build_prompt(judge_input, rubric)
    last_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        attempt_messages = list(messages)
        if last_error:
            attempt_messages.append(
                {
                    "role": "user",
                    "content": f"Tu respuesta anterior era invalida: {last_error}\nCorrige y responde solo con el JSON valido.",
                }
            )
        try:
            response = chat_fn(model=model, messages=attempt_messages, temperature=0.0)
            content = response.choices[0].message.content
            payload = _validate_and_parse(content, schema)
            return _to_judge_result(payload, attempt)
        except Exception as exc:  # noqa: BLE001 -- any failure here is a retry/unscore signal, not a crash
            last_error = f"{type(exc).__name__}: {exc}"

    return _unscored_result(f"invalid judge output after {max_attempts} attempts: {last_error}", max_attempts)
