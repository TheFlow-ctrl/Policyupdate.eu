// Loads digest.json (written by fetch_digest.py) and renders it as cards,
// filtered by three independent dimensions:
//   1. field (Green Deal, Security, Tech, Health)
//   2. topic -- which EU law an entry mentions, within Green Deal
//      (see TOPIC_LABELS, kept in sync with LEGISLATION_TAGS in fetch_digest.py)
//   3. actor type -- what kind of source it is (see ACTOR_LABELS, kept in
//      sync with the actor_type values used in sources.yaml)
// No build step, no framework — just fetch + template strings.

const FIELD_LABELS = {
  "green-deal": "Green Deal",
  security: "Security",
  tech: "Tech",
  health: "Health",
};

// Keep in sync with LEGISLATION_TAGS in fetch_digest.py.
const TOPIC_LABELS = {
  ets1: "ETS I",
  ets2: "ETS II",
  cbam: "CBAM",
  red3: "RED III",
  csddd: "CSDDD",
  crma: "CRMA",
  nzia: "NZIA",
  csrd: "CSRD",
  taxonomy: "EU Taxonomy",
  sfdr: "SFDR",
  eudr: "EUDR",
  "nature-restoration": "Nature Restoration Law",
  lulucf: "LULUCF",
  ccus: "CCUS",
  eed: "EED",
};

// Keep in sync with actor_type values in sources.yaml.
const ACTOR_LABELS = {
  "think-tank": "Think Tank",
  academic: "Academic Journal",
  political: "Political",
  industry: "Industry & Lobby Groups",
  ngo: "NGO & Advocacy",
  "eu-institution": "EU Institutions",
};

// Plain-language explainer + "why it matters" + link to the original legal
// text for each law, shown as an info card whenever that topic filter is
// active. Written for a general reader, not a policy specialist. Keep ids
// in sync with TOPIC_LABELS / LEGISLATION_TAGS.
const TOPIC_INFO = {
  ets1: {
    instrument: "Directive 2003/87/EC",
    description:
      "The EU's carbon market. It puts a price on CO2 from power plants, heavy industry and flights within Europe — companies get a shrinking number of permits each year and must buy more if they emit beyond that.",
    whyItMatters:
      "It's the EU's main tool for making pollution cost money, which pushes industry toward cleaner technology.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32003L0087",
  },
  ets2: {
    instrument: "Directive (EU) 2023/959",
    description:
      "A second, separate carbon price covering the fuel used to heat buildings and to power cars and trucks, starting in 2027.",
    whyItMatters:
      "Unlike the original carbon market, this is the part that will eventually show up in people's heating and fuel bills, not just industry's costs.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023L0959",
  },
  cbam: {
    instrument: "Regulation (EU) 2023/956",
    description:
      "A charge on imports of carbon-heavy goods like steel, cement, aluminium and fertiliser, matching the carbon price European producers already pay.",
    whyItMatters:
      "It stops European industry from being undercut by cheaper goods made in countries with weaker climate rules, and pressures those countries to clean up too.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R0956",
  },
  red3: {
    instrument: "Directive (EU) 2023/2413",
    description:
      "Sets a target for how much of Europe's energy must come from renewable sources by 2030 (at least 42.5%), with specific goals for industry, transport, heating and hydrogen.",
    whyItMatters:
      "It's the main driver behind the growth of wind, solar and renewable hydrogen projects across the EU.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023L2413",
  },
  csddd: {
    instrument: "Directive (EU) 2024/1760",
    description:
      "Requires large companies to check that their suppliers anywhere in the world aren't causing serious harm to people or the environment, and to have a credible plan for cutting their own climate impact.",
    whyItMatters:
      "It makes big companies legally responsible for problems — like forced labour or pollution — deep in their supply chains, not just their own factories.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024L1760",
  },
  crma: {
    instrument: "Regulation (EU) 2024/1252",
    description:
      "Sets targets for Europe to mine, process and recycle more of the raw materials — like lithium, cobalt and rare earths — needed for batteries, wind turbines and electronics, and speeds up permits for projects that do.",
    whyItMatters:
      "Europe currently depends heavily on a handful of countries, especially China, for these materials; this law is about reducing that dependence.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1252",
  },
  nzia: {
    instrument: "Regulation (EU) 2024/1735",
    description:
      "Aims to get at least 40% of the clean-energy equipment Europe needs — solar panels, batteries, heat pumps, electrolysers — manufactured in Europe itself, with faster permits and support for factories.",
    whyItMatters:
      "It's the EU's response to competition from cheaper, subsidised clean-tech manufacturing in China and the US.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1735",
  },
  csrd: {
    instrument: "Directive (EU) 2022/2464",
    description:
      "Requires large companies, and many listed smaller ones, to publish detailed, standardised reports on their environmental and social impact, checked by outside auditors.",
    whyItMatters:
      "It's meant to stop vague \"greenwashing\" claims by forcing companies to report real, comparable numbers on things like emissions and labour practices.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022L2464",
  },
  taxonomy: {
    instrument: "Regulation (EU) 2020/852",
    description:
      "A rulebook defining which business activities can officially be called \"environmentally sustainable\" in the EU.",
    whyItMatters:
      "It's the reference point investors, banks and companies use to back up — or challenge — claims that money is being invested \"green.\"",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32020R0852",
  },
  sfdr: {
    instrument: "Regulation (EU) 2019/2088",
    description:
      "Requires investment funds and financial advisers to disclose how sustainable their products really are, using a common set of categories.",
    whyItMatters:
      "It's why you'll see investment funds labelled by their sustainability tier when you look at products in Europe.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32019R2088",
  },
  eudr: {
    instrument: "Regulation (EU) 2023/1115",
    description:
      "Bans selling products in the EU — like coffee, cocoa, palm oil, beef, timber and rubber — if they were grown on land deforested after 2020, and requires proof of where they came from.",
    whyItMatters:
      "It puts the burden of proof on companies to show their supply chains aren't driving deforestation, rather than leaving it to consumers to guess.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R1115",
  },
  "nature-restoration": {
    instrument: "Regulation (EU) 2024/1991",
    description:
      "Sets binding targets to repair damaged nature — wetlands, forests, rivers, farmland habitats — covering at least a fifth of the EU's land and sea by 2030.",
    whyItMatters:
      "It's the EU's first legally binding commitment to actively restore nature, not just slow its decline.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1991",
  },
  lulucf: {
    instrument: "Regulation (EU) 2018/841 (as amended by (EU) 2023/839)",
    description:
      "Sets targets for how much CO2 Europe's forests, soils and farmland must absorb from the atmosphere, and requires countries to report and offset losses — for example from deforestation or wildfires.",
    whyItMatters:
      "Forests and land are supposed to be one of Europe's biggest natural carbon sinks; this law is what keeps countries accountable for protecting that.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32018R0841",
  },
  ccus: {
    instrument: "Directive 2009/31/EC",
    description:
      "Sets the legal rules for capturing CO2 from industrial sites and storing it permanently underground, plus (via the Net-Zero Industry Act) a target for how much storage capacity Europe should build.",
    whyItMatters:
      "It's central to plans for cleaning up industries — like cement and steel — where cutting emissions to zero any other way is very difficult.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009L0031",
  },
  eed: {
    instrument: "Directive (EU) 2023/1791",
    description:
      "Sets a binding target to cut how much energy Europe uses overall — by at least 11.7% by 2030 — and requires governments to renovate public buildings and run energy-saving programmes.",
    whyItMatters:
      "Using less energy in the first place is usually the cheapest way to cut emissions, and it directly affects things like building renovation rules.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023L1791",
  },
};

let digestData = null;
let archiveData = null;
let policyCycleData = null;
let activeField = "green-deal";
let activeTopic = "all";
let activeActor = "all";

// Fixed display order for the 15 laws in the Policy Cycle view -- matches
// the order the law tabs already appear in, in index.html.
const POLICY_CYCLE_LAW_ORDER = [
  "ets1", "ets2", "cbam", "red3", "csddd", "crma", "nzia", "csrd",
  "taxonomy", "sfdr", "eudr", "nature-restoration", "lulucf", "ccus", "eed",
];

async function loadDigest() {
  const entriesEl = document.getElementById("entries");
  const dateEl = document.getElementById("generated-date");

  try {
    const res = await fetch("digest.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    digestData = await res.json();
    dateEl.textContent = digestData.generated ? `Updated ${digestData.generated}` : "";
    renderActiveField();
  } catch (err) {
    entriesEl.innerHTML =
      '<p class="error">Couldn\'t load the digest yet. Run <code>fetch_digest.py</code> to generate site/digest.json, ' +
      "then reload this page.</p>";
    console.error(err);
  }
}

function matchesFilters(entry) {
  const topicOk = activeTopic === "all" || (entry.tags || []).includes(activeTopic);
  const actorOk = activeActor === "all" || (entry.actor_type || "think-tank") === activeActor;
  return topicOk && actorOk;
}

function renderTopicInfo() {
  const el = document.getElementById("topic-info");
  if (!el) return;

  if (activeTopic === "all" || !TOPIC_INFO[activeTopic]) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }

  const info = TOPIC_INFO[activeTopic];
  const label = escapeHtml(TOPIC_LABELS[activeTopic] || activeTopic);

  el.hidden = false;
  el.innerHTML = `
    <h3>${label}</h3>
    <p>${escapeHtml(info.description)}</p>
    <p class="topic-info-why"><strong>Why it matters:</strong> ${escapeHtml(info.whyItMatters)}</p>
    <p class="topic-info-source">${escapeHtml(info.instrument)} · <a href="${info.eurlexUrl}" target="_blank" rel="noopener">official legal text on EUR-Lex ↗</a></p>
  `;
}

function renderActiveField() {
  const entriesEl = document.getElementById("entries");
  const labelEl = document.getElementById("active-field-label");
  labelEl.textContent = `— ${FIELD_LABELS[activeField] || activeField}`;
  renderTopicInfo();

  if (!digestData || !digestData.entries) return;

  const filtered = digestData.entries.filter(
    (e) => (e.field || "green-deal") === activeField && matchesFilters(e)
  );

  if (filtered.length === 0) {
    entriesEl.innerHTML = activeTopic === "all" && activeActor === "all"
      ? '<p class="empty">No new publications this week — check back soon.</p>'
      : '<p class="empty">No entries this week match that filter.</p>';
    return;
  }

  entriesEl.innerHTML = filtered.map(renderEntry).join("");
}

function setupFieldTabs() {
  const tabs = document.querySelectorAll(".field-tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      if (tab.disabled) return;
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");

      if (tab.dataset.view === "archive") {
        showArchiveView();
      } else if (tab.dataset.view === "policy-cycle") {
        showPolicyCycleView();
      } else {
        activeField = tab.dataset.field;
        showDigestView();
        renderActiveField();
      }
    });
  });
}

function setupTopicTabs() {
  const tabs = document.querySelectorAll(".topic-tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      activeTopic = tab.dataset.topic;
      rerenderCurrentView();
    });
  });
}

function setupActorTabs() {
  const tabs = document.querySelectorAll(".actor-tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      activeActor = tab.dataset.actor;
      rerenderCurrentView();
    });
  });
}

function rerenderCurrentView() {
  const policyCycleVisible = !document.getElementById("policy-cycle-section").hidden;
  const archiveVisible = !document.getElementById("archive-section").hidden;
  if (policyCycleVisible) {
    renderPolicyCycle();
  } else if (archiveVisible) {
    renderArchive();
  } else {
    renderActiveField();
  }
}

function showDigestView() {
  document.getElementById("digest-section").hidden = false;
  document.getElementById("archive-section").hidden = true;
  document.getElementById("policy-cycle-section").hidden = true;
  document.getElementById("topic-tabs").hidden = false;
  document.getElementById("actor-tabs").hidden = false;
}

function showArchiveView() {
  document.getElementById("digest-section").hidden = true;
  document.getElementById("archive-section").hidden = false;
  document.getElementById("policy-cycle-section").hidden = true;
  document.getElementById("topic-tabs").hidden = false;
  document.getElementById("actor-tabs").hidden = false;
  loadArchive();
}

// The law/topic filter (ETS I, CBAM, ...) applies here too -- clicking a
// law shows just that law's diagram. Actor type (Academic/Political/Lobby)
// doesn't apply to a law's own legislative status, so that bar stays
// hidden, along with the per-law info card (description/EUR-Lex link),
// which would otherwise duplicate what each diagram's caption already says.
function showPolicyCycleView() {
  document.getElementById("digest-section").hidden = true;
  document.getElementById("archive-section").hidden = true;
  document.getElementById("policy-cycle-section").hidden = false;
  document.getElementById("topic-tabs").hidden = false;
  document.getElementById("actor-tabs").hidden = true;
  document.getElementById("topic-info").hidden = true;
  loadPolicyCycle();
}

async function loadPolicyCycle() {
  const legendEl = document.getElementById("policy-cycle-legend");
  const lawsEl = document.getElementById("policy-cycle-laws");

  if (policyCycleData) {
    renderPolicyCycle();
    return;
  }

  try {
    const res = await fetch("policy_stages.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    policyCycleData = await res.json();
    renderPolicyCycle();
  } catch (err) {
    legendEl.innerHTML = "";
    lawsEl.innerHTML =
      '<p class="error">Couldn\'t load policy cycle data. Run <code>fetch_digest.py</code> or check that site/policy_stages.json exists.</p>';
    console.error(err);
  }
}

function renderPolicyCycle() {
  const legendEl = document.getElementById("policy-cycle-legend");
  const lawsEl = document.getElementById("policy-cycle-laws");
  if (!policyCycleData) return;

  const { stages, laws } = policyCycleData;

  // Stage names are now printed directly on each diagram, so the separate
  // numbered legend that used to live here would just repeat them -- a
  // single explanatory line is enough. A framing line sits above it: why
  // this view matters, before how to read it.
  legendEl.innerHTML =
    '<p class="policy-cycle-legend-intro">In Brussels you need to know what is happening when. Here we help you understand where in the policy cycle each law currently stands and what the next deadline is.</p>' +
    '<p><span class="policy-cycle-legend-label">How to read this:</span> each diagram traces a law\'s path through all 9 stages of the EU legislative process; the gold node marks where it stands today.</p>';

  // The law/topic filter (shared with the digest/archive views) applies
  // here too -- selecting e.g. "CBAM" shows just that law's diagram.
  const idsToShow =
    activeTopic === "all" ? POLICY_CYCLE_LAW_ORDER : POLICY_CYCLE_LAW_ORDER.filter((id) => id === activeTopic);
  const visibleIds = idsToShow.filter((id) => laws[id]);

  lawsEl.innerHTML = visibleIds.length
    ? visibleIds.map((id) => renderLawCycle(id, laws[id], stages)).join("")
    : '<p class="empty">No policy cycle data for this law yet.</p>';
}

function renderLawCycle(lawId, law, stages) {
  const label = escapeHtml(TOPIC_LABELS[lawId] || lawId);
  const currentIndex = stages.findIndex((s) => s.id === law.current_stage);
  const currentLabel = stages[currentIndex] ? stages[currentIndex].label : law.current_stage;

  const nextDeadline = law.next_deadline ? ` — expected ${escapeHtml(law.next_deadline)}` : "";

  // Only shown for laws Omnibus actually touched -- badging all 15 would
  // bury the (few) laws where it matters under noise from the 12 it didn't.
  const omnibusBadge =
    law.omnibus_impact && law.omnibus_impact !== "none"
      ? `<span class="policy-cycle-omnibus-badge policy-cycle-omnibus-${escapeHtml(
          law.omnibus_impact
        )}">Omnibus-affected</span>`
      : "";

  const omnibusNote =
    law.omnibus_impact && law.omnibus_impact !== "none" && law.omnibus_note
      ? `<p class="policy-cycle-omnibus-note"><strong>Omnibus impact:</strong> ${escapeHtml(law.omnibus_note)}</p>`
      : "";

  const oeilCitation =
    law.oeil_url && law.oeil_procedure
      ? `<p class="policy-cycle-source">Source: <a href="${law.oeil_url}" target="_blank" rel="noopener">European Parliament Legislative Observatory (OEIL) — ${escapeHtml(
          law.oeil_procedure
        )} ↗</a></p>`
      : "";

  const revisionBlock = law.active_revision ? renderRevisionBlock(law.active_revision, stages) : "";

  return `
    <div class="policy-cycle-law">
      <h3>${label} <span class="policy-cycle-current-stage">— currently: ${escapeHtml(currentLabel)}</span>${omnibusBadge}</h3>
      ${buildStepperSvg(stages, currentIndex, law.stage_dates)}
      <p class="policy-cycle-caption"><strong>Next:</strong> ${escapeHtml(law.next_step || "—")}${nextDeadline}</p>
      ${law.notes ? `<p class="policy-cycle-notes">${escapeHtml(law.notes)}</p>` : ""}
      ${omnibusNote}
      ${oeilCitation}
      ${revisionBlock}
    </div>
  `;
}

// Renders a law's active revision (a separate, ongoing legislative
// procedure amending an already-adopted law) as a visually distinct
// sub-card: a different accent color throughout -- both the card border
// and the diagram's current-stage node -- so it reads unmistakably as its
// own, separate policy cycle rather than a continuation of the main one.
function renderRevisionBlock(revision, stages) {
  const currentIndex = stages.findIndex((s) => s.id === revision.current_stage);
  const currentLabel = stages[currentIndex] ? stages[currentIndex].label : revision.current_stage;
  const nextDeadline = revision.next_deadline ? ` — expected ${escapeHtml(revision.next_deadline)}` : "";
  const oeilCitation =
    revision.oeil_url && revision.oeil_procedure
      ? `<p class="policy-cycle-source">Source: <a href="${revision.oeil_url}" target="_blank" rel="noopener">European Parliament Legislative Observatory (OEIL) — ${escapeHtml(
          revision.oeil_procedure
        )} ↗</a></p>`
      : "";

  return `
    <div class="policy-cycle-revision">
      <h4><span class="policy-cycle-revision-badge">Active revision</span> ${escapeHtml(revision.label)} <span class="policy-cycle-current-stage">— currently: ${escapeHtml(currentLabel)}</span></h4>
      ${buildStepperSvg(stages, currentIndex, revision.stage_dates, REVISION_ACCENT)}
      <p class="policy-cycle-caption"><strong>Next:</strong> ${escapeHtml(revision.next_step || "—")}${nextDeadline}</p>
      ${revision.notes ? `<p class="policy-cycle-notes">${escapeHtml(revision.notes)}</p>` : ""}
      ${oeilCitation}
    </div>
  `;
}

// Formats an ISO date ("YYYY-MM-DD" or "YYYY-MM") as a compact "Mon YYYY"
// string for display inside the diagram, where horizontal space per node is
// tight. Returns "" for null/missing dates.
const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function formatShortDate(isoDate) {
  if (!isoDate) return "";
  const m = /^(\d{4})-(\d{2})/.exec(isoDate);
  if (!m) return isoDate;
  const year = m[1];
  const monthIndex = parseInt(m[2], 10) - 1;
  const monthName = MONTH_ABBR[monthIndex];
  return monthName ? `${monthName} ${year}` : isoDate;
}

// Accent used for an active-revision sub-diagram's current-stage node, in
// place of the main diagram's gold -- a deliberately different color so a
// revision's diagram is visually unmistakable as its own, separate cycle
// even at a glance. { current, label } mirror the gold/gold-dark pairing
// used for the main diagram's CURRENT_COLOR/LABEL_CURRENT.
const REVISION_ACCENT = { current: "#2C6E8A", label: "#1D4A5C" };

// Builds an "S" stepper diagram (a boustrophedon path: top row left-to-right,
// middle row right-to-left, bottom row left-to-right -- starting top-left,
// ending bottom-right) as an inline SVG string, with each stage's full name
// AND date (when known) printed at its node. Completed stages are solid
// navy, the current stage is a larger accent-colored node (gold by default,
// overridable via `accent` -- see REVISION_ACCENT), upcoming stages are
// muted outlines. Assumes exactly 9 stages (3 rows of 3) -- if the stage
// list ever changes length, this layout needs revisiting.
function buildStepperSvg(stages, currentIndex, stageDates, accent) {
  const dates = stageDates || {};
  const width = 680;
  const height = 560;
  const colX = [560, 340, 120]; // right, middle, left
  const rowY = [90, 280, 470];
  const n = stages.length;

  const DONE_COLOR = "#1E3A57"; // var(--navy-700)
  const CURRENT_COLOR = accent ? accent.current : "#C9A227"; // var(--gold)
  const UPCOMING_COLOR = "#DEDACD"; // var(--border)
  const UPCOMING_STROKE = "#B7B2A3";
  const LABEL_DONE = "#1E3A57";
  const LABEL_CURRENT = accent ? accent.label : "#8A6F1E";
  const LABEL_UPCOMING = "#5B6B78";
  const ARROW_OPACITY = 0.4; // kept faint so lines don't visually clash with the stage labels

  // Position of stage i: row = floor(i/3); even rows run left-to-right
  // (colX reversed to left/mid/right), odd rows run right-to-left (colX
  // as-is, right/mid/left) -- so the path starts top-left and ends
  // bottom-right.
  function pos(i) {
    const row = Math.floor(i / 3);
    const posInRow = i % 3;
    const cols = row % 2 === 0 ? [...colX].reverse() : colX;
    return { x: cols[posInRow], y: rowY[row] };
  }

  const defs = `<defs>
    <marker id="arrow-done" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="${DONE_COLOR}" fill-opacity="${ARROW_OPACITY}" />
    </marker>
    <marker id="arrow-upcoming" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="${UPCOMING_STROKE}" fill-opacity="${ARROW_OPACITY}" />
    </marker>
  </defs>`;

  // Connecting arrows: gentle curves rather than straight segments, so the
  // whole path reads as one smooth flowing S rather than a blocky zigzag.
  // Horizontal (within-row) segments get a slight arc; vertical
  // (row-to-row) segments get a proper S-wiggle cubic bezier, since those
  // are the "corners" where the smoothing matters most.
  let arrows = "";
  for (let i = 0; i < n - 1; i++) {
    const a = pos(i);
    const b = pos(i + 1);
    const row = Math.floor(i / 3);
    const done = i + 1 <= currentIndex;
    const color = done ? DONE_COLOR : UPCOMING_STROKE;
    const marker = `url(#arrow-${done ? "done" : "upcoming"})`;

    if (a.y === b.y) {
      // Same row: shorten so the curve doesn't run under the node circles,
      // then bow it gently up or down.
      const dir = b.x > a.x ? 1 : -1;
      const x1 = a.x + dir * 22;
      const x2 = b.x - dir * 22;
      const midX = (x1 + x2) / 2;
      const bow = row === 1 ? -14 : 14; // middle row bows up, outer rows bow down
      arrows += `<path d="M ${x1} ${a.y} Q ${midX} ${a.y + bow} ${x2} ${b.y}" fill="none" stroke="${color}" stroke-opacity="${ARROW_OPACITY}" stroke-width="2.5" marker-end="${marker}" />`;
    } else {
      // Row transition: same x, different y -- an S-wiggle cubic bezier
      // (bulge right then left) turns the sharp corner into a smooth curve.
      const y1 = a.y + 22;
      const y2 = b.y - 22;
      const dx = 26;
      const cy1 = y1 + (y2 - y1) / 3;
      const cy2 = y1 + (2 * (y2 - y1)) / 3;
      arrows += `<path d="M ${a.x} ${y1} C ${a.x + dx} ${cy1}, ${a.x - dx} ${cy2}, ${a.x} ${y2}" fill="none" stroke="${color}" stroke-opacity="${ARROW_OPACITY}" stroke-width="2.5" marker-end="${marker}" />`;
    }
  }

  // Nodes + embedded labels.
  let nodes = "";
  for (let i = 0; i < n; i++) {
    const { x, y } = pos(i);
    const stage = stages[i];
    let radius = 11;
    let fill = UPCOMING_COLOR;
    let stroke = UPCOMING_STROKE;
    let numColor = "white";
    let labelColor = LABEL_UPCOMING;
    let labelWeight = "500";

    if (i < currentIndex) {
      fill = DONE_COLOR;
      stroke = DONE_COLOR;
      numColor = "white";
      labelColor = LABEL_DONE;
    } else if (i === currentIndex) {
      radius = 18;
      fill = CURRENT_COLOR;
      stroke = CURRENT_COLOR;
      numColor = "#16202A";
      labelColor = LABEL_CURRENT;
      labelWeight = "700";
    } else {
      numColor = "#5B6B78";
    }

    // Label (and date, when known) sits below nodes in the two
    // right-to-left rows (even rows) and above nodes in the left-to-right
    // middle row, so text never collides with the vertical connector
    // arrows running along the left/right edges. The date line continues
    // outward past the name line, in the same direction.
    const row = Math.floor(i / 3);
    const outward = row % 2 === 0 ? 1 : -1;
    const labelY = y + outward * (radius + (row % 2 === 0 ? 20 : 12));
    const dateY = labelY + outward * 16;

    const rawDate = dates[stage.id];
    const shortDate = i <= currentIndex ? formatShortDate(rawDate) : ""; // only show dates for stages already reached
    const dateLine = shortDate
      ? `<text x="${x}" y="${dateY}" text-anchor="middle" font-size="10.5" font-family="IBM Plex Sans, sans-serif" fill="${labelColor}" opacity="0.75">${escapeHtml(shortDate)}</text>`
      : "";

    const tooltipDate = rawDate ? ` — ${escapeHtml(formatShortDate(rawDate))}` : "";

    nodes += `<g>
      <circle cx="${x}" cy="${y}" r="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="2">
        <title>${escapeHtml(`${i + 1}. ${stage.label}`)}${tooltipDate}${i === currentIndex ? " (current stage)" : ""}</title>
      </circle>
      <text x="${x}" y="${y + 5}" text-anchor="middle" font-size="12" font-family="IBM Plex Sans, sans-serif" fill="${numColor}" font-weight="700">${i + 1}</text>
      <text x="${x}" y="${labelY}" text-anchor="middle" font-size="13" font-family="IBM Plex Sans, sans-serif" fill="${labelColor}" font-weight="${labelWeight}">${escapeHtml(stage.label)}</text>
      ${dateLine}
    </g>`;
  }

  const openTag = `<svg class="policy-cycle-svg" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Legislative stage progress">`;
  return openTag + defs + arrows + nodes + "</svg>";
}

async function loadArchive() {
  const monthsEl = document.getElementById("archive-months");

  if (archiveData) {
    renderArchive();
    return;
  }

  try {
    const res = await fetch("archive.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    archiveData = await res.json();
    renderArchive();
  } catch (err) {
    monthsEl.innerHTML = '<p class="error">Couldn\'t load the archive yet — check back once a few weekly digests have run.</p>';
    console.error(err);
  }
}

function renderArchive() {
  const monthsEl = document.getElementById("archive-months");
  renderTopicInfo();

  if (!archiveData || !archiveData.months || archiveData.months.length === 0) {
    monthsEl.innerHTML = '<p class="empty">No archived entries yet — the archive fills in as weekly digests run.</p>';
    return;
  }

  const filteredMonths = archiveData.months
    .map((month) => ({
      ...month,
      entries: month.entries.filter(
        (e) => (e.field || "green-deal") === "green-deal" && matchesFilters(e)
      ),
    }))
    .filter((month) => month.entries.length > 0);

  if (filteredMonths.length === 0) {
    monthsEl.innerHTML = activeTopic === "all" && activeActor === "all"
      ? '<p class="empty">No archived entries yet — the archive fills in as weekly digests run.</p>'
      : '<p class="empty">No archived entries match that filter yet.</p>';
    return;
  }

  monthsEl.innerHTML = filteredMonths
    .map((month, i) => `
      <details class="archive-month"${i === 0 ? " open" : ""}>
        <summary>${escapeHtml(month.label)} <span class="archive-count">(${month.entries.length})</span></summary>
        <div class="entries">
          ${month.entries.map(renderEntry).join("")}
        </div>
      </details>
    `)
    .join("");
}

function renderEntry(entry) {
  const title = escapeHtml(entry.title || "(no title)");
  const org = escapeHtml(entry.org || "");
  const date = escapeHtml(entry.date || "");
  const link = entry.link || "#";
  const actorLabel = ACTOR_LABELS[entry.actor_type] || "";
  const summary = entry.summary ? `<p class="entry-summary">${escapeHtml(stripHtml(entry.summary)).slice(0, 280)}</p>` : "";
  const tags = (entry.tags || [])
    .map((t) => `<span class="entry-tag">${escapeHtml(TOPIC_LABELS[t] || t)}</span>`)
    .join("");
  const tagsHtml = tags ? `<div class="entry-tags">${tags}</div>` : "";

  return `
    <article class="entry-card">
      <h3><a href="${link}" target="_blank" rel="noopener">${title}</a></h3>
      <div class="entry-meta">${org}${actorLabel ? ` · ${escapeHtml(actorLabel)}` : ""} — ${date}</div>
      ${summary}
      ${tagsHtml}
    </article>
  `;
}

function stripHtml(str) {
  const tmp = document.createElement("div");
  tmp.innerHTML = str;
  return tmp.textContent || tmp.innerText || "";
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

setupFieldTabs();
setupTopicTabs();
setupActorTabs();
loadDigest();
