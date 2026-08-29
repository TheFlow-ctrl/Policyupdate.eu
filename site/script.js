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

function renderActiveField() {
  const entriesEl = document.getElementById("entries");
  const labelEl = document.getElementById("active-field-label");
  labelEl.textContent = `— ${FIELD_LABELS[activeField] || activeField}`;

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
