/* ==========================================================================
   SIGNAL DESK — frontend
   No build step, no framework: plain fetch() against the JSON files that
   build_data.py writes to /docs/data/. If those files aren't reachable
   (e.g. you're previewing this file on its own, not via the deployed
   site), it falls back to small embedded sample data so the layout is
   still visible.
   ========================================================================== */

const STACK_ORDER = [
  "Singapore", "United States", "Southeast Asia (SEA)", "World Affairs",
  "Geopolitics", "Healthcare & Biotech", "Technology & AI", "Business & Finance",
];

const VIEW_COPY = {
  weekly: {
    title: "This week's signal",
    subtitle: (data) => `Covers the last 7 days · refreshed every Tuesday 9am Singapore time · generated ${formatGeneratedAt(data.generated_at)}`,
  },
  daily: {
    title: "Today's signal",
    subtitle: (data) => `Covers the last 24 hours · refreshed daily · generated ${formatGeneratedAt(data.generated_at)}. Quiet sections mean nothing cleared the noteworthiness bar today — that's expected, not a bug.`,
  },
};

// --- Fallback sample data, used only if data/*.json can't be fetched -------
const FALLBACK_DAILY = {
  generated_at: new Date().toISOString(),
  mode: "daily",
  stacks: {
    "Singapore": [
      { title: "MAS holds monetary policy steady as inflation eases", link: "#", snippet: "The central bank kept its policy band unchanged, citing moderating price pressures.", source_domain: "channelnewsasia.com", outlet_name: "CNA", published_utc: new Date().toISOString(), stack_tag: "SG", score: 51.2, corroboration_count: 3, corroborating_outlets: ["CNA", "Straits Times", "Business Times"] },
    ],
    "United States": [
      { title: "Fed signals openness to a September rate cut", link: "#", snippet: "Markets rallied after minutes showed growing consensus among policymakers.", source_domain: "cnbc.com", outlet_name: "CNBC", published_utc: new Date().toISOString(), stack_tag: "US", score: 44.0, corroboration_count: 2, corroborating_outlets: ["CNBC", "NPR"] },
    ],
    "Southeast Asia (SEA)": [],
    "World Affairs": [],
    "Geopolitics": [],
    "Healthcare & Biotech": [],
    "Technology & AI": [
      { title: "New inference chip claims record throughput per watt", link: "#", snippet: "The startup says early benchmarks show a meaningful efficiency jump over incumbents.", source_domain: "techcrunch.com", outlet_name: "TechCrunch", published_utc: new Date().toISOString(), stack_tag: "TECH", score: 38.5, corroboration_count: 1, corroborating_outlets: ["TechCrunch"] },
    ],
    "Business & Finance": [],
  },
};

const FALLBACK_WEEKLY = FALLBACK_DAILY;

const FALLBACK_SOURCES = {
  generated_at: new Date().toISOString(),
  stacks: {
    "Singapore": [
      { outlet_name: "CNA — Singapore", feed_url: "https://www.channelnewsasia.com/rssfeeds/8395986", stack_tag: "SG" },
      { outlet_name: "The Straits Times — Singapore", feed_url: "https://www.straitstimes.com/news/singapore/rss.xml", stack_tag: "SG" },
    ],
  },
};

// --- State ------------------------------------------------------------------

const cache = {};
let activeTab = "weekly";

// --- Helpers ------------------------------------------------------------------

function formatGeneratedAt(iso) {
  if (!iso) return "just now";
  const date = new Date(iso);
  return date.toLocaleString("en-SG", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZoneName: "short",
  });
}

function relativeTime(iso) {
  if (!iso) return "time unknown";
  const then = new Date(iso).getTime();
  const diffMinutes = Math.round((Date.now() - then) / 60000);
  if (diffMinutes < 60) return `${Math.max(diffMinutes, 0)}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 48) return `${diffHours}h ago`;
  return `${Math.round(diffHours / 24)}d ago`;
}

async function fetchJson(path, fallback) {
  try {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } catch (err) {
    console.warn(`[signal-desk] Falling back to sample data for ${path}:`, err.message);
    return fallback;
  }
}

function signalMeterHtml(corroborationCount, outlets) {
  const capped = Math.min(corroborationCount, 5);
  const ticks = Array.from({ length: 5 }, (_, i) =>
    `<span class="signal-tick${i < capped ? " filled" : ""}"></span>`
  ).join("");
  const label = corroborationCount <= 1
    ? "single source"
    : `reported by ${corroborationCount} outlets`;
  const title = outlets && outlets.length ? outlets.join(", ") : "";
  return `
    <span class="signal-meter" title="${escapeHtml(title)}">
      <span class="signal-ticks">${ticks}</span>
      <span class="signal-label">${label}</span>
    </span>
  `;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}

// --- Rendering: story board --------------------------------------------------

function renderStory(story) {
  return `
    <article class="story">
      <div class="story-meta">
        <span class="tag-pill">${escapeHtml(story.stack_tag)}</span>
        <span>${escapeHtml(story.outlet_name)}</span>
        <span>&bull;</span>
        <span>${relativeTime(story.published_utc)}</span>
      </div>
      <a class="story-title" href="${escapeHtml(story.link)}" target="_blank" rel="noopener">
        ${escapeHtml(story.title)}
      </a>
      <p class="story-snippet">${escapeHtml(story.snippet)}</p>
      ${signalMeterHtml(story.corroboration_count, story.corroborating_outlets)}
    </article>
  `;
}

function renderStackColumn(stackName, stories) {
  const body = stories.length
    ? stories.map(renderStory).join("")
    : `<p class="empty-note">No stories cleared the noteworthiness bar in this window.</p>`;
  return `
    <section class="stack-column">
      <div class="stack-header">
        <h2>${escapeHtml(stackName)}</h2>
        <span class="stack-count">${stories.length} ${stories.length === 1 ? "story" : "stories"}</span>
      </div>
      ${body}
    </section>
  `;
}

function renderBoard(data) {
  const board = document.getElementById("board");
  board.innerHTML = STACK_ORDER
    .map((stack) => renderStackColumn(stack, data.stacks[stack] || []))
    .join("");
}

// --- Rendering: sources directory --------------------------------------------

function renderSources(data) {
  const view = document.getElementById("sources-view");
  view.innerHTML = STACK_ORDER
    .filter((stack) => data.stacks[stack])
    .map((stack) => `
      <section class="sources-stack">
        <h2>${escapeHtml(stack)}</h2>
        ${data.stacks[stack].map((s) => `
          <div class="source-row">
            <span class="source-name">${escapeHtml(s.outlet_name)}</span>
            <span class="source-domain">${escapeHtml(new URL(s.feed_url, location.href).hostname)}</span>
          </div>
        `).join("")}
        <span class="free-badge">FREE &middot; PUBLIC RSS</span>
      </section>
    `).join("");
}

// --- Tab switching -------------------------------------------------------------

async function showTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.setAttribute("aria-selected", String(btn.dataset.tab === tab));
  });

  const board = document.getElementById("board");
  const sourcesView = document.getElementById("sources-view");
  const title = document.getElementById("view-title");
  const subtitle = document.getElementById("view-subtitle");

  if (tab === "sources") {
    board.hidden = true;
    sourcesView.hidden = false;
    title.textContent = "Where this comes from";
    subtitle.textContent = "Every outlet below is a free, publicly accessible RSS feed. No paywalled or licensed data is used.";
    if (!cache.sources) cache.sources = await fetchJson("data/sources.json", FALLBACK_SOURCES);
    renderSources(cache.sources);
    return;
  }

  board.hidden = false;
  sourcesView.hidden = true;

  if (!cache[tab]) {
    const fallback = tab === "daily" ? FALLBACK_DAILY : FALLBACK_WEEKLY;
    cache[tab] = await fetchJson(`data/${tab}.json`, fallback);
  }
  const data = cache[tab];
  title.textContent = VIEW_COPY[tab].title;
  subtitle.textContent = VIEW_COPY[tab].subtitle(data);
  renderBoard(data);
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});

showTab(activeTab);
