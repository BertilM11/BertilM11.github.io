"""Generación determinista de elementos visuales: Graphviz, SVG saneado y gráficas."""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from defusedxml import ElementTree as SafeET

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
FORBIDDEN_TAGS = {"script", "foreignObject", "iframe", "object", "embed", "audio", "video", "canvas", "handler"}
DOT_FORBIDDEN = re.compile(
    r"\b(image|shapefile|imagepath|fontpath|imagescale|stylesheet|URL|href)\s*=|<\s*img\b", re.I
)
MAX_DOT_CHARS = 30_000
MAX_SVG_CHARS = 300_000


class VisualError(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def sanitize_svg(svg: str) -> str:
    """Elimina scripts, manejadores de eventos y referencias externas de un SVG."""
    if not svg or len(svg) > MAX_SVG_CHARS:
        raise VisualError("SVG vacío o demasiado grande")
    svg = re.sub(r"<\?xml[^>]*\?>", "", svg).strip()
    svg = re.sub(r"<!DOCTYPE[^>]*>", "", svg, flags=re.I).strip()
    try:
        root = SafeET.fromstring(svg)
    except Exception as exc:  # noqa: BLE001 - defusedxml lanza varios tipos
        raise VisualError(f"SVG inválido: {exc.__class__.__name__}") from exc
    if _local(root.tag) != "svg":
        raise VisualError("el documento no es un SVG")

    def clean(el: ET.Element) -> None:
        for child in list(el):
            if _local(child.tag) in FORBIDDEN_TAGS:
                el.remove(child)
                continue
            clean(child)
        for attr in list(el.attrib):
            name = _local(attr).lower()
            value = el.attrib[attr].strip()
            if name.startswith("on"):
                del el.attrib[attr]
            elif name == "href" and not (value.startswith("#") or value.startswith("data:image/")):
                del el.attrib[attr]
            elif "javascript:" in value.lower() or "url(http" in value.lower().replace(" ", ""):
                del el.attrib[attr]
        if _local(el.tag) == "style" and el.text:
            el.text = re.sub(r"@import[^;]*;?", "", el.text)
            el.text = re.sub(r"url\(\s*['\"]?https?:[^)]*\)", "none", el.text, flags=re.I)

    clean(root)
    # Garantizar viewBox para que el SVG escale al ancho disponible.
    if "viewBox" not in root.attrib:
        w = re.match(r"[\d.]+", root.attrib.get("width", "") or "")
        h = re.match(r"[\d.]+", root.attrib.get("height", "") or "")
        if w and h:
            root.set("viewBox", f"0 0 {w.group(0)} {h.group(0)}")
    root.attrib.pop("width", None)
    root.attrib.pop("height", None)
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    return ET.tostring(root, encoding="unicode")


def graphviz_to_svg(dot_source: str, timeout: float = 20.0) -> str:
    if not dot_source or len(dot_source) > MAX_DOT_CHARS:
        raise VisualError("programa DOT vacío o demasiado grande")
    if DOT_FORBIDDEN.search(dot_source):
        raise VisualError("el programa DOT usa atributos no permitidos (image/shapefile/URL...)")
    dot = shutil.which("dot")
    if not dot:
        raise VisualError("Graphviz (dot) no está instalado en el servidor")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            proc = subprocess.run(
                [dot, "-Tsvg", "-Gbgcolor=white"],
                input=dot_source.encode("utf-8"),
                capture_output=True,
                timeout=timeout,
                cwd=tmp,
                env={"PATH": "/usr/bin:/bin", "HOME": tmp},
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VisualError("Graphviz tardó demasiado") from exc
    if proc.returncode != 0:
        raise VisualError("Graphviz: " + proc.stderr.decode("utf-8", "replace")[:400])
    return sanitize_svg(proc.stdout.decode("utf-8", "replace"))


def plot_to_png(title: str, x_label: str, y_label: str, series: list, width_px: int) -> bytes:
    """Gráfica con matplotlib (backend Agg) a partir de series numéricas."""
    if not series:
        raise VisualError("la gráfica no tiene series válidas")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dpi = 200
    w_in = width_px / dpi
    fig, ax = plt.subplots(figsize=(w_in, w_in * 0.8), dpi=dpi)
    try:
        fig.patch.set_facecolor("white")
        for s in series[:8]:
            ax.plot(s.x, s.y, linewidth=1.8, label=s.label or None)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel(x_label, fontsize=9)
        ax.set_ylabel(y_label, fontsize=9)
        ax.grid(True, alpha=0.35)
        ax.axhline(0, color="#555", linewidth=0.7)
        ax.axvline(0, color="#555", linewidth=0.7)
        if any(s.label for s in series):
            ax.legend(fontsize=8)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        return buf.getvalue()
    finally:
        plt.close(fig)
