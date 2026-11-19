"""Renderizado determinista de respuestas a PNG con Chromium (Playwright).

1. Markdown -> HTML (markdown.py) dentro de una plantilla tipo conversación.
2. KaTeX renderiza las fórmulas; se reducen fórmulas/tablas demasiado anchas.
3. Se miden las "unidades atómicas" (líneas de texto, fórmulas, filas, imágenes) y se
   calculan cortes de página que nunca parten una línea por la mitad.
4. Cada página se recorta y se compone en un lienzo fijo con cabecera "n/N".
"""

from __future__ import annotations

import base64
import html
import io
import math
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from PIL import Image, ImageDraw, ImageFont

from .markdown import markdown_to_html, pygments_css
from .theme import BG, BORDER, MUTED, PRESETS, SVG_PAGE_CSS, TEXT, Preset, stylesheet

VENDOR = Path(__file__).parent / "vendor"

MEASURE_JS = r"""
() => {
  const root = document.getElementById('page-root');
  const units = [];
  const sy = window.scrollY;
  const add = (r) => { if (r.height > 0.5 && r.width > 0.5) units.push([r.top + sy, r.bottom + sy]); };
  root.querySelectorAll('.katex, .katex-display, img, svg, tr, .bubble, .code-head, hr, .math-error')
      .forEach(el => add(el.getBoundingClientRect()));
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: n => (!n.textContent.trim() || (n.parentElement && n.parentElement.closest('.katex, .bubble')))
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT
  });
  const range = document.createRange();
  let n;
  while ((n = walker.nextNode())) {
    range.selectNodeContents(n);
    for (const r of range.getClientRects()) add(r);
  }
  const headings = [];
  root.querySelectorAll('h1, h2, h3, h4').forEach(h => {
    const r = h.getBoundingClientRect(); headings.push([r.top + sy, r.bottom + sy]);
  });
  return { height: Math.ceil(document.documentElement.scrollHeight), units, headings };
}
"""

PREPARE_JS = r"""
async () => {
  const errors = [];
  document.querySelectorAll('.math-tex').forEach(el => {
    const tex = el.textContent;
    const display = el.dataset.display === '1';
    try {
      katex.render(tex, el, { displayMode: display, throwOnError: true, output: 'html', strict: 'ignore' });
    } catch (e) {
      errors.push(String(e && e.message || e));
      el.textContent = display ? tex : '$' + tex + '$';
      el.classList.add('math-error');
    }
  });
  await document.fonts.ready;
  const fit = (el) => {
    let size = 100;
    while (el.scrollWidth > el.clientWidth + 1 && size > 50) { size -= 5; el.style.fontSize = size + '%'; }
    if (el.scrollWidth > el.clientWidth + 1) {
      const s = el.clientWidth / el.scrollWidth;
      const inner = el.firstElementChild;
      if (inner) {
        const h = inner.getBoundingClientRect().height;
        inner.style.transformOrigin = 'left top';
        inner.style.transform = 'scale(' + s + ')';
        el.style.height = (h * s) + 'px';
      }
    }
  };
  document.querySelectorAll('div.math-tex, .table-wrap').forEach(fit);
  return errors;
}
"""


@dataclass
class RenderedPage:
    png: bytes
    index: int
    total: int


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        ["Inter-SemiBold.ttf", "Inter-Bold.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else ["Inter-Regular.ttf", "Inter.ttf", "DejaVuSans.ttf"]
    )
    dirs = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts"]
    for name in candidates:
        for d in dirs:
            if d.exists():
                for p in d.rglob(name):
                    try:
                        return ImageFont.truetype(str(p), size)
                    except OSError:
                        continue
    return ImageFont.load_default(size=size)


def compute_cuts(
    units: list[list[float]], headings: list[list[float]], total_height: float, page_height: float
) -> list[tuple[int, int]]:
    """Devuelve rangos [y0, y1) en px CSS sin partir ninguna unidad atómica.

    Si una unidad es más alta que una página (imagen enorme), se corta a la fuerza.
    Evita dejar un encabezado huérfano al final de una página.
    """
    total_height = max(1, int(math.ceil(total_height)))
    intervals = sorted((float(a), float(b)) for a, b in units if b > a)
    merged: list[list[float]] = []
    for a, b in intervals:
        if merged and a < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])

    def containing(y: float) -> list[float] | None:
        for iv in merged:
            if iv[0] < y < iv[1]:
                return iv
            if iv[0] >= y:
                break
        return None

    pages: list[tuple[int, int]] = []
    y0 = 0
    while y0 < total_height:
        limit = y0 + page_height
        if limit >= total_height:
            pages.append((y0, total_height))
            break
        cut: float = limit
        iv = containing(limit)
        if iv is not None:
            cut = iv[0] if iv[0] > y0 + 4 else limit  # unidad mayor que una página: corte forzado
        # Evitar encabezado huérfano al final de la página.
        for ht, hb in headings:
            if y0 + 4 < ht and hb <= cut and cut - hb < 40:
                cut = ht
                break
        cut_i = int(math.floor(cut))
        if cut_i <= y0:
            cut_i = int(limit)
        pages.append((y0, cut_i))
        y0 = cut_i
    # Descartar una última página vacía (sólo margen inferior).
    if len(pages) > 1:
        last_a, last_b = pages[-1]
        if not any(a < last_b and b > last_a for a, b in intervals):
            pages.pop()
            prev_a, _ = pages[-1]
            pages[-1] = (prev_a, last_b)
    return pages


class Renderer:
    def __init__(self, chromium_executable: str = ""):
        self.chromium_executable = chromium_executable

    @contextmanager
    def _browser_page(self, preset: Preset) -> Iterator[object]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            kwargs = {"args": ["--disable-gpu", "--no-sandbox"]}
            if self.chromium_executable:
                kwargs["executable_path"] = self.chromium_executable
            browser = pw.chromium.launch(**kwargs)
            try:
                context = browser.new_context(
                    viewport={"width": preset.css_width, "height": preset.css_height},
                    device_scale_factor=preset.dpr,
                    java_script_enabled=True,
                )

                def guard(route):  # sólo recursos locales: nada sale a la red
                    url = route.request.url
                    if url.startswith("file://") or url.startswith("data:"):
                        route.continue_()
                    else:
                        route.abort()

                context.route("**/*", guard)
                page = context.new_page()
                yield page
            finally:
                browser.close()

    # ------------------------------------------------------------ respuestas
    def build_html(self, markdown_text: str, preset: Preset, photo_thumbs: list[bytes], prompt: str) -> str:
        katex_css = (VENDOR / "katex" / "katex.min.css").as_uri()
        katex_js = (VENDOR / "katex" / "katex.min.js").as_uri()
        thumbs = "".join(
            f'<img src="data:image/jpeg;base64,{base64.b64encode(t).decode()}">' for t in photo_thumbs[:4]
        )
        body = markdown_to_html(markdown_text)
        return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<link rel="stylesheet" href="{katex_css}">
<style>{stylesheet(preset)}{pygments_css()}</style>
<script src="{katex_js}"></script></head>
<body><div id="page-root">
<div class="user-row"><div class="bubble">{f'<div class="thumbs">{thumbs}</div>' if thumbs else ''}
<div class="prompt">{html.escape(prompt)}</div></div></div>
<div class="assistant-head"><span class="dot"></span><span>Respuesta</span></div>
<div id="answer">{body}</div>
</div></body></html>"""

    def render_answer(
        self,
        markdown_text: str,
        *,
        preset_name: str = "watch",
        title: str = "Respuesta",
        photo_thumbs: list[bytes] | None = None,
        prompt: str = "Resuelve esto",
    ) -> tuple[list[RenderedPage], list[str]]:
        preset = PRESETS.get(preset_name, PRESETS["watch"])
        doc = self.build_html(markdown_text, preset, photo_thumbs or [], prompt)
        with tempfile.TemporaryDirectory() as tmp, self._browser_page(preset) as page:
            path = Path(tmp) / "answer.html"
            path.write_text(doc, encoding="utf-8")
            page.goto(path.as_uri(), wait_until="load")
            math_errors = page.evaluate(PREPARE_JS)
            m = page.evaluate(MEASURE_JS)
            cuts = compute_cuts(m["units"], m["headings"], m["height"], preset.content_height)
            slices = []
            for y0, y1 in cuts:
                shot = page.screenshot(
                    clip={"x": 0, "y": y0, "width": preset.css_width, "height": max(1, y1 - y0)},
                    full_page=True,
                    type="png",
                )
                slices.append(shot)
        total = len(slices)
        pages = [
            RenderedPage(self._frame(s, preset, title, f"{i}/{total}"), i, total)
            for i, s in enumerate(slices, start=1)
        ]
        return pages, list(math_errors or [])

    # ------------------------------------------------------------- visuales
    def svg_to_png(self, svg: str, preset_name: str = "watch") -> bytes:
        preset = PRESETS.get(preset_name, PRESETS["watch"])
        width = preset.css_width
        doc = (
            f'<!doctype html><html><head><meta charset="utf-8"><style>{SVG_PAGE_CSS}'
            f"#card{{width:{width}px}}</style></head><body><div id=\"card\">{svg}</div></body></html>"
        )
        with tempfile.TemporaryDirectory() as tmp, self._browser_page(preset) as page:
            path = Path(tmp) / "visual.html"
            path.write_text(doc, encoding="utf-8")
            page.goto(path.as_uri(), wait_until="load")
            return page.locator("#card").screenshot(type="png")

    def frame_visual(self, png: bytes, preset_name: str, title: str, label: str) -> bytes:
        preset = PRESETS.get(preset_name, PRESETS["watch"])
        return self._frame(png, preset, title, label, fit=True)

    # ------------------------------------------------------------ composición
    def _frame(self, png: bytes, preset: Preset, title: str, label: str, fit: bool = False) -> bytes:
        W, H = preset.pixel_size
        s = preset.dpr
        canvas = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(canvas)
        head_h = preset.header_px * s
        f_title = _font(int(preset.header_px * 0.42 * s), bold=True)
        f_label = _font(int(preset.header_px * 0.42 * s), bold=True)
        pad = preset.pad_x * s
        label_w = draw.textlength(label, font=f_label)
        max_title_w = W - 2 * pad - label_w - 12 * s
        t = title
        while t and draw.textlength(t, font=f_title) > max_title_w:
            t = t[:-2]
        if t != title:
            t = t.rstrip() + "…"
        cy = head_h // 2
        draw.text((pad, cy), t, fill=TEXT, font=f_title, anchor="lm")
        draw.text((W - pad, cy), label, fill=MUTED, font=f_label, anchor="rm")
        draw.line([(0, head_h - 1), (W, head_h - 1)], fill=BORDER, width=max(1, s // 2))

        content = Image.open(io.BytesIO(png)).convert("RGB")
        top = head_h + preset.pad_top * s
        avail_h = H - top - preset.pad_bottom * s
        if fit:
            avail_w = W - 2 * pad
            scale = min(avail_w / content.width, avail_h / content.height)
            new = (max(1, int(content.width * scale)), max(1, int(content.height * scale)))
            content = content.resize(new, Image.LANCZOS)
            x = (W - content.width) // 2
            y = top + (avail_h - content.height) // 2
        else:
            if content.height > avail_h:  # no debería ocurrir: los cortes respetan la altura
                content = content.crop((0, 0, content.width, avail_h))
            x, y = 0, top
        canvas.paste(content, (x, y))
        out = io.BytesIO()
        canvas.save(out, format="PNG", optimize=True)
        return out.getvalue()
