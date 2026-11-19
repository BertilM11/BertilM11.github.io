"""Integración con OpenAI: análisis de fotografías (Responses API + visión) y
generación de imágenes. Formatos de petición verificados contra el SDK oficial
`openai` (ver requirements.txt): `client.responses.create(model, instructions,
input=[{role, content:[input_text, input_image]}], text={"format": json_schema})`
y `client.images.generate(model, prompt, size)` -> `data[0].b64_json`.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .config import Settings

VISUAL_KINDS = ("graphviz", "svg", "plot", "illustration")


class TransientAIError(RuntimeError):
    """Error recuperable (red, límite de tasa, 5xx): el trabajo se reintenta."""


class PermanentAIError(RuntimeError):
    """Error no recuperable (configuración, petición inválida, rechazo)."""


@dataclass
class PlotSeries:
    label: str
    x: list[float]
    y: list[float]


@dataclass
class Visual:
    kind: str
    title: str
    code: str | None = None
    prompt: str | None = None
    x_label: str = ""
    y_label: str = ""
    series: list[PlotSeries] = field(default_factory=list)


@dataclass
class Analysis:
    is_relevant: bool
    title: str
    answer_markdown: str
    irrelevant_reason: str | None = None
    visuals: list[Visual] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_relevant": self.is_relevant,
            "title": self.title,
            "answer_markdown": self.answer_markdown,
            "irrelevant_reason": self.irrelevant_reason,
            "model": self.model,
            "visuals": [
                {
                    "kind": v.kind,
                    "title": v.title,
                    "code": v.code,
                    "prompt": v.prompt,
                    "x_label": v.x_label,
                    "y_label": v.y_label,
                    "series": [{"label": s.label, "x": s.x, "y": s.y} for s in v.series],
                }
                for v in self.visuals
            ],
        }


class AIProvider(Protocol):
    def analyze(self, images: list[Path], options: dict[str, Any]) -> Analysis: ...

    def generate_image(self, prompt: str, size: str) -> bytes: ...


# ----------------------------------------------------------------- esquema
def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_relevant", "irrelevant_reason", "title", "answer_markdown", "visuals"],
    "properties": {
        "is_relevant": {
            "type": "boolean",
            "description": "true si las fotos contienen documentos, ejercicios, preguntas o laboratorios a resolver.",
        },
        "irrelevant_reason": _nullable({"type": "string"}),
        "title": {"type": "string", "description": "Título breve (máx. 60 caracteres) del contenido."},
        "answer_markdown": {
            "type": "string",
            "description": "Respuesta completa en Markdown (GFM) con LaTeX entre $...$ o $$...$$.",
        },
        "visuals": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "title", "code", "prompt", "plot"],
                "properties": {
                    "kind": {"type": "string", "enum": list(VISUAL_KINDS)},
                    "title": {"type": "string"},
                    "code": _nullable({"type": "string"}),
                    "prompt": _nullable({"type": "string"}),
                    "plot": _nullable(
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["x_label", "y_label", "series"],
                            "properties": {
                                "x_label": {"type": "string"},
                                "y_label": {"type": "string"},
                                "series": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["label", "x", "y"],
                                        "properties": {
                                            "label": {"type": "string"},
                                            "x": {"type": "array", "items": {"type": "number"}},
                                            "y": {"type": "array", "items": {"type": "number"}},
                                        },
                                    },
                                },
                            },
                        }
                    ),
                },
            },
        },
    },
}


def build_instructions(options: dict[str, Any]) -> str:
    language = options.get("language", "es")
    lang_line = (
        "Responde en español."
        if language == "es"
        else "Responde en el mismo idioma en que están escritas las preguntas."
    )
    allow_illustrations = bool(options.get("allow_illustrations", True))
    illus = (
        "- kind=\"illustration\": SOLO si piden explícitamente un dibujo artístico o diseño libre que no pueda "
        "hacerse con precisión de forma determinista. Rellena `prompt` con una descripción detallada."
        if allow_illustrations
        else "- No uses kind=\"illustration\" (desactivado por el usuario)."
    )
    return f"""Eres un asistente experto que resuelve documentos, laboratorios, problemas y ejercicios a partir de fotografías.
{lang_line}

Tarea:
1. Lee con atención TODAS las fotografías (pueden ser varias páginas del mismo documento).
2. Si no contienen preguntas, ejercicios, documentos o laboratorios (p. ej. una foto personal), devuelve is_relevant=false, una razón breve, answer_markdown vacío y visuals vacío.
3. En caso contrario, responde TODAS las preguntas de forma completa, como lo haría ChatGPT:
   - Encabezados por pregunta/ejercicio (## Ejercicio 1, ...), respetando la numeración original.
   - Procedimientos completos paso a paso, sin resumir ni omitir pasos; resultado final destacado en **negrita**.
   - Fórmulas en LaTeX: en línea con $...$ y en bloque con $$...$$ (no uses \\( \\) ni \\[ \\]).
   - Tablas en Markdown cuando ayuden; código en bloques ``` con el lenguaje indicado.
   - Si algo de la foto es ilegible, dilo y continúa con la mejor interpretación razonable.
4. Elementos visuales (`visuals`): genera uno SOLO si la pregunta pide un dibujo, diagrama, gráfica, circuito, autómata, árbol, grafo o diseño. No generes ilustraciones innecesarias. Prioriza herramientas deterministas:
   - kind="graphviz": autómatas, grafos, árboles, diagramas de flujo, máquinas de estado. `code` = programa DOT completo (digraph/graph). No uses atributos image ni shapefile.
   - kind="svg": circuitos, figuras geométricas, esquemas técnicos precisos. `code` = documento SVG completo con viewBox, fondo blanco, trazos negros legibles, sin scripts ni recursos externos.
   - kind="plot": gráficas de funciones o datos. Rellena `plot` con etiquetas y series (x e y de igual longitud, 50-400 puntos para funciones continuas).
   {illus}
   - Para cada visual, deja en null los campos que no apliquen a su tipo. Menciona en el texto "(ver imagen: <título>)".
5. `title`: título corto del documento o tema.
"""


def parse_analysis(payload: dict[str, Any], model: str = "") -> Analysis:
    visuals = []
    for v in payload.get("visuals") or []:
        kind = v.get("kind")
        if kind not in VISUAL_KINDS:
            continue
        plot = v.get("plot") or {}
        series = []
        for s in plot.get("series") or []:
            xs = [float(x) for x in s.get("x") or []]
            ys = [float(y) for y in s.get("y") or []]
            n = min(len(xs), len(ys))
            if n >= 2:
                series.append(PlotSeries(label=str(s.get("label", "")), x=xs[:n], y=ys[:n]))
        visuals.append(
            Visual(
                kind=kind,
                title=str(v.get("title") or kind)[:120],
                code=v.get("code"),
                prompt=v.get("prompt"),
                x_label=str(plot.get("x_label", "")),
                y_label=str(plot.get("y_label", "")),
                series=series,
            )
        )
    return Analysis(
        is_relevant=bool(payload.get("is_relevant")),
        irrelevant_reason=payload.get("irrelevant_reason"),
        title=(str(payload.get("title") or "Respuesta").strip() or "Respuesta")[:80],
        answer_markdown=str(payload.get("answer_markdown") or ""),
        visuals=visuals,
        model=model,
    )


class OpenAIProvider:
    """Proveedor real. Requiere OPENAI_API_KEY y OPENAI_MODEL en el entorno."""

    def __init__(self, settings: Settings):
        problems = settings.ai_config_problems()
        if problems:
            raise PermanentAIError("; ".join(problems))
        import openai  # import diferido: los tests no necesitan red

        self._openai = openai
        self.settings = settings
        self.client = openai.OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_seconds,
            max_retries=2,
        )

    def _classify(self, exc: Exception) -> Exception:
        o = self._openai
        if isinstance(exc, (o.APIConnectionError, o.RateLimitError, o.InternalServerError)):
            return TransientAIError(f"{exc.__class__.__name__}: {exc}")
        if isinstance(exc, o.APIStatusError) and exc.status_code in (408, 409, 425, 500, 502, 503, 504):
            return TransientAIError(f"{exc.__class__.__name__}: {exc}")
        return PermanentAIError(f"{exc.__class__.__name__}: {exc}")

    def analyze(self, images: list[Path], options: dict[str, Any]) -> Analysis:
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": f"Resuelve el contenido de estas {len(images)} fotografía(s), en orden.",
            }
        ]
        for p in images:
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{b64}",
                    "detail": self.settings.openai_image_detail,
                }
            )
        kwargs: dict[str, Any] = {
            "model": self.settings.openai_model,
            "instructions": build_instructions(options),
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "autogpt_watch_answer",
                    "schema": ANALYSIS_SCHEMA,
                    "strict": True,
                }
            },
            "max_output_tokens": self.settings.openai_max_output_tokens,
            "store": False,
        }
        if self.settings.openai_reasoning_effort:
            kwargs["reasoning"] = {"effort": self.settings.openai_reasoning_effort}
        try:
            response = self.client.responses.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - se clasifica abajo
            raise self._classify(exc) from exc

        status = getattr(response, "status", None)
        if status == "incomplete":
            details = getattr(response, "incomplete_details", None)
            reason = getattr(details, "reason", None) or "desconocido"
            raise PermanentAIError(
                f"Respuesta incompleta de OpenAI ({reason}). Aumenta OPENAI_MAX_OUTPUT_TOKENS o divide las fotos."
            )
        for item in getattr(response, "output", None) or []:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "refusal":
                    raise PermanentAIError(f"El modelo rechazó la solicitud: {getattr(part, 'refusal', '')}")
        text = response.output_text
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TransientAIError("La respuesta de OpenAI no es JSON válido") from exc
        return parse_analysis(payload, model=getattr(response, "model", self.settings.openai_model) or "")

    def generate_image(self, prompt: str, size: str = "1024x1536") -> bytes:
        if not self.settings.openai_image_model:
            raise PermanentAIError("Falta OPENAI_IMAGE_MODEL para generar ilustraciones")
        try:
            result = self.client.images.generate(
                model=self.settings.openai_image_model,
                prompt=prompt[:4000],
                size=size,
                n=1,
            )
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from exc
        if not result.data or not result.data[0].b64_json:
            raise PermanentAIError("La API de imágenes no devolvió datos")
        return base64.b64decode(result.data[0].b64_json)
