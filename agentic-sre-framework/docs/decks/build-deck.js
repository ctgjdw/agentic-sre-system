// Generates the management brief deck for the Agentic SRE Framework.
// Output: management-brief.pptx in the same directory.

const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";   // 13.3" x 7.5"
pres.author = "SRE Team";
pres.title = "AI Agents for SRE & SysAdmin Operations";

// --------------------------------------------------------------------------
// Palette + typography
// --------------------------------------------------------------------------
const C = {
  navy:        "1E2761",
  navyDeep:    "131A47",
  iceblue:     "CADCFC",
  amber:       "F59E0B",
  white:       "FFFFFF",
  pageBg:      "F8FAFC",
  cardBg:      "FFFFFF",
  cardBorder:  "E5E7EB",
  textDark:    "1F2937",
  textMid:     "374151",
  textMuted:   "6B7280",
  divider:     "D1D5DB",
  good:        "16A34A",
  warn:        "DC2626",
};

const F = {
  header: "Georgia",
  body:   "Calibri",
};

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------
function addPageChrome(slide, opts = {}) {
  const { dark = false, pageNum, total } = opts;
  // Thin top accent strip
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 13.3, h: 0.18,
    fill: { color: dark ? C.amber : C.navy }, line: { color: dark ? C.amber : C.navy, width: 0 }
  });
  // Bottom page indicator
  if (pageNum) {
    slide.addText(`${pageNum} / ${total}`, {
      x: 12.0, y: 7.15, w: 1.0, h: 0.3,
      fontFace: F.body, fontSize: 9, color: dark ? C.iceblue : C.textMuted,
      align: "right", valign: "middle", margin: 0,
    });
  }
  // Bottom-left brand footer
  slide.addText("Agentic SRE Framework  ·  Management Brief", {
    x: 0.6, y: 7.15, w: 8, h: 0.3,
    fontFace: F.body, fontSize: 9, color: dark ? C.iceblue : C.textMuted,
    align: "left", valign: "middle", margin: 0,
  });
}

function addSlideTitle(slide, title, eyebrow) {
  if (eyebrow) {
    slide.addText(eyebrow.toUpperCase(), {
      x: 0.6, y: 0.45, w: 12.1, h: 0.3,
      fontFace: F.body, fontSize: 11, bold: true,
      color: C.amber, charSpacing: 4, margin: 0,
    });
  }
  slide.addText(title, {
    x: 0.6, y: eyebrow ? 0.8 : 0.55, w: 12.1, h: 0.8,
    fontFace: F.header, fontSize: 30, bold: true,
    color: C.navy, align: "left", valign: "middle", margin: 0,
  });
}

function addCard(slide, { x, y, w, h, fill = C.cardBg, border = C.cardBorder, shadow = true }) {
  const opts = {
    x, y, w, h,
    fill: { color: fill },
    line: { color: border, width: 0.75 },
  };
  if (shadow) {
    opts.shadow = { type: "outer", color: "000000", opacity: 0.06, blur: 6, offset: 2, angle: 90 };
  }
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { ...opts, rectRadius: 0.08 });
}

function addArrow(slide, x1, y, x2, color = C.navy, width = 1.5) {
  // Horizontal arrow line
  slide.addShape(pres.shapes.LINE, {
    x: x1, y: y, w: x2 - x1, h: 0,
    line: { color, width, endArrowType: "triangle" },
  });
}

function addVerticalArrow(slide, x, y1, y2, color = C.navy, width = 1.5) {
  slide.addShape(pres.shapes.LINE, {
    x: x, y: y1, w: 0, h: y2 - y1,
    line: { color, width, endArrowType: "triangle" },
  });
}

// --------------------------------------------------------------------------
// Slide 1 — Title
// --------------------------------------------------------------------------
function slide1() {
  const s = pres.addSlide();
  s.background = { color: C.navy };

  // Background dots — subtle "agent network" motif (top-right cluster)
  const dotPositions = [
    [9.2, 0.8], [10.0, 1.0], [10.8, 0.6], [11.5, 1.2], [12.2, 0.8],
    [9.6, 1.8], [10.5, 2.0], [11.3, 1.8], [12.0, 2.2],
    [9.8, 2.8], [10.7, 3.0], [11.6, 2.8],
  ];
  // Connector lines (subtle)
  const lines = [
    [9.2,0.8,  10.0,1.0],
    [10.0,1.0, 10.8,0.6],
    [10.8,0.6, 11.5,1.2],
    [11.5,1.2, 12.2,0.8],
    [10.0,1.0, 10.5,2.0],
    [10.8,0.6, 11.3,1.8],
    [11.5,1.2, 12.0,2.2],
    [10.5,2.0, 11.3,1.8],
    [11.3,1.8, 12.0,2.2],
    [10.5,2.0, 10.7,3.0],
    [11.3,1.8, 11.6,2.8],
    [9.6,1.8,  9.8,2.8],
  ];
  lines.forEach(([x1,y1,x2,y2]) => {
    s.addShape(pres.shapes.LINE, {
      x: x1, y: y1, w: x2-x1, h: y2-y1,
      line: { color: C.iceblue, width: 0.5, transparency: 65 },
    });
  });
  dotPositions.forEach(([x,y]) => {
    s.addShape(pres.shapes.OVAL, {
      x: x-0.08, y: y-0.08, w: 0.16, h: 0.16,
      fill: { color: C.iceblue }, line: { color: C.iceblue, width: 0 },
    });
  });
  // Highlight one node as the "supervisor"
  s.addShape(pres.shapes.OVAL, {
    x: 10.8-0.13, y: 1.7-0.13, w: 0.26, h: 0.26,
    fill: { color: C.amber }, line: { color: C.amber, width: 0 },
  });

  // Eyebrow
  s.addText("MANAGEMENT STEERING BRIEF", {
    x: 0.8, y: 2.6, w: 12, h: 0.4,
    fontFace: F.body, fontSize: 13, bold: true,
    color: C.amber, charSpacing: 6, margin: 0,
  });
  // Title
  s.addText("AI Agents for SRE\n& SysAdmin Operations", {
    x: 0.8, y: 3.1, w: 11.5, h: 2.3,
    fontFace: F.header, fontSize: 54, bold: true,
    color: C.white, align: "left", valign: "top", margin: 0,
    lineSpacingMultiple: 1.05,
  });
  // Subtitle
  s.addText("A framework that augments — not replaces — our SRE and SysAdmin teams, with humans in command of every state change.", {
    x: 0.8, y: 5.5, w: 10.5, h: 1.0,
    fontFace: F.body, fontSize: 18, italic: true,
    color: C.iceblue, align: "left", valign: "top", margin: 0,
  });
  // Date + attribution
  s.addText("SRE Team   ·   May 2026", {
    x: 0.8, y: 6.7, w: 10, h: 0.4,
    fontFace: F.body, fontSize: 12, color: C.iceblue, margin: 0,
  });
}

// --------------------------------------------------------------------------
// Slide 2 — Where engineering time leaks today
// --------------------------------------------------------------------------
function slide2(pageNum, total) {
  const s = pres.addSlide();
  s.background = { color: C.pageBg };
  addPageChrome(s, { pageNum, total });
  addSlideTitle(s, "Where engineering time leaks today", "The problem");

  // Four pain cards in 2x2 grid
  const pains = [
    {
      n: "1",
      title: "Issues surface via ad-hoc chat",
      body: "Most incidents reach us as free-form Mattermost messages. Engineers must read every channel and decide what's real.",
    },
    {
      n: "2",
      title: "We lack fine-tuned dashboards",
      body: "Few automated signals exist for the things that actually break. Postmortems repeatedly conclude \"we should have had a dashboard for that.\"",
    },
    {
      n: "3",
      title: "Tickets are interpreted by hand",
      body: "DB / IAM / network requests arrive as prose. SysAdmins read, interpret, script, execute — every time, from scratch.",
    },
    {
      n: "4",
      title: "Postmortem actions don't land",
      body: "Action items get written, then never implemented. The same incident recurs. The learning loop leaks.",
    },
  ];

  const cardW = 5.8, cardH = 2.2;
  const xs = [0.6, 6.9];
  const ys = [1.85, 4.25];

  pains.forEach((p, i) => {
    const x = xs[i % 2], y = ys[Math.floor(i / 2)];
    addCard(s, { x, y, w: cardW, h: cardH });
    // Number badge
    s.addShape(pres.shapes.OVAL, {
      x: x + 0.35, y: y + 0.35, w: 0.55, h: 0.55,
      fill: { color: C.navy }, line: { color: C.navy, width: 0 },
    });
    s.addText(p.n, {
      x: x + 0.35, y: y + 0.35, w: 0.55, h: 0.55,
      fontFace: F.header, fontSize: 20, bold: true,
      color: C.white, align: "center", valign: "middle", margin: 0,
    });
    s.addText(p.title, {
      x: x + 1.1, y: y + 0.35, w: cardW - 1.3, h: 0.55,
      fontFace: F.header, fontSize: 18, bold: true,
      color: C.navy, align: "left", valign: "middle", margin: 0,
    });
    s.addText(p.body, {
      x: x + 0.35, y: y + 1.1, w: cardW - 0.7, h: cardH - 1.3,
      fontFace: F.body, fontSize: 13, color: C.textMid,
      align: "left", valign: "top", margin: 0,
    });
  });

  // Caption strip at the bottom of grid
  s.addText("These compound. Engineer time leaks; monitoring debt accumulates; the next incident looks like the last one.", {
    x: 0.6, y: 6.85, w: 12.1, h: 0.3,
    fontFace: F.body, fontSize: 12, italic: true,
    color: C.textMuted, align: "center", valign: "middle", margin: 0,
  });
}

// --------------------------------------------------------------------------
// Slide 3 — Proposal: one supervisor, agents mirror our roles
// --------------------------------------------------------------------------
function slide3(pageNum, total) {
  const s = pres.addSlide();
  s.background = { color: C.pageBg };
  addPageChrome(s, { pageNum, total });
  addSlideTitle(s, "An AI team that mirrors our SRE org chart", "The proposal");

  // Supervisor card centered at top (wider so subtitle fits on one line)
  const supX = 4.9, supY = 1.7, supW = 3.5, supH = 0.9;
  addCard(s, { x: supX, y: supY, w: supW, h: supH, fill: C.navy, border: C.navy });
  s.addText("Supervisor", {
    x: supX, y: supY + 0.05, w: supW, h: 0.4,
    fontFace: F.header, fontSize: 16, bold: true,
    color: C.white, align: "center", valign: "middle", margin: 0,
  });
  s.addText("routes signals  ·  owns audit  ·  runs HITL gate", {
    x: supX, y: supY + 0.45, w: supW, h: 0.4,
    fontFace: F.body, fontSize: 10, color: C.iceblue,
    align: "center", valign: "middle", margin: 0,
  });

  // Manifold connector: short drop from supervisor → horizontal bus → 3 verticals into columns
  const supCx = supX + supW/2;
  const busY = 2.95;          // horizontal bus level (just above the grid row)
  const gridY_local = 3.2;    // matches gridY below
  const colCx0 = 0.6 + 4.0/2;                 // col 0 center x
  const colCx1 = 0.6 + (4.0 + 0.07) + 4.0/2;  // col 1
  const colCx2 = 0.6 + 2*(4.0 + 0.07) + 4.0/2;// col 2
  // Drop from supervisor
  s.addShape(pres.shapes.LINE, {
    x: supCx, y: supY + supH, w: 0, h: busY - (supY + supH),
    line: { color: C.navy, width: 1.2 },
  });
  // Horizontal bus across all three columns
  s.addShape(pres.shapes.LINE, {
    x: colCx0, y: busY, w: colCx2 - colCx0, h: 0,
    line: { color: C.navy, width: 1.2 },
  });
  // Drops into each column
  [colCx0, colCx1, colCx2].forEach(cx => {
    s.addShape(pres.shapes.LINE, {
      x: cx, y: busY, w: 0, h: gridY_local - busY,
      line: { color: C.navy, width: 1.2 },
    });
  });

  // 9 specialist cards in a 3x3 grid
  const agents = [
    { name: "Duty Engineer",       tier: "small",    body: "intake from chat / alerts; triage" },
    { name: "SRE Investigator",    tier: "medium",   body: "initial investigation; evidence" },
    { name: "Principal SRE",       tier: "frontier", body: "senior review; final RCA + plan" },
    { name: "Remediation Engineer",tier: "frontier", body: "drafts the fix as an MR" },
    { name: "SysAdmin Drafter",    tier: "medium",   body: "free-text ticket → playbook" },
    { name: "Security Triage",     tier: "medium",   body: "CVE exploitability + mitigation" },
    { name: "Compliance Evidence", tier: "small",    body: "continuous evidence packets" },
    { name: "Postmortem Scribe",   tier: "medium",   body: "timeline + factors + actions" },
    { name: "Observability Eng.",  tier: "medium",   body: "drafts dashboards + alert rules" },
  ];

  const gridX = 0.6, gridY = 3.2;
  const gW = 4.0, gH = 1.05, gapX = 0.07, gapY = 0.12;
  agents.forEach((a, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = gridX + col * (gW + gapX);
    const y = gridY + row * (gH + gapY);
    addCard(s, { x, y, w: gW, h: gH });
    // Tier badge (small colored pill)
    const tierColor = a.tier === "frontier" ? C.amber : (a.tier === "medium" ? C.navy : C.textMuted);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x + gW - 0.95, y: y + 0.18, w: 0.78, h: 0.28,
      fill: { color: tierColor }, line: { color: tierColor, width: 0 },
      rectRadius: 0.05,
    });
    s.addText(a.tier, {
      x: x + gW - 0.95, y: y + 0.18, w: 0.78, h: 0.28,
      fontFace: F.body, fontSize: 9, bold: true,
      color: C.white, align: "center", valign: "middle", margin: 0,
    });
    s.addText(a.name, {
      x: x + 0.25, y: y + 0.15, w: gW - 1.3, h: 0.35,
      fontFace: F.header, fontSize: 13.5, bold: true,
      color: C.navy, align: "left", valign: "middle", margin: 0,
    });
    s.addText(a.body, {
      x: x + 0.25, y: y + 0.55, w: gW - 0.4, h: 0.45,
      fontFace: F.body, fontSize: 11, color: C.textMid,
      align: "left", valign: "top", margin: 0,
    });
  });

  // Bottom strip — three core pillars
  const pillarsY = 6.85;
  const pillars = [
    "Humans approve every state change",
    "Permissions visible and revocable",
    "Same model on-prem and online",
  ];
  pillars.forEach((p, i) => {
    const x = 0.6 + i * 4.1;
    s.addShape(pres.shapes.OVAL, {
      x: x, y: pillarsY + 0.05, w: 0.18, h: 0.18,
      fill: { color: C.amber }, line: { color: C.amber, width: 0 },
    });
    s.addText(p, {
      x: x + 0.3, y: pillarsY, w: 3.8, h: 0.3,
      fontFace: F.body, fontSize: 11, bold: true,
      color: C.textDark, align: "left", valign: "middle", margin: 0,
    });
  });
}

// --------------------------------------------------------------------------
// Slide 4 — Prime example: Incident response TODAY
// --------------------------------------------------------------------------
function slide4(pageNum, total) {
  const s = pres.addSlide();
  s.background = { color: C.pageBg };
  addPageChrome(s, { pageNum, total });
  addSlideTitle(s, "Incident response — today", "Prime example");

  // Flow row (5 boxes, manual labour) — muted style
  const steps = [
    { title: "Chat report",        body: "Free-form Mattermost message" },
    { title: "Engineer reads",     body: "Asks clarifying Qs by hand" },
    { title: "Diagnosis",          body: "Hunts logs / metrics / traces" },
    { title: "Hypothesis & fix",   body: "Writes ad-hoc commands" },
    { title: "Status updates",     body: "Channel comms manual" },
  ];
  const flowY = 2.6, flowH = 1.6, boxW = 2.18;
  const gap = (12.1 - steps.length * boxW) / (steps.length - 1);

  steps.forEach((st, i) => {
    const x = 0.6 + i * (boxW + gap);
    addCard(s, { x, y: flowY, w: boxW, h: flowH, fill: C.cardBg, border: C.divider });
    s.addText(st.title, {
      x: x + 0.15, y: flowY + 0.2, w: boxW - 0.3, h: 0.55,
      fontFace: F.header, fontSize: 14, bold: true,
      color: C.textDark, align: "left", valign: "top", margin: 0,
    });
    s.addText(st.body, {
      x: x + 0.15, y: flowY + 0.8, w: boxW - 0.3, h: 0.7,
      fontFace: F.body, fontSize: 11, color: C.textMid,
      align: "left", valign: "top", margin: 0,
    });
    if (i < steps.length - 1) {
      const ax1 = x + boxW + 0.05;
      const ax2 = x + boxW + gap - 0.05;
      addArrow(s, ax1, flowY + flowH/2, ax2, C.textMuted, 1.5);
    }
  });

  // Pain annotations under the flow
  const annotations = [
    { x: 0.6 + 0 * (boxW + gap), label: "Manual filter" },
    { x: 0.6 + 1 * (boxW + gap), label: "Back-and-forth" },
    { x: 0.6 + 2 * (boxW + gap), label: "Uneven by skill" },
    { x: 0.6 + 3 * (boxW + gap), label: "From scratch" },
    { x: 0.6 + 4 * (boxW + gap), label: "Easy to skip" },
  ];
  annotations.forEach(a => {
    s.addText(a.label, {
      x: a.x, y: flowY + flowH + 0.15, w: boxW, h: 0.3,
      fontFace: F.body, fontSize: 10, italic: true,
      color: C.warn, align: "center", valign: "middle", margin: 0,
    });
  });

  // Bottom outcome strip
  addCard(s, { x: 0.6, y: 5.5, w: 12.1, h: 1.2, fill: "FEF3F2", border: "FECACA", shadow: false });
  s.addText("Result today", {
    x: 0.95, y: 5.65, w: 3, h: 0.4,
    fontFace: F.header, fontSize: 14, bold: true,
    color: C.warn, align: "left", valign: "middle", margin: 0,
  });
  s.addText("Triage quality depends on who's on call.  Investigation re-derives what seniors already know.  Postmortems get written late, if at all.", {
    x: 0.95, y: 6.0, w: 11.5, h: 0.7,
    fontFace: F.body, fontSize: 12, color: C.textMid,
    align: "left", valign: "top", margin: 0,
  });
}

// --------------------------------------------------------------------------
// Slide 5 — Prime example: Incident response WITH FRAMEWORK
// --------------------------------------------------------------------------
function slide5(pageNum, total) {
  const s = pres.addSlide();
  s.background = { color: C.pageBg };
  addPageChrome(s, { pageNum, total });
  addSlideTitle(s, "Incident response — with the framework", "Prime example");

  // Main row (7 boxes)
  const mainSteps = [
    { title: "Signal",            sub: "Chat / Alert / Issue",      color: C.iceblue, textColor: C.navy },
    { title: "Duty Engineer",     sub: "Structures intake",          color: C.navy,    textColor: C.white },
    { title: "SRE Investigator",  sub: "Drafts investigation",       color: C.navy,    textColor: C.white },
    { title: "HITL gate",         sub: "On-call approves",           color: C.amber,   textColor: C.white, gate: true },
    { title: "Execute",           sub: "Ansible / GitLab CI",        color: C.iceblue, textColor: C.navy },
    { title: "Postmortem Scribe", sub: "Drafts review + actions",    color: C.navy,    textColor: C.white },
    { title: "Obs Engineer",      sub: "Drafts new dashboard + alert", color: C.navy,  textColor: C.white },
  ];
  const mainY = 2.0, mainH = 1.2, mboxW = 1.55;
  const mgap = (12.1 - mainSteps.length * mboxW) / (mainSteps.length - 1);

  // Draw connecting arrows first so boxes overlay them cleanly
  for (let i = 0; i < mainSteps.length - 1; i++) {
    const x = 0.6 + i * (mboxW + mgap);
    const ax1 = x + mboxW + 0.04;
    const ax2 = x + mboxW + mgap - 0.04;
    addArrow(s, ax1, mainY + mainH/2, ax2, C.navy, 1.5);
  }

  // Main boxes
  mainSteps.forEach((st, i) => {
    const x = 0.6 + i * (mboxW + mgap);
    addCard(s, { x, y: mainY, w: mboxW, h: mainH, fill: st.color, border: st.color, shadow: true });
    s.addText(st.title, {
      x: x + 0.08, y: mainY + 0.2, w: mboxW - 0.16, h: 0.45,
      fontFace: F.header, fontSize: 11, bold: true,
      color: st.textColor, align: "center", valign: "middle", margin: 0,
    });
    s.addText(st.sub, {
      x: x + 0.08, y: mainY + 0.65, w: mboxW - 0.16, h: 0.45,
      fontFace: F.body, fontSize: 9.5,
      color: st.gate ? C.white : (st.textColor === C.white ? C.iceblue : C.textMid),
      align: "center", valign: "middle", margin: 0,
    });
  });

  // Escalation branch — beneath positions 2 (SRE Investigator) and the HITL gate
  const escY = 4.6, escH = 1.05;
  // Down arrow from SRE Investigator (index 2)
  const investX = 0.6 + 2 * (mboxW + mgap);
  const investCx = investX + mboxW/2;
  addVerticalArrow(s, investCx, mainY + mainH + 0.05, escY - 0.05, C.amber, 1.5);
  // "escalate?" label, placed to the RIGHT of the vertical arrow (not on top of it)
  s.addText("escalate?", {
    x: investCx + 0.08, y: (mainY + mainH + escY) / 2 - 0.18, w: 0.95, h: 0.32,
    fontFace: F.body, fontSize: 10, italic: true, bold: true,
    color: C.amber, align: "left", valign: "middle", margin: 0,
  });

  // Two escalation boxes
  const princX = investX + 0.1;
  const princW = mboxW + 0.4;
  addCard(s, { x: princX, y: escY, w: princW, h: escH, fill: C.cardBg, border: C.amber, shadow: true });
  s.addText("Principal SRE", {
    x: princX + 0.1, y: escY + 0.1, w: princW - 0.2, h: 0.4,
    fontFace: F.header, fontSize: 12.5, bold: true,
    color: C.navy, align: "center", valign: "middle", margin: 0,
  });
  s.addText("Final RCA — uses arch docs + code", {
    x: princX + 0.1, y: escY + 0.5, w: princW - 0.2, h: 0.45,
    fontFace: F.body, fontSize: 10, color: C.textMid,
    align: "center", valign: "middle", margin: 0,
  });

  const remedX = princX + princW + 0.25;
  addCard(s, { x: remedX, y: escY, w: princW, h: escH, fill: C.cardBg, border: C.amber, shadow: true });
  s.addText("Remediation Engineer", {
    x: remedX + 0.1, y: escY + 0.1, w: princW - 0.2, h: 0.4,
    fontFace: F.header, fontSize: 12.5, bold: true,
    color: C.navy, align: "center", valign: "middle", margin: 0,
  });
  s.addText("Drafts the fix as an MR", {
    x: remedX + 0.1, y: escY + 0.5, w: princW - 0.2, h: 0.45,
    fontFace: F.body, fontSize: 10, color: C.textMid,
    align: "center", valign: "middle", margin: 0,
  });

  // Arrow between Principal SRE and Remediation Engineer
  addArrow(s, princX + princW + 0.04, escY + escH/2, remedX - 0.04, C.amber, 1.5);

  // Loop-back from Remediation Engineer up to HITL gate as a clean L-shape
  const hitlX = 0.6 + 3 * (mboxW + mgap);
  const hitlCenter = hitlX + mboxW/2;
  const remedCenter = remedX + princW/2;
  const elbowY = escY - 0.28;   // shared corner level between the two verticals
  // 1) up from Remediation Engineer (no arrowhead)
  s.addShape(pres.shapes.LINE, {
    x: remedCenter, y: elbowY,
    w: 0, h: escY - elbowY,
    line: { color: C.amber, width: 1.5, endArrowType: "none" },
  });
  // 2) horizontal across to the HITL column (no arrowhead)
  s.addShape(pres.shapes.LINE, {
    x: hitlCenter, y: elbowY,
    w: remedCenter - hitlCenter, h: 0,
    line: { color: C.amber, width: 1.5, endArrowType: "none" },
  });
  // 3) up into HITL gate bottom (arrowhead at top)
  s.addShape(pres.shapes.LINE, {
    x: hitlCenter, y: mainY + mainH + 0.04,
    w: 0, h: elbowY - (mainY + mainH + 0.04),
    line: { color: C.amber, width: 1.5, beginArrowType: "triangle", endArrowType: "none" },
  });

  // HITL callout label
  s.addText("HITL — single approve/edit/reject thread for the on-call", {
    x: hitlX - 1.5, y: mainY - 0.5, w: mboxW + 3.0, h: 0.35,
    fontFace: F.body, fontSize: 11, italic: true, bold: true,
    color: C.amber, align: "center", valign: "middle", margin: 0,
  });

  // Bottom outcome strip
  addCard(s, { x: 0.6, y: 6.05, w: 12.1, h: 1.0, fill: "ECFDF5", border: "BBF7D0", shadow: false });
  s.addText("Result with the framework", {
    x: 0.95, y: 6.15, w: 4.5, h: 0.35,
    fontFace: F.header, fontSize: 14, bold: true,
    color: C.good, align: "left", valign: "middle", margin: 0,
  });
  s.addText("Structured case in minutes  ·  consistent investigation regardless of who's on call  ·  every closed incident drafts its own postmortem and monitoring improvement.", {
    x: 0.95, y: 6.5, w: 11.5, h: 0.55,
    fontFace: F.body, fontSize: 12, color: C.textMid,
    align: "left", valign: "top", margin: 0,
  });
}

// --------------------------------------------------------------------------
// Slide 6 — Value landed
// --------------------------------------------------------------------------
function slide6(pageNum, total) {
  const s = pres.addSlide();
  s.background = { color: C.pageBg };
  addPageChrome(s, { pageNum, total });
  addSlideTitle(s, "What our SRE team gets back", "The value");

  // Three big stat-style cards
  const cards = [
    {
      stat: "Minutes",
      label: "to structured triage",
      body: "Chat reports become GitLab cases with initial investigation immediately — no waiting for someone to get to it.",
    },
    {
      stat: "Consistent",
      label: "investigation depth",
      body: "Every case gets the same L2 pass; hard cases get a senior reviewer with code + architecture context.",
    },
    {
      stat: "Compounding",
      label: "monitoring quality",
      body: "Every closed incident drafts a new dashboard and alert. Monitoring grows automatically over time.",
    },
  ];

  const cardW = 3.95, cardH = 4.5, gap = 0.13;
  const startX = 0.6;
  cards.forEach((c, i) => {
    const x = startX + i * (cardW + gap);
    const y = 1.85;
    addCard(s, { x, y, w: cardW, h: cardH });
    // Big stat — uses the full card width with center alignment so 11-char words fit
    s.addText(c.stat, {
      x: x + 0.05, y: y + 0.55, w: cardW - 0.1, h: 1.0,
      fontFace: F.header, fontSize: 32, bold: true,
      color: C.navy, align: "center", valign: "middle", margin: 0,
    });
    // Label
    s.addText(c.label, {
      x: x + 0.2, y: y + 1.65, w: cardW - 0.4, h: 0.45,
      fontFace: F.body, fontSize: 14, italic: true,
      color: C.amber, align: "center", valign: "middle", margin: 0,
    });
    // Divider
    s.addShape(pres.shapes.LINE, {
      x: x + 0.5, y: y + 2.35, w: cardW - 1.0, h: 0,
      line: { color: C.divider, width: 1 },
    });
    // Body
    s.addText(c.body, {
      x: x + 0.35, y: y + 2.6, w: cardW - 0.7, h: cardH - 2.8,
      fontFace: F.body, fontSize: 13, color: C.textMid,
      align: "left", valign: "top", margin: 0,
    });
  });

  // Bottom strip — closing note
  s.addText("And zero unauthorised state changes — humans approve every action.", {
    x: 0.6, y: 6.65, w: 12.1, h: 0.4,
    fontFace: F.body, fontSize: 14, italic: true,
    color: C.textDark, align: "center", valign: "middle", margin: 0,
  });
}

// --------------------------------------------------------------------------
// Slide 7 — Humans stay in command
// --------------------------------------------------------------------------
function slide7(pageNum, total) {
  const s = pres.addSlide();
  s.background = { color: C.pageBg };
  addPageChrome(s, { pageNum, total });
  addSlideTitle(s, "Humans approve every state change", "Governance");

  // Left side: mock HITL approval card
  const mockX = 0.6, mockY = 1.85, mockW = 6.2, mockH = 4.6;
  addCard(s, { x: mockX, y: mockY, w: mockW, h: mockH });
  // Mock header strip
  slide7Header(s, mockX, mockY, mockW);
  // Mock content
  s.addText("Proposed mitigation — restart api-svc pod in prod-east", {
    x: mockX + 0.3, y: mockY + 0.95, w: mockW - 0.6, h: 0.4,
    fontFace: F.header, fontSize: 15, bold: true,
    color: C.textDark, align: "left", valign: "middle", margin: 0,
  });
  s.addText("Hypothesis: memory leak after deploy at 09:12 UTC.  Mitigation:\nrolling-restart api-svc-* in prod-east.  Rollback: redeploy prior image.", {
    x: mockX + 0.3, y: mockY + 1.4, w: mockW - 0.6, h: 0.95,
    fontFace: F.body, fontSize: 11, color: C.textMid,
    align: "left", valign: "top", margin: 0,
  });
  // Confidence + affected
  s.addText("Confidence: 0.78  ·  Affected: api-svc (prod-east)  ·  Blast radius: low", {
    x: mockX + 0.3, y: mockY + 2.5, w: mockW - 0.6, h: 0.35,
    fontFace: F.body, fontSize: 10, italic: true,
    color: C.textMuted, align: "left", valign: "middle", margin: 0,
  });
  // Buttons
  const btnY = mockY + 3.3, btnH = 0.55, btnGap = 0.2;
  const btnW = (mockW - 0.6 - 2 * btnGap) / 3;
  const buttons = [
    { label: "Approve",          color: C.good,    textColor: C.white },
    { label: "Approve w/ edits", color: C.navy,    textColor: C.white },
    { label: "Reject",           color: C.cardBg,  textColor: C.warn, border: C.warn },
  ];
  buttons.forEach((b, i) => {
    const x = mockX + 0.3 + i * (btnW + btnGap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y: btnY, w: btnW, h: btnH,
      fill: { color: b.color },
      line: { color: b.border || b.color, width: b.border ? 1.5 : 0 },
      rectRadius: 0.06,
    });
    s.addText(b.label, {
      x, y: btnY, w: btnW, h: btnH,
      fontFace: F.body, fontSize: 12, bold: true,
      color: b.textColor, align: "center", valign: "middle", margin: 0,
    });
  });
  // Footer line
  s.addText("Approval signed against on-call rotation  ·  recorded in append-only audit log", {
    x: mockX + 0.3, y: mockY + mockH - 0.5, w: mockW - 0.6, h: 0.35,
    fontFace: F.body, fontSize: 10, italic: true,
    color: C.textMuted, align: "left", valign: "middle", margin: 0,
  });

  // Right side: three governance pillars
  const rightX = 7.2, rightW = 5.5;
  const pillars = [
    {
      title: "Default-deny permissions",
      body: "Every agent's tools are declared in git. Operators see the full list and can revoke any tool at runtime — no redeploy.",
    },
    {
      title: "Append-only audit log",
      body: "Every signal, agent call, tool call, and approval click is recorded with hashes. WORM storage, periodic verification.",
    },
    {
      title: "Hard budget caps",
      body: "Per-case and per-agent ceilings on tokens, tool calls, wall-clock. Tripping a cap pages on-call with the draft so far.",
    },
  ];
  const pY0 = 1.95, pH = 1.45, pGap = 0.15;
  pillars.forEach((p, i) => {
    const y = pY0 + i * (pH + pGap);
    addCard(s, { x: rightX, y, w: rightW, h: pH });
    // Left accent strip
    s.addShape(pres.shapes.RECTANGLE, {
      x: rightX, y: y, w: 0.1, h: pH,
      fill: { color: C.amber }, line: { color: C.amber, width: 0 },
    });
    s.addText(p.title, {
      x: rightX + 0.3, y: y + 0.15, w: rightW - 0.5, h: 0.4,
      fontFace: F.header, fontSize: 15, bold: true,
      color: C.navy, align: "left", valign: "middle", margin: 0,
    });
    s.addText(p.body, {
      x: rightX + 0.3, y: y + 0.55, w: rightW - 0.5, h: pH - 0.6,
      fontFace: F.body, fontSize: 12, color: C.textMid,
      align: "left", valign: "top", margin: 0,
    });
  });
}

function slide7Header(s, x, y, w) {
  s.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h: 0.7,
    fill: { color: C.navy }, line: { color: C.navy, width: 0 },
  });
  s.addText("CASE  ·  #INC-2026-0517-014", {
    x: x + 0.3, y: y, w: w - 0.6, h: 0.7,
    fontFace: F.body, fontSize: 11, bold: true,
    color: C.iceblue, charSpacing: 3, align: "left", valign: "middle", margin: 0,
  });
  s.addText("AWAITING APPROVAL", {
    x: x + w - 2.4, y: y, w: 2.1, h: 0.7,
    fontFace: F.body, fontSize: 10, bold: true,
    color: C.amber, align: "right", valign: "middle", margin: 0,
  });
}

// --------------------------------------------------------------------------
// Slide 8 — The value loop
// --------------------------------------------------------------------------
function slide8(pageNum, total) {
  const s = pres.addSlide();
  s.background = { color: C.pageBg };
  addPageChrome(s, { pageNum, total });
  addSlideTitle(s, "Every incident becomes better monitoring", "The value loop");

  // Five nodes in a horizontal flow with a "loop back" arrow underneath
  const nodes = [
    { title: "Incident",          sub: "Today: caught late or by chat" },
    { title: "Investigation",     sub: "Agents draft RCA + actions" },
    { title: "Postmortem Scribe", sub: "Timeline + factors + actions" },
    { title: "Obs Engineer",      sub: "Drafts dashboard + alert MR" },
    { title: "Next incident",     sub: "Caught earlier by automated alert" },
  ];
  const flowY = 2.8, flowH = 1.4, boxW = 2.18;
  const gap = (12.1 - nodes.length * boxW) / (nodes.length - 1);

  // Draw arrows first (under boxes for clean overlap)
  for (let i = 0; i < nodes.length - 1; i++) {
    const x = 0.6 + i * (boxW + gap);
    const ax1 = x + boxW + 0.03;
    const ax2 = x + boxW + gap - 0.03;
    addArrow(s, ax1, flowY + flowH/2, ax2, C.navy, 1.6);
  }

  nodes.forEach((n, i) => {
    const x = 0.6 + i * (boxW + gap);
    const isFirst = i === 0;
    const isLast = i === nodes.length - 1;
    const fill = (isFirst || isLast) ? C.amber : C.navy;
    const textColor = C.white;
    addCard(s, { x, y: flowY, w: boxW, h: flowH, fill, border: fill });
    s.addText(n.title, {
      x: x + 0.1, y: flowY + 0.18, w: boxW - 0.2, h: 0.5,
      fontFace: F.header, fontSize: 13.5, bold: true,
      color: textColor, align: "center", valign: "middle", margin: 0,
    });
    s.addText(n.sub, {
      x: x + 0.15, y: flowY + 0.7, w: boxW - 0.3, h: 0.65,
      fontFace: F.body, fontSize: 10.5,
      color: isFirst || isLast ? C.navyDeep : C.iceblue,
      align: "center", valign: "top", margin: 0,
    });
  });

  // Loop-back arrow: from Next incident back to Incident, with breathing room around the label
  const lastX = 0.6 + (nodes.length - 1) * (boxW + gap) + boxW/2;
  const firstX = 0.6 + boxW/2;
  const loopY = flowY + flowH + 0.7;   // a bit further from the row of boxes
  // Down from last node (arrowhead at bottom)
  addVerticalArrow(s, lastX, flowY + flowH + 0.04, loopY, C.amber, 1.5);
  // Across to first node (no arrow)
  s.addShape(pres.shapes.LINE, {
    x: firstX, y: loopY,
    w: lastX - firstX, h: 0,
    line: { color: C.amber, width: 1.5, endArrowType: "none" },
  });
  // Up into first node — positive h with beginArrowType so the arrow points up cleanly into the box
  s.addShape(pres.shapes.LINE, {
    x: firstX, y: flowY + flowH + 0.04,
    w: 0, h: loopY - (flowY + flowH + 0.04),
    line: { color: C.amber, width: 1.5, beginArrowType: "triangle", endArrowType: "none" },
  });
  // Label on loop arrow, placed below with clear breathing room
  s.addText("monitoring compounds — next time the issue arrives as an automated signal, with richer context", {
    x: 1.5, y: loopY + 0.25, w: 10.3, h: 0.4,
    fontFace: F.body, fontSize: 11.5, italic: true,
    color: C.amber, align: "center", valign: "middle", margin: 0,
  });

  // Bottom caption
  s.addText("This is how the framework's value compounds without engineers having to find time for the followup.", {
    x: 0.6, y: 6.55, w: 12.1, h: 0.5,
    fontFace: F.body, fontSize: 13, italic: true,
    color: C.textDark, align: "center", valign: "middle", margin: 0,
  });
}

// --------------------------------------------------------------------------
// Slide 9 — Phased rollout
// --------------------------------------------------------------------------
function slide9(pageNum, total) {
  const s = pres.addSlide();
  s.background = { color: C.pageBg };
  addPageChrome(s, { pageNum, total });
  addSlideTitle(s, "Five gated phases — each delivers value on its own", "Rollout");

  const phases = [
    { p: "0", title: "Foundations",            body: "Stand up supervisor, governance, audit log.  Apply GitLab label dictionary.  No agents enabled yet." },
    { p: "1", title: "Triage + Investigation", body: "Duty Engineer + SRE Investigator.  Read-only output.  First structured chat-intake cases." },
    { p: "2", title: "Drafting",               body: "SysAdmin Drafter + Postmortem Scribe.  First HITL gates fire.  First draft MRs and postmortems." },
    { p: "3", title: "Security + Compliance",  body: "Security Triage + Compliance Evidence.  Continuous evidence packets, exploitability assessments." },
    { p: "4", title: "Senior tier + Loop",     body: "Principal SRE + Remediation Engineer + Observability Engineer.  The value loop closes." },
  ];

  // Each phase as a vertical card
  const startX = 0.6, cardW = 2.36, cardH = 3.4, gap = 0.135;
  phases.forEach((ph, i) => {
    const x = startX + i * (cardW + gap);
    const y = 2.4;
    addCard(s, { x, y, w: cardW, h: cardH });
    // Phase header strip
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: cardW, h: 0.95,
      fill: { color: C.navy }, line: { color: C.navy, width: 0 },
    });
    s.addText(`Phase ${ph.p}`, {
      x: x + 0.2, y: y + 0.1, w: cardW - 0.4, h: 0.4,
      fontFace: F.body, fontSize: 11, bold: true,
      color: C.amber, charSpacing: 3, align: "left", valign: "middle", margin: 0,
    });
    s.addText(ph.title, {
      x: x + 0.2, y: y + 0.45, w: cardW - 0.4, h: 0.5,
      fontFace: F.header, fontSize: 15, bold: true,
      color: C.white, align: "left", valign: "middle", margin: 0,
    });
    // Body
    s.addText(ph.body, {
      x: x + 0.2, y: y + 1.15, w: cardW - 0.4, h: cardH - 1.4,
      fontFace: F.body, fontSize: 11.5, color: C.textMid,
      align: "left", valign: "top", margin: 0,
    });

    // Gate-arrow between phases
    if (i < phases.length - 1) {
      const ax = x + cardW;
      addArrow(s, ax + 0.005, y + 0.475, ax + gap - 0.005, C.amber, 1.5);
    }
  });

  // Bottom strip: gated criteria
  addCard(s, { x: 0.6, y: 6.35, w: 12.1, h: 0.7, fill: C.iceblue, border: C.iceblue, shadow: false });
  s.addText("Each phase is gated on the previous one's exit criteria — agent edit-rate, budget compliance, no out-of-scope tool calls.  No big bang.", {
    x: 0.85, y: 6.35, w: 11.6, h: 0.7,
    fontFace: F.body, fontSize: 12, italic: true,
    color: C.navy, align: "center", valign: "middle", margin: 0,
  });
}

// --------------------------------------------------------------------------
// Slide 10 — Honest limits
// --------------------------------------------------------------------------
function slide10(pageNum, total) {
  const s = pres.addSlide();
  s.background = { color: C.pageBg };
  addPageChrome(s, { pageNum, total });
  addSlideTitle(s, "What this framework won't do", "Honest limits");

  // Two columns: out of scope, key risks
  const colY = 1.85, colH = 5.0;
  const leftX = 0.6, leftW = 6.2;
  const rightX = 7.1, rightW = 5.6;

  // LEFT column — out of scope
  addCard(s, { x: leftX, y: colY, w: leftW, h: colH });
  s.addShape(pres.shapes.RECTANGLE, {
    x: leftX, y: colY, w: leftW, h: 0.6,
    fill: { color: C.navy }, line: { color: C.navy, width: 0 },
  });
  s.addText("Deliberately out of scope (v1)", {
    x: leftX + 0.3, y: colY, w: leftW - 0.6, h: 0.6,
    fontFace: F.header, fontSize: 15, bold: true,
    color: C.white, align: "left", valign: "middle", margin: 0,
  });
  const outOfScope = [
    "Autonomous state changes — humans approve everything",
    "Replacing the change-manager / CAB authority",
    "Replacing Grafana, GitLab, or Ansible",
    "Customer-facing communication",
    "Capacity forecasting (deterministic tooling wins)",
    "Drift detection (GitOps already covers it)",
    "Cost / FinOps optimisation",
  ];
  outOfScope.forEach((item, i) => {
    const y = colY + 0.85 + i * 0.55;
    s.addShape(pres.shapes.OVAL, {
      x: leftX + 0.35, y: y + 0.12, w: 0.13, h: 0.13,
      fill: { color: C.navy }, line: { color: C.navy, width: 0 },
    });
    s.addText(item, {
      x: leftX + 0.6, y: y, w: leftW - 0.8, h: 0.4,
      fontFace: F.body, fontSize: 12, color: C.textDark,
      align: "left", valign: "middle", margin: 0,
    });
  });

  // RIGHT column — quality caveat + key risks
  addCard(s, { x: rightX, y: colY, w: rightW, h: colH });
  s.addShape(pres.shapes.RECTANGLE, {
    x: rightX, y: colY, w: rightW, h: 0.6,
    fill: { color: C.amber }, line: { color: C.amber, width: 0 },
  });
  s.addText("Known limits to call out", {
    x: rightX + 0.3, y: colY, w: rightW - 0.6, h: 0.6,
    fontFace: F.header, fontSize: 15, bold: true,
    color: C.navyDeep, align: "left", valign: "middle", margin: 0,
  });
  const limits = [
    { h: "On-prem quality gap",
      body: "Open-weight frontier models are visibly weaker than online. Plan for higher human edit rate in air-gapped deployments." },
    { h: "Hallucination is real",
      body: "Every draft is HITL-reviewed; \"AI draft — verify\" tag persists for first 90 days." },
    { h: "Not free",
      body: "GPU and inference cost; budget caps keep it bounded but it is real." },
    { h: "Preconditions required",
      body: "GitLab labels, service catalogue, on-call API, playbook inventory must be in place first." },
  ];
  let lY = colY + 0.85;
  limits.forEach((l) => {
    // small amber dot to mirror the left column's bullet style
    s.addShape(pres.shapes.OVAL, {
      x: rightX + 0.35, y: lY + 0.12, w: 0.13, h: 0.13,
      fill: { color: C.amber }, line: { color: C.amber, width: 0 },
    });
    s.addText(l.h, {
      x: rightX + 0.6, y: lY, w: rightW - 0.95, h: 0.35,
      fontFace: F.header, fontSize: 13, bold: true,
      color: C.navy, align: "left", valign: "middle", margin: 0,
    });
    s.addText(l.body, {
      x: rightX + 0.6, y: lY + 0.35, w: rightW - 0.95, h: 0.7,
      fontFace: F.body, fontSize: 11.5, color: C.textMid,
      align: "left", valign: "top", margin: 0,
    });
    lY += 1.0;
  });
}

// --------------------------------------------------------------------------
// Slide 11 — The ask
// --------------------------------------------------------------------------
function slide11(pageNum, total) {
  const s = pres.addSlide();
  s.background = { color: C.navy };
  // Slim amber accent line at the very top, not a thick band
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 13.3, h: 0.08,
    fill: { color: C.amber }, line: { color: C.amber, width: 0 },
  });
  // Footer brand + page indicator (light text directly on the dark background)
  s.addText("Agentic SRE Framework  ·  Management Brief", {
    x: 0.6, y: 7.15, w: 8, h: 0.3,
    fontFace: F.body, fontSize: 9, color: C.iceblue,
    align: "left", valign: "middle", margin: 0,
  });
  s.addText(`${pageNum} / ${total}`, {
    x: 12.0, y: 7.15, w: 1.0, h: 0.3,
    fontFace: F.body, fontSize: 9, color: C.iceblue,
    align: "right", valign: "middle", margin: 0,
  });

  // Eyebrow
  s.addText("THE ASK", {
    x: 0.8, y: 1.0, w: 12, h: 0.4,
    fontFace: F.body, fontSize: 13, bold: true,
    color: C.amber, charSpacing: 6, margin: 0,
  });
  // Title
  s.addText("Approve Phase 0 — Foundations", {
    x: 0.8, y: 1.5, w: 12, h: 1.0,
    fontFace: F.header, fontSize: 40, bold: true,
    color: C.white, align: "left", valign: "top", margin: 0,
  });

  // Sub
  s.addText("Stand up the orchestration plane, audit log, governance dashboard, and the GitLab label dictionary.  No agents enabled yet — only the foundations that make the rest gated and safe.", {
    x: 0.8, y: 2.7, w: 11.0, h: 1.2,
    fontFace: F.body, fontSize: 17, italic: true,
    color: C.iceblue, align: "left", valign: "top", margin: 0,
  });

  // Two columns at the bottom: What we need, Who owns it
  const yBase = 4.4, ch = 2.5;
  // Left
  addCard(s, { x: 0.8, y: yBase, w: 5.9, h: ch, fill: "2A3F73", border: C.amber, shadow: false });
  s.addText("What we need from you", {
    x: 1.05, y: yBase + 0.2, w: 5.4, h: 0.4,
    fontFace: F.body, fontSize: 11, bold: true,
    color: C.amber, charSpacing: 3, align: "left", valign: "middle", margin: 0,
  });
  const asks = [
    "Approval to proceed with Phase 0",
    "SRE team headcount for the framework operator role",
    "Security sign-off on default-deny permission model",
    "Budget envelope for inference cost in pilot quarter",
  ];
  asks.forEach((a, i) => {
    const y = yBase + 0.7 + i * 0.42;
    s.addShape(pres.shapes.OVAL, {
      x: 1.1, y: y + 0.12, w: 0.13, h: 0.13,
      fill: { color: C.amber }, line: { color: C.amber, width: 0 },
    });
    s.addText(a, {
      x: 1.35, y: y, w: 5.2, h: 0.4,
      fontFace: F.body, fontSize: 13, color: C.white,
      align: "left", valign: "middle", margin: 0,
    });
  });

  // Right — who owns + how we know we're winning
  addCard(s, { x: 7.0, y: yBase, w: 5.8, h: ch, fill: "2A3F73", border: C.amber, shadow: false });
  s.addText("How we know we're winning", {
    x: 7.25, y: yBase + 0.2, w: 5.3, h: 0.4,
    fontFace: F.body, fontSize: 11, bold: true,
    color: C.amber, charSpacing: 3, align: "left", valign: "middle", margin: 0,
  });
  const measures = [
    "Every chat report becomes a GitLab case within minutes",
    "Every service ticket arrives with a draft playbook",
    "Every closed postmortem produces a merged dashboard",
    "Zero unauthorised state changes",
  ];
  measures.forEach((m, i) => {
    const y = yBase + 0.7 + i * 0.42;
    s.addShape(pres.shapes.OVAL, {
      x: 7.3, y: y + 0.12, w: 0.13, h: 0.13,
      fill: { color: C.amber }, line: { color: C.amber, width: 0 },
    });
    s.addText(m, {
      x: 7.55, y: y, w: 5.1, h: 0.4,
      fontFace: F.body, fontSize: 13, color: C.white,
      align: "left", valign: "middle", margin: 0,
    });
  });
}

// --------------------------------------------------------------------------
// Build deck
// --------------------------------------------------------------------------
const TOTAL = 11;
slide1();
slide2(2, TOTAL);
slide3(3, TOTAL);
slide4(4, TOTAL);
slide5(5, TOTAL);
slide6(6, TOTAL);
slide7(7, TOTAL);
slide8(8, TOTAL);
slide9(9, TOTAL);
slide10(10, TOTAL);
slide11(11, TOTAL);

pres.writeFile({ fileName: "/Users/alexgoh/Code/agentic-ons/agentic-sre-framework/docs/decks/management-brief.pptx" })
  .then(fn => console.log("Wrote " + fn));
