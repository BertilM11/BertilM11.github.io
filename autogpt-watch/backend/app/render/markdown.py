"""Markdown (GFM + LaTeX) -> HTML seguro.

- HTML crudo desactivado: el contenido del modelo nunca puede inyectar etiquetas.
- Las fórmulas se emiten como <span class="math-tex"> y KaTeX las renderiza en Chromium.
- El código se resalta en el servidor con Pygments.
"""

from __future__ import annotations

import html
import re

from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound

PYGMENTS_STYLE = "github-dark"
_formatter = HtmlFormatter(style=PYGMENTS_STYLE, nowrap=True)

_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})")


def pygments_css() -> str:
    return HtmlFormatter(style=PYGMENTS_STYLE).get_style_defs(".code-body")


def normalize_math_delimiters(text: str) -> str:
    r"""Convierte \( \) y \[ \] a $ y $$ fuera de bloques/fragmentos de código."""
    out: list[str] = []
    in_fence: str | None = None
    for line in text.split("\n"):
        m = _FENCE.match(line)
        if in_fence:
            out.append(line)
            if m and m.group(2)[0] == in_fence[0] and len(m.group(2)) >= len(in_fence):
                in_fence = None
            continue
        if m:
            in_fence = m.group(2)
            out.append(line)
            continue
        # Respetar `código en línea`
        parts = re.split(r"(`+[^`]*`+)", line)
        for i, part in enumerate(parts):
            if i % 2 == 1:
                continue
            part = re.sub(r"\\\[(.+?)\\\]", lambda mm: "$$" + mm.group(1) + "$$", part)
            part = re.sub(r"\\\((.+?)\\\)", lambda mm: "$" + mm.group(1) + "$", part)
            parts[i] = part
        out.append("".join(parts))
    text = "\n".join(out)
    # \[ ... \] en varias líneas
    text = re.sub(r"(?ms)^\s*\\\[\s*\n(.+?)\n\s*\\\]\s*$", lambda mm: "$$\n" + mm.group(1) + "\n$$", text)
    return text


def _math_renderer(content: str, options: dict) -> str:
    display = "1" if options.get("display_mode") else "0"
    tag = "div" if display == "1" else "span"
    return f'<{tag} class="math-tex" data-display="{display}">{html.escape(content)}</{tag}>'


def _highlight(code: str, lang: str, _attrs: str) -> str:
    lexer = None
    if lang:
        try:
            lexer = get_lexer_by_name(lang.strip().split()[0])
        except ClassNotFound:
            lexer = None
    if lexer is None:
        try:
            lexer = guess_lexer(code) if len(code) > 40 else None
        except ClassNotFound:
            lexer = None
    body = highlight(code, lexer, _formatter) if lexer else html.escape(code)
    label = html.escape(lang.strip().split()[0] if lang.strip() else (lexer.name if lexer else "texto"))
    return (
        f'<div class="code-block"><div class="code-head">{label}</div>'
        f'<pre class="code-body"><code>{body}</code></pre></div>'
    )


def _build() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False, "highlight": _highlight})
    md.enable(["table", "strikethrough"])
    md.use(dollarmath_plugin, allow_digits=False, allow_space=True, double_inline=True, renderer=_math_renderer)
    md.use(tasklists_plugin)

    def fence(tokens, idx, options, env):  # type: ignore[no-untyped-def]
        token = tokens[idx]
        return _highlight(token.content, token.info.strip() if token.info else "", "")

    md.renderer.rules["fence"] = fence
    md.renderer.rules["code_block"] = lambda tokens, idx, options, env: _highlight(tokens[idx].content, "", "")
    # Tablas envueltas para poder reducirlas si son demasiado anchas.
    md.renderer.rules["table_open"] = lambda *a, **k: '<div class="table-wrap"><table>'
    md.renderer.rules["table_close"] = lambda *a, **k: "</table></div>"
    return md


_md = _build()


def markdown_to_html(text: str) -> str:
    return _md.render(normalize_math_delimiters(text or ""))
