"""Pruebas unitarias: Markdown, paginación, validación de imágenes, SVG/DOT, esquema de OpenAI, APNs."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import httpx
import pytest
from conftest import has_graphviz, jpeg_bytes
from PIL import Image

from app.ai import ANALYSIS_SCHEMA, OpenAIProvider, PermanentAIError, build_instructions, parse_analysis
from app.config import Settings
from app.render.markdown import markdown_to_html, normalize_math_delimiters
from app.render.renderer import Renderer, compute_cuts
from app.render.visuals import VisualError, graphviz_to_svg, sanitize_svg
from app.storage import Storage, UploadRejected, validate_image


# ------------------------------------------------------------ Markdown
def test_math_delimiters_converted_outside_code():
    src = "Sea \\(x^2\\) y\n\\[y=1\\]\n```\n\\(no\\)\n```\n`\\(tampoco\\)`"
    out = normalize_math_delimiters(src)
    assert "$x^2$" in out
    assert "$$y=1$$" in out
    assert "```\n\\(no\\)\n```" in out
    assert "`\\(tampoco\\)`" in out


def test_raw_html_is_escaped():
    html = markdown_to_html("<script>alert(1)</script> <img src=x onerror=alert(1)>")
    assert "<script>" not in html
    assert "<img" not in html


def test_markdown_features():
    html = markdown_to_html("# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nprint(1)\n```\n\n$$a^2$$ y $b$")
    assert '<div class="table-wrap"><table>' in html
    assert 'class="code-block"' in html and "python" in html
    assert html.count('class="math-tex"') == 2
    assert 'data-display="1"' in html


def test_currency_not_parsed_as_math():
    html = markdown_to_html("Cuesta 5$ y 10$ en total")
    assert "math-tex" not in html


# ----------------------------------------------------------- paginación
def _assert_no_split(units, cuts):
    for a, b in units:
        for y0, y1 in cuts[:-1]:
            if b - a <= 100:  # sólo unidades que caben en una página
                assert not (a < y1 < b), f"unidad {a}-{b} partida en {y1}"


def test_cuts_never_split_lines():
    units = [[i * 30 + 5, i * 30 + 28] for i in range(40)]
    cuts = compute_cuts(units, [], 1200, 100)
    _assert_no_split(units, cuts)
    assert cuts[0][0] == 0 and cuts[-1][1] == 1200
    for (a0, a1), (b0, _) in zip(cuts, cuts[1:]):
        assert a1 == b0  # contiguas, sin huecos ni solapes
    assert all(y1 - y0 <= 100 for y0, y1 in cuts)


def test_cut_forced_for_huge_unit():
    cuts = compute_cuts([[10, 450]], [], 500, 100)
    assert len(cuts) >= 5
    assert all(y1 - y0 <= 100 for y0, y1 in cuts)


def test_heading_not_orphaned():
    units = [[0, 20], [25, 45], [50, 70], [75, 95], [100, 120]]
    headings = [[75, 95]]
    cuts = compute_cuts(units, headings, 130, 98)
    assert cuts[0] == (0, 75)


def test_trailing_empty_page_merged():
    cuts = compute_cuts([[0, 90]], [], 105, 100)
    assert cuts == [(0, 105)]


# ------------------------------------------------------------- imágenes
def test_validate_image_strips_exif_and_reencodes(settings):
    raw = jpeg_bytes(exif_gps=True)
    with Image.open(io.BytesIO(raw)) as im:
        assert im.getexif()
    v = validate_image(raw, settings)
    with Image.open(io.BytesIO(v.jpeg_bytes)) as im:
        assert im.format == "JPEG"
        assert not im.getexif().get(0x8825)


def test_validate_image_rejects(settings):
    with pytest.raises(UploadRejected):
        validate_image(b"", settings)
    with pytest.raises(UploadRejected):
        validate_image(b"GIF89a....", settings)
    big = b"\xff\xd8\xff" + b"0" * int(settings.max_upload_mb * 1024 * 1024 + 10)
    with pytest.raises(UploadRejected):
        validate_image(big, settings)
    with pytest.raises(UploadRejected):
        validate_image(b"\xff\xd8\xff\xe0garbage", settings)


def test_result_file_path_traversal(settings):
    st = Storage(settings)
    d = st.result_dir("job1")
    d.mkdir(parents=True)
    (d / "01-a.png").write_bytes(b"x")
    assert st.result_file("job1", "01-a.png")
    assert st.result_file("job1", "../job1/01-a.png") is None
    assert st.result_file("job1", "/etc/passwd") is None


# ---------------------------------------------------------------- SVG/DOT
def test_sanitize_svg_removes_active_content():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="100" height="50" onload="x()">'
        '<script>alert(1)</script><foreignObject><div/></foreignObject>'
        '<a href="https://evil.example"><rect width="10" height="10" onclick="y()"/></a>'
        '<image xlink:href="http://evil.example/x.png"/><use href="#ok"/></svg>'
    )
    out = sanitize_svg(svg)
    assert "script" not in out and "foreignObject" not in out
    assert "onload" not in out and "onclick" not in out
    assert "evil.example" not in out
    assert 'viewBox="0 0 100 50"' in out
    assert "#ok" in out


def test_sanitize_svg_rejects_entities():
    bomb = '<!DOCTYPE x [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>'
    with pytest.raises(VisualError):
        sanitize_svg(bomb)
    with pytest.raises(VisualError):
        sanitize_svg("<html><body>no es svg</body></html>")


def test_dot_forbidden_attributes():
    for bad in ['digraph { a [image="/etc/passwd"] }', 'digraph { a [label=<<IMG SRC="/x"/>>] }',
                'digraph { a [URL="http://x"] }']:
        with pytest.raises(VisualError):
            graphviz_to_svg(bad)


@pytest.mark.skipif(not has_graphviz(), reason="Graphviz no instalado")
def test_graphviz_renders():
    svg = graphviz_to_svg("digraph { q0 -> q1 [label=a] }")
    assert svg.startswith("<svg") and "q1" in svg


def test_render_answer_pages(settings):
    r = Renderer(settings.chromium_executable)
    md = "\n\n".join(f"Párrafo {i} con fórmula $x_{i}^2$ y texto suficiente para ocupar varias líneas en el reloj." for i in range(30))
    pages, errors = r.render_answer(md, preset_name="watch", title="T")
    assert errors == []
    assert len(pages) > 3
    assert [p.index for p in pages] == list(range(1, len(pages) + 1))
    for p in pages:
        assert Image.open(io.BytesIO(p.png)).size == (792, 968)


def test_render_reports_bad_math(settings):
    r = Renderer(settings.chromium_executable)
    _, errors = r.render_answer("Mal: $\\frac{1}{$ fin", title="T")
    assert errors


# ------------------------------------------------------------ OpenAI
def _walk(schema):
    yield schema
    for key in ("properties",):
        for v in schema.get(key, {}).values():
            yield from _walk(v)
    if "items" in schema:
        yield from _walk(schema["items"])
    for v in schema.get("anyOf", []):
        yield from _walk(v)


def test_schema_is_strict_compatible():
    for node in _walk(ANALYSIS_SCHEMA):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
            assert set(node["required"]) == set(node["properties"])


def test_instructions_respect_options():
    assert "No uses kind=\"illustration\"" in build_instructions({"allow_illustrations": False})
    assert "mismo idioma" in build_instructions({"language": "auto"})


def test_parse_analysis_cleans_input():
    a = parse_analysis(
        {
            "is_relevant": True,
            "title": "",
            "answer_markdown": "x",
            "irrelevant_reason": None,
            "visuals": [
                {"kind": "bogus", "title": "x", "code": None, "prompt": None, "plot": None},
                {"kind": "plot", "title": "p", "code": None, "prompt": None,
                 "plot": {"x_label": "x", "y_label": "y", "series": [{"label": "s", "x": [0, 1, 2], "y": [0, 1]}]}},
            ],
        }
    )
    assert a.title == "Respuesta"
    assert len(a.visuals) == 1
    assert a.visuals[0].series[0].x == [0.0, 1.0]


def test_openai_provider_requires_config():
    with pytest.raises(PermanentAIError):
        OpenAIProvider(Settings(_env_file=None, openai_api_key="", openai_model=""))


def test_openai_provider_request_shape(tmp_path):
    s = Settings(_env_file=None, openai_api_key="sk-test", openai_model="modelo-x", openai_reasoning_effort="high")
    p = OpenAIProvider(s)
    captured = {}
    payload = {"is_relevant": True, "irrelevant_reason": None, "title": "T", "answer_markdown": "**ok**", "visuals": []}

    class Responses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(status="completed", output=[], output_text=json.dumps(payload), model="modelo-x")

    p.client = SimpleNamespace(responses=Responses())
    img = tmp_path / "a.jpg"
    img.write_bytes(jpeg_bytes())
    a = p.analyze([img], {"language": "es"})
    assert a.answer_markdown == "**ok**"
    assert captured["model"] == "modelo-x"
    assert captured["store"] is False
    assert captured["reasoning"] == {"effort": "high"}
    fmt = captured["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["name"]
    content = captured["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/jpeg;base64,")


def test_openai_provider_incomplete_and_refusal(tmp_path):
    s = Settings(_env_file=None, openai_api_key="sk-test", openai_model="m")
    p = OpenAIProvider(s)
    img = tmp_path / "a.jpg"
    img.write_bytes(jpeg_bytes())

    def make(resp):
        return SimpleNamespace(responses=SimpleNamespace(create=lambda **k: resp))

    p.client = make(SimpleNamespace(status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                                    output=[], output_text=""))
    with pytest.raises(PermanentAIError, match="incompleta"):
        p.analyze([img], {})
    refusal = SimpleNamespace(type="refusal", refusal="no")
    p.client = make(SimpleNamespace(status="completed", output=[SimpleNamespace(content=[refusal])], output_text=""))
    with pytest.raises(PermanentAIError, match="rechazó"):
        p.analyze([img], {})


def test_openai_errors_are_classified():
    import openai

    from app.ai import TransientAIError

    p = OpenAIProvider(Settings(_env_file=None, openai_api_key="sk-test", openai_model="m"))
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    assert isinstance(p._classify(openai.APIConnectionError(request=req)), TransientAIError)
    resp400 = httpx.Response(400, request=req, json={"error": {"message": "bad"}})
    assert isinstance(p._classify(openai.BadRequestError("bad", response=resp400, body=None)), PermanentAIError)
    resp503 = httpx.Response(503, request=req, json={})
    assert isinstance(p._classify(openai.InternalServerError("x", response=resp503, body=None)), TransientAIError)


# --------------------------------------------------------------- APNs
def test_apns_payloads_and_invalid_token_cleanup(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from app.db import Database
    from app.push import APNsClient

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    kp = tmp_path / "AuthKey.p8"
    kp.write_bytes(pem)
    s = Settings(_env_file=None, apns_key_id="KEY123", apns_team_id="TEAM123", apns_bundle_id="com.example.app",
                 apns_key_path=str(kp), data_dir=tmp_path)
    db = Database(s.db_path)
    db.upsert_device("owner", "aa" * 32, "sandbox")
    db.upsert_device("owner", "bb" * 32, "production")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "bb" * 32 in str(request.url):
            return httpx.Response(410, json={"reason": "Unregistered"})
        return httpx.Response(200)

    c = APNsClient(s, db)
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    job = SimpleNamespace(id="j1", owner="owner", title="Tarea")
    assert c.notify_completed(job) is True
    bg = seen[0]
    assert bg.url.host == "api.sandbox.push.apple.com"
    assert bg.headers["apns-push-type"] == "background"
    assert bg.headers["apns-priority"] == "5"
    assert json.loads(bg.content)["aps"] == {"content-available": 1}
    # El token inválido se elimina
    assert db.devices_for("owner") == [("aa" * 32, "sandbox")]
    c.notify_needs_attention(job)
    alert = seen[-1]
    assert alert.headers["apns-push-type"] == "alert"
    assert "Tarea" in json.loads(alert.content)["aps"]["alert"]["body"]
