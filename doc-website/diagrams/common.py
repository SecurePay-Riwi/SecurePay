"""Small SVG toolkit for the architecture diagrams.

Cards sit on a grid, arrows are polylines with explicit corners, and
`render()` turns the SVG into the PNG/JPG the pages show (Playwright's
Chromium). Standard library only, apart from Playwright for the image.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path

FONT = "'DejaVu Sans', 'Segoe UI', Arial, sans-serif"
INK = "#1b2533"
MUTED = "#5b6676"
PAPER = "#f4f6fa"

# Arrow colors, one per kind of flow (the legend repeats them).
FLOW = {
    "realtime": "#e07a2e",
    "async": "#3a78c9",
    "batch": "#2e8a57",
    "analytics": "#7b4fc0",
    "admin": "#7a869a",
    "replication": "#8a94a6",
}

# Icon colors, by AWS service category.
ICON = {
    "compute": "#ed7100",
    "database": "#3b48cc",
    "storage": "#3f8624",
    "integration": "#e7157b",
    "analytics": "#8c4fff",
    "security": "#dd344c",
    "network": "#8c4fff",
    "management": "#e7157b",
    "external": "#5b6676",
}


@dataclass
class Card:
    x: float
    y: float
    title: str
    sub: str = ""
    flow: str = "admin"
    icon: str = "external"
    tag: str = ""
    w: float = 300
    h: float = 66
    dashed: bool = False

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def left(self, dy: float = 0) -> tuple[float, float]:
        return (self.x, self.cy + dy)

    def right(self, dy: float = 0) -> tuple[float, float]:
        return (self.x + self.w, self.cy + dy)

    def top(self, dx: float = 0) -> tuple[float, float]:
        return (self.cx + dx, self.y)

    def bottom(self, dx: float = 0) -> tuple[float, float]:
        return (self.cx + dx, self.y + self.h)


@dataclass
class Svg:
    width: float
    height: float
    parts: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)

    def add(self, text: str) -> None:
        self.parts.append(text)

    def text(self, x, y, s, size=13, weight="normal", color=INK, anchor="start"):
        self.add(
            f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'fill="{color}" text-anchor="{anchor}">{escape(s)}</text>'
        )

    def box(self, x, y, w, h, fill="#ffffff", stroke="#d5dbe5", rx=10, dash=False, width=1.2):
        d = ' stroke-dasharray="6 5"' if dash else ""
        self.add(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{width}"{d}/>'
        )

    def card(self, c: Card) -> None:
        color = FLOW[c.flow]
        self.add(
            f'<rect x="{c.x}" y="{c.y}" width="{c.w}" height="{c.h}" rx="8" fill="#ffffff" '
            f'stroke="#d5dbe5" stroke-width="1"{" stroke-dasharray=\"6 5\"" if c.dashed else ""} '
            'filter="url(#shadow)"/>'
        )
        self.add(f'<rect x="{c.x}" y="{c.y}" width="5" height="{c.h}" rx="2" fill="{color}"/>')
        ix, iy = c.x + 16, c.cy - 14
        self.add(f'<rect x="{ix}" y="{iy}" width="28" height="28" rx="6" fill="{ICON[c.icon]}"/>')
        tag = c.tag or c.title[:2]
        size = 11 if len(tag) <= 2 else 8.5
        self.text(ix + 14, iy + 18 if len(tag) <= 2 else iy + 17.5, tag, size=size, weight="bold", color="#ffffff", anchor="middle")
        lines = c.sub.split("\n") if c.sub else []
        ty = c.cy - 6 * len(lines) + 4
        self.text(c.x + 54, ty, c.title, size=13, weight="bold")
        for i, line in enumerate(lines):
            self.text(c.x + 54, ty + 16 + 14 * i, line, size=11, color=MUTED)

    def arrow(self, points, flow, label="", at=0, dashed=False, both=False, lx=0.0, ly=0.0, start_dot=True):
        color = FLOW[flow]
        pts = " ".join(f"{x},{y}" for x, y in points)
        d = ' stroke-dasharray="7 5"' if dashed else ""
        start = f' marker-start="url(#head-{flow})"' if both else ""
        self.add(
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.2" '
            f'stroke-linejoin="round"{d}{start} marker-end="url(#head-{flow})"/>'
        )
        if start_dot and not both:
            x, y = points[0]
            self.add(f'<circle cx="{x}" cy="{y}" r="3.5" fill="{color}"/>')
        if label:
            (x1, y1), (x2, y2) = points[at], points[at + 1]
            x, y = (x1 + x2) / 2 + lx, (y1 + y2) / 2 + ly
            w = 6.6 * len(label) + 10
            self.labels.append(
                f'<rect x="{x - w / 2}" y="{y - 9}" width="{w}" height="17" rx="4" fill="{PAPER}" opacity="0.95"/>'
                f'<text x="{x}" y="{y + 4}" font-size="11" font-weight="bold" fill="{color}" '
                f'text-anchor="middle">{escape(label)}</text>'
            )

    def svg(self) -> str:
        heads = "".join(
            f'<marker id="head-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{v}"/></marker>'
            for k, v in FLOW.items()
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}" font-family="{FONT}">'
            f'<defs>{heads}<filter id="shadow" x="-5%" y="-5%" width="110%" height="120%">'
            '<feDropShadow dx="0" dy="1" stdDeviation="1.5" flood-opacity="0.12"/></filter></defs>'
            f'<rect width="100%" height="100%" fill="{PAPER}"/>'
            + "".join(self.parts)
            + "".join(self.labels)
            + "</svg>"
        )


def panel(s: Svg, x, y, w, h, title, rows):
    """A titled box of (icon, tag, title, sub) rows, two columns when wide."""
    s.box(x, y, w, h, fill="#e9eef6", stroke="#cdd6e3")
    s.text(x + w / 2, y + 22, title, size=13, weight="bold", anchor="middle")
    cols = 2 if w > 600 else 1
    cw = (w - 20 - 10 * (cols - 1)) / cols
    for i, (icon, tag, t, sub) in enumerate(rows):
        cx = x + 10 + (i % cols) * (cw + 10)
        cy = y + 36 + (i // cols) * 50
        s.box(cx, cy, cw, 44, rx=6, stroke="#dde3ec")
        s.add(f'<rect x="{cx + 8}" y="{cy + 10}" width="24" height="24" rx="5" fill="{ICON[icon]}"/>')
        s.text(cx + 20, cy + 26, tag, size=8 if len(tag) > 2 else 10, weight="bold", color="#ffffff", anchor="middle")
        s.text(cx + 40, cy + 19, t, size=12, weight="bold")
        s.text(cx + 40, cy + 34, sub, size=10.5, color=MUTED)


def legend(s: Svg, x, y, w, h, items, note):
    s.box(x, y, w, h, fill="#e9eef6", stroke="#cdd6e3")
    s.text(x + w / 2, y + 22, "Cómo leerlo" if note.startswith("≈") else "How to read it", size=13, weight="bold", anchor="middle")
    for i, (flow, text, dashed) in enumerate(items):
        yy = y + 44 + i * 19
        d = ' stroke-dasharray="7 5"' if dashed else ""
        s.add(f'<line x1="{x + 14}" y1="{yy}" x2="{x + 44}" y2="{yy}" stroke="{FLOW[flow]}" stroke-width="3"{d}/>')
        s.text(x + 54, yy + 4, text, size=11)
    s.box(x + 12, y + h - 38, w - 24, 26, rx=6, stroke="#dde3ec")
    s.text(x + w / 2, y + h - 21, note, size=11, weight="bold", anchor="middle")


def render(svg: str, out: Path, scale: float = 2.0) -> None:
    """Keep the SVG beside this script and screenshot it into `out`.

    Uses Node's Playwright (`npx playwright` or a global install) and its
    Chromium, so no Python package is needed.
    """
    import json
    import subprocess

    src = Path(__file__).parent / f"{out.stem}.svg"
    src.write_text(svg, encoding="utf-8")
    kind = "jpeg" if out.suffix == ".jpg" else "png"
    script = f"""
const {{ chromium }} = require('playwright');
(async () => {{
  const browser = await chromium.launch();
  const page = await browser.newPage({{ deviceScaleFactor: {scale} }});
  const svg = require('fs').readFileSync({json.dumps(str(src))}, 'utf8');
  await page.setContent('<html><body style="margin:0">' + svg + '</body></html>');
  await page.locator('svg').first().screenshot({{ path: {json.dumps(str(out))}, type: '{kind}'{", quality: 92" if kind == "jpeg" else ""} }});
  await browser.close();
}})();
"""
    subprocess.run(["node", "-e", script], check=True)
