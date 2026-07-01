#!/usr/bin/env python3
"""Render Part B markdown -> PDF with native vector diagrams (reportlab)."""
import re
import sys
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Preformatted, ListFlowable, ListItem, KeepTogether,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon, Ellipse, PolyLine

SRC, OUT = sys.argv[1], sys.argv[2]

INK = colors.HexColor("#1b1b1d")
ACC = colors.HexColor("#2f5d8a")
GRN = colors.HexColor("#2f7a55")
MUT = colors.HexColor("#5b6470")
LINE = colors.HexColor("#9aa4b0")
RULE = colors.HexColor("#cdd3da")
CODEBG = colors.HexColor("#f4f5f7")
HEADBG = colors.HexColor("#eef2f6")
F_BLUE = colors.HexColor("#e7eef6")
F_GRN = colors.HexColor("#e5f0ea")
F_GRY = colors.HexColor("#eef0f2")
F_AMB = colors.HexColor("#fbf0da")

ss = getSampleStyleSheet()
body = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica",
                      fontSize=9.4, leading=13.8, textColor=INK, spaceAfter=6)
h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                    fontSize=16, leading=20, textColor=INK, spaceBefore=15, spaceAfter=7)
h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                    fontSize=12, leading=15, textColor=ACC, spaceBefore=11, spaceAfter=4)
h3 = ParagraphStyle("h3", parent=ss["Heading3"], fontName="Helvetica-Bold",
                    fontSize=10.3, leading=13, textColor=INK, spaceBefore=7, spaceAfter=3)
quote = ParagraphStyle("quote", parent=body, leftIndent=10, textColor=MUT,
                       fontName="Helvetica-Oblique")
cap = ParagraphStyle("cap", parent=body, fontSize=8, leading=10.5, textColor=MUT,
                     fontName="Helvetica-Oblique", spaceBefore=3, spaceAfter=10, alignment=1)
cell = ParagraphStyle("cell", parent=body, fontSize=8.3, leading=11, spaceAfter=0)
cellh = ParagraphStyle("cellh", parent=cell, fontName="Helvetica-Bold")
code = ParagraphStyle("code", parent=ss["Code"], fontName="Courier", fontSize=7.6,
                      leading=10, textColor=INK, backColor=CODEBG, borderPadding=6,
                      spaceAfter=8, spaceBefore=2)


def esc(t):
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`(.+?)`", r'<font face="Courier" size="8">\1</font>', t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", t)
    return t


def _wrap(text, maxc):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= maxc:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def box(d, x, y, w, h, text, fill, tcol=INK, fs=8.2, bold=True, stroke=ACC):
    d.add(Rect(x, y, w, h, rx=5, ry=5, fillColor=fill, strokeColor=stroke, strokeWidth=1))
    lines = _wrap(text, max(6, int(w / (fs * 0.53))))
    fh = fs + 2.2
    ty = y + h / 2 + (len(lines) - 1) * fh / 2 - fs / 2 + 1
    for ln in lines:
        d.add(String(x + w / 2, ty, ln, fontSize=fs, fillColor=tcol,
                     fontName="Helvetica-Bold" if bold else "Helvetica", textAnchor="middle"))
        ty -= fh


def gnode(d, cx, cy, w, h, text, fill, dashed=False, fs=7.8):
    e = Ellipse(cx, cy, w / 2, h / 2, fillColor=fill, strokeColor=ACC, strokeWidth=1.1)
    if dashed:
        e.strokeDashArray = [3, 2]; e.strokeColor = MUT
    d.add(e)
    lines = _wrap(text, max(6, int(w / (fs * 0.5))))
    fh = fs + 1.6
    ty = cy + (len(lines) - 1) * fh / 2 - fs / 2 + 1
    for ln in lines:
        d.add(String(cx, ty, ln, fontSize=fs, fillColor=INK, fontName="Helvetica", textAnchor="middle"))
        ty -= fh


def arrow(d, x1, y1, x2, y2, label=None, dashed=False, col=LINE, lw=1.1, lcol=MUT, lfs=7):
    import math
    ln = Line(x1, y1, x2, y2, strokeColor=col, strokeWidth=lw)
    if dashed:
        ln.strokeDashArray = [3, 2]
    d.add(ln)
    ang = math.atan2(y2 - y1, x2 - x1); a = 5.5
    d.add(Polygon([x2, y2, x2 - a * math.cos(ang - 0.4), y2 - a * math.sin(ang - 0.4),
                   x2 - a * math.cos(ang + 0.4), y2 - a * math.sin(ang + 0.4)],
                  fillColor=col, strokeColor=col))
    if label:
        d.add(String((x1 + x2) / 2, (y1 + y2) / 2 + 3, label, fontSize=lfs, fillColor=lcol, textAnchor="middle"))


def fig_loop():
    d = Drawing(468, 118); ys, w = 52, 110
    labels = [("Crawler acts", F_BLUE), ("Observer snapshots", F_GRY),
              ("Reasoner (graph)", F_BLUE), ("Validator + Ingestor", F_GRN)]
    xs = [8, 122, 236, 350]
    for (t, f), x in zip(labels, xs):
        box(d, x, ys, w, 40, t, f, fs=8.2)
    for k in range(3):
        arrow(d, xs[k] + w, ys + 20, xs[k + 1], ys + 20)
    d.add(Line(xs[3] + w / 2, ys, xs[3] + w / 2, ys - 16, strokeColor=ACC, strokeWidth=1.1))
    d.add(Line(xs[3] + w / 2, ys - 16, xs[0] + w / 2, ys - 16, strokeColor=ACC, strokeWidth=1.1))
    arrow(d, xs[0] + w / 2, ys - 16, xs[0] + w / 2, ys, col=ACC)
    d.add(String(234, ys - 26, "graph plans the next experiment", fontSize=7, fillColor=ACC, textAnchor="middle"))
    return d


def fig_agents():
    d = Drawing(468, 232)
    box(d, 356, 150, 104, 42, "Graph (Neo4j)", F_GRN, fs=8.6, stroke=GRN)
    box(d, 8, 96, 336, 34, "Agent harness  -  state, retries, replay, HITL, output schemas", F_AMB, fs=8.2, stroke=colors.HexColor("#c99a3a"))
    box(d, 40, 176, 130, 34, "Planner (what to test next)", F_BLUE, fs=7.8)
    box(d, 190, 176, 130, 34, "Reasoner (graph gaps)", F_BLUE, fs=7.8)
    bx = [8, 92, 176, 260, 344]
    names = ["Crawler", "Observer", "Validator", "Safety veto", "Ingestor"]
    fills = [F_BLUE, F_GRY, F_GRN, F_AMB, F_GRN]
    for x, nm, f in zip(bx, names, fills):
        box(d, x, 40, 78, 30, nm, f, fs=7.8)
        arrow(d, x + 39, 70, x + 39, 96)
    arrow(d, 105, 176, 105, 130); arrow(d, 255, 176, 255, 130)
    arrow(d, 320, 193, 356, 178, label="Query Machine", col=ACC, lcol=ACC, lfs=6.6)
    arrow(d, 383, 70, 400, 150, label="only writer", col=GRN, lcol=GRN, lfs=6.6)
    d.add(String(234, 20, "Only the Ingestor writes graph truth; nothing is 'validated' without the Validator.",
                 fontSize=7, fillColor=MUT, textAnchor="middle"))
    return d


def fig_sample_graph():
    d = Drawing(468, 250)
    gnode(d, 74, 212, 96, 28, "Run  commit a14f", F_GRY)
    gnode(d, 74, 150, 112, 32, "Observation shopping_cart", F_GRY)
    gnode(d, 214, 208, 96, 28, "add_to_cart", F_GRN)
    gnode(d, 214, 150, 112, 32, "change_quantity", F_GRN)
    gnode(d, 384, 150, 92, 34, "subtotal (observed, not validated)", colors.white, dashed=True)
    gnode(d, 214, 92, 104, 28, "proceed_to_checkout", F_GRN)
    gnode(d, 384, 92, 96, 28, "checkout_boundary", F_GRN)
    gnode(d, 300, 38, 156, 30, "Scenario: quantity -> subtotal", F_BLUE)
    arrow(d, 74, 198, 74, 166, label="OBSERVED", col=LINE, lfs=6.4)
    for ty, tx in [(208, 172), (150, 162), (92, 168)]:
        arrow(d, 122, 150, tx, ty, label="SAW", col=LINE, lfs=6)
    arrow(d, 262, 150, 340, 150, label="SHOULD_CAUSE (gap)", dashed=True, col=MUT, lcol=colors.HexColor("#b04a3a"), lfs=6.4)
    arrow(d, 258, 92, 338, 92, label="reached", col=GRN, lcol=GRN, lfs=6.4)
    arrow(d, 300, 53, 224, 136, label="DEPENDS_ON", col=LINE, lfs=6)
    arrow(d, 362, 53, 384, 135, label="DEPENDS_ON", col=LINE, lfs=6)
    return d


def fig_query_machine():
    d = Drawing(468, 210)
    box(d, 8, 150, 96, 40, "Agent (LLM)", F_BLUE, fs=8.4)
    d.add(Rect(140, 30, 190, 165, rx=6, ry=6, fillColor=colors.HexColor("#f7f9fb"), strokeColor=ACC, strokeWidth=1.2))
    d.add(String(235, 182, "Query Machine", fontSize=8.6, fillColor=ACC, fontName="Helvetica-Bold", textAnchor="middle"))
    box(d, 150, 148, 170, 24, "1 - Typed Cypher templates (tools)", F_GRN, fs=7.4)
    box(d, 150, 116, 170, 24, "2 - Guarded NL to Cypher (read-only)", F_AMB, fs=7.4)
    box(d, 150, 84, 170, 24, "3 - Hybrid graph + vector", F_BLUE, fs=7.4)
    box(d, 150, 46, 170, 24, "validate, cost cap, log", F_GRY, fs=7.4)
    box(d, 360, 128, 100, 34, "Neo4j", F_GRN, fs=8.2, stroke=GRN)
    box(d, 360, 80, 100, 30, "pgvector", F_BLUE, fs=8)
    arrow(d, 104, 176, 140, 164, label="typed tool call", col=ACC, lcol=ACC, lfs=6.4)
    arrow(d, 140, 150, 104, 150, col=LINE)
    d.add(String(120, 138, "typed rows", fontSize=6, fillColor=MUT, textAnchor="middle"))
    arrow(d, 320, 150, 360, 145, col=LINE); arrow(d, 320, 92, 360, 94, col=LINE)
    return d


def fig_decay():
    d = Drawing(468, 150)
    ox, oy, w, h = 44, 28, 396, 96
    d.add(Line(ox, oy, ox, oy + h, strokeColor=MUT)); d.add(Line(ox, oy, ox + w, oy, strokeColor=MUT))
    d.add(String(ox - 4, oy + h - 4, "confidence", fontSize=7, fillColor=MUT, textAnchor="end"))
    d.add(String(ox + w, oy - 10, "runs ->", fontSize=7, fillColor=MUT, textAnchor="end"))
    thr = oy + 0.42 * h
    tl = Line(ox, thr, ox + w, thr, strokeColor=colors.HexColor("#b04a3a"), strokeWidth=0.8); tl.strokeDashArray = [3, 2]
    d.add(tl); d.add(String(ox + w, thr + 3, "retest line", fontSize=6.6, fillColor=colors.HexColor("#b04a3a"), textAnchor="end"))
    top = oy + 0.92 * h
    pts = [(ox, top), (ox + 70, thr + 6), (ox + 118, thr - 8), (ox + 148, top),
           (ox + 216, thr + 4), (ox + 246, top), (ox + 326, thr - 2), (ox + 356, top), (ox + 426, thr + 8)]
    d.add(PolyLine([c for p in pts for c in p], strokeColor=ACC, strokeWidth=1.6))
    for (x, y) in [(ox + 148, top), (ox + 246, top), (ox + 356, top)]:
        d.add(Ellipse(x, y, 2.4, 2.4, fillColor=GRN, strokeColor=GRN))
    d.add(String(ox + 246, top + 6, "reconfirmed", fontSize=6.4, fillColor=GRN, textAnchor="middle"))
    return d


def fig_eval():
    d = Drawing(468, 150)
    box(d, 8, 96, 118, 32, "Offline golden sets", F_GRY, fs=8)
    box(d, 8, 54, 118, 32, "Online prod sampling", F_GRY, fs=8)
    box(d, 156, 72, 130, 40, "Grader: deterministic where possible, calibrated LLM-judge where not", F_BLUE, fs=7.4)
    box(d, 314, 72, 100, 40, "Calibration ECE/Brier + canary gate", F_AMB, fs=7.4, stroke=colors.HexColor("#c99a3a"))
    box(d, 314, 16, 100, 28, "model / prompt change", colors.white, fs=7.2, stroke=MUT)
    arrow(d, 126, 112, 156, 98); arrow(d, 126, 70, 156, 86)
    arrow(d, 286, 92, 314, 92)
    arrow(d, 364, 44, 364, 72, label="canary", col=ACC, lcol=ACC, lfs=6.4)
    arrow(d, 414, 92, 452, 92, label="ship", col=GRN, lcol=GRN, lfs=6.4)
    return d


FIGS = {"loop": fig_loop, "agents": fig_agents, "sample_graph": fig_sample_graph,
        "query_machine": fig_query_machine, "decay": fig_decay, "eval": fig_eval}


def split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def make_table(rows):
    header, *data = rows
    tbl = [[Paragraph(esc(c), cellh) for c in header]]
    for r in data:
        tbl.append([Paragraph(esc(c), cell) for c in r])
    ncol = len(header)
    t = Table(tbl, colWidths=[468.0 / ncol] * ncol, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADBG),
        ("GRID", (0, 0), (-1, -1), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    return t


lines = open(SRC, encoding="utf-8").read().split("\n")
flow, i, n = [], 0, len(lines)
while i < n:
    ln = lines[i]
    m = re.match(r"\[\[FIG:([a-z_]+)\|(.+)\]\]", ln.strip())
    if m and m.group(1) in FIGS:
        flow.append(KeepTogether([Spacer(1, 4), FIGS[m.group(1)](), Paragraph(esc(m.group(2)), cap)]))
        i += 1; continue
    if ln.startswith("```"):
        buf = []; i += 1
        while i < n and not lines[i].startswith("```"):
            buf.append(lines[i]); i += 1
        flow.append(Preformatted("\n".join(buf), code)); i += 1; continue
    if re.match(r"^\|.*\|", ln) and i + 1 < n and re.match(r"^\|[\s:|-]+\|", lines[i + 1]):
        rows = [split_row(ln)]; i += 2
        while i < n and re.match(r"^\|.*\|", lines[i]):
            rows.append(split_row(lines[i])); i += 1
        flow.append(make_table(rows)); flow.append(Spacer(1, 6)); continue
    if ln.startswith("### "):
        flow.append(Paragraph(esc(ln[4:]), h3))
    elif ln.startswith("## "):
        flow.append(Paragraph(esc(ln[3:]), h2))
    elif ln.startswith("# "):
        flow.append(Paragraph(esc(ln[2:]), h1))
    elif ln.strip() == "---":
        flow.append(Spacer(1, 2)); flow.append(HRFlowable(width="100%", color=RULE)); flow.append(Spacer(1, 2))
    elif ln.startswith("> "):
        flow.append(Paragraph(esc(ln[2:]), quote))
    elif re.match(r"^\s*[-*] ", ln):
        items = []
        while i < n and re.match(r"^\s*[-*] ", lines[i]):
            items.append(ListItem(Paragraph(esc(re.sub(r"^\s*[-*] ", "", lines[i])), body), leftIndent=10)); i += 1
        flow.append(ListFlowable(items, bulletType="bullet", start="•", leftIndent=12)); continue
    elif ln.strip():
        para = [ln]; j = i + 1
        while j < n and lines[j].strip() and not (
            lines[j].startswith(("```", "#", ">", "|", "[[")) or lines[j].strip() == "---"
            or re.match(r"^\s*[-*] ", lines[j])):
            para.append(lines[j]); j += 1
        flow.append(Paragraph(esc(" ".join(para)), body)); i = j; continue
    i += 1

doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                        topMargin=17 * mm, bottomMargin=16 * mm,
                        title="Part B - Production Architecture", author="Avijit Kundal")
doc.build(flow)
print("wrote", OUT)
