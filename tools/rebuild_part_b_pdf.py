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


OUT = "output/pdf/Part_B_Production_Architecture_TestSigma_Final.pdf"

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


def orth_arrow(c, points, color=LINE, width=1.1, dash=None):
    c.setStrokeColor(color)
    c.setLineWidth(width)
    if dash:
        c.setDash(*dash)
    else:
        c.setDash()
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        c.line(x1, y1, x2, y2)
    c.setDash()
    if len(points) >= 2:
        import math
        x1, y1 = points[-2]
        x2, y2 = points[-1]
        a = math.atan2(y2-y1, x2-x1)
        c.setStrokeColor(color)
        c.setLineWidth(width)
        for da in (2.65, -2.65):
            c.line(x2, y2, x2 + 4.5*math.cos(a+da), y2 + 4.5*math.sin(a+da))


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


class SystemDesignDiagram(Flowable):
    def __init__(self, w):
        self.w, self.h = w, 188*mm
        self.s = w / (174*mm)
        super().__init__()

    def wrap(self, aw, ah):
        return self.w, self.h

    def X(self, v):
        return v * mm * self.s

    def Y(self, v):
        return v * mm

    def box(self, x, y, w, h, title, sub="", stroke=INK, fill=colors.white, title_size=6.5, sub_size=5.2):
        c = self.canv
        x, y, w, h = self.X(x), self.Y(y), self.X(w), self.Y(h)
        c.setFillColor(fill)
        c.setStrokeColor(stroke)
        c.roundRect(x, y, w, h, 4, fill=1, stroke=1)
        centered_lines(c, x+w/2, y+h/2 + (1.8 if sub else -1), title, size=title_size, leading=6.7, fill=stroke)
        if sub:
            centered_lines(c, x+w/2, y+3.2, sub, font="Helvetica", size=sub_size, leading=5.5, fill=MUTED)
        return (x, y, w, h)

    def band(self, y, h, label, fill):
        c = self.canv
        c.setFillColor(fill)
        c.setStrokeColor(fill)
        c.roundRect(0, self.Y(y), self.w, self.Y(h), 6, fill=1, stroke=0)
        c.setFillColor(MUTED)
        c.setFont("Helvetica-BoldOblique", 6.8)
        c.drawString(self.X(3), self.Y(y+h-5), label)

    def path(self, pts, color=colors.HexColor("#9AA8B6"), dash=None):
        orth_arrow(self.canv, [(self.X(x), self.Y(y)) for x, y in pts], color=color, width=1.0, dash=dash)

    def draw(self):
        c = self.canv
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(INK)
        c.drawString(0, self.Y(181), "Full production system design")
        c.setFont("Helvetica", 6.2)
        c.setFillColor(MUTED)
        c.drawString(0, self.Y(176), "Components are boxes; connectors are routed around boxes. The only graph writer is the Ingestor.")

        self.band(145, 26, "cross-cutting", colors.HexColor("#F1F3F5"))
        self.band(70, 66, "act, orchestrate, route", colors.HexColor("#EEF3F8"))
        self.band(6, 56, "remember", colors.HexColor("#ECF5EF"))

        self.box(4, 154, 25, 11, "GitHub PR", "code change", colors.HexColor("#475569"), colors.HexColor("#F8FAFC"))
        self.box(34, 154, 25, 11, "PR blast|radius", "risk set", VIOLET, colors.HexColor("#F3F0FA"), 6.0)
        self.box(64, 154, 25, 11, "Release|gate", "block or advise", VIOLET, colors.HexColor("#F3F0FA"), 6.0)
        self.box(97, 154, 35, 11, "Eval +|confidence", "golden, canary, ECE", AMBER, colors.HexColor("#FCF4E7"), 6.0)
        self.box(137, 154, 33, 11, "Observability", "traces, audit", AMBER, colors.HexColor("#FCF4E7"), 6.0)

        self.box(4, 108, 27, 19, "Target|web app", "app under test", colors.HexColor("#475569"), colors.white)
        self.box(4, 78, 27, 19, "Browser|execution", "Playwright + browser-use", GREEN, colors.HexColor("#EEF7F1"), 6.0)
        self.box(38, 91, 25, 18, "Safety|veto", "deny-list", AMBER, colors.HexColor("#FCF4E7"), 6.0)

        self.box(69, 78, 55, 52, "Agent harness", "state, replay, schemas, HITL", colors.HexColor("#274766"), colors.HexColor("#F2F5F8"), 7.0, 4.8)
        for title, x, y in [
            ("Planner", 72, 114), ("Reasoner", 90, 114), ("Triage", 108, 114),
            ("Crawler", 72, 101), ("Observer", 90, 101), ("Validator", 108, 101),
            ("Healer", 72, 88), ("Ingestor", 90, 88),
        ]:
            self.box(x, y, 15, 8.6, title, "", colors.HexColor("#274766"), colors.HexColor("#E8EEF5"), 4.7)

        self.box(132, 82, 39, 48, "Model router", "task to model, cost aware", VIOLET, colors.HexColor("#F3F0FA"), 6.4, 4.8)
        self.box(135, 115, 15, 8, "Claude", "reason", VIOLET, colors.white, 4.8, 4.2)
        self.box(153, 115, 15, 8, "GPT-4o|mini", "executor", VIOLET, colors.white, 4.6, 4.0)
        self.box(135, 103, 15, 8, "Mistral", "classify", VIOLET, colors.white, 4.8, 4.2)
        self.box(153, 103, 15, 8, "Code", "validate", VIOLET, colors.white, 4.8, 4.2)

        self.box(4, 31, 37, 18, "S3 / GCS", "DOM, screenshots; graph refs only", colors.HexColor("#475569"), colors.white, 6.4, 4.7)
        self.box(57, 37, 52, 19, "Query Machine", "typed Cypher | guarded NL | vector start", VIOLET, colors.HexColor("#F3F0FA"), 6.4, 4.8)
        self.box(57, 12, 52, 19, "Neo4j knowledge|graph", "concepts, scenarios, confidence edges", GREEN, colors.HexColor("#EEF7F1"), 6.0, 4.7)
        self.box(122, 14, 38, 17, "pgvector", "selector repair, semantic match", colors.HexColor("#274766"), colors.HexColor("#F2F5F8"), 6.2, 4.6)

        # Cross-cutting flow.
        self.path([(29, 159.5), (34, 159.5)], colors.HexColor("#6B7280"))
        self.path([(59, 159.5), (64, 159.5)], VIOLET)
        self.path([(89, 159.5), (97, 159.5)], VIOLET)
        self.path([(132, 159.5), (137, 159.5)], AMBER)
        self.path([(114, 154), (114, 136), (112, 136)], AMBER, dash=(3, 2))
        self.path([(154, 154), (154, 136), (118, 136)], AMBER, dash=(3, 2))

        # Action path: route around boxes, never through them.
        self.path([(17.5, 108), (17.5, 97)], colors.HexColor("#6B7280"))
        self.path([(31, 88), (38, 96)], AMBER)
        self.path([(63, 100), (69, 104)], AMBER)
        self.path([(69, 86), (64, 86), (64, 74), (31, 74), (31, 82)], GREEN)
        self.path([(124, 106), (132, 106)], VIOLET)

        # Memory and graph paths.
        self.path([(81, 78), (81, 56)], VIOLET)
        self.path([(83, 37), (83, 31)], VIOLET)
        self.path([(109, 45), (122, 24)], colors.HexColor("#274766"))
        self.path([(98, 88), (114, 88), (114, 21), (109, 21)], GREEN)
        self.path([(88, 78), (88, 64), (45, 64), (45, 40), (41, 40)], colors.HexColor("#6B7280"))
        self.path([(46.5, 154), (46.5, 141), (65, 141), (65, 64), (78, 64), (78, 56)], VIOLET, dash=(3, 2))

        c.setFillColor(MUTED)
        c.setFont("Helvetica-Oblique", 5.5)
        c.drawCentredString(self.w/2, self.Y(1.5), "Safety veto is shown on the action path; it also runs as a harness gate. Heavy artifacts stay in object storage; Neo4j stores references and graph truth.")


class GraphDiagram(Flowable):
    def __init__(self, w):
        self.w, self.h = w, 72*mm
        super().__init__()

    def wrap(self, aw, ah):
        return self.w, self.h

    def node(self, x, y, label, color, dashed=False):
        c = self.canv
        c.setFillColor(colors.white)
        c.setStrokeColor(color)
        c.setLineWidth(1.2)
        c.setDash(3, 2) if dashed else c.setDash()
        c.circle(x, y, 9*mm, fill=1, stroke=1)
        c.setDash()
        centered_lines(c, x, y - 1, label, size=6.2, leading=6.6, fill=color)

    def legend(self, x, y, title, color, text):
        c = self.canv
        c.setFillColor(colors.white)
        c.setStrokeColor(color)
        c.roundRect(x, y, 43*mm, 8*mm, 3, fill=1, stroke=1)
        c.setFillColor(color)
        c.setFont("Helvetica-Bold", 5.7)
        c.drawCentredString(x + 21.5*mm, y + 4.7*mm, title)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 5.2)
        c.drawCentredString(x + 21.5*mm, y + 1.8*mm, text)

    def draw(self):
        c = self.canv
        pts = {
            "run": (20*mm, 52*mm),
            "obs": (58*mm, 42*mm),
            "cart": (100*mm, 56*mm),
            "qty": (102*mm, 28*mm),
            "subtotal": (144*mm, 42*mm),
            "checkout": (178*mm, 28*mm),
            "scenario": (43*mm, 20*mm),
        }
        for a, b in [
            ("run", "obs"), ("obs", "cart"), ("obs", "qty"),
            ("qty", "subtotal"), ("scenario", "qty"),
            ("scenario", "checkout"),
        ]:
            x1, y1 = pts[a]; x2, y2 = pts[b]
            arrow(c, x1, y1, x2, y2, colors.HexColor("#9AA8B6"))
        self.node(*pts["run"], "Run|a14f", BLUE)
        self.node(*pts["obs"], "Observation|cart", TEAL)
        self.node(*pts["cart"], "add to|cart", GREEN)
        self.node(*pts["qty"], "change|quantity", GREEN)
        self.node(*pts["subtotal"], "subtotal|gap", AMBER, True)
        self.node(*pts["checkout"], "checkout|boundary", GREEN)
        self.node(*pts["scenario"], "quantity to|subtotal", VIOLET)
        self.legend(3*mm, 1*mm, "OBSERVED", BLUE, "run captured evidence")
        self.legend(49*mm, 1*mm, "SAW", TEAL, "observation saw concept")
        self.legend(95*mm, 1*mm, "SHOULD_CAUSE", AMBER, "expected effect gap")
        self.legend(141*mm, 1*mm, "DEPENDS_ON", VIOLET, "scenario requirement")


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
        P("Turning the Amazon-checkout prototype into something a real testing platform could run on - the part of the stack a team leans on to decide what is actually safe to ship.", "Subtitle"),
        P("The architecture is built around two things that are painful to change later: the agent harness, where agents live, and the evaluation loop, where you prove the system is improving instead of quietly rotting.", "Callout"),
        Spacer(1, 5*mm),
        CoreLoopDiagram(width),
        P("The core loop: the graph plans, the browser acts, the harness validates and writes memory, and the graph reasons over what it learned.", "Caption"),
    ]

    section(story, "0. The one belief this rests on")
    story += [
        P("A browser agent and a knowledge graph are good at almost opposite things. The browser agent is opportunistic: it can work out which control adds an item to cart after the DOM changes, but it only exercises the paths it happens to walk and can report success on an action that quietly did nothing.", "BodyX"),
        P("The graph is the part that remembers: every state seen, every control, what was proved versus merely noticed, and what should exist but has not been found. The crawler discovers; the graph remembers and cross-examines; the harness stops the loop from lying to itself.", "Callout"),
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
    story.append(P("1.2 How the Validator handles unknown actions", "Subsection"))
    story.append(P("The Validator can only fully confirm an action when it knows what evidence to check. So every action lands in one of three states: done and confirmed, done but unverified, or blocked/failed. The system keeps useful unknown actions, but it does not call them successful until there is proof.", "BodyX"))
    story.append(styled_table([
        ["Validator fallback", "How it keeps the result honest"],
        ["Graph expectation", "Read cause-and-effect rules such as change_quantity SHOULD_CAUSE subtotal_change."],
        ["Always-true invariants", "Check facts that should never break, such as totals matching item sums."],
        ["Before / after comparison", "Look for meaningful state change when an action should have produced one."],
        ["Calibrated judge", "Use a different model only when no rule or invariant exists, then measure judge agreement against humans."],
    ], [48*mm, 130*mm]))
    story.append(P("The safe default is simple: admit uncertainty. A tool that tells teams what is safe to ship should prefer 'unverified' over a confident but unsupported pass.", "Callout"))

    section(story, "2. System design at a glance")
    story.append(P("The full production system has three layers: cross-cutting release concerns, the agent runtime that acts on the app, and the memory layer that stores evidence and graph truth.", "BodyX"))
    story.append(SystemDesignDiagram(width))
    story.append(PageBreak())
    story.append(HarnessDiagram(width))
    story.append(P("The agent network around the harness and graph.", "Caption"))
    story.append(P("3. The agent harness - this is the architecture", "Section"))
    story.append(P("The harness owns state, retries, timeouts, tool dispatch, schema enforcement, deterministic replay, and human-in-the-loop interrupts. LangGraph can provide state-machine primitives; the durable value sits above it.", "BodyX"))
    bullets(story, [
        "<b>State and replay:</b> durable Temporal workflows record inputs, outputs, model and prompt versions, trace IDs, and artifacts.",
        "<b>Structured dispatch:</b> agents return schema-validated objects; malformed output is a caught failure.",
        "<b>Retries and budgets:</b> latency, token, and circuit-breaker policies are observable, not silent spend.",
        "<b>HITL interrupts:</b> runs pause cleanly, ask a human, then resume with provenance intact.",
    ])

    section(story, "4. Guardrails built into each agent")
    story.append(P("One shared safety layer across the whole system is the wrong shape because each agent is unsure about different things. Guardrails attach to each agent individually: every agent declares what not confident enough means, and what happens when it crosses that line.", "BodyX"))
    story.append(P("The Part-A deny-list safety veto is the right shape: default-allow reversible exploration, hard-block enumerable irreversible actions such as purchase, payment, sign-out, and navigation away from the product under test.", "Callout"))
    story.append(styled_table([
        ["Guardrail", "What it does"],
        ["Output validators / schema enforcement", "The output must fit the contract or the step fails."],
        ["Confidence gating", "Below threshold: escalate, fall back, or write unverified. No silent low-confidence passes."],
        ["Circuit breakers", "Repeated failures trip a feature-level stop and surface a flag."],
        ["Fallback chains", "Frontier model to small model to deterministic rule to human, per agent."],
        ["Deny-list veto", "Irreversible actions blocked before execution by a separate process."],
    ], [52*mm, 126*mm]))

    section(story, "5. Model routing and composition")
    story.append(P("The job is choosing the right model for each task and combining them without one model's guess turning into the next one's fact. The principle is deterministic by default, small models for high-volume fuzzy work, and frontier models only where reasoning value is high and volume is low.", "BodyX"))
    story.append(styled_table([
        ["Task", "Route", "Why"],
        ["State resolution, validation, inference, ingestion", "Deterministic code", "About 90 percent of operations; must be explainable and repeatable."],
        ["Which element to click", "Small / fast model", "High volume, latency-sensitive UI skill."],
        ["Locator stability / flake classification", "Fine-tuned small model", "Narrow, repetitive, cheaper at scale."],
        ["Graph gap reasoning, root-cause chains, eval adjudication", "Frontier model", "Low volume, high reasoning value."],
    ], [56*mm, 45*mm, 77*mm]))
    bullets(story, [
        "Chain models without letting errors snowball: put deterministic checks or graph lookups between model stages.",
        "Pin prompt and model versions so provider changes are measured before customers file a ticket.",
        "Keep long sessions small by using the graph as long-term memory and querying only the needed slice.",
        "Keep frontier models off the hot path; cache small-model calls by graph-state signature and invalidate bounded subgraphs.",
    ])

    story.append(P("Cost shape", "Subsection"))
    story.append(P("The exact provider prices will move, so I would track this with current vendor pricing in production. The architecture target is more important: small models do nearly all live crawl work, graph queries are deterministic, and frontier models run offline or on rare long-tail questions.", "BodyX"))
    story.append(styled_table([
        ["Unit", "What runs", "Budget / cost shape"],
        ["Per feature crawl", "About 25 small-model browser steps, roughly 75k input / 7.5k output tokens", "Around cents, not dollars"],
        ["Graph reasoning", "Mostly cached deterministic Cypher; a few small calls near convergence", "Near zero on unchanged graph state"],
        ["Tier-1 graph query", "Typed Cypher template", "No model cost"],
        ["Tier-2 graph query", "Rare guarded NL-to-Cypher frontier call", "Use for under 5 percent of graph questions"],
        ["50 features nightly", "1,500 crawls per customer per month", "Keep in the low tens of dollars with caching"],
        ["Offline frontier work", "Rule discovery, eval adjudication, canaries", "Amortised across customers"],
    ], [43*mm, 82*mm, 53*mm]))
    story.append(P("The spend stays controlled because unchanged pages are cached by graph-state signature, PRs invalidate bounded subgraphs instead of the whole app, and the frontier model never sits on the normal crawl path.", "BodyX"))

    section(story, "6. The production graph schema")
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
    story.append(P("The edges are where most of the value lives, so provenance and confidence belong on edges too: where the relationship came from, and how sure the system is of it.", "BodyX"))
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
    story.append(P("6.1 Why a graph and not just vectors", "Subsection"))
    bullets(story, [
        "<b>Absence:</b> missing tests are structural gaps, not similarity queries.",
        "<b>Temporal reasoning:</b> knowledge at commit X needs stamped edges and history.",
        "<b>Multi-hop traversal:</b> CodeArtifact to Selector to Concept to Scenario is the product.",
        "Vectors still help with selector repair and semantic matching, but only as an auxiliary index.",
    ])
    story.append(P("6.2 Indexes and constraints I would declare", "Subsection"))
    story.append(P("A graph schema without indexes is a wish. The indexes should map to the exact queries the platform will run every day.", "BodyX"))
    story.append(styled_table([
        ["Index / constraint", "Why it exists"],
        ["Concept(tenant_id, feature_key, key)", "Makes concept upserts correct and answers expected-vs-observed questions inside one feature."],
        ["Run(tenant_id, app_id, run_id)", "Keeps run identity stable and replayable."],
        ["Selector(hash)", "Fast selector repair and PR blast radius by locator content."],
        ["CodeArtifact(commit_sha, path, symbol)", "Entry point for the PR hook."],
        ["Concept(tenant_id, feature_key)", "Hot-path scoped feature lookups."],
        ["Run(commit_sha, started_at)", "Temporal questions such as what changed between two commits."],
        ["SHOULD_CAUSE(valid_from, confidence)", "Cheap queries for what the graph believed at time T and how sure it was."],
    ], [62*mm, 116*mm]))

    story.append(PageBreak())
    section(story, "7. The Query Machine")
    story.append(P("The Query Machine lives between agents and Neo4j. It turns 'what does the graph know?' into bounded, typed answers instead of dumping the graph into a prompt or letting an agent write arbitrary Cypher.", "BodyX"))
    story.append(QueryDiagram(width))
    story.append(P("Agents ask structured questions; the Query Machine returns typed rows with provenance and confidence.", "Caption"))
    bullets(story, [
        "<b>Tier 1:</b> reviewed, parameterised graph-query tools such as missed_scenarios, absence, blast_radius, neighbours, confidence_of, and what_did_we_know_at.",
        "<b>Tier 2:</b> guarded natural-language to Cypher for the long tail: read-only, schema allow-listed, row/cost capped, logged, and reviewable.",
        "<b>Tier 3:</b> hybrid graph plus vector lookup: similarity finds the starting node, structure performs the reasoning.",
    ])

    section(story, "8. Keeping the graph correct over time")
    story.append(styled_table([
        ["Operation", "Trigger", "How"],
        ["Incremental", "Every crawl", "Upsert observations, bump last_seen, append evidence, add Scenario-[:CONFIRMED_BY]->Run."],
        ["Recomputed", "A run touching a feature", "Re-run inference and confidence for that feature only; never global."],
        ["Invalidated", "PR touches mapped code; selector fails repeatedly; validation fails", "Mark a bounded subgraph stale and push affected scenarios into the retest frontier."],
        ["Compounds", "Many runs over time", "Selector stability, flake rate, transition probabilities, and confidence-decay curves."],
    ], [31*mm, 55*mm, 92*mm]))
    bullets(story, [
        "Conflict resolution preserves history instead of overwriting: old and new observations remain stamped by commit and time, so what the system believed at commit X stays answerable.",
        "Validated decisions feed the next run: confirmed scenarios raise priors; repeatedly flaky ones lower them.",
        "Full nightly recompute is rejected as the freshness story. Bounded invalidation is the defendable production shape.",
    ])
    story.append(ConfidenceChart(width))
    story.append(P("Confidence decays when runs do not reconfirm a scenario and snaps back on proof. Below the retest line it re-enters the frontier.", "Caption"))

    story.append(PageBreak())
    section(story, "9. Eval and confidence")
    story.append(P("This is the layer that decides whether the system is a product or a science project. It protects against two confidently-wrong states: the agent clicked the wrong thing, and the graph inferred a scenario that is not real.", "BodyX"))
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

    section(story, "10. Observability and operations")
    bullets(story, [
        "One trace id follows the whole chain of agent calls, with model and prompt versions stamped at each hop.",
        "Decision audit trails record frontier score, guardrail choice, confidence, and veto/pass outcome.",
        "Latency and cost budgets per stage make stalls visible.",
        "Alerts focus on agentic failure modes: wander-rate drift, validation spikes, stale concepts, and model-upgrade regressions.",
        "Rollout moves from observe-only to recommend to gated execution to autonomous safe execution after thresholds clear.",
    ])

    section(story, "11. Multi-tenancy and scale")
    story.append(styled_table([
        ["Layer", "Isolated per tenant", "Shared"],
        ["Graph", "Tenant/app/feature partition; database-per-tenant for large accounts", "Schema and inference engine code"],
        ["Artifacts", "Per-tenant namespace, retention, redaction", "Storage implementation"],
        ["Models / prompts", "Customer vocabulary and trace versions", "Generic templates"],
        ["Learning", "No selectors, DOM, screenshots, or scenarios cross tenants", "Aggregated, reviewed structural priors only"],
    ], [33*mm, 88*mm, 57*mm]))
    story.append(P("Scale shape: async agents on a queue, durable Temporal workflows, LLM-call caching by graph-state signature, bounded Query Machine traversals, and heavy DOM/screenshot artifacts in object storage while Neo4j stores references.", "BodyX"))

    story.append(PageBreak())
    section(story, "12. PR blast radius")
    story.append(P("The PR hook falls straight out of the graph: CodeArtifact to Selector to Concept to Scenario to confidence. The output should say exactly which selectors, validated scenarios, and inferred scenarios are at risk - not 'rerun all checkout tests.'", "BodyX"))

    section(story, "13. Production concerns beyond the checklist")
    story.append(styled_table([
        ["Concern", "Production stance"],
        ["Security and privacy", "DOM, screenshots, and sessions are sensitive. Encrypt per tenant, redact PII/tokens before storage, cap screenshot retention, and never log cookies or auth tokens."],
        ["Test data and safe environments", "Use dedicated test accounts and seeded staging/sandbox data. The system can prove it reached a checkout boundary; it must not cross into real purchase."],
        ["Auth and sessions", "A human handles OTP/CAPTCHA once; encrypted per-tenant sessions are refreshed safely. Account-level controls stay on the deny-list."],
        ["CI and release gates", "Start in recommend mode, then earn blocking gates only after confidence and flake metrics hold. Known flaky tests should not block good releases blindly."],
    ], [43*mm, 135*mm]))

    section(story, "14. What I would refuse to ship")
    story.append(styled_table([
        ["Refusal", "Why, and what must exist first"],
        ["A path that can click final purchase", "Money pages must be structurally incapable of final submit; red-team it until it cannot buy."],
        ["LLM self-report as validation", "Every mutating action needs a deterministic post-condition."],
        ["Uncalibrated confidence in the UI", "Confidence without calibration is false authority."],
        ["Nightly full-graph recompute as freshness", "Expensive and hides drift; prove bounded invalidation on a golden tenant."],
        ["Unreviewed cross-tenant learning", "Only reviewed structural priors may cross tenants; never DOM, selectors, screenshots, or scenarios."],
        ["Hard-coded concept vocabulary as-is", "Fine for one feature; production needs a learned per-tenant concept model behind an adapter."],
    ], [64*mm, 114*mm]))
    story.append(P("The hardest problem is knowing the system is wrong before a human notices. The architecture answers with deterministic floors under the fuzzy parts, confidence that is measured rather than assumed, canaries between model changes and customers, and a graph that remembers what used to be true so drift is visible.", "Callout"))

    section(story, "15. How Part A grounds every claim")
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
    story.append(P("A concrete run makes the point clearer.", "Subsection"))
    bullets(story, [
        "<b>Discovered by the crawler:</b> Add to Cart works, and the quantity stepper moves. The Validator confirmed this by re-reading the actual cart.",
        "<b>Inferred by the graph:</b> Proceeding to checkout should reach the checkout boundary. The free crawl saw the control but never proved the effect.",
        "<b>Why the graph inferred it:</b> action.proceed_to_checkout SHOULD_CAUSE domain.checkout_boundary. Observed cause, expected effect, no proof.",
        "<b>What happened next:</b> the graph turned that gap into a directed probe, the browser clicked Proceed, and the run reached the real checkout boundary.",
    ])

    section(story, "16. The stack, and why")
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
    story.append(P("In one line: the valuable part is not the clever crawler. It is the loop between something that explores and something that remembers, with a hard wall between what the system did and what it is allowed to believe.", "Callout"))

    doc.build(story)


if __name__ == "__main__":
    build()
