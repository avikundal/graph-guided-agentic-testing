#!/usr/bin/env python3
"""Build the Part B production-architecture PDF with native vector diagrams."""
import math
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                ListFlowable, ListItem, KeepTogether, HRFlowable, PageBreak)
from reportlab.graphics.shapes import Drawing, Circle, Rect, String, Line, Polygon, Group
from reportlab.graphics import renderPDF

INK   = colors.HexColor('#1f2933')
MUTE  = colors.HexColor('#52606d')
RULE  = colors.HexColor('#cbd2d9')
ACC   = colors.HexColor('#2563a8')   # blue accent
BG_CALL = colors.HexColor('#f4f7fb')
BG_TBLH = colors.HexColor('#eef2f7')

styles = getSampleStyleSheet()
def S(name, **kw):
    base = kw.pop('parent', styles['Normal'])
    return ParagraphStyle(name, parent=base, **kw)

body   = S('body', fontName='Helvetica', fontSize=9.3, leading=13.6, textColor=INK, spaceAfter=6)
h1     = S('h1', fontName='Helvetica-Bold', fontSize=15, leading=18, textColor=INK, spaceBefore=14, spaceAfter=4)
h2     = S('h2', fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=ACC, spaceBefore=10, spaceAfter=3)
small  = S('small', fontName='Helvetica', fontSize=8, leading=11, textColor=MUTE)
cap    = S('cap', fontName='Helvetica-Oblique', fontSize=7.8, leading=10, textColor=MUTE, spaceBefore=2, spaceAfter=8)
cell   = S('cell', fontName='Helvetica', fontSize=8.2, leading=11, textColor=INK)
cellb  = S('cellb', fontName='Helvetica-Bold', fontSize=8.2, leading=11, textColor=INK)
callh  = S('callh', fontName='Helvetica-Bold', fontSize=8.6, leading=11.5, textColor=ACC)
callt  = S('callt', fontName='Helvetica', fontSize=8.6, leading=11.8, textColor=INK)
title  = S('title', fontName='Helvetica-Bold', fontSize=20, leading=23, textColor=INK)
sub    = S('sub', fontName='Helvetica', fontSize=10.5, leading=14, textColor=MUTE)
mono   = S('mono', fontName='Courier', fontSize=7.4, leading=9.6, textColor=colors.HexColor('#0b3d2e'))

def para(t, st=body): return Paragraph(t, st)

def tbl(data, colw, header=True, font=8.2):
    t = Table(data, colWidths=colw, repeatRows=1 if header else 0)
    cmds = [
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LINEBELOW',(0,0),(-1,-2),0.4,RULE),
        ('TOPPADDING',(0,0),(-1,-1),3.5),
        ('BOTTOMPADDING',(0,0),(-1,-1),3.5),
        ('LEFTPADDING',(0,0),(-1,-1),5),
        ('RIGHTPADDING',(0,0),(-1,-1),5),
    ]
    if header:
        cmds += [('BACKGROUND',(0,0),(-1,0),BG_TBLH),('LINEBELOW',(0,0),(-1,0),0.7,ACC)]
    t.setStyle(TableStyle(cmds))
    return t

def callout(decision, tradeoff, refusal):
    rows = [[Paragraph('Decision', callh), Paragraph(decision, callt)],
            [Paragraph('Trade-off', callh), Paragraph(tradeoff, callt)],
            [Paragraph('Refusal line', callh), Paragraph(refusal, callt)]]
    t = Table(rows, colWidths=[24*mm, 142*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),BG_CALL),
        ('BOX',(0,0),(-1,-1),0.6,RULE),
        ('LINEAFTER',(0,0),(0,-1),0.6,RULE),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
        ('LINEBELOW',(0,0),(-1,-2),0.4,RULE),
    ]))
    return t

# ---------------- diagram helpers ----------------
def _edge_pts(x1,y1,r1,x2,y2,r2):
    a = math.atan2(y2-y1, x2-x1)
    return (x1+r1*math.cos(a), y1+r1*math.sin(a), x2-r2*math.cos(a), y2-r2*math.sin(a))

def arrow(d, x1,y1,x2,y2, label=None, color=colors.HexColor('#7b8794'), lw=1.0, dash=None, lift=0):
    ln = Line(x1,y1,x2,y2, strokeColor=color, strokeWidth=lw)
    if dash: ln.strokeDashArray = dash
    d.add(ln)
    a = math.atan2(y2-y1, x2-x1); L=7.5
    d.add(Polygon(points=[x2,y2, x2-L*math.cos(a-0.42),y2-L*math.sin(a-0.42),
                          x2-L*math.cos(a+0.42),y2-L*math.sin(a+0.42)],
                  fillColor=color, strokeColor=color))
    if label:
        mx,my=(x1+x2)/2,(y1+y2)/2
        d.add(String(mx, my+2+lift, label, fontSize=6.3, fillColor=MUTE, textAnchor='middle'))

def box(d,x,y,w,h,text,fill,stroke=None,fs=8.2,tcol=colors.white,sub=None):
    stroke = stroke or fill
    d.add(Rect(x,y,w,h, fillColor=fill, strokeColor=stroke, strokeWidth=1, rx=5, ry=5))
    d.add(String(x+w/2, y+h/2-3+(4 if sub else 0), text, fontSize=fs, fillColor=tcol,
                 textAnchor='middle', fontName='Helvetica-Bold'))
    if sub:
        d.add(String(x+w/2, y+h/2-12, sub, fontSize=6.2, fillColor=tcol, textAnchor='middle'))

def node(d,x,y,label,fill,sub=None,r=20):
    d.add(Circle(x,y,r, fillColor=fill, strokeColor=colors.white, strokeWidth=1.6))
    d.add(String(x,y-3,label, fontSize=7.2, fillColor=colors.white, textAnchor='middle', fontName='Helvetica-Bold'))
    if sub:
        d.add(String(x,y-r-8,sub, fontSize=6.0, fillColor=MUTE, textAnchor='middle'))
    return (x,y,r)

# ---- Figure 1: production loop ----
def fig_loop():
    d = Drawing(470, 188)
    d.add(String(0,176,'Figure 1 — the loop: agents act, deterministic services decide what becomes truth.',
                 fontSize=7.8, fillColor=MUTE, fontName='Helvetica-Oblique'))
    pl  = (18,120,120,34); ex=(180,120,120,34); ob=(342,120,120,34)
    val = (180,40,120,34); gr=(342,40,120,34); sf=(18,40,120,34)
    box(d,*pl,'Planner','#2563a8',sub='what to test (deterministic)')
    box(d,*ex,'Browser executor','#3a8f6b',sub='one UI action (LLM)')
    box(d,*ob,'Observer / State','#b07d2b',sub='page -> typed state')
    box(d,*sf,'Safety supervisor','#a23b3b',sub='veto before execute')
    box(d,*val,'Validator','#6b4fa3',sub='prove it (deterministic)')
    box(d,*gr,'Graph (Neo4j)','#33728f',sub='durable memory + reason')
    arrow(d, 138,137, 180,137, 'one intent')
    arrow(d, 300,137, 342,137, 'artifacts')
    arrow(d, 402,120, 402,74, 'observation')
    arrow(d, 342,57, 300,57, 'post-condition')
    arrow(d, 180,57, 138,57, 'allow / deny', color=colors.HexColor('#a23b3b'))
    arrow(d, 78,74, 78,120, 'frontier')
    arrow(d, 240,74, 240,120, 'feed missed scenarios back', color=ACC, dash=(3,2))
    return d

# ---- Figure 2: sample Neo4j graph ----
LEG = [('Feature','#2563a8'),('Run','#3a8f6b'),('Observation','#b07d2b'),
       ('Concept','#6b4fa3'),('Intent','#33728f'),('Scenario','#a23b3b'),
       ('Selector','#7b8794'),('CodeArtifact','#8a6d3b')]
def fig_graph():
    d = Drawing(490, 330)
    d.add(String(0,318,'Figure 2 — a slice of the production graph as Neo4j would draw it (Amazon checkout).',
                 fontSize=7.8, fillColor=MUTE, fontName='Helvetica-Oblique'))
    d.add(String(0,306,'CONFIRMED_BY and RESOLVES_TO exist too (see §2.2); omitted here so the slice stays readable.',
                 fontSize=6.6, fillColor=MUTE, fontName='Helvetica-Oblique'))
    # three columns (70 / 245 / 415), three rows (265 / 175 / 90), mostly orthogonal edges.
    F  = node(d, 70,265,'Feature','#2563a8','amazon_checkout')
    R  = node(d, 245,265,'Run','#3a8f6b','commit_sha, cost')
    O  = node(d, 415,265,'Observ.','#b07d2b','shopping_cart')
    SE = node(d, 70,175,'Selector','#7b8794','proceedToRetailCheckout')
    I  = node(d, 245,175,'Intent','#33728f','proceed_to_checkout')
    C1 = node(d, 415,175,'Concept','#6b4fa3','cart_item • validated')
    CA = node(d, 70,90,'Code','#8a6d3b','cart.js')
    SC = node(d, 245,90,'Scenario','#a23b3b','delete→subtotal (MISSED)')
    C2 = node(d, 415,90,'Concept','#6b4fa3','subtotal • observed')
    def link(a,b,lab,near=0.5,**kw):
        x1,y1,x2,y2=_edge_pts(a[0],a[1],a[2], b[0],b[1],b[2])
        d.add(Line(x1,y1,x2,y2, strokeColor=kw.get('color',colors.HexColor('#7b8794')),
                   strokeWidth=kw.get('lw',1.0)))
        aa=math.atan2(y2-y1,x2-x1); L=7.5
        col=kw.get('color',colors.HexColor('#7b8794'))
        d.add(Polygon(points=[x2,y2,x2-L*math.cos(aa-0.42),y2-L*math.sin(aa-0.42),
                              x2-L*math.cos(aa+0.42),y2-L*math.sin(aa+0.42)],fillColor=col,strokeColor=col))
        lxp,lyp=x1+(x2-x1)*near, y1+(y2-y1)*near
        d.add(String(lxp, lyp+3, lab, fontSize=6.3, fillColor=MUTE, textAnchor='middle'))
    link(F,R,'HAS_RUN'); link(R,O,'OBSERVED'); link(O,C1,'SAW_CONCEPT')
    link(R,I,'HAS_INTENT'); link(I,C1,'TARGETS'); link(I,SE,'USED_SELECTOR')
    link(CA,SE,'BACKS', color=colors.HexColor('#8a6d3b'))
    link(F,SC,'HAS_SCENARIO', near=0.34, color=colors.HexColor('#a23b3b'))
    link(SC,C2,'DEPENDS_ON', color=colors.HexColor('#a23b3b'))
    # legend as a bottom strip
    lx=14
    for name,c in LEG:
        d.add(Circle(lx,18,4.6, fillColor=colors.HexColor(c), strokeColor=colors.white))
        d.add(String(lx+8,15,name,fontSize=6.6,fillColor=INK))
        lx += 18 + 6.0*len(name) + 8
    return d

# ---- Figure 3: living-graph policy ----
def fig_living():
    d=Drawing(470,150)
    d.add(String(0,138,'Figure 3 — the living-graph policy: four jobs with different costs and triggers.',
                 fontSize=7.8, fillColor=MUTE, fontName='Helvetica-Oblique'))
    items=[('Incremental','#3a8f6b','every run','bump last_seen,\nappend evidence'),
           ('Recomputed','#2563a8','feature touched','re-infer that\nfeature only'),
           ('Invalidated','#a23b3b','PR / selector fail','mark bounded\nsubgraph stale'),
           ('Compounds','#6b4fa3','over many runs','stability, flake,\nconfidence decay')]
    for i,(t,c,trig,impl) in enumerate(items):
        x=8+i*116
        box(d,x,64,104,46,t,colors.HexColor(c),sub=trig)
        d.add(String(x+52,52,impl.split('\n')[0],fontSize=6.4,fillColor=MUTE,textAnchor='middle'))
        d.add(String(x+52,44,impl.split('\n')[1],fontSize=6.4,fillColor=MUTE,textAnchor='middle'))
    d.add(String(235,18,'cheap & frequent  ───────────────────────────────────────►  durable & compounding',
                 fontSize=6.6, fillColor=MUTE, textAnchor='middle'))
    return d

# ---- Figure 4: validation / trust ladder ----
def fig_trust():
    d=Drawing(300,200)
    d.add(String(0,188,'Figure 4 — trust ladder: nothing is "validated" on the executor\'s word alone.',
                 fontSize=7.8, fillColor=MUTE, fontName='Helvetica-Oblique'))
    rungs=[('Executor says "done"','#cbd2d9','#52606d','evidence, not truth'),
           ('Right target? (negative-target check)','#b8c7d6','#1f2933','wrong-target / wander rate'),
           ('Re-observe + deterministic post-condition','#7fa8cf','#ffffff','validation pass rate'),
           ('Replay on clean sessions + golden apps','#3a6ea5','#ffffff','flake rate, pass@k'),
           ('Calibrated confidence vs reproduction','#1f4e79','#ffffff','ECE / Brier')]
    for i,(t,fill,tc,metric) in enumerate(rungs):
        y=20+i*32
        d.add(Rect(10,y,210,26,fillColor=colors.HexColor(fill),strokeColor=colors.white,strokeWidth=1.2,rx=4,ry=4))
        d.add(String(16,y+9,t,fontSize=7.1,fillColor=colors.HexColor(tc) if tc.startswith('#') else colors.black,fontName='Helvetica-Bold'))
        d.add(String(228,y+9,metric,fontSize=6.3,fillColor=MUTE))
    d.add(String(115,178,'more trust  ▲',fontSize=6.6,fillColor=MUTE,textAnchor='middle'))
    return d

# ---- Figure 5: PR blast radius chain ----
def fig_blast():
    d=Drawing(470,90)
    d.add(String(0,78,'Figure 5 — PR blast radius is a traversal, not a "rerun everything".',
                 fontSize=7.8, fillColor=MUTE, fontName='Helvetica-Oblique'))
    chain=[('CodeArtifact','#8a6d3b'),('Selector','#7b8794'),('Concept','#6b4fa3'),
           ('Scenario','#a23b3b'),('Run / confidence','#3a8f6b')]
    x=6
    centers=[]
    for t,c in chain:
        box(d,x,28,82,30,t,colors.HexColor(c)); centers.append(x+82); x+=92
    labels=['BACKS','RESOLVES','DEPENDS_ON','CONFIRMED_BY']
    for i in range(4):
        arrow(d, centers[i], 43, centers[i]+10, 43, labels[i])
    d.add(String(235,12,'output = these selectors, these scenarios, this decay, this retest frontier',
                 fontSize=6.6, fillColor=MUTE, textAnchor='middle'))
    return d

# ---------------- header / footer ----------------
def deco(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica',7); canvas.setFillColor(MUTE)
    canvas.drawString(18*mm, 287*mm, 'Testsigma — AI Architect Assignment · Part B · Production Architecture')
    canvas.setStrokeColor(RULE); canvas.setLineWidth(0.5)
    canvas.line(18*mm, 285*mm, 192*mm, 285*mm)
    canvas.drawRightString(192*mm, 10*mm, f'{doc.page}')
    canvas.drawString(18*mm, 10*mm, 'Graph-guided agentic testing platform')
    canvas.restoreState()

# ================= content =================
def build(path):
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=18*mm, rightMargin=18*mm, topMargin=24*mm, bottomMargin=16*mm)
    W = doc.width
    e=[]
    e.append(para('Part B — Production Architecture', title))
    e.append(Spacer(1,3))
    e.append(para('My plan for turning the little Amazon-checkout prototype into something that could actually run '
                  'as a product — for 100+ customers, across apps that change every sprint, still trustworthy on the '
                  '50th run six months from now.', sub))
    e.append(Spacer(1,8))
    e.append(HRFlowable(width='100%', thickness=1, color=ACC))
    e.append(Spacer(1,8))

    e.append(para('Before any of the detail, here\'s the one belief the whole thing rests on. The crawler is a '
                  'guesser — it only finds what it happens to bump into. The graph is the opposite — it\'s '
                  'structured, so it can reason about what <i>ought</i> to be there. I don\'t want production trusting '
                  'either of them blindly. So browser agents do the sensing and clicking, plain deterministic code '
                  'does the validating and storing, and the graph is the thing that decides what\'s still risky, '
                  'what\'s missing, and what\'s quietly gone stale.', body))
    e.append(para('One thing I want to be upfront about: this isn\'t architecture astronomy. I\'m not drawing boxes '
                  'I\'ve never built. Almost every claim in here already has a tiny working version in the Part A '
                  'prototype, and I\'ve put a table at the end (section 11) pointing at the exact function that backs '
                  'each one — so you don\'t have to take my word for any of it.', body))

    e.append(tbl([
        [para('What the prototype already does',cellb), para('What it has to become in production',cellb)],
        [para('browser-use + a DFS frontier',cell), para('An agent harness that picks what to test, constrains the action, checks the outcome, and keeps replayable traces.',cell)],
        [para('Neo4j concepts / intents / scenarios',cell), para('A temporal, living graph: provenance, confidence, absence modeling, PR blast-radius traversal.',cell)],
        [para('Graph-inferred missed scenarios',cell), para('A deterministic rule engine with eval-calibrated confidence and a promotion workflow.',cell)],
        [para('Amazon checkout only',cell), para('One feature modeled deeply; the same pattern repeated per customer/app/feature under hard tenant isolation.',cell)],
    ], [W*0.42, W*0.58]))
    e.append(Spacer(1,4))

    # 0 exec summary
    e.append(para('0 · The short version', h1))
    e.append(para('Let me start with what the prototype already does, because the production plan is really just '
                  '"do this, but make it survive contact with reality." The browser agent walks through Amazon '
                  'checkout, everything it sees gets written into Neo4j as typed facts, and then the graph points out '
                  'behaviours the agent skipped — like "does changing the quantity update the subtotal?" or "does '
                  'deleting an item?" And it doesn\'t just list them in a report; it hands the doable ones back to the '
                  'agent, which goes and tests them. In a real run it genuinely does this for the quantity change.', body))
    e.append(para('Production keeps that same division of labour and toughens it up. The browser agent stays a '
                  'guesser that we never treat as the source of truth. The graph stays the long-term memory, and it\'s '
                  'not allowed to make anything up beyond what was actually observed plus the rules we\'ve vetted. '
                  'In between sits a deterministic harness that owns the parts you can\'t leave to a model: what to '
                  'test, what\'s safe, what state we\'re in, what to re-run, and what counts as proven.', body))
    e.append(para('Here\'s the failure I actually lose sleep over. It isn\'t the agent missing a button — you can '
                  'always crawl again. It\'s <b>confident wrongness</b>: the agent swears checkout worked when it '
                  'really hit a login wall; a button\'s selector quietly changed after a deploy and nobody noticed; '
                  'the graph quietly assumes a feature was tested when it never even appeared. Every design choice in '
                  'here is bent toward dragging that kind of quiet uncertainty into the open where you can see it.', body))
    e.append(callout(
        'Planning, safety, validation, ingestion, replay and graph reasoning are deterministic services. The LLM / browser-use is used only for perception and one narrow UI action at a time.',
        'I give up some apparent autonomy. In return I get auditability and repeatability — and I still absorb DOM churn, because the executor leans on the visible page, ARIA and screenshot rather than brittle selectors.',
        'I would not ship a system where browser-use\'s own "done" is enough to mark a scenario validated.'))
    e.append(Spacer(1,5))
    e.append(fig_loop()); e.append(Spacer(1,8))
    e.append(para('Three things break this loop once you leave the demo, and they organise the rest of the document: '
                  'the app changes (so the schema needs versioning, §2, and the graph needs a freshness policy, §3); '
                  'both layers are probabilistic (so you need an eval harness, §4); and cost compounds per customer '
                  'per crawl (so models get routed to tasks under hard budgets, §5).', body))

    e.append(PageBreak())
    # 1 agents
    e.append(para('1 · Agent decomposition and boundaries', h1))
    e.append(para('The biggest call I made is to split responsibilities instead of building one clever agent. A single '
                  'agent that plans, clicks, reasons, validates, writes to the graph and then narrates itself looks '
                  'wonderful in a demo and comes apart the first week you operate it. So this is a harness of small '
                  'services, each with a contract it cannot step outside of.', body))
    e.append(tbl([
        [para('Service',cellb),para('Owns',cellb),para('LLM?',cellb),para('The boundary I enforce',cellb)],
        [para('Planner',cell),para('Frontier, priority, budgets, expected states, replay requests',cell),para('No',cell),para('Decides what to test; it never clicks.',cell)],
        [para('Browser executor',cell),para('One UI action via browser-use (DOM/ARIA/screenshot/context)',cell),para('Yes',cell),para('Runs one intent, returns artifacts; never writes graph truth.',cell)],
        [para('Observer',cell),para('Page snapshot → state, actions, forms, raw artifacts',cell),para('Mostly no',cell),para('A small classifier is fine, but it must hand back the raw evidence.',cell)],
        [para('State resolver',cell),para('Authoritative state from URL + DOM + ARIA + graph + summary',cell),para('No',cell),para('The browser-use opinion is an input, not the verdict.',cell)],
        [para('Validator',cell),para('Deterministic post-conditions after an action',cell),para('No',cell),para('Required before "executed" is allowed to become "validated".',cell)],
        [para('Reasoner',cell),para('Missed / absent scenarios from graph structure',cell),para('No online',cell),para('Online path is Cypher; an LLM only proposes new rules offline.',cell)],
        [para('Safety supervisor',cell),para('Allow-list, forbidden final-payment, destructive controls',cell),para('No',cell),para('Vetoes before browser-use ever sees the task.',cell)],
        [para('Ingestor',cell),para('Idempotent graph writes, provenance, confidence, artifact refs',cell),para('No',cell),para('No model calls; every write is typed and replayable.',cell)],
    ], [W*0.16,W*0.30,W*0.10,W*0.44]))
    e.append(Spacer(1,4))
    e.append(para('The boundary I care about most: the executor is allowed to <i>say</i> "I clicked Proceed to '
                  'Checkout." The validator still has to <i>prove</i> we reached a checkout boundary, a sign-in wall, '
                  'or a failure, from independent evidence. The executor\'s words are evidence, not a verdict. That is '
                  'precisely what the prototype already does in <font name="Courier">_checkout_reached_ok</font> and '
                  '<font name="Courier">_verify_cart_mutation</font> — it re-observes and asserts instead of believing '
                  'the model\'s summary.', body))
    e.append(para('I also keep safety as its own gate, separate from planning, so a planning bug can never quietly '
                  'remove a safety check. The canonical risk on an intent wins; an LLM suggestion can only make it '
                  '<i>more</i> restrictive, never less. In the prototype that is '
                  '<font name="Courier">normalize_suggestion</font> ignoring any risk the model tries to attach — a '
                  'model cannot talk a destructive action into looking "safe".', body))
    e.append(para('1.1 · The runtime contract', h2))
    e.append(para('Every item the planner hands the executor carries a tight contract. This was the single change '
                  'that turned the prototype from "the agent wandered off" into a disciplined executor.', body))
    e.append(tbl([
        [para('Field',cellb),para('Example',cellb),para('Why it exists',cellb)],
        [para('intent_id',cell),para('PROCEED_TO_CHECKOUT',cell),para('No dotted internal keys browser-use can mistake for a URL.',cell)],
        [para('expected_state',cell),para('shopping_cart',cell),para('Stops it hunting for cart controls on a product or checkout page.',cell)],
        [para('positive target',cell),para('"Proceed to checkout / retail checkout"',cell),para('Gives the executor a semantic target to find.',cell)],
        [para('negative targets',cell),para('Add to Cart, logo, search, Buy Now, Place Order',cell),para('Heads off the usual wrong-clicks.',cell)],
        [para('success evidence',cell),para('checkout URL, secure checkout, address/payment',cell),para('Keeps "clicked" and "validated" as separate ideas.',cell)],
        [para('risk',cell),para('safe / mutating / destructive / forbidden',cell),para('Drives the safety and replay policy.',cell)],
        [para('budget',cell),para('max one UI-changing action',cell),para('Stops the executor from re-planning mid-task.',cell)],
    ], [W*0.16,W*0.34,W*0.50]))

    e.append(PageBreak())
    # 2 schema
    e.append(para('2 · The production graph schema', h1))
    e.append(para('The obvious thing to reach for here is the textbook hierarchy — Element → Component → Flow → '
                  'Feature. I deliberately didn\'t use it as the backbone. It\'s decent vocabulary, but it\'s the '
                  'wrong shape for the questions this platform actually has to answer: what did we observe, what did '
                  'we genuinely prove, what should be there but isn\'t, what changed, and which tests depend on which '
                  'pieces. So I built the graph around those questions instead. And the single most important choice '
                  'is that the unit of meaning is a <i>behaviour</i> — a Concept like "add-to-cart" — not a DOM '
                  'element. Elements are the first thing to break every time a site gets redesigned; if I anchored '
                  'the graph to them it would rot constantly. Anchoring it to what a control <i>means</i> keeps it '
                  'stable across redesigns.', body))
    e.append(fig_graph()); e.append(Spacer(1,6))
    e.append(para('2.1 · Node types', h2))
    e.append(tbl([
        [para('Node',cellb),para('Key properties',cellb),para('Query it answers',cellb)],
        [para('Tenant / App / Feature',cell),para('tenant_id, app_id, feature_key',cell),para('Everything is tenant/app scoped; one feature modeled deeply.',cell)],
        [para('Run',cell),para('run_id, commit_sha, started_at, model/prompt version, cost',cell),para('What was known at run N vs N+1; canary and rollback analysis.',cell)],
        [para('Observation',cell),para('state, url, artifact_ref, screenshot_ref, step',cell),para('Replay and audit exactly what the browser saw.',cell)],
        [para('Concept',cell),para('key, kind, expected, observed, executed, validated, confidence, first_seen, last_seen',cell),para('Expected-not-observed; observed-not-validated; stale concepts.',cell)],
        [para('Intent',cell),para('source, status, risk, selector_ref, evidence, confidence',cell),para('Why an action ran, failed, or was blocked.',cell)],
        [para('Scenario',cell),para('feature-scoped key, status, kind, confidence, last_confirmed_run',cell),para('Which scenarios are trusted right now versus decayed.',cell)],
        [para('Selector',cell),para('hash, css/xpath/role, quality, stability, last_failed',cell),para('PR blast radius and self-healing.',cell)],
        [para('CodeArtifact',cell),para('path, symbol, commit_sha',cell),para('Map a PR change to selectors, concepts and scenarios.',cell)],
    ], [W*0.18,W*0.40,W*0.42]))
    e.append(Spacer(1,4))
    e.append(para('2.2 · Edges', h2))
    e.append(para(
        '(:Tenant)-[:OWNS]-&gt;(:App)-[:HAS_FEATURE]-&gt;(:Feature)<br/>'
        '(:Feature)-[:HAS_RUN]-&gt;(:Run)-[:OBSERVED]-&gt;(:Observation)-[:ON_STATE]-&gt;(:PageState)<br/>'
        '(:Observation)-[:SAW_CONCEPT]-&gt;(:Concept)<br/>'
        '(:Run)-[:HAS_INTENT]-&gt;(:Intent)-[:TARGETS]-&gt;(:Concept)<br/>'
        '(:Intent)-[:USED_SELECTOR]-&gt;(:Selector)-[:RESOLVES_TO]-&gt;(:Concept)<br/>'
        '(:Feature)-[:HAS_SCENARIO]-&gt;(:Scenario)-[:DEPENDS_ON]-&gt;(:Concept)<br/>'
        '(:Scenario)-[:CONFIRMED_BY]-&gt;(:Run)<br/>'
        '(:CodeArtifact)-[:BACKS]-&gt;(:Selector)', mono))
    e.append(Spacer(1,4))
    e.append(para('2.3 · Three changes from the prototype, each earning its keep', h2))
    e.append(ListFlowable([
        ListItem(para('<b>Scenario becomes feature-scoped, not run-scoped,</b> with CONFIRMED_BY edges back to runs. '
                      'That is what lets the graph answer "is this scenario still true, and which commits confirmed it?" '
                      'The prototype\'s run-scoped scenarios can only say "a run once produced this."', body)),
        ListItem(para('<b>Selector becomes a first-class node</b> (the prototype keeps it as a property on the intent). '
                      'Now the PR blast radius is a plain traversal, CodeArtifact → Selector → Concept → Scenario. The '
                      'prototype\'s <font name="Courier">pr_blast_radius.py</font> is the contract-only seed of exactly this.', body)),
        ListItem(para('<b>Time and commit_sha live on everything.</b> That turns "show me concepts that existed at '
                      'commit A but were never observed after commit B" into a graph diff — regression detection for free.', body)),
    ], bulletType='1', leftIndent=14))
    e.append(para('2.4 · Indexes and constraints I would actually declare', h2))
    e.append(para(
        'CREATE CONSTRAINT concept_key  FOR (c:Concept)  REQUIRE<br/>'
        '&nbsp;&nbsp;(c.tenant_id,c.app_id,c.feature_key,c.key) IS NODE KEY;<br/>'
        'CREATE CONSTRAINT run_key      FOR (r:Run)      REQUIRE<br/>'
        '&nbsp;&nbsp;(r.tenant_id,r.app_id,r.feature_key,r.run_id) IS NODE KEY;<br/>'
        'CREATE CONSTRAINT selector_key FOR (s:Selector) REQUIRE (s.tenant_id,s.app_id,s.hash) IS NODE KEY;<br/>'
        'CREATE RANGE INDEX run_time     FOR (r:Run)     ON (r.started_at);<br/>'
        'CREATE RANGE INDEX concept_seen FOR (c:Concept) ON (c.last_seen);', mono))
    e.append(para('The DOM and screenshot blobs do not belong in Neo4j — Observation.artifact_ref points at '
                  'per-tenant object storage. The graph stays a reasoning index, not a document store. (The prototype '
                  'truncates text into the node to keep things simple; production moves it out.)', body))

    e.append(para('2.5 · Modeling absence — the part most designs skip', h2))
    e.append(para('Absence is not the same as missing data. For a testing platform it is often the product itself: '
                  '"we expected a promo-code capability and never saw it", or "delete was here last week and vanished '
                  'after a PR". So expected concepts get materialized before they are ever observed (the prototype '
                  'already does this in <font name="Courier">seed_expected_concepts</font>), and absence comes in three '
                  'flavours, each a one-line query.', body))
    e.append(tbl([
        [para('Type',cellb),para('Definition',cellb),para('Example',cellb)],
        [para('Structural',cell),para('expected ∧ ¬observed',cell),para('The expected checkout boundary was never reached.',cell)],
        [para('Behavioural',cell),para('observed ∧ ¬validated',cell),para('The quantity control exists, but the subtotal update was never proven.',cell)],
        [para('Regression',cell),para('last_seen &lt; latest run',cell),para('The promo field used to exist; gone after commit X.',cell)],
    ], [W*0.16,W*0.30,W*0.54]))
    e.append(para('The prototype already ships the first two (<font name="Courier">missing_expected_concepts</font> and '
                  'the inference query). Regression absence is the one that catches a sprint quietly deleting a field.', body))
    e.append(para('2.6 · The reasoning query (this is the real one, not a sketch)', h2))
    e.append(para('Rules are data, not code — a set of prerequisites plus the pivot action whose validation would '
                  'prove the behaviour. A scenario is "missed" when every prerequisite was observed but the pivot was '
                  'never validated:', body))
    e.append(para(
        'UNWIND $rules AS rule<br/>'
        'OPTIONAL MATCH (c:Concept {tenant_id:$t, app_id:$a, feature_key:$f})<br/>'
        '&nbsp;&nbsp;WHERE c.key IN rule.requires AND coalesce(c.observed,false)=true<br/>'
        'WITH rule, collect(DISTINCT c.key) AS present<br/>'
        'WHERE size(present) = size(rule.requires)&nbsp;&nbsp;// all prerequisites observed<br/>'
        'OPTIONAL MATCH (pv:Concept {tenant_id:$t, app_id:$a, feature_key:$f, key:rule.pivot})<br/>'
        'WITH rule, pv<br/>'
        'WHERE rule.pivot IS NULL OR pv IS NULL OR coalesce(pv.validated,false)=false&nbsp;&nbsp;// pivot unproven<br/>'
        'RETURN rule.key, rule.title, rule.status, rule.requires', mono))
    e.append(para('Because the online reasoning is deterministic Cypher, it cannot hallucinate. It can only be wrong '
                  'about a <i>rule</i> — which is exactly why §4 evaluates the rules, not individual inferences.', body))

    e.append(PageBreak())
    # 3 living
    e.append(para('3 · Keeping the graph honest over time', h1))
    e.append(para('This is the part the brief really pushes on, and rightly so: how is the graph still correct on the '
                  '50th run, six months and 30 deploys later? My answer is to stop pretending facts are permanent. '
                  'A behaviour we confirmed six months ago is simply worth less than one we confirmed after last '
                  'night\'s deploy. So "living" isn\'t a vibe — it\'s a concrete policy about what happens to each '
                  'piece of data: some of it just gets topped up as we go, some gets recomputed, some gets thrown out '
                  'and re-checked, and some quietly compounds into the thing that\'s actually valuable.', body))
    e.append(fig_living()); e.append(Spacer(1,6))
    e.append(tbl([
        [para('Operation',cellb),para('Trigger',cellb),para('Implementation',cellb)],
        [para('Incremental',cell),para('every crawl run',cell),para('Upsert observations, bump last_seen, append evidence, update concept rollups, add Scenario-[:CONFIRMED_BY]->Run. O(seen this run).',cell)],
        [para('Recomputed',cell),para('a run touching a feature',cell),para('Re-run inference and scenario confidence for that feature only. Never global.',cell)],
        [para('Invalidated',cell),para('PR touches mapped code, selector fails N runs, repeated validation failure',cell),para('Mark a bounded subgraph stale; push the affected scenarios into the retest frontier.',cell)],
        [para('Compounds',cell),para('many runs over time',cell),para('Selector stability, flake rate, transition probabilities, confidence-decay curves — the six-month moat.',cell)],
    ], [W*0.16,W*0.28,W*0.56]))
    e.append(para('3.1 · Confidence decay and retest', h2))
    e.append(para('Every scenario\'s confidence decays unless something renews it: roughly '
                  '<font name="Courier">conf = w1·recency + w2·confirm_count − w3·flake_rate − w4·stale_dependencies</font>. '
                  'A scenario nobody has re-confirmed in K runs slips below threshold and is automatically re-queued '
                  'for the crawler — which closes the loop the prototype\'s "living graph" section only reports on. '
                  'Nothing is true forever; truth has a half-life, and the system pays to renew it.', body))
    e.append(callout(
        'Invalidate bounded subgraphs; never nightly-recompute the whole customer graph.',
        'It needs careful provenance and dependency edges to do well, but the cost and debuggability are far better — and invalidation actually <i>detects</i> drift instead of papering over it.',
        'I would refuse to ship nightly full-graph recomputation as the main freshness mechanism.'))

    # 4 eval
    e.append(para('4 · How I\'d know any of it is actually right', h1))
    e.append(para('There are two places this system can be confidently wrong, and they need different checks. The '
                  'browser agent can miss things or fumble a click. And the graph rules can infer something that '
                  'looks structurally sensible but is actually useless. So I check both, separately — and the golden '
                  'rule is that "the agent said it worked" is never where the story ends.', body))
    e.append(fig_trust()); e.append(Spacer(1,6))
    e.append(tbl([
        [para('Question',cellb),para('Signal',cellb),para('Metric',cellb)],
        [para('Did it click the right target?',cell),para('browser-use trace + target + negative-target check',cell),para('wrong-target rate, wander rate',cell)],
        [para('Did the action succeed?',cell),para('deterministic post-condition after re-observation',cell),para('validation pass rate',cell)],
        [para('Is the scenario reproducible?',cell),para('replay across clean sessions + golden apps',cell),para('flake rate, pass@k',cell)],
        [para('Are confidence scores calibrated?',cell),para('predicted confidence vs observed reproduction',cell),para('ECE, Brier score',cell)],
        [para('Did a model/prompt change regress?',cell),para('canary evals on versioned golden trajectories',cell),para('delta vs baseline',cell)],
    ], [W*0.30,W*0.44,W*0.26]))
    e.append(para('I would run three eval layers. Offline <b>golden apps</b> with human-labeled states, actions and '
                  'scenarios — precision and recall of discovered scenarios is the agent\'s regression metric. '
                  '<b>Canary crawls</b> before any model or prompt change ships. And <b>production sampling</b>, where '
                  'a small slice of high-impact actions is checked by deterministic assertions plus the occasional '
                  'human spot-check. One nuance worth stating: because inference is deterministic, I evaluate the '
                  '<i>rules</i>, not each inference — every rule carries a precision score on golden data, and an '
                  'LLM-proposed rule sits in shadow mode until it earns its way in.', body))
    e.append(callout(
        'A confidence number shown to a customer must be calibrated.',
        'Calibration costs you a feedback loop and some humility about early numbers.',
        'If scenarios we label 0.90 only reproduce 65% of the time, that number does not go in the product UI.'))

    e.append(PageBreak())
    # 5 cost
    e.append(para('5 · What this costs, and which model does what', h1))
    e.append(para('The strategy here is emphatically not "use the smartest model everywhere" — that\'s how you go '
                  'broke. It\'s matching each job to the cheapest thing that can actually do it, with real budgets. '
                  'Most of the work is plain code and costs nothing. The high-volume clicking goes to a small, fast '
                  'model. The big expensive model only comes out for the rare, genuinely hard stuff — discovering new '
                  'rules offline, settling eval disputes — where its reasoning earns its price.', body))
    e.append(tbl([
        [para('Task',cellb),para('Default',cellb),para('Why',cellb)],
        [para('State resolver, validation, inference, ingestion, frontier',cell),para('Deterministic (free)',cellb),para('~90% of operations; must be explainable and repeatable. Never use a model to check a model.',cell)],
        [para('Browser execution (which element to click)',cell),para('Small/fast — GPT-4o-mini / Haiku-class / Gemini Flash',cellb),para('High volume, low stakes, latency-sensitive UI skill.',cell)],
        [para('Neighbor proposals',cell),para('Cheap, cached by graph-state signature',cellb),para('Useful breadth, not trusted directly.',cell)],
        [para('Rule discovery, eval adjudication, hard flows, onboarding triage',cell),para('Frontier — Claude Opus-class',cellb),para('Low volume, high reasoning value; amortized across customers and releases.',cell)],
    ], [W*0.30,W*0.30,W*0.40]))
    e.append(para('5.1 · The math, worked through', h2))
    e.append(para('Per feature-crawl, steady state: the executor runs ~25 steps at roughly 3k in / 0.3k out tokens. '
                  'At mini-tier pricing ($0.15 / $0.60 per 1M) that is about '
                  '<font name="Courier">3000×0.15/1e6 + 300×0.60/1e6 = $0.00063</font> a step, ×25 ≈ '
                  '<b>$0.016</b>. The few neighbor calls are cached and round to ~$0.001. Everything else — observer, '
                  'planner, validator, inference, writes — is deterministic and costs nothing. So roughly '
                  '<b>$0.017 per feature-crawl</b>.', body))
    e.append(para('Scale that up. A customer with 50 features crawled nightly is '
                  '<font name="Courier">50 × 30 × $0.017 ≈ $26 / customer / month</font>. At 100 customers, about '
                  '<b>$2,600 / month</b> in inference — and it is dominated by the executor, which is exactly why that '
                  'call stays on the cheap tier and why validation has to be deterministic. The frontier model is '
                  'amortized, not per-customer: rule discovery and onboarding triage might be ~100 calls a week across '
                  'the whole platform, on the order of <b>$120 / month total</b> — a rounding error per customer.', body))
    e.append(tbl([
        [para('Cost lever',cellb),para('What it buys',cellb)],
        [para('Cache neighbor calls by graph-state signature',cell),para('No repeat LLM suggestions when the page and concepts have not changed.',cell)],
        [para('Invalidate instead of full recrawl',cell),para('You only spend on the bounded subgraph a PR touched.',cell)],
        [para('Small models for the executor',cell),para('The high-volume call stays cheap.',cell)],
        [para('Reserve the frontier model for offline work',cell),para('The expensive reasoning is amortized across customers and releases.',cell)],
        [para('Token & latency budgets per stage',cell),para('Stalls and runaway loops surface as observable failures, not silent spend.',cell)],
    ], [W*0.42,W*0.58]))
    e.append(para('The anti-pattern I refuse is "LLM-judge every step in real time". It makes cost scale with token '
                  'usage and makes the reasoning non-repeatable — the two things I most want to avoid.', body))

    # 6 tenancy
    e.append(para('6 · A hundred customers, kept apart', h1))
    e.append(para('My default here is to over-isolate, and I\'m comfortable saying so. In a tool that crawls people\'s '
                  'logged-in accounts, a forgotten "which tenant is this?" filter isn\'t a tidy little bug — it\'s a '
                  'customer-data incident with someone\'s name on it. So every query is scoped, every customer\'s '
                  'data lives apart, and the only thing allowed to cross between customers is anonymized, general '
                  'pattern — never one customer\'s actual screens or scenarios.', body))
    e.append(tbl([
        [para('Layer',cellb),para('Isolated per tenant',cellb),para('Shared',cellb)],
        [para('Graph',cell),para('Tenant/app/feature partition; database-per-tenant for large accounts',cell),para('Schema + inference engine (code, not data)',cell)],
        [para('Artifacts',cell),para('Per-tenant object-store namespace, retention, redaction',cell),para('Storage implementation',cell)],
        [para('Models/prompts',cell),para('Versions visible in traces; customer vocabulary stays isolated',cell),para('Generic executor prompt templates',cell)],
        [para('Learning',cell),para('No selectors, DOM, screenshots or scenarios cross tenants',cell),para('Aggregated, reviewed structural priors only',cell)],
        [para('Ops',cell),para('Per-tenant budgets and throttles',cell),para('Global monitoring + anomaly detection',cell)],
    ], [W*0.16,W*0.46,W*0.38]))
    e.append(para('Cross-customer learning is deliberately fenced in. We can learn structural priors — "checkout '
                  'usually has an address step before payment", selector-stability heuristics, candidate inference '
                  'rules — but a customer\'s concepts, selectors, scenarios and DOM never cross the boundary. The only '
                  'thing that moves is anonymized, aggregated pattern, and only after review. Put bluntly: one '
                  'retailer\'s cart is not evidence about another retailer\'s checkout. Cross-customer learning '
                  'sharpens heuristics; it does not copy concepts.', body))

    e.append(PageBreak())
    # 7 ops
    e.append(para('7 · Operations and observability', h1))
    e.append(para('Agentic systems fail in ways ordinary services do not: same prompt, different outcome; a correct '
                  'click that lands on the wrong state; false confidence; a slow model; a provider-side regression you '
                  'did not cause. So observability has to capture reasoning, artifacts, cost and decisions together, '
                  'not just latency and error codes.', body))
    e.append(tbl([
        [para('Telemetry',cellb),para('Example fields',cellb),para('Why it matters',cellb)],
        [para('Trace id per run/intent',cell),para('tenant, app, feature, run_id, step, model_version, prompt_version',cell),para('Reconstruct a failure across every agent that touched it.',cell)],
        [para('Decision audit',cell),para('frontier score, graph priority, safety decision, confidence',cell),para('Explain why an action ran or was blocked.',cell)],
        [para('Artifact refs',cell),para('DOM snapshot, screenshot, browser-use trace, transition',cell),para('Human debugging and eval labeling.',cell)],
        [para('Cost / latency',cell),para('tokens, model, cache hit, duration, retries',cell),para('Budget governance and customer pricing.',cell)],
        [para('Health metrics',cell),para('wander rate, validation-failure rate, stale-concept count, flake rate',cell),para('Catch degradation before customers do.',cell)],
    ], [W*0.20,W*0.42,W*0.38]))
    e.append(para('The alerts I would actually wire up: executor wander rate climbing after a model upgrade; '
                  'validation failures spiking on one feature right after a PR; scenario confidence decaying past the '
                  'customer-facing threshold without enough retest capacity to catch up; a cross-tenant query guard '
                  'rejecting a query that forgot its tenant scope; and cost-per-crawl blowing past budget because of a '
                  'retry loop. The prototype already emits a good chunk of this — wander detection, validation '
                  'overrides, per-source accounting — in its run report.', body))

    # 8 blast radius
    e.append(para('8 · PR blast radius', h1))
    e.append(para('The optional PR hook is not a separate feature; it falls straight out of the same graph. A PR is '
                  'an invalidation event. When it touches a component, route, selector or symbol, it invalidates a '
                  'bounded subgraph, and the blast-radius answer is a traversal.', body))
    e.append(fig_blast()); e.append(Spacer(1,6))
    e.append(tbl([
        [para('Step',cellb),para('Question it answers',cellb)],
        [para('CodeArtifact changed',cell),para('What paths/symbols did the PR touch?',cell)],
        [para('CodeArtifact → Selector',cell),para('Which UI locators/components are backed by this code?',cell)],
        [para('Selector → Concept',cell),para('Which controls or capabilities are affected?',cell)],
        [para('Concept → Scenario',cell),para('Which discovered and inferred scenarios are at risk?',cell)],
        [para('Scenario → Run / confidence',cell),para('Which of those risks are stale, high-confidence, or just validated?',cell)],
    ], [W*0.30,W*0.70]))
    e.append(para('The discipline is in the output. It is never "rerun all the checkout tests". It is: these '
                  'selectors, these concepts, these scenarios, this much confidence decay, and this retest frontier. '
                  'The prototype\'s <font name="Courier">pr_blast_radius.py</font> already produces the contract-only '
                  'version of exactly that.', body))

    # 9 refuse
    e.append(para('9 · The things I\'d refuse to ship', h1))
    e.append(para('This is the section I\'d most expect to get grilled on in a review, and honestly that\'s why it\'s '
                  'here. Saying what you\'d block is how you set a quality bar instead of just listing features. None '
                  'of these are "nice to haves" — they\'re lines I wouldn\'t cross, each with the thing I\'d need to '
                  'see before I changed my mind.', body))
    e.append(tbl([
        [para('Refusal',cellb),para('Why, and what I would need first',cellb)],
        [para('A path that can click final purchase/payment — even behind a flag',cell),para('Flags get flipped. Production-money pages must be structurally incapable of a final submit: an allow-list of actions enforced by the safety supervisor as a separate process. First I would want a red-team that tries to make it buy something and fails every time.',cell)],
        [para('LLM self-report as validation',cell),para('Every mutating or state-changing action needs a deterministic post-condition. First I would want a validator that cannot be satisfied by model prose — which the prototype already does for cart and checkout.',cell)],
        [para('Nightly full-graph recomputation as the freshness strategy',cell),para('It is expensive and it hides drift. Invalidate bounded subgraphs instead. First I would want the invalidation path proven to catch a real regression on a golden tenant.',cell)],
        [para('Unreviewed cross-tenant learning',cell),para('Aggregated priors may cross tenants; concepts, selectors, DOM, screenshots and scenarios may not. First I would want an audit log, a human promotion step, and a privacy review.',cell)],
        [para('Uncalibrated confidence in the UI',cell),para('Confidence without calibration is just false authority. First I would want the calibration check from §4 passing.',cell)],
        [para('Site-specific hacks in the platform core',cell),para('App quirks — the prototype\'s smart-wagon readiness, subtotal parsing, marketplace URL handling — belong in adapters. The core owns state, safety, validation, graph and eval. First I would want the adapter boundary plus two genuinely different apps running through it.',cell)],
    ], [W*0.30,W*0.70]))

    e.append(PageBreak())
    # 10 roadmap
    e.append(para('10 · Delivery roadmap', h1))
    e.append(para('I would ship this in phases that keep the system runnable after every step. The prototype already '
                  'taught me why: big-bang refactors make agent systems almost impossible to debug.', body))
    e.append(tbl([
        [para('Phase',cellb),para('Deliverable',cellb),para('Exit criteria',cellb)],
        [para('0 · Working slice',cell),para('One feature, browser-use crawler, graph ingest, an inferred missed scenario',cell),para('Add-to-cart + quantity validated; inference shown (done in Part A).',cell)],
        [para('1 · Harness hardening',cell),para('Execution memory, constrained executor, readiness gates, deterministic validator',cell),para('No duplicate execution; no LLM self-report validation (done).',cell)],
        [para('2 · Living graph',cell),para('Feature-scoped scenarios, confidence decay, bounded invalidation',cell),para('Stale selectors/concepts re-enter the retest frontier on their own.',cell)],
        [para('3 · Eval harness',cell),para('Golden apps, canaries, calibration dashboards',cell),para('Model/prompt regressions caught before customer rollout.',cell)],
        [para('4 · Multi-tenant beta',cell),para('Tenant isolation, budgets, artifact retention, observability',cell),para('100-customer architecture exercised under load and cost tests.',cell)],
        [para('5 · PR blast radius',cell),para('CodeArtifact → Selector → Concept → Scenario traversal',cell),para('A PR produces a bounded risk report and a retest plan.',cell)],
    ], [W*0.20,W*0.42,W*0.38]))

    # 11 grounding
    e.append(para('11 · How Part A grounds every claim here', h1))
    e.append(para('None of this is hypothetical. Each production claim already has a working seed in the prototype — '
                  'which is the main reason I am comfortable defending it.', body))
    e.append(tbl([
        [para('Production claim',cellb),para('Prototype function',cellb)],
        [para('Deterministic planner / LLM executor split',cell),para('GraphGuidedExplorer / BrowserUseIntentExecutor',cell)],
        [para('Executor output is evidence, not truth (re-observe + assert)',cell),para('_verify_cart_mutation, _checkout_reached_ok',cell)],
        [para('Safety an LLM cannot downgrade',cell),para('normalize_suggestion (ignores LLM-supplied risk)',cell)],
        [para('Absence as a graph query',cell),para('seed_expected_concepts, missing_expected_concepts',cell)],
        [para('Deterministic Cypher inference',cell),para('GraphStore.infer_missed_scenarios + INFERENCE_RULES',cell)],
        [para('Graph reasoning feeds back into exploration',cell),para('_graph_driven_intents (an inferred scenario was executed)',cell)],
        [para('Per-app adapter need (state / marketplace quirks)',cell),para('_cart_url_for, _ensure_ready_for_intent',cell)],
        [para('PR blast radius as a graph traversal',cell),para('pr_blast_radius.py, GraphStore.blast_radius',cell)],
        [para('Quantified graph value',cell),para('the report\'s "Graph impact" block',cell)],
    ], [W*0.55,W*0.45]))

    # 12 closing
    e.append(para('12 · Where I\'d plant the flag', h1))
    e.append(para('If I had to put the whole argument in one line: the valuable thing here was never the clever '
                  'crawler. It\'s the memory that builds up around it — what we saw, what we actually proved, what '
                  'should have been there and wasn\'t, what changed, what went stale, what a code change put at risk, '
                  'and why the system believes its own answers. That\'s why I anchored everything on the living graph '
                  'and a boring, dependable harness instead of on any particular agent framework.', body))
    e.append(para('Get that right and the flashy parts — browser-use, Playwright, whichever model is in fashion, the '
                  'prompts — all become swappable. The part that\'s genuinely hard to copy, the part I\'d actually be '
                  'building a moat around, is the graph of proven behaviour and the evaluation machinery that keeps it '
                  'honest as everything underneath it keeps moving.', body))

    doc.build(e, onFirstPage=deco, onLaterPages=deco)
    print('wrote', path)

if __name__ == '__main__':
    import sys
    build(sys.argv[1])
