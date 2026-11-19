"""Presets de tamaño y hoja de estilos con apariencia de conversación oscura tipo ChatGPT."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    name: str
    css_width: int  # ancho de la página en px CSS
    css_height: int  # alto total de cada imagen en px CSS
    dpr: int  # factor de escala del dispositivo
    font_px: int
    code_px: int
    header_px: int
    pad_x: int
    pad_top: int
    pad_bottom: int

    @property
    def content_height(self) -> int:
        return self.css_height - self.header_px - self.pad_top - self.pad_bottom

    @property
    def pixel_size(self) -> tuple[int, int]:
        return self.css_width * self.dpr, self.css_height * self.dpr


PRESETS: dict[str, Preset] = {
    # Proporción ~4:5 similar a la pantalla del Apple Watch; letra grande para leer en el reloj.
    "watch": Preset("watch", 396, 484, 2, 21, 16, 34, 16, 8, 10),
    # Pantalla completa de iPhone (9:19.5).
    "phone": Preset("phone", 430, 932, 3, 17, 14, 40, 18, 10, 14),
}

BG = "#212121"
TEXT = "#ececec"
MUTED = "#b4b4b4"
BUBBLE = "#303030"
CODE_BG = "#0d0d0d"
CODE_HEAD = "#2f2f2f"
BORDER = "#3d3d3d"
ACCENT = "#10a37f"


def stylesheet(p: Preset) -> str:
    return f"""
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: {BG}; }}
body {{
  width: {p.css_width}px;
  font-family: "Inter", "Noto Sans", "DejaVu Sans", system-ui, sans-serif;
  font-size: {p.font_px}px; line-height: 1.5; color: {TEXT};
  -webkit-font-smoothing: antialiased; overflow-wrap: anywhere;
}}
#page-root {{ padding: 6px {p.pad_x}px 24px {p.pad_x}px; }}
.user-row {{ display: flex; justify-content: flex-end; margin: 4px 0 18px; }}
.bubble {{ background: {BUBBLE}; border-radius: 20px; padding: 10px 14px; max-width: 82%; }}
.bubble .thumbs {{ display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; margin-bottom: 6px; }}
.bubble .thumbs img {{ height: {int(p.font_px * 3.4)}px; border-radius: 10px; object-fit: cover; }}
.bubble .prompt {{ text-align: right; }}
.assistant-head {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; color: {MUTED}; font-size: 0.8em; }}
.assistant-head .dot {{ width: 0.95em; height: 0.95em; border-radius: 50%; background: {ACCENT}; display: inline-block; }}
#answer > *:first-child {{ margin-top: 0; }}
h1, h2, h3, h4 {{ line-height: 1.25; margin: 1.1em 0 0.45em; font-weight: 650; }}
h1 {{ font-size: 1.45em; }} h2 {{ font-size: 1.28em; }} h3 {{ font-size: 1.12em; }} h4 {{ font-size: 1em; }}
p {{ margin: 0.55em 0; }}
strong {{ font-weight: 650; color: #fff; }}
ul, ol {{ margin: 0.45em 0; padding-left: 1.35em; }}
li {{ margin: 0.22em 0; }}
li > p {{ margin: 0.2em 0; }}
blockquote {{ margin: 0.6em 0; padding: 0.1em 0 0.1em 0.8em; border-left: 3px solid {BORDER}; color: {MUTED}; }}
hr {{ border: 0; border-top: 1px solid {BORDER}; margin: 1em 0; }}
a {{ color: #7ab7ff; text-decoration: none; }}
code {{ font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace; font-size: 0.86em;
  background: #424242; border-radius: 5px; padding: 0.08em 0.32em; }}
.code-block {{ margin: 0.7em 0; border-radius: 10px; overflow: hidden; background: {CODE_BG}; }}
.code-head {{ background: {CODE_HEAD}; color: {MUTED}; font-size: 0.68em; padding: 5px 12px; font-family: "Inter", sans-serif; }}
pre.code-body {{ margin: 0; padding: 10px 12px; white-space: pre-wrap; word-break: break-word;
  font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace; font-size: {p.code_px}px; line-height: 1.45; }}
pre.code-body code {{ background: none; padding: 0; font-size: inherit; }}
.table-wrap {{ margin: 0.7em 0; overflow: hidden; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.86em; }}
th, td {{ border: 1px solid {BORDER}; padding: 5px 7px; text-align: left; vertical-align: top; }}
th {{ background: #2f2f2f; font-weight: 650; }}
div.math-tex {{ margin: 0.6em 0; overflow: hidden; text-align: center; }}
.katex {{ font-size: 1.08em; }}
.katex-display {{ margin: 0; }}
.math-error {{ color: #ff8a80; font-family: monospace; }}
.contains-task-list {{ list-style: none; padding-left: 0.4em; }}
"""


SVG_PAGE_CSS = """
html, body { margin: 0; padding: 0; background: #ffffff; }
#card { display: inline-block; background: #ffffff; padding: 12px; }
#card svg { display: block; width: 100%; height: auto; }
"""
