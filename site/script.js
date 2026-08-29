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
  political: "Political",
  lobby: "Lobby / NGO",
};

// One-line explainer + link to the original legal text for each law, shown
// as an info card whenever that topic filter is active. Keep ids in sync
// with TOPIC_LABELS / LEGISLATION_TAGS.
const TOPIC_INFO = {
  ets1: {
    instrument: "Directive 2003/87/EC",
    description:
      "Establishes the EU Emissions Trading System (EU ETS), the cap-and-trade scheme covering power generation, industry and intra-EU aviation, under which a shrinking cap on allowances is auctioned or freely allocated and traded.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32003L0087",
  },
  ets2: {
    instrument: "Directive (EU) 2023/959",
    description:
      "Revises the main EU ETS and, within the same amending act, creates a new separate emissions trading system (\"ETS2\") covering fuel combustion in buildings, road transport and additional small-industry sectors, with trading due to start in 2027.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023L0959",
  },
  cbam: {
    instrument: "Regulation (EU) 2023/956",
    description:
      "Requires importers of carbon-intensive goods (cement, iron and steel, aluminium, fertilisers, hydrogen, electricity) to purchase certificates reflecting embedded carbon emissions, priced in line with the EU ETS, to prevent carbon leakage as free ETS allowances are phased out.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R0956",
  },
  red3: {
    instrument: "Directive (EU) 2023/2413",
    description:
      "The third revision of the EU's renewable energy framework, raising the binding EU-wide renewables target to at least 42.5% of final energy consumption by 2030, with sub-targets for industry, transport, heating/cooling and renewable hydrogen.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023L2413",
  },
  csddd: {
    instrument: "Directive (EU) 2024/1760",
    description:
      "Requires large EU and non-EU companies above set turnover/headcount thresholds to identify, prevent and mitigate adverse human rights and environmental impacts in their operations and value chains, and to adopt a 1.5°C-aligned climate transition plan.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024L1760",
  },
  crma: {
    instrument: "Regulation (EU) 2024/1252",
    description:
      "Sets EU-wide capacity benchmarks for domestic extraction, processing and recycling of critical raw materials, streamlines permitting for \"strategic projects,\" and requires supply-risk monitoring and diversification.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1252",
  },
  nzia: {
    instrument: "Regulation (EU) 2024/1735",
    description:
      "Aims to scale up EU manufacturing capacity for net-zero technologies (solar, wind, batteries, heat pumps, electrolysers, CCS) to meet at least 40% of EU deployment needs by 2030, via faster permitting, procurement criteria and a CO2 storage injection-capacity target.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1735",
  },
  csrd: {
    instrument: "Directive (EU) 2022/2464",
    description:
      "Expands and standardises mandatory sustainability reporting for large EU companies and listed SMEs, requiring double-materiality disclosures under the European Sustainability Reporting Standards, digitally tagged and subject to third-party assurance.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022L2464",
  },
  taxonomy: {
    instrument: "Regulation (EU) 2020/852",
    description:
      "Creates a common EU classification defining which economic activities qualify as \"environmentally sustainable\" against six environmental objectives, via technical screening criteria set out in delegated acts.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32020R0852",
  },
  sfdr: {
    instrument: "Regulation (EU) 2019/2088",
    description:
      "Imposes harmonised disclosure obligations on asset managers, insurers and financial advisers on how they integrate sustainability risks into investment decisions, and introduces the Article 6/8/9 fund classification used across EU sustainable finance.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32019R2088",
  },
  eudr: {
    instrument: "Regulation (EU) 2023/1115",
    description:
      "Bans placing on the EU market (or exporting from it) cattle, cocoa, coffee, palm oil, rubber, soy, wood and derived products unless they are deforestation-free, legally produced, and covered by a due-diligence statement with geolocation traceability.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R1115",
  },
  "nature-restoration": {
    instrument: "Regulation (EU) 2024/1991",
    description:
      "Sets the EU's first binding, continent-wide targets to restore degraded ecosystems, covering at least 20% of EU land and sea areas by 2030 and all ecosystems in need of restoration by 2050, via national restoration plans.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1991",
  },
  lulucf: {
    instrument: "Regulation (EU) 2018/841 (as amended by (EU) 2023/839)",
    description:
      "Requires Member States to account for and offset greenhouse gas emissions and removals from land use, land-use change and forestry, and sets a binding EU-wide net removals target of 310 Mt CO2eq by 2030.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32018R0841",
  },
  ccus: {
    instrument: "Directive 2009/31/EC",
    description:
      "The EU's dedicated legal framework for carbon capture and storage: permitting, site selection, monitoring, leakage liability and closure of geological CO2 storage sites. Current deployment is additionally driven by the Net-Zero Industry Act's CO2 storage-capacity target.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009L0031",
  },
  eed: {
    instrument: "Directive (EU) 2023/1791",
    description:
      "Recast of the Energy Efficiency Directive, setting a binding EU target to cut final energy consumption by 11.7% by 2030 (vs. a 2020 baseline), enshrining \"energy efficiency first,\" and imposing annual public-sector renovation obligations.",
    eurlexUrl: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023L1791",
  },
};

let digestData = null;
let archiveData = null;
let activeField = "green-deal";
let activeTopic = "all";
let activeActor = "all";

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
    <h3>${label} <span class="topic-info-instrument">— ${escapeHtml(info.instrument)}</span></h3>
    <p>${escapeHtml(info.description)}</p>
    <a href="${info.eurlexUrl}" target="_blank" rel="noopener">Read the full text on EUR-Lex →</a>
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
  const archiveVisible = !document.getElementById("archive-section").hidden;
  if (archiveVisible) {
    renderArchive();
  } else {
    renderActiveField();
  }
}

function showDigestView() {
  document.getElementById("digest-section").hidden = false;
  document.getElementById("archive-section").hidden = true;
}

function showArchiveView() {
  document.getElementById("digest-section").hidden = true;
  document.getElementById("archive-section").hidden = false;
  loadArchive();
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
