from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Flowable,
)


OUT = "output/pdf/Part_B_Production_Architecture_Improved.pdf"

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
MARGIN_TOP = 18 * mm
MARGIN_BOTTOM = 16 * mm

INK = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#62717F")
BLUE = colors.HexColor("#2563EB")
TEAL = colors.HexColor("#0F766E")
AMBER = colors.HexColor("#B45309")
RED = colors.HexColor("#B91C1C")
GREEN = colors.HexColor("#15803D")
VIOLET = colors.HexColor("#6D28D9")
BG = colors.HexColor("#F7F9FC")
LINE = colors.HexColor("#D8E0EA")


styles = getSampleStyleSheet()
styles.add(ParagraphStyle(
    name="Kicker", fontName="Helvetica-Bold", fontSize=8.5, leading=11,
    textColor=BLUE, spaceAfter=5, uppercase=True,
))
styles.add(ParagraphStyle(
    name="TitleLarge", fontName="Helvetica-Bold", fontSize=25, leading=29,
    textColor=INK, spaceAfter=10,
))
styles.add(ParagraphStyle(
    name="Subtitle", fontName="Helvetica", fontSize=10.5, leading=15,
    textColor=MUTED, spaceAfter=12,
))
styles.add(ParagraphStyle(
    name="Section", fontName="Helvetica-Bold", fontSize=15, leading=18,
    textColor=INK, spaceBefore=10, spaceAfter=7,
))
styles.add(ParagraphStyle(
    name="Subsection", fontName="Helvetica-Bold", fontSize=11.5, leading=14,
    textColor=INK, spaceBefore=8, spaceAfter=5,
))
styles.add(ParagraphStyle(
    name="BodyX", fontName="Helvetica", fontSize=9.2, leading=12.6,
    textColor=INK, spaceAfter=6,
))
styles.add(ParagraphStyle(
    name="Callout", fontName="Helvetica-Bold", fontSize=10.2, leading=14,
    textColor=colors.HexColor("#0F172A"), backColor=colors.HexColor("#EAF2FF"),
    borderColor=colors.HexColor("#BBD2FF"), borderWidth=0.75,
    borderPadding=8, spaceBefore=5, spaceAfter=8,
))
styles.add(ParagraphStyle(
    name="Caption", fontName="Helvetica-Oblique", fontSize=7.8, leading=10,
    textColor=MUTED, alignment=TA_CENTER, spaceBefore=4, spaceAfter=8,
))
styles.add(ParagraphStyle(
    name="Cell", fontName="Helvetica", fontSize=7.6, leading=9.4,
    textColor=INK, alignment=TA_LEFT,
))
styles.add(ParagraphStyle(
    name="CellBold", fontName="Helvetica-Bold", fontSize=7.6, leading=9.4,
    textColor=INK, alignment=TA_LEFT,
))


def P(text, style="BodyX"):
    return Paragraph(text, styles[style])


class HeaderFooterDoc(BaseDocTemplate):
    def __init__(self, filename):
        super().__init__(
            filename, pagesize=A4,
            leftMargin=MARGIN_X, rightMargin=MARGIN_X,
            topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
        )
        frame = Frame(
            self.leftMargin, self.bottomMargin,
            self.width, self.height,
            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        )
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=self.decorate)])

    def decorate(self, canvas, doc):
        canvas.saveState()
        if doc.page > 1:
            canvas.setStrokeColor(LINE)
            canvas.line(MARGIN_X, PAGE_H - 12 * mm, PAGE_W - MARGIN_X, PAGE_H - 12 * mm)
            canvas.setFont("Helvetica-Bold", 7.5)
            canvas.setFillColor(MUTED)
            canvas.drawString(MARGIN_X, PAGE_H - 9.5 * mm, "Part B - Production Architecture")
            canvas.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 9.5 * mm, f"{doc.page}")
        canvas.restoreState()


class PillBox(Flowable):
    def __init__(self, text, color=BLUE, w=55*mm, h=13*mm, font=7.5):
        super().__init__()
        self.text, self.color, self.w, self.h, self.font = text, color, w, h, font

    def wrap(self, aw, ah):
        return self.w, self.h

    def draw(self):
        c = self.canv
        c.setFillColor(colors.white)
        c.setStrokeColor(self.color)
        c.roundRect(0, 0, self.w, self.h, 4, fill=1, stroke=1)
        c.setFillColor(self.color)
        c.setFont("Helvetica-Bold", self.font)
        c.drawCentredString(self.w/2, self.h/2 - self.font/2 + 2.2, self.text)


def arrow(c, x1, y1, x2, y2, color=LINE):
    c.setStrokeColor(color)
    c.setLineWidth(1.2)
    c.line(x1, y1, x2, y2)
    import math
    a = math.atan2(y2-y1, x2-x1)
    for da in (2.65, -2.65):
        c.line(x2, y2, x2 + 5*math.cos(a+da), y2 + 5*math.sin(a+da))


def centered_lines(c, x, y, text, font="Helvetica-Bold", size=7, leading=8, fill=INK):
    lines = text.split("|")
    c.setFillColor(fill)
    c.setFont(font, size)
    start = y + (len(lines) - 1) * leading / 2
    for i, line in enumerate(lines):
        c.drawCentredString(x, start - i * leading, line)


class CoreLoopDiagram(Flowable):
    def __init__(self, w):
        self.w, self.h = w, 52*mm
        super().__init__()

    def wrap(self, aw, ah):
        return self.w, self.h

    def draw_node(self, x, y, title, sub, color):
        c = self.canv
        c.setFillColor(colors.white)
        c.setStrokeColor(color)
        c.roundRect(x, y, 43*mm, 17*mm, 5, fill=1, stroke=1)
        c.setFillColor(color)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(x+21.5*mm, y+10.5*mm, title)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.5)
        c.drawCentredString(x+21.5*mm, y+5*mm, sub)

    def draw(self):
        c = self.canv
        y = 21*mm
        xs = [0, 49*mm, 98*mm, 147*mm]
        nodes = [
            ("Reasoner", "graph plans", VIOLET),
            ("Crawler", "browser acts", BLUE),
            ("Observer", "captures evidence", TEAL),
            ("Validator + Ingestor", "checks, then writes", GREEN),
        ]
        for x, n in zip(xs, nodes):
            self.draw_node(x, y, *n)
        for x in xs[:-1]:
            arrow(c, x+43*mm, y+8.5*mm, x+49*mm, y+8.5*mm, colors.HexColor("#9AA8B6"))
        arrow(c, xs[-1]+21*mm, y, xs[0]+21*mm, y-14*mm, colors.HexColor("#9AA8B6"))
        arrow(c, xs[0]+21*mm, y-14*mm, xs[0]+21*mm, y, colors.HexColor("#9AA8B6"))
        c.setFillColor(MUTED)
        c.setFont("Helvetica-Oblique", 7)
        c.drawCentredString(self.w/2, 3*mm, "Loop: plan the next experiment, act, validate independently, write memory, reason again.")


class HarnessDiagram(Flowable):
    def __init__(self, w):
        self.w, self.h = w, 70*mm
        super().__init__()

    def wrap(self, aw, ah):
        return self.w, self.h

    def box(self, x, y, w, h, title, color, fill=colors.white):
        c = self.canv
        c.setFillColor(fill)
        c.setStrokeColor(color)
        c.roundRect(x, y, w, h, 5, fill=1, stroke=1)
        c.setFillColor(color)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawCentredString(x+w/2, y+h/2-2.5, title)

    def draw(self):
        c = self.canv
        self.box(69*mm, 26*mm, 62*mm, 24*mm, "Agent harness", INK, colors.HexColor("#F3F6FA"))
        for label, x, y, col in [
            ("Planner", 0, 50*mm, VIOLET), ("Reasoner", 69*mm, 54*mm, VIOLET),
            ("Crawler", 6*mm, 8*mm, BLUE),
            ("Observer", 48*mm, 4*mm, TEAL), ("Validator", 94*mm, 4*mm, GREEN),
            ("Safety veto", 132*mm, 8*mm, RED), ("Ingestor", 154*mm, 30*mm, AMBER),
        ]:
            self.box(x, y, 34*mm, 12*mm, label, col)
        self.box(120*mm, 50*mm, 30*mm, 12*mm, "Query Machine", TEAL)
        self.box(156*mm, 54*mm, 34*mm, 12*mm, "Neo4j graph", colors.HexColor("#475569"), colors.HexColor("#EEF2F7"))
        for sx, sy, ex, ey in [
            (34*mm, 56*mm, 69*mm, 43*mm), (103*mm, 54*mm, 100*mm, 50*mm),
            (150*mm, 56*mm, 156*mm, 60*mm), (86*mm, 26*mm, 23*mm, 20*mm),
            (88*mm, 26*mm, 65*mm, 16*mm), (106*mm, 26*mm, 111*mm, 16*mm),
            (131*mm, 34*mm, 132*mm, 20*mm), (131*mm, 42*mm, 154*mm, 36*mm),
            (174*mm, 42*mm, 168*mm, 54*mm),
        ]:
            arrow(c, sx, sy, ex, ey, colors.HexColor("#9AA8B6"))
        c.setFillColor(MUTED)
        c.setFont("Helvetica-Oblique", 7)
        c.drawCentredString(self.w/2, 0, "Only the Ingestor writes graph truth; nothing becomes validated without the Validator.")


class GraphDiagram(Flowable):
    def __init__(self, w):
        self.w, self.h = w, 60*mm
        super().__init__()

    def wrap(self, aw, ah):
        return self.w, self.h

    def node(self, x, y, label, color, dashed=False):
        c = self.canv
        c.setFillColor(colors.white)
        c.setStrokeColor(color)
        c.setDash(3, 2) if dashed else c.setDash()
        c.circle(x, y, 10*mm, fill=1, stroke=1)
        c.setDash()
        c.setFillColor(color)
        c.setFont("Helvetica-Bold", 6.6)
        lines = label.split("|")
        for i, line in enumerate(lines):
            c.drawCentredString(x, y + (len(lines)-1-i)*3.5 - 2, line)

    def draw(self):
        c = self.canv
        pts = {
            "run": (20*mm, 40*mm), "obs": (62*mm, 28*mm), "cart": (102*mm, 43*mm),
            "qty": (101*mm, 14*mm), "subtotal": (145*mm, 30*mm), "checkout": (178*mm, 14*mm),
            "scenario": (42*mm, 5*mm),
        }
        for a, b, label in [
            ("run", "obs", "OBSERVED"), ("obs", "cart", "SAW"), ("obs", "qty", "SAW"),
            ("qty", "subtotal", "SHOULD_CAUSE"), ("scenario", "qty", "DEPENDS_ON"),
            ("scenario", "checkout", "DEPENDS_ON"),
        ]:
            x1, y1 = pts[a]; x2, y2 = pts[b]
            arrow(c, x1, y1, x2, y2, colors.HexColor("#9AA8B6"))
            c.setFont("Helvetica", 5.8)
            c.setFillColor(MUTED)
            c.drawCentredString((x1+x2)/2, (y1+y2)/2+3, label)
        self.node(*pts["run"], "Run|a14f", BLUE)
        self.node(*pts["obs"], "Observation|cart", TEAL)
        self.node(*pts["cart"], "add to|cart", GREEN)
        self.node(*pts["qty"], "change|quantity", GREEN)
        self.node(*pts["subtotal"], "subtotal|gap", AMBER, True)
        self.node(*pts["checkout"], "checkout|boundary", GREEN)
        self.node(*pts["scenario"], "quantity to|subtotal", VIOLET)


class QueryDiagram(Flowable):
    def __init__(self, w):
        self.w, self.h = w, 54*mm
        super().__init__()

    def wrap(self, aw, ah):
        return self.w, self.h

    def draw(self):
        c = self.canv
        def rect(x, y, w, h, label, col, fill=colors.white):
            c.setFillColor(fill); c.setStrokeColor(col)
            c.roundRect(x, y, w, h, 5, fill=1, stroke=1)
            centered_lines(c, x+w/2, y+h/2-1, label, size=6.7, leading=7.5, fill=col)
        rect(0, 22*mm, 34*mm, 15*mm, "Agent|LLM", BLUE)
        rect(51*mm, 14*mm, 65*mm, 31*mm, "Query Machine", INK, colors.HexColor("#F3F6FA"))
        rect(128*mm, 38*mm, 62*mm, 11*mm, "1. typed Cypher templates", TEAL)
        rect(128*mm, 22*mm, 62*mm, 11*mm, "2. guarded NL to Cypher", AMBER)
        rect(128*mm, 6*mm, 62*mm, 11*mm, "3. graph + vector lookup", VIOLET)
        rect(60*mm, 0, 46*mm, 10*mm, "validate, cap, log", RED)
        rect(24*mm, 0, 28*mm, 10*mm, "typed rows", GREEN)
        rect(154*mm, 0, 28*mm, 10*mm, "Neo4j|pgvector", colors.HexColor("#475569"))
        arrow(c, 34*mm, 29*mm, 51*mm, 29*mm)
        for y in [43.5*mm, 27.5*mm, 11.5*mm]:
            arrow(c, 116*mm, 29*mm, 128*mm, y)
        arrow(c, 154*mm, 6*mm, 106*mm, 5*mm)
        arrow(c, 60*mm, 5*mm, 52*mm, 5*mm)
        arrow(c, 24*mm, 5*mm, 17*mm, 22*mm)


class ConfidenceChart(Flowable):
    def __init__(self, w):
        self.w, self.h = w, 42*mm
        super().__init__()

    def wrap(self, aw, ah):
        return self.w, self.h

    def draw(self):
        c = self.canv
        x0, y0, ww, hh = 16*mm, 8*mm, self.w-32*mm, 28*mm
        c.setStrokeColor(LINE); c.rect(x0, y0, ww, hh, fill=0, stroke=1)
        c.setStrokeColor(RED); c.setDash(4, 3); c.line(x0, y0+10*mm, x0+ww, y0+10*mm); c.setDash()
        c.setFillColor(RED); c.setFont("Helvetica-Bold", 6.5); c.drawString(x0+2, y0+10*mm+3, "retest line")
        pts = []
        vals = [0.92, 0.78, 0.64, 0.53, 0.95, 0.80, 0.66, 0.52, 0.41, 0.94]
        for i, v in enumerate(vals):
            x = x0 + i * ww/(len(vals)-1)
            y = y0 + v*hh
            pts.append((x, y))
        c.setStrokeColor(BLUE); c.setLineWidth(2)
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            c.line(x1, y1, x2, y2)
        c.setFillColor(BLUE)
        for x, y in pts:
            c.circle(x, y, 2.2, fill=1, stroke=0)
        c.setFillColor(MUTED); c.setFont("Helvetica", 7)
        c.drawCentredString(x0+ww/2, 1*mm, "runs ->")
        c.drawString(0, y0+hh-3, "confidence")
        c.setFillColor(GREEN); c.setFont("Helvetica-Bold", 7)
        c.drawString(pts[4][0]-12, pts[4][1]+6, "reconfirmed")
        c.drawString(pts[9][0]-12, pts[9][1]+6, "reconfirmed")


class EvalDiagram(Flowable):
    def __init__(self, w):
        self.w, self.h = w, 48*mm
        super().__init__()

    def wrap(self, aw, ah):
        return self.w, self.h

    def draw(self):
        c = self.canv
        def r(x, y, w, h, label, col):
            c.setFillColor(colors.white); c.setStrokeColor(col); c.roundRect(x, y, w, h, 5, fill=1, stroke=1)
            centered_lines(c, x+w/2, y+h/2-1, label, size=6.5, leading=7.3, fill=col)
        r(0, 31*mm, 45*mm, 12*mm, "Offline golden|apps", BLUE)
        r(0, 8*mm, 45*mm, 12*mm, "Online prod|sampling", TEAL)
        r(68*mm, 18*mm, 56*mm, 18*mm, "Grader|deterministic where possible|calibrated judge where not", INK)
        r(146*mm, 23*mm, 43*mm, 12*mm, "Calibration|ECE / Brier", AMBER)
        r(146*mm, 5*mm, 43*mm, 12*mm, "Canary gate|ship / hold", GREEN)
        arrow(c, 45*mm, 37*mm, 68*mm, 29*mm); arrow(c, 45*mm, 14*mm, 68*mm, 25*mm)
        arrow(c, 124*mm, 27*mm, 146*mm, 29*mm); arrow(c, 167*mm, 23*mm, 167*mm, 17*mm)


def styled_table(rows, widths=None, header=True):
    data = []
    for ridx, row in enumerate(rows):
        data.append([P(str(c), "CellBold" if ridx == 0 and header else "Cell") for c in row])
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG]),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF7")),
            ("TEXTCOLOR", (0, 0), (-1, 0), INK),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#B8C5D6")),
        ]
    t.setStyle(TableStyle(style))
    return t


def section(story, title):
    story.append(P(title, "Section"))


def bullets(story, items):
    for item in items:
        story.append(P(f"&bull; {item}", "BodyX"))


def build():
    doc = HeaderFooterDoc(OUT)
    story = []
    width = PAGE_W - 2*MARGIN_X

    story += [
        P("Production architecture", "Kicker"),
        P("Part B - Production Architecture", "TitleLarge"),
        P("Turning the Amazon-checkout prototype into the intelligence layer of an agentic testing platform - the layer between every code change and every confident release.", "Subtitle"),
        P("The architecture is organised around two load-bearing spines: the agent harness and the evaluation layer. Framework choices can change; the contracts, replay model, validation discipline, graph memory, and confidence gates are the parts that must be designed carefully.", "Callout"),
        Spacer(1, 5*mm),
        CoreLoopDiagram(width),
        P("The core loop: the graph plans, the browser acts, the harness validates and writes memory, and the graph reasons over what it learned.", "Caption"),
    ]

    section(story, "0. The one belief this rests on")
    story += [
        P("A browser agent and a knowledge graph have opposite strengths. The browser agent is a probabilistic discovery device: it can find the control that adds to cart on a redesigned page, but it is a poor historian and can be confidently wrong. The graph cannot click anything, but it is structural memory: it records what was observed, what was proven, and what should exist but does not.", "BodyX"),
        P("The design therefore makes confident-wrong states expensive to reach and cheap to detect. The crawler may be wrong; the graph and harness must keep that wrongness from becoming truth.", "Callout"),
    ]

    section(story, "1. The multi-agent network")
    story.append(P("The work is split into small agents with hard boundaries rather than one clever mega-agent. Each agent owns one kind of decision, and the hand-off is a typed contract rather than a shared blob of state.", "BodyX"))
    story.append(styled_table([
        ["Agent", "Owns", "LLM?", "Boundary enforced"],
        ["Planner", "Frontier, priorities, budgets", "No", "Decides what to explore; never touches the browser."],
        ["Crawler", "One UI action via browser-use / Playwright", "Small / fast", "Executes how; never writes graph truth or decides pass/fail."],
        ["Observer", "Snapshot: DOM, screenshot, URL, controls", "Mostly no", "Returns raw evidence, not a trusted summary."],
        ["Reasoner", "Missed, absent, causal scenarios", "LLM proposes; Cypher decides", "Deterministic graph queries remain the trustworthy floor."],
        ["Validator", "Independent post-conditions", "No", "Nothing is validated until evidence is rechecked."],
        ["Healer", "Selector repair", "Small model + graph", "Suggests fixes; Validator confirms."],
        ["Triage", "Failure clustering and flake calls", "LLM + graph history", "Escalates; does not silently suppress."],
        ["Safety supervisor", "Pre-action guardrails", "No", "Vetoes before the browser sees the task."],
        ["Ingestor", "Idempotent graph writes", "No", "Typed, replayable writes only; no model calls."],
    ], [24*mm, 50*mm, 24*mm, 80*mm]))
    story.append(P("The most important boundary is between Crawler and Validator. When the Crawler says it changed the quantity, the Validator reads the cart again and checks that the number actually moved.", "BodyX"))
    bullets(story, [
        "<b>Fails:</b> retry with backoff up to a budget, then mark the step failed and continue. A failed step is data, not a crash.",
        "<b>Stalls:</b> an action ledger and no-repeat guard turn repeated clicks into a fast veto.",
        "<b>Low confidence:</b> escalate, hand off to a human, or write an explicit unverified marker. Uncertainty is a first-class output.",
    ])
    story.append(P("1.1 The contract between agents", "Subsection"))
    story.append(P("Every hand-off carries intent, expected state, confidence, evidence to seek, risk class, and escalation signal. Those Pydantic-style contracts are the durable interface that lets models or frameworks change underneath.", "BodyX"))

    story.append(PageBreak())
    story.append(HarnessDiagram(width))
    P("The agent network around the harness and graph.", "Caption")
    story.append(P("The agent harness - this is the architecture", "Section"))
    story.append(P("The harness owns state, retries, timeouts, tool dispatch, schema enforcement, deterministic replay, and human-in-the-loop interrupts. LangGraph can provide state-machine primitives; the durable value sits above it.", "BodyX"))
    bullets(story, [
        "<b>State and replay:</b> durable Temporal workflows record inputs, outputs, model and prompt versions, trace IDs, and artifacts.",
        "<b>Structured dispatch:</b> agents return schema-validated objects; malformed output is a caught failure.",
        "<b>Retries and budgets:</b> latency, token, and circuit-breaker policies are observable, not silent spend.",
        "<b>HITL interrupts:</b> runs pause cleanly, ask a human, then resume with provenance intact.",
    ])

    section(story, "3. Guardrails per agent")
    story.append(P("A single global safety middleware is the wrong shape because each agent is uncertain about different things. Guardrails live with the agent contract.", "BodyX"))
    story.append(P("The Part-A deny-list safety veto is the right shape: default-allow reversible exploration, hard-block enumerable irreversible actions such as purchase, payment, sign-out, and navigation away from the product under test.", "Callout"))
    story.append(styled_table([
        ["Guardrail", "What it does"],
        ["Output validators / schema enforcement", "The output must fit the contract or the step fails."],
        ["Confidence gating", "Below threshold: escalate, fall back, or write unverified. No silent low-confidence passes."],
        ["Circuit breakers", "Repeated failures trip a feature-level stop and surface a flag."],
        ["Fallback chains", "Frontier model to small model to deterministic rule to human, per agent."],
        ["Deny-list veto", "Irreversible actions blocked before execution by a separate process."],
    ], [52*mm, 126*mm]))

    section(story, "4. Model routing and composition")
    story.append(P("The principle is deterministic by default, small models for high-volume fuzzy work, and frontier models only where reasoning value is high and volume is low.", "BodyX"))
    story.append(styled_table([
        ["Task", "Route", "Why"],
        ["State resolution, validation, inference, ingestion", "Deterministic code", "About 90 percent of operations; must be explainable and repeatable."],
        ["Which element to click", "Small / fast model", "High volume, latency-sensitive UI skill."],
        ["Locator stability / flake classification", "Fine-tuned small model", "Narrow, repetitive, cheaper at scale."],
        ["Graph gap reasoning, root-cause chains, eval adjudication", "Frontier model", "Low volume, high reasoning value."],
    ], [56*mm, 45*mm, 77*mm]))
    bullets(story, [
        "Compose models without compounding hallucination: put deterministic checks or graph lookups between model stages.",
        "Pin prompt and model versions so provider changes are measured before customers feel them.",
        "Keep long sessions small by using the graph as long-term memory and querying only the needed slice.",
        "Keep frontier models off the hot path; cache small-model calls by graph-state signature and invalidate bounded subgraphs.",
    ])

    section(story, "5. The production graph schema")
    story.append(P("The graph is not built around Element to Component to Flow to Feature. It is built around provenance and absence: why we believe something, and what should exist but does not.", "BodyX"))
    story.append(styled_table([
        ["Node", "Key properties", "Question answered"],
        ["Tenant / App / Feature", "ids", "Scope one feature deeply without tenant bleed."],
        ["Run", "commit_sha, started_at, model_version, cost", "What did we know at run N versus N+1?"],
        ["Observation", "state, url, artifact_ref, screenshot_ref", "Replay exactly what the browser saw."],
        ["Concept", "key, kind, observed, validated, expected, confidence", "Expected-not-observed; observed-not-validated."],
        ["Intent", "source, status, risk, selector_ref, confidence", "Why an action ran, passed, or was vetoed."],
        ["Scenario", "key, status, confidence, last_confirmed_run", "Which scenarios are trusted now versus decayed?"],
        ["Selector", "hash, role/css/xpath, stability, last_failed", "Blast radius and self-healing."],
        ["CodeArtifact", "path, symbol, commit_sha", "Map PR change to selectors to concepts to scenarios."],
    ], [34*mm, 66*mm, 78*mm]))
    story.append(P("The unit of meaning is a Concept - a behaviour - not a DOM element. Selectors churn; the meaning of 'add to cart' survives redesigns.", "Callout"))
    story.append(styled_table([
        ["Edge", "Between", "What it lets us ask"],
        ["OBSERVED / SAW_CONCEPT", "Run to Observation to Concept", "What did we see, and where?"],
        ["TARGETS", "Intent to Concept", "Which attempt exercised which behaviour, and did it pass?"],
        ["DEPENDS_ON", "Scenario to Concept", "Which concepts does this scenario rely on?"],
        ["SHOULD_CAUSE", "Concept to Concept", "Which expected effect remains unproven?"],
        ["BACKS", "CodeArtifact to Selector", "Which code backs this locator?"],
    ], [42*mm, 54*mm, 82*mm]))
    story.append(GraphDiagram(width))
    story.append(P("A sample checkout graph: the dashed subtotal node and SHOULD_CAUSE edge are the causal gap the reasoner surfaces.", "Caption"))
    story.append(P("5.1 Why a graph and not just vectors", "Subsection"))
    bullets(story, [
        "<b>Absence:</b> missing tests are structural gaps, not similarity queries.",
        "<b>Temporal reasoning:</b> knowledge at commit X needs stamped edges and history.",
        "<b>Multi-hop traversal:</b> CodeArtifact to Selector to Concept to Scenario is the product.",
        "Vectors still help with selector repair and semantic matching, but only as an auxiliary index.",
    ])

    story.append(PageBreak())
    section(story, "6. The Query Machine")
    story.append(P("The Query Machine sits between agents and Neo4j. It turns 'what does the graph know?' into bounded, typed answers instead of dumping the graph into a prompt or letting an agent write arbitrary Cypher.", "BodyX"))
    story.append(QueryDiagram(width))
    story.append(P("Agents ask structured questions; the Query Machine returns typed rows with provenance and confidence.", "Caption"))
    bullets(story, [
        "<b>Tier 1:</b> reviewed, parameterised graph-query tools such as missed_scenarios, absence, blast_radius, neighbours, confidence_of, and what_did_we_know_at.",
        "<b>Tier 2:</b> guarded natural-language to Cypher for the long tail: read-only, schema allow-listed, row/cost capped, logged, and reviewable.",
        "<b>Tier 3:</b> hybrid graph plus vector lookup: similarity finds the starting node, structure performs the reasoning.",
    ])

    section(story, "7. Keeping the graph correct over time")
    story.append(styled_table([
        ["Operation", "Trigger", "How"],
        ["Incremental", "Every crawl", "Upsert observations, bump last_seen, append evidence, add Scenario-[:CONFIRMED_BY]->Run."],
        ["Recomputed", "A run touching a feature", "Re-run inference and confidence for that feature only; never global."],
        ["Invalidated", "PR touches mapped code; selector fails repeatedly; validation fails", "Mark a bounded subgraph stale and push affected scenarios into the retest frontier."],
        ["Compounds", "Many runs over time", "Selector stability, flake rate, transition probabilities, and confidence-decay curves."],
    ], [31*mm, 55*mm, 92*mm]))
    bullets(story, [
        "Conflict resolution preserves history instead of overwriting: old and new observations remain stamped by commit and time.",
        "Validated decisions become signal: confirmed scenarios raise priors; flaky ones lower them.",
        "Full nightly recompute is rejected as the freshness story. Bounded invalidation is the defendable production shape.",
    ])
    story.append(ConfidenceChart(width))
    story.append(P("Confidence decays when runs do not reconfirm a scenario and snaps back on proof. Below the retest line it re-enters the frontier.", "Caption"))

    story.append(PageBreak())
    section(story, "8. Eval and confidence")
    story.append(P("The eval layer protects against two confidently-wrong states: the agent clicked the wrong thing, and the graph inferred a scenario that is not real.", "BodyX"))
    story.append(EvalDiagram(width))
    story.append(P("Offline golden sets and online sampling feed graders; calibration and canary gates stand between a model change and customers.", "Caption"))
    story.append(styled_table([
        ["Question", "Signal", "Metric"],
        ["Did it click the right target?", "Trace plus positive/negative target check", "Wrong-target rate, wander rate"],
        ["Did the action succeed?", "Deterministic post-condition after re-observe", "Validation pass rate"],
        ["Is the scenario reproducible?", "Replay across clean sessions", "Flake rate, pass@k"],
        ["Are confidence scores honest?", "Predicted confidence versus observed reproduction", "ECE, Brier score"],
        ["Did a model change regress us?", "Canary on versioned golden trajectories", "Delta versus baseline"],
    ], [52*mm, 72*mm, 54*mm]))
    story.append(P("Use a managed eval store to move fast, but own the golden sets and grading logic in-house. LLM-as-judge must be calibrated against human spot-checks, and never used where a deterministic check exists.", "BodyX"))

    section(story, "9. Observability and operations")
    bullets(story, [
        "Trace IDs follow reasoning chains across every agent call, with model and prompt versions at each hop.",
        "Decision audit trails record frontier score, guardrail choice, confidence, and veto/pass outcome.",
        "Latency and cost budgets per stage make stalls visible.",
        "Alerts focus on agentic failure modes: wander-rate drift, validation spikes, stale concepts, and model-upgrade regressions.",
        "Rollout moves from observe-only to recommend to gated execution to autonomous safe execution after thresholds clear.",
    ])

    section(story, "10. Multi-tenancy and scale")
    story.append(styled_table([
        ["Layer", "Isolated per tenant", "Shared"],
        ["Graph", "Tenant/app/feature partition; database-per-tenant for large accounts", "Schema and inference engine code"],
        ["Artifacts", "Per-tenant namespace, retention, redaction", "Storage implementation"],
        ["Models / prompts", "Customer vocabulary and trace versions", "Generic templates"],
        ["Learning", "No selectors, DOM, screenshots, or scenarios cross tenants", "Aggregated, reviewed structural priors only"],
    ], [33*mm, 88*mm, 57*mm]))
    story.append(P("Scale shape: async agents on a queue, durable Temporal workflows, LLM-call caching by graph-state signature, bounded Query Machine traversals, and heavy DOM/screenshot artifacts in object storage while Neo4j stores references.", "BodyX"))

    story.append(PageBreak())
    section(story, "11. PR blast radius")
    story.append(P("The PR hook falls straight out of the graph: CodeArtifact to Selector to Concept to Scenario to confidence. The output should say exactly which selectors, validated scenarios, and inferred scenarios are at risk - not 'rerun all checkout tests.'", "BodyX"))

    section(story, "12. What I would refuse to ship")
    story.append(styled_table([
        ["Refusal", "Why, and what must exist first"],
        ["A path that can click final purchase", "Money pages must be structurally incapable of final submit; red-team it until it cannot buy."],
        ["LLM self-report as validation", "Every mutating action needs a deterministic post-condition."],
        ["Uncalibrated confidence in the UI", "Confidence without calibration is false authority."],
        ["Nightly full-graph recompute as freshness", "Expensive and hides drift; prove bounded invalidation on a golden tenant."],
        ["Unreviewed cross-tenant learning", "Only reviewed structural priors may cross tenants; never DOM, selectors, screenshots, or scenarios."],
        ["Hard-coded concept vocabulary as-is", "Fine for one feature; production needs a learned per-tenant concept model behind an adapter."],
    ], [64*mm, 114*mm]))
    story.append(P("The hardest unsolved production-agent problem is knowing a probabilistic system is wrong before a human does. The architecture answers with deterministic floors, measured calibration, canaries, and a graph that remembers what was true so drift is visible.", "Callout"))

    section(story, "13. How Part A grounds every claim")
    story.append(styled_table([
        ["Production claim", "Prototype seed"],
        ["Planner / Crawler split; graph plans, browser acts", "GraphGuidedExplorer._autonomous_loop; BrowserUseIntentExecutor"],
        ["Guardrails an LLM cannot bypass", "safety_guard.veto_reason in the browser-use callback"],
        ["Executor output is evidence, not truth", "re-observe plus _run_assertions; cart-delta / checkout verification"],
        ["Graph reasons about missed and causal gaps", "infer_missed_scenarios; CAUSAL_EXPECTATIONS / SHOULD_CAUSE"],
        ["Query Machine tier 1 and NL taste", "infer_missed_scenarios; blast_radius; graph_expansion.expand_from_graph"],
        ["Absence as graph query", "seed_expected_concepts; missing_expected_concepts"],
        ["PR blast radius traversal", "pr_blast_radius.py; GraphStore.blast_radius"],
        ["Provenance and confidence on writes", "write_intent; write_observation"],
    ], [82*mm, 96*mm]))

    section(story, "14. The stack, and why")
    story.append(styled_table([
        ["Layer", "Start with", "Avoid"],
        ["Agent harness", "Custom harness over LangGraph primitives; Temporal for durable runs", "A fully autonomous agent with no state/replay contract"],
        ["Browser execution", "Playwright plus browser-use, sandboxed", "No action contract or veto"],
        ["Graph store", "Neo4j with temporal provenance and confidence on edges", "Graph-shaped dependencies hidden in relational tables"],
        ["Retrieval", "pgvector / Weaviate as auxiliary hybrid lookup", "Vector similarity replacing graph truth"],
        ["Query Machine", "Parameterised Cypher tools plus guarded NL-to-Cypher", "Free-form model-written Cypher on the hot path"],
        ["Models", "Frontier reasoning/judge; small executors; fine-tuned narrow classifiers; deterministic validation", "Provider name as the whole strategy"],
        ["Eval", "Versioned golden apps, managed eval store, calibrated judge, canaries", "Shipping prompt changes without canaries"],
        ["Observability", "OpenTelemetry, trace IDs, decision audit", "Plain logs with no trace IDs"],
        ["Async / queue", "Celery + Redis, FastAPI, Docker/K8s, AWS/GCP", "Fire-and-forget cron for retryable crawls"],
        ["Artifacts", "S3/GCS; Neo4j holds refs only", "Large DOM/screenshot blobs inside Neo4j"],
    ], [31*mm, 82*mm, 65*mm]))
    story.append(P("In one line: the valuable part is not the clever crawler. It is the loop between a probabilistic explorer and structural memory, with a hard wall between what the system did and what it is allowed to believe.", "Callout"))

    doc.build(story)


if __name__ == "__main__":
    build()
