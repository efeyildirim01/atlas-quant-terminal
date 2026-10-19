"""PDF rendering of a stored report document (fpdf2 + matplotlib). Renders only what the document contains.

Fonts: DejaVu Sans from matplotlib's bundled data. It covers Turkish characters (ş, ğ, ı, İ) and math symbols.
"""

from __future__ import annotations

import io
import os
from datetime import datetime

import matplotlib

matplotlib.use("Agg")  # headless; must precede pyplot import
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.ticker  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from fpdf import FPDF  # noqa: E402
from fpdf.fonts import FontFace  # noqa: E402

FONT_DIR = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
COLORS = ["#2563eb", "#d97706", "#0d9488", "#7c3aed", "#db2777", "#65a30d", "#ea580c", "#0284c7", "#c026d3", "#ca8a04"]
INK, MUTED, RULE, WARN = (15, 23, 42), (100, 116, 139), (203, 213, 225), (180, 83, 9)


def fmt(value, kind: str) -> str:
    """Shared cell formatting contract (mirrored in apps/web/features/reports/format.ts)."""
    if isinstance(value, dict):
        (k, v), = value.items()
        return fmt(v, "pct2" if k == "pct" else "num2")
    if value is None:
        return "—"
    if kind == "text":
        return str(value)
    if kind == "int":
        return f"{int(value):,}"
    if kind.startswith("pct"):
        return f"{value * 100:,.{int(kind[3:])}f}%"
    if kind.startswith("num"):
        return f"{value:,.{int(kind[3:])}f}"
    if kind == "auto":
        return f"{value:,.2f}" if isinstance(value, (int, float)) else str(value)
    return str(value)


def scope_text(scope: dict) -> str:
    parts = []
    for k, v in scope.items():
        if isinstance(v, dict):
            v = " to ".join(str(x) for x in v.values()) if set(v) <= {"start", "end"} else ", ".join(f"{a} {b}" for a, b in v.items())
        elif isinstance(v, list):
            v = ", ".join(map(str, v))
        parts.append(f"{k.replace('_', ' ')}: {v}")
    return " · ".join(parts)


def _clean(text: str) -> str:
    return text.replace("ᵀ", "T").replace(" ", " ")


def _chart_png(chart: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(7.2, 2.6), dpi=150)
    for i, s in enumerate(chart["series"]):
        xs = [datetime.fromisoformat(d) for d in s["dates"]]
        ys = [v if v is not None else float("nan") for v in s["values"]]
        ax.plot(xs, ys, lw=1.4 if i == 0 else 1.0, color=COLORS[i % len(COLORS)], label=s["label"])
    if chart.get("baseline") is not None:
        ax.axhline(chart["baseline"], color="#94a3b8", lw=0.6, ls="--")
    if chart.get("y_format") == "pct":
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v * 100:.0f}%"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=7, colors="#475569")
    ax.grid(True, color="#e2e8f0", lw=0.5)
    if len(chart["series"]) > 1:  # legend below the axes so it never covers data
        ax.legend(fontsize=7, frameon=False, ncol=min(6, len(chart["series"])), loc="upper center", bbox_to_anchor=(0.5, -0.14))
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


class _PDF(FPDF):
    def __init__(self, doc: dict):
        super().__init__(format="A4")
        self.doc = doc
        self.add_font("DejaVu", "", os.path.join(FONT_DIR, "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf"))
        self.set_auto_page_break(True, margin=18)
        self.set_margins(15, 15, 15)

    def footer(self):
        self.set_y(-12)
        self.set_font("DejaVu", "", 7)
        self.set_text_color(*MUTED)
        snap = self.doc["data_snapshot"]
        self.cell(0, 4, _clean(f"ATLAS QUANT TERMINAL · snapshot {snap['snapshot_id']} · data as of {snap['as_of']} · "
                               f"methodology v{self.doc['methodology_version']} · page {self.page_no()}/{{nb}}"), align="C")

    def h1(self, text):
        self.set_font("DejaVu", "B", 16)
        self.set_text_color(*INK)
        self.multi_cell(0, 8, _clean(text), new_x="LMARGIN", new_y="NEXT")

    def h2(self, text, keep: float = 30):
        """Section heading; starts a new page if less than `keep` mm would remain under it (no orphaned headings)."""
        if self.get_y() + keep > self.h - self.b_margin:
            self.add_page()
        self.ln(3)
        self.set_font("DejaVu", "B", 11)
        self.set_text_color(*INK)
        self.cell(0, 6, _clean(text), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def para(self, text, size=9, color=INK):
        self.set_font("DejaVu", "", size)
        self.set_text_color(*color)
        self.multi_cell(0, 4.6, _clean(text), align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def bullets(self, items, color=INK):
        self.set_font("DejaVu", "", 9)
        self.set_text_color(*color)
        for it in items:
            self.set_x(self.l_margin + 2)
            self.multi_cell(0, 4.6, _clean(f"•  {it}"), align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def table_block(self, t: dict):
        cols, kinds = t["columns"], t["formats"]
        avail = self.w - self.l_margin - self.r_margin
        size = 8.5
        while True:
            self.set_font("DejaVu", "B", size)
            head_w = [self.get_string_width(c) for c in cols]
            self.set_font("DejaVu", "", size)
            cell_w = [max((self.get_string_width(_clean(fmt(r[i], kinds[i]))) for r in t["rows"]), default=0) for i in range(len(cols))]
            natural = [max(h, c) + 3.5 for h, c in zip(head_w, cell_w)]
            if sum(natural) <= avail or size <= 6.5:
                break
            size -= 0.5
        if sum(natural) > avail:  # shrink free-text columns first; numbers keep their full width
            text_cols = [i for i, k in enumerate(kinds) if k == "text" and i > 0] or [i for i, k in enumerate(kinds) if k == "text"]
            excess = sum(natural) - avail
            pool = sum(natural[i] for i in text_cols)
            for i in text_cols:
                natural[i] = max(22, natural[i] - excess * natural[i] / pool)
        scale = avail / sum(natural)
        col_w = [w * scale for w in natural]
        self.set_font("DejaVu", "", size)
        self.set_text_color(*INK)
        with self.table(col_widths=col_w, text_align=["LEFT" if k == "text" else "RIGHT" for k in kinds],
                        line_height=4.6, borders_layout="HORIZONTAL_LINES", first_row_as_headings=True,
                        headings_style=FontFace(emphasis="BOLD", color=MUTED, fill_color=(241, 245, 249))) as table:
            head = table.row()
            for c in cols:
                head.cell(_clean(c))
            for r in t["rows"]:
                row = table.row()
                for v, k in zip(r, kinds):
                    row.cell(_clean(fmt(v, k)))
        self.ln(2)


def render(doc: dict) -> bytes:
    pdf = _PDF(doc)
    pdf.set_title(_clean(doc["title"]))
    pdf.set_author("ATLAS QUANT TERMINAL")
    pdf.add_page()
    if doc["data_snapshot"]["is_fixture"]:
        pdf.set_fill_color(254, 243, 199)
        pdf.set_text_color(*WARN)
        pdf.set_font("DejaVu", "B", 8.5)
        pdf.multi_cell(0, 5, "FIXTURE DATA: synthetic development data, not market data. Do not use for investment decisions.", fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_fill_color(255, 255, 255)
        pdf.ln(2)
    pdf.h1(doc["title"])
    pdf.para(f"{doc['subtitle']} · generated {doc['generated_at']} UTC", 9, MUTED)

    snap = doc["data_snapshot"]
    pdf.h2("Data snapshot")
    pdf.para(f"Snapshot id {snap['snapshot_id']} · data as of {snap['as_of']} · data version {', '.join(snap['data_version'])}", 8.5, MUTED)
    pdf.para("Scope: " + scope_text(doc["scope"]), 8.5, MUTED)

    pdf.h2("Executive summary")
    pdf.bullets(doc["executive_summary"])
    for sec in doc["sections"]:
        pdf.h2(sec["heading"], keep=80 if sec.get("chart") else 30)
        for p in sec.get("paragraphs", []):
            pdf.para(p, 8.5, MUTED)
        if sec.get("chart"):
            pdf.image(io.BytesIO(_chart_png(sec["chart"])), w=pdf.w - pdf.l_margin - pdf.r_margin)
            pdf.ln(1)
        if sec.get("table"):
            pdf.table_block(sec["table"])
    pdf.h2("Risk factors")
    pdf.bullets(doc["risk_factors"], WARN)
    pdf.h2("Limitations")
    pdf.bullets(doc["limitations"], MUTED)
    pdf.h2("Methodology")
    pdf.bullets([f"{k}: {v}" for k, v in doc["methodology"].items()], MUTED)
    pdf.h2("Sources")
    pdf.bullets(doc["sources"], MUTED)
    pdf.para(doc["disclaimer"], 8, MUTED)
    return bytes(pdf.output())
