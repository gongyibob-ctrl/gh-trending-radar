const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

async function load() {
  const r = await fetch('data.json', { cache: 'no-cache' });
  if (!r.ok) throw new Error('data.json missing');
  return r.json();
}

function fmtInt(n) {
  if (n == null) return '·';
  return n.toLocaleString();
}

function sourceLabel(s) {
  return ({ github_trending: 'github', hn: 'hn', product_hunt: 'ph' })[s] || s;
}

function metricLabel(it) {
  if (it.source === 'github_trending') return { label: 'stars', value: it.stars };
  if (it.source === 'hn') return { label: 'points', value: it.hnPoints };
  return { label: 'item', value: null };
}

function ageDays(iso) {
  if (!iso) return null;
  const d = (Date.now() - new Date(iso).getTime()) / 86400000;
  return Math.floor(d);
}

function applyFilters(items, f) {
  return items.filter((it) => {
    if (f.source && it.source !== f.source) return false;
    if (f.bucket && it.bucket !== f.bucket) return false;
    if (f.audience && it.audience !== f.audience) return false;
    if (f.q) {
      const q = f.q.toLowerCase();
      const blob = [it.title, it.description, (it.tags || []).join(' '), (it.topics || []).join(' '), it.rationale].join(' ').toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  });
}

function sortItems(items, key) {
  const copy = items.slice();
  copy.sort((a, b) => {
    if (key === 'stars') return (b.stars || 0) - (a.stars || 0);
    if (key === 'seen') return new Date(b.firstSeenAt) - new Date(a.firstSeenAt);
    return (b.stars7dDelta || 0) - (a.stars7dDelta || 0);
  });
  return copy;
}

function renderSummary(data) {
  const sum = $('#summary');
  const t = data.totals;
  const parts = [
    `<span class="pill"><b>${t.items}</b> items</span>`,
    ...Object.entries(t.bySource).map(([k, v]) => `<span class="pill">${sourceLabel(k)}: <b>${v}</b></span>`),
    `<span class="pill">audience · ` + Object.entries(t.byAudience).map(([k, v]) => `${k}:<b>${v}</b>`).join(' ') + `</span>`,
  ];
  sum.innerHTML = parts.join('');
}

function renderGrid(items) {
  const grid = $('#grid');
  if (!items.length) { grid.innerHTML = '<div class="muted">no matches</div>'; return; }
  grid.innerHTML = items.map((it) => {
    const m = metricLabel(it);
    const age = ageDays(it.createdAt);
    const tags = (it.tags || []).map((t) => `<span class="tag">${t}</span>`).join('');
    const audClass = `audience-${it.audience}`;
    const stats = [];
    if (m.value != null) stats.push(`<span class="stat">${m.label}: <b>${fmtInt(m.value)}</b></span>`);
    if (it.stars7dDelta != null) stats.push(`<span class="stat">Δ7d: <b>+${fmtInt(it.stars7dDelta)}</b></span>`);
    if (age != null) stats.push(`<span class="stat">age: <b>${age}d</b></span>`);
    if (it.language) stats.push(`<span class="stat">${it.language}</span>`);
    return `
      <article class="card">
        <div class="row">
          <span class="badge bucket">${it.bucket}</span>
          <span class="badge ${audClass}">${it.audience}</span>
          <span class="muted">${sourceLabel(it.source)}</span>
        </div>
        <div class="title"><a href="${it.url}" target="_blank" rel="noopener">${it.title}</a></div>
        ${it.description ? `<div class="desc">${escapeHtml(it.description)}</div>` : ''}
        ${it.rationale ? `<div class="rationale">${escapeHtml(it.rationale)}</div>` : ''}
        <div class="stats">${stats.join('')}</div>
        ${tags ? `<div class="tags">${tags}</div>` : ''}
      </article>`;
  }).join('');
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function populateBuckets(buckets) {
  const sel = $('#f-bucket');
  sel.innerHTML = '<option value="">all</option>' + buckets.map((b) => `<option value="${b}">${b}</option>`).join('');
}

async function main() {
  try {
    const data = await load();
    $('#meta').textContent = `generated ${new Date(data.generatedAt).toLocaleString()} · ${data.items.length} items`;
    const buckets = Object.keys(data.totals.byBucket).sort();
    populateBuckets(buckets);
    renderSummary(data);

    const re = () => {
      const f = { source: $('#f-source').value, bucket: $('#f-bucket').value, audience: $('#f-audience').value, q: $('#f-q').value.trim() };
      const sorted = sortItems(applyFilters(data.items, f), $('#f-sort').value);
      renderGrid(sorted);
    };
    ['#f-source', '#f-bucket', '#f-audience', '#f-sort'].forEach((s) => $(s).addEventListener('change', re));
    $('#f-q').addEventListener('input', re);
    re();
  } catch (e) {
    $('#grid').innerHTML = `<div class="muted">error loading data.json: ${e.message}</div>`;
  }
}

main();
