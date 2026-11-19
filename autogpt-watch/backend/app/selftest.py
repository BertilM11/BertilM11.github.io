"""Contenido de PRUEBA de renderizado (no es una respuesta de IA).

Permite verificar descarga + guardado en Fotos + Favoritos de extremo a extremo
sin gastar créditos de OpenAI. Siempre va etiquetado como PRUEBA.
"""

from .ai import Analysis, Visual

SELFTEST_MARKDOWN = r"""
## PRUEBA de renderizado

> Esta imagen la genera el servidor **sin** usar IA, para comprobar que el renderizado,
> la descarga y el guardado en Fotos funcionan.

### Fórmulas
La solución de $ax^2 + bx + c = 0$ es:

$$x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$$

### Tabla
| Magnitud | Símbolo | Unidad |
|---|---|---|
| Fuerza | $F$ | N |
| Masa | $m$ | kg |
| Aceleración | $a$ | m/s² |

### Código
```python
def fibonacci(n: int) -> list[int]:
    a, b = 0, 1
    serie = []
    for _ in range(n):
        serie.append(a)
        a, b = b, a + b
    return serie
```

### Lista
1. Primer paso con **negrita**.
2. Segundo paso con `código en línea`.
3. Resultado: $\boxed{42}$

(ver imagen: Autómata de prueba)
"""

SELFTEST_DOT = """digraph G {
  rankdir=LR; node [shape=circle, fontname="Helvetica"];
  q0 [shape=doublecircle]; start [shape=point];
  start -> q0; q0 -> q1 [label="a"]; q1 -> q0 [label="b"]; q1 -> q1 [label="a"];
}"""


def selftest_analysis() -> Analysis:
    return Analysis(
        is_relevant=True,
        title="PRUEBA – no es respuesta de IA",
        answer_markdown=SELFTEST_MARKDOWN,
        visuals=[Visual(kind="graphviz", title="Autómata de prueba", code=SELFTEST_DOT)],
        model="selftest",
    )
