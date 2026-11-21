/* PR Radar web dashboard. Renders data.json (or data.js) written by `pr-radar export-web`. */
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const pct = (x) => `${Math.round((x || 0) * 100)}%`;
  const pts = (x, digits = 1) => `${x > 0 ? "+" : x < 0 ? "−" : "±"}${Math.abs(x).toFixed(digits)} pts`;
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const regionNames = (() => {
    try { return new Intl.DisplayNames(["en"], { type: "region" }); } catch { return null; }
  })();
  const country = (cc) => {
    if (!cc || cc === "??") return "Unknown";
    try { return (regionNames && regionNames.of(cc)) || cc; } catch { return cc; }
  };
  const fmtDate = (iso, opts = { day: "numeric", month: "short" }) => {
    const d = new Date(`${String(iso).slice(0, 10)}T00:00:00Z`);
    return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleDateString("en-GB", { ...opts, timeZone: "UTC" });
  };
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  let DATA = null;
  let current = null;
  const name = (id) => (DATA.brands && DATA.brands[id]) || id || "?";
  const isUs = (id) => id === DATA.primary;

  function bind(key, text) { $$(`[data-bind="${key}"]`).forEach((el) => { el.textContent = text; }); }
  function list(key, html) { const el = $(`[data-list="${key}"]`); if (el) el.innerHTML = html; }
  function chart(key, html) { const el = $(`[data-chart="${key}"]`); if (el) el.innerHTML = html; }
  const li = (html) => `<li>${html}</li>`;
  const chips = (brands) =>
    (brands || []).map((b) => `<span class="chip${isUs(b) ? " us" : ""}">${esc(name(b))}</span>`).join("");

  /* ---------- Sections ---------- */

  function renderHero(w) {
    const k = w.kpis;
    const brand = name(DATA.primary);
    bind("brand", brand);
    bind("period", `${fmtDate(w.start)} – ${fmtDate(w.end, { day: "numeric", month: "short", year: "numeric" })} · last ${w.days} days`);
    bind("lede", `${k.total_mentions} brand mentions across ${Object.keys(DATA.brands).length} tracked brands. Share of voice, market gaps, pitch targets and narrative gaps from public news headlines.`);
    document.title = `PR Radar · ${brand} · ${fmtDate(w.start)}–${fmtDate(w.end)}`;

    $('[data-kpi="mentions"]').textContent = k.mentions;
    $('[data-kpi="share"]').textContent = pct(k.share);
    $('[data-kpi="outlets"]').textContent = k.outlets;
    const change = $('[data-kpi="change"]');
    change.className = "";
    if (k.share_change_pts === null || k.share_change_pts === undefined) {
      change.textContent = "first period";
      change.title = "No comparison until the previous window has been collected";
    } else {
      change.textContent = pts(k.share_change_pts);
      change.className = k.share_change_pts > 0 ? "up" : k.share_change_pts < 0 ? "down" : "";
      change.title = "Change vs the previous period";
    }

    bind("volume-sub", `Articles naming ${brand} in the last ${w.days} days.`);
    bind("share-sub", k.share_change_pts === null || k.share_change_pts === undefined
      ? "First tracked period: no comparison yet."
      : `Change vs the previous ${w.days} days.`);
    bind("reach-sub", `Distinct outlets, across ${k.markets} market${k.markets === 1 ? "" : "s"}.`);

    const leader = w.comparison[0];
    const prevMentions = (w.comparison.find((r) => isUs(r.brand)) || {}).mentions_prev;
    list("volume", [
      li(`<strong>${k.stories}</strong> distinct stories`),
      li(`<strong>${k.total_mentions}</strong> mentions tracked across all brands`),
      li(w.baseline && prevMentions !== undefined ? `<strong>${prevMentions}</strong> mentions in the previous period` : "Baseline builds up from the next run"),
    ].join(""));
    list("share", [
      li(k.rank ? `Ranked <strong>#${k.rank}</strong> of ${k.brands} brands` : `No coverage for ${esc(brand)} yet`),
      leader && !isUs(leader.brand)
        ? li(`${esc(name(leader.brand))} leads with <strong>${pct(leader.share)}</strong>`)
        : li(`<strong>${esc(brand)}</strong> leads the conversation`),
      li(`${w.market_gaps.length} market${w.market_gaps.length === 1 ? "" : "s"} where a competitor leads`),
      li(`${w.topic_gaps.filter((t) => t.gap_pts >= 5).length} narrative gaps of 5+ pts`),
    ].join(""));
    const ourMarkets = [...new Set(w.market_share.filter((r) => isUs(r.brand)).map((r) => r.country))];
    const warm = w.outlet_gaps.filter((o) => o.primary_all_time > 0).length;
    list("reach", [
      li(`<strong>${k.markets}</strong> markets${ourMarkets.length ? `: ${esc(ourMarkets.join(", "))}` : ""}`),
      li(`<strong>${w.outlet_gaps.length}</strong> outlets covered competitors only`),
      li(warm ? `<strong>${warm}</strong> warm contacts to re-pitch` : "No warm contacts in this period's gaps"),
    ].join(""));
  }

  function renderInsights(w) {
    list("insights", (w.insights || []).map((t) => li(esc(t).replace(/(\d+(?:\.\d+)?%|[+-]\d+(?:\.\d+)? pts|(?<![&\w])#\d+)/g, "<strong>$1</strong>"))).join(""));
  }

  /* LLM brief: the newest one that fits this window and passed the checks. */
  function renderBrief(w) {
    const box = $("#brief");
    const b = w.brief;
    if (!b || !b.summary) { box.hidden = true; return; }
    box.hidden = false;
    const strong = (t) => esc(t).replace(/(\d+(?:\.\d+)?%|(?<![&\w])#\d+)/g, "<strong>$1</strong>");
    $('[data-bind="brief-summary"]').innerHTML = strong(b.summary);
    list("brief-actions", (b.actions || []).map((a) => li(`<span>${strong(a)}</span>`)).join(""));
    const span = b.start && b.end ? `${fmtDate(b.start, { day: "numeric", month: "short" })} – ${fmtDate(b.end, { day: "numeric", month: "short" })}` : `the last ${w.days} days`;
    bind("brief-note", `What ${name(DATA.primary)}'s PR team could do next, written from the coverage of ${span}.`);
    const when = b.created_at ? ` on ${fmtDate(b.created_at, { day: "numeric", month: "short", year: "numeric" })}` : "";
    bind("brief-meta", `Written by ${b.model || "a local LLM"} running locally${when}, from that period's numbers only, and checked automatically against the data before publishing.`);
  }

  function renderSov(w) {
    const rows = w.share_of_voice;
    const peak = Math.max(...rows.map((r) => r.share), 0.0001);
    chart("sov", rows.length ? rows.map((r) => `
      <div class="bar-row${isUs(r.brand) ? " us" : ""}" role="listitem"
           data-tip="${esc(`<b>${esc(name(r.brand))}</b><br>${pct(r.share)} share · ${r.mentions} mentions<br>${r.stories} stories · ${r.outlets} outlets · ${r.markets} markets`)}">
        <span class="name">${esc(name(r.brand))}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${(r.share / peak) * 100}%"></span></span>
        <span class="val">${pct(r.share)}</span>
      </div>`).join("") : `<p class="empty">No coverage in this period.</p>`);

    const head = `<thead><tr><th>Brand</th><th class="n">Mentions</th><th class="n prev">Prev.</th><th class="n">Share</th><th class="n">Δ</th></tr></thead>`;
    const body = w.comparison.map((r) => {
      const d = r.share_change_pts;
      return `<tr class="${isUs(r.brand) ? "us" : ""}"><td>${esc(name(r.brand))}</td><td class="n">${r.mentions}</td>
        <td class="n prev">${w.baseline ? r.mentions_prev : "–"}</td><td class="n">${pct(r.share)}</td>
        <td class="n ${w.baseline ? (d > 0 ? "up" : d < 0 ? "down" : "") : "muted"}">${w.baseline ? pts(d) : "–"}</td></tr>`;
    }).join("");
    $('[data-table="sov"]').innerHTML = head + `<tbody>${body}</tbody>`;
    $('[data-table="sov"]').setAttribute("aria-label", "Share of voice by brand");

    // Weekly split: brand vs all competitors (two series, validated pair).
    const weeks = {};
    w.weekly_trend.forEach((r) => {
      const wk = (weeks[r.week] = weeks[r.week] || { us: 0, all: 0 });
      wk.all += r.mentions;
      if (isUs(r.brand)) wk.us += r.mentions;
    });
    const keys = Object.keys(weeks).sort();
    chart("trend", keys.length > 1 ? `
      <h3>Weekly share of voice</h3>
      <div class="legend"><span><i class="k-us"></i>${esc(name(DATA.primary))}</span><span><i class="k-them"></i>All competitors</span></div>
      ${keys.map((k) => {
        const { us, all } = weeks[k];
        const s = all ? us / all : 0;
        return `<div class="trend-row" data-tip="${esc(`<b>Week of ${esc(fmtDate(k))}</b><br>${esc(name(DATA.primary))}: ${us} of ${all} mentions (${pct(s)})`)}">
          <span class="wk">Wk of ${esc(fmtDate(k))}</span>
          <span class="stack"><span class="s-us" style="flex:${us}"></span><span class="s-them" style="flex:${all - us}"></span></span>
          <span class="val">${pct(s)}</span></div>`;
      }).join("")}` : "");
  }

  function renderMarkets(w) {
    const brand = name(DATA.primary);
    bind("markets-note", `Markets where a competitor out-shouts ${brand} (min. 5 mentions).`);
    chart("markets", w.market_gaps.length ? w.market_gaps.map((g) => `
      <div class="market">
        <div class="market-top"><span class="cc">${esc(g.country)}</span><span class="gap">${Math.round(g.gap_pts)} pts behind</span></div>
        <p class="meta">${esc(country(g.country))} · ${g.total} mentions</p>
        <div class="duel">
          <div class="duel-row them" data-tip="${esc(`<b>${esc(name(g.leader))}</b> holds ${pct(g.leader_share)} of ${esc(g.country)} coverage`)}">
            <span class="name">${esc(name(g.leader))}</span><span class="t"><span class="f" style="width:${g.leader_share * 100}%;display:block"></span></span><span class="v">${pct(g.leader_share)}</span></div>
          <div class="duel-row us" data-tip="${esc(`<b>${esc(brand)}</b> holds ${pct(g.primary_share)} of ${esc(g.country)} coverage`)}">
            <span class="name">${esc(brand)}</span><span class="t"><span class="f" style="width:${g.primary_share * 100}%;display:block"></span></span><span class="v">${pct(g.primary_share)}</span></div>
        </div>
      </div>`).join("") : `<p class="empty">No market where a competitor leads ${esc(brand)}.</p>`);
  }

  function renderOutlets(w) {
    const brand = name(DATA.primary);
    bind("outlets-note", `Outlets that covered competitors this period but not ${brand}. Gold = covered ${brand} before (warm contact).`);
    const el = $('[data-list="outlets"]');
    const items = [...w.outlet_gaps].sort((a, b) => (b.primary_all_time > 0) - (a.primary_all_time > 0) || b.competitor_articles - a.competitor_articles);
    const row = (o) => `
      <li class="outlet${o.primary_all_time > 0 ? " warm" : ""}">
        <div><div class="dom">${esc(o.outlet)}${o.primary_all_time > 0 ? `<span class="warm-badge" title="${esc(brand)} articles from this outlet, all time">★ ${o.primary_all_time} before</span>` : ""}</div>
          <div class="chips">${chips(o.competitors)}</div></div>
        <div class="count">${o.competitor_articles}<small>articles</small></div>
      </li>`;
    if (!items.length) { el.innerHTML = `<li class="empty">No outlet gaps this period.</li>`; return; }
    const LIMIT = 10;
    el.innerHTML = items.slice(0, LIMIT).map(row).join("");
    const old = el.parentElement.querySelector(".more");
    if (old) old.remove();
    if (items.length > LIMIT) {
      const wrap = document.createElement("div");
      wrap.className = "more";
      wrap.innerHTML = `<button class="ghost" type="button">Show all ${items.length}</button>`;
      wrap.querySelector("button").addEventListener("click", () => { el.innerHTML = items.map(row).join(""); wrap.remove(); });
      el.after(wrap);
    }
  }

  function renderTopics(w) {
    const brand = name(DATA.primary);
    const rows = w.topic_gaps;
    $('[data-legend="topics"]').innerHTML =
      `<span><i class="k-them"></i>Competitors own the narrative</span><span><i class="k-us"></i>${esc(brand)} leads</span>`;
    if (!rows.length) { chart("topics", `<p class="empty">No topic-tagged coverage this period.</p>`); return; }
    const peak = Math.max(...rows.map((r) => Math.abs(r.gap_pts)), 1);
    chart("topics", rows.map((t) => {
      const width = (Math.abs(t.gap_pts) / peak) * 50;
      const cls = t.gap_pts >= 0 ? "pos" : "neg";
      const topic = String(t.topic).replace(/_/g, " ");
      const tip = `<b>${esc(topic)}</b><br>Competitors: ${pct(t.competitor_share)} of coverage (${t.competitor_articles})<br>${esc(brand)}: ${pct(t.primary_share)} (${t.primary_articles})${t.top_competitor ? `<br>Led by ${esc(name(t.top_competitor))}` : ""}`;
      return `<div class="div-row" role="listitem" data-tip="${esc(tip)}">
        <span class="name">${esc(topic)}</span>
        <span class="div-axis"><span class="f ${cls}" style="width:${width}%"></span></span>
        <span class="v ${t.gap_pts > 0 ? "down" : "up"}">${pts(t.gap_pts, 0)}</span></div>`;
    }).join("") + `<div class="div-scale"><span></span><span class="ends"><span>← ${esc(brand)} leads</span><span>competitors own →</span></span><span></span></div>`);
  }

  function renderStories(w) {
    list("stories", w.top_stories.length ? w.top_stories.map((s) => `
      <li class="story">
        <div><a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>
          <div class="meta">${chips(s.brands)} ${s.markets && s.markets.length ? `· ${esc(s.markets.join(", "))}` : ""} · first seen ${esc(fmtDate(s.first_seen))}</div></div>
        <div class="outl">${s.outlets}<small>outlet${s.outlets === 1 ? "" : "s"}</small></div>
      </li>`).join("") : `<li class="empty">No stories in this period.</li>`);
  }

  /* Aspect sentiment (DimABSA). Accepts a list of
     {brand, aspect, valence, arousal, mentions?} on the 1-9 scale, or {items: [...]}. */
  function renderSentiment() {
    const raw = DATA.aspect_sentiment;
    const items = (Array.isArray(raw) ? raw : (raw && raw.items) || [])
      .filter((r) => r && Number.isFinite(+r.valence) && Number.isFinite(+r.arousal));
    if (!items.length) return;
    const S = 300, P = 34, lo = 1, hi = 9;
    const x = (v) => P + ((v - lo) / (hi - lo)) * (S - 2 * P);
    const y = (a) => S - P - ((a - lo) / (hi - lo)) * (S - 2 * P);
    const grid = [1, 3, 5, 7, 9].map((t) =>
      `<line x1="${x(t)}" y1="${P}" x2="${x(t)}" y2="${S - P}"/><line x1="${P}" y1="${y(t)}" x2="${S - P}" y2="${y(t)}"/>`).join("");
    const pts = items.map((r) => {
      const n = +r.mentions || +r.n || 1;
      const rad = Math.min(4 + Math.sqrt(n) * 2, 14);
      const tip = `<b>${esc(name(r.brand))} · ${esc(r.aspect)}</b><br>valence ${(+r.valence).toFixed(2)} · arousal ${(+r.arousal).toFixed(2)}${r.mentions || r.n ? `<br>${n} mentions` : ""}`;
      return `<circle class="pt ${isUs(r.brand) ? "us" : "them"}" cx="${x(+r.valence).toFixed(1)}" cy="${y(+r.arousal).toFixed(1)}" r="${rad.toFixed(1)}" data-tip="${esc(tip)}"/>` +
        (isUs(r.brand) ? `<text class="lbl" x="${(x(+r.valence) + rad + 3).toFixed(1)}" y="${(y(+r.arousal) + 4).toFixed(1)}">${esc(r.aspect)}</text>` : "");
    }).join("");
    const svg = `<svg viewBox="0 0 ${S} ${S}" role="img" aria-label="Valence and arousal by aspect">
      <g class="grid">${grid}</g>
      <g class="axis"><text x="${S / 2}" y="${S - 8}" text-anchor="middle">valence →</text>
      <text x="12" y="${S / 2}" text-anchor="middle" transform="rotate(-90 12 ${S / 2})">arousal →</text></g>${pts}</svg>`;
    const rows = [...items].sort((a, b) => isUs(b.brand) - isUs(a.brand) || String(a.aspect).localeCompare(b.aspect));
    chart("sentiment", `<div class="legend"><span><i class="k-us"></i>${esc(name(DATA.primary))}</span><span><i class="k-them"></i>Competitors</span></div>
      <div class="va-grid"><div class="va-plot">${svg}</div>
      <div class="table-wrap"><table class="data"><thead><tr><th>Brand</th><th>Aspect</th><th class="n">Valence</th><th class="n">Arousal</th><th class="n">n</th></tr></thead><tbody>
      ${rows.map((r) => `<tr class="${isUs(r.brand) ? "us" : ""}"><td>${esc(name(r.brand))}</td><td>${esc(r.aspect)}</td><td class="n">${(+r.valence).toFixed(2)}</td><td class="n">${(+r.arousal).toFixed(2)}</td><td class="n">${esc(r.mentions ?? r.n ?? "–")}</td></tr>`).join("")}
      </tbody></table></div></div>`);
  }

  function render(key) {
    current = key;
    const w = DATA.windows[key];
    renderHero(w);
    renderInsights(w);
    renderBrief(w);
    renderSov(w);
    renderMarkets(w);
    renderOutlets(w);
    renderTopics(w);
    renderStories(w);
  }

  /* ---------- Interaction ---------- */

  function setupToggle() {
    const keys = Object.keys(DATA.windows).sort((a, b) => +a - +b);
    const btn = $("#window-toggle");
    if (keys.length < 2) { btn.hidden = true; return; }
    const [a, b] = keys;
    $(".toggle-label .off", btn).textContent = `${a} days`;
    $(".toggle-label .on", btn).textContent = `${b} days`;
    btn.setAttribute("aria-label", `Show the last ${b} days instead of ${a}`);
    const apply = (key) => { btn.setAttribute("aria-checked", String(key === b)); render(key); };
    btn.addEventListener("click", () => {
      const next = current === b ? a : b;
      store.set("pr-radar-window", next);
      apply(next);
    });
    const saved = store.get("pr-radar-window");
    apply(keys.includes(saved) ? saved : String(DATA.default_window || a));
  }

  function setupTooltip() {
    const tip = $(".tooltip");
    let active = null;
    const place = (e) => {
      const pad = 14, r = tip.getBoundingClientRect();
      let left = e.clientX + pad, top = e.clientY + pad;
      if (left + r.width > window.innerWidth - 8) left = e.clientX - r.width - pad;
      if (top + r.height > window.innerHeight - 8) top = e.clientY - r.height - pad;
      tip.style.left = `${Math.max(8, left)}px`;
      tip.style.top = `${Math.max(8, top)}px`;
    };
    document.addEventListener("pointermove", (e) => {
      const el = e.target.closest && e.target.closest("[data-tip]");
      if (!el || e.pointerType === "touch") { if (active) { tip.hidden = true; active = null; } return; }
      if (el !== active) { tip.innerHTML = el.getAttribute("data-tip"); tip.hidden = false; active = el; }
      place(e);
    });
    document.addEventListener("pointerleave", () => { tip.hidden = true; active = null; });
  }

  function setupNav() {
    const links = $$(".pill-nav a[href^='#']");
    const targets = links.map((a) => document.getElementById(a.getAttribute("href").slice(1))).filter(Boolean);
    if (!("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (!en.isIntersecting) return;
        links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === `#${en.target.id}`));
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    targets.forEach((t) => io.observe(t));

    const reveal = new IntersectionObserver((entries) => {
      entries.forEach((en) => { if (en.isIntersecting) { en.target.classList.add("in"); reveal.unobserve(en.target); } });
    }, { rootMargin: "0px 0px -8% 0px" });
    $$(".panel, .section-title").forEach((el) => { el.classList.add("reveal"); reveal.observe(el); });
  }

  function setupScrollState() {
    const onScroll = () => document.body.classList.toggle("scrolled", window.scrollY > 40);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  function probeHero() {
    const img = new Image();
    img.onload = () => document.body.classList.add("has-hero");
    img.src = "assets/hero.webp";
  }

  function showError(msg) {
    const main = $("#main");
    const box = document.createElement("section");
    box.className = "glass panel error";
    box.innerHTML = `<h2>No data yet</h2><p class="muted" style="margin-top:8px">${esc(msg)}</p>`;
    main.prepend(box);
    bind("period", "No data");
  }

  async function load() {
    if (window.PR_RADAR_DATA) return window.PR_RADAR_DATA;
    const res = await fetch("data.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`data.json: HTTP ${res.status}`);
    return res.json();
  }

  async function init() {
    probeHero();
    setupTooltip();
    setupScrollState();
    try {
      DATA = await load();
    } catch (err) {
      showError(`Run "pr-radar export-web" to create web/data.json. (${err.message})`);
      return;
    }
    const gen = `Data generated ${DATA.generated_at.replace("T", " ").replace("Z", " UTC")}.`;
    bind("generated", gen);
    bind("footer-generated", gen);
    renderSentiment();
    setupToggle();
    setupNav();
    // Content renders after load, so re-apply a #section link once it exists.
    const target = location.hash && document.getElementById(location.hash.slice(1));
    if (target) {
      const jump = () => setTimeout(() => target.scrollIntoView({ behavior: "instant", block: "start" }), 0);
      if (document.readyState === "complete") jump(); else window.addEventListener("load", jump, { once: true });
    }
  }

  init();
})();
