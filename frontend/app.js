// ---------- State ----------
const reportsById = new Map();   // memory_id -> report JSON, for export buttons
let activeHistoryId = null;

// ---------- Elements ----------
const queryInput = document.getElementById('queryInput');
const runBtn = document.getElementById('runBtn');
const thread = document.getElementById('thread');
const threadEmpty = document.getElementById('threadEmpty');
const historyList = document.getElementById('historyList');
const cardTemplate = document.getElementById('cardTemplate');

// ---------- Sidebar / history ----------

async function loadHistory() {
  try {
    const res = await fetch('/api/memory/recent?limit=30');
    const records = await res.json();
    renderHistory(records);
  } catch (err) {
    console.error('Failed to load history', err);
  }
}

function renderHistory(records) {
  historyList.innerHTML = '';
  if (!records.length) {
    historyList.innerHTML = '<div class="history-empty">No past research yet — run your first query to see it here.</div>';
    return;
  }
  for (const record of records) {
    const item = document.createElement('div');
    item.className = 'history-item';
    item.dataset.id = record.id;
    const confPct = record.metadata && record.metadata.confidence_score != null
      ? Math.round(record.metadata.confidence_score * 100) + '%'
      : '—';
    const date = new Date(record.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    item.innerHTML = `
      <div class="history-item-query">${escapeHtml(record.query)}</div>
      <div class="history-item-meta"><span>${date}</span><span class="conf">${confPct}</span></div>
    `;
    item.addEventListener('click', () => openFromHistory(record.id));
    historyList.appendChild(item);
  }
}

async function openFromHistory(id) {
  setActiveHistoryItem(id);
  try {
    const res = await fetch(`/api/memory/${id}`);
    if (!res.ok) throw new Error('Report not found');
    const report = await res.json();
    reportsById.set(id, report);

    // If this report's card already exists in the thread, just scroll to it
    const existing = thread.querySelector(`[data-memory-id="${id}"]`);
    if (existing) {
      existing.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }

    const card = createCard();
    card.dataset.memoryId = id;
    card.classList.add('from-history');
    renderReportIntoCard(card, report, id);
    hideEmptyState();
    thread.prepend(card);
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    console.error(err);
  }
}

function setActiveHistoryItem(id) {
  activeHistoryId = id;
  document.querySelectorAll('.history-item').forEach(el => {
    el.classList.toggle('active', Number(el.dataset.id) === Number(id));
  });
}

// ---------- Thread / cards ----------

function hideEmptyState() {
  threadEmpty.style.display = 'none';
}

function createCard() {
  const fragment = cardTemplate.content.cloneNode(true);
  const card = fragment.querySelector('.card');
  thread.prepend(card);
  return card;
}

function renderReportIntoCard(card, r, memoryId) {
  const confPct = Math.round(r.confidence_score * 100);
  card.querySelector('.card-query').textContent = r.query;
  card.querySelector('.card-confidence').textContent = `confidence ${confPct}%`;

  const trace = card.querySelector('.card-trace');
  trace.classList.remove('visible');
  trace.innerHTML = '';

  const body = card.querySelector('.card-body');
  body.innerHTML = `
    <div class="trace-summary" title="This report drew on ${r.references.length} source(s)">
      ${r.references.length} sources · confidence ${confPct}%
    </div>
    <h2>Executive Summary</h2>
    <p>${escapeHtml(r.executive_summary)}</p>

    <h2>Key Findings</h2>
    <ul>${r.key_findings.map(f => `<li>${escapeHtml(f)}</li>`).join('')}</ul>

    ${r.detailed_analysis.map(s => `<h2>${escapeHtml(s.heading)}</h2><p>${escapeHtml(s.content)}</p>`).join('')}

    ${r.comparisons ? `<h2>Comparisons</h2><p>${escapeHtml(r.comparisons)}</p>` : ''}

    ${r.statistics && r.statistics.length ? `<h2>Key Statistics</h2><ul>${r.statistics.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>` : ''}

    ${r.actionable_insights && r.actionable_insights.length ? `<h2>Actionable Insights</h2><ul>${r.actionable_insights.map(i => `<li>${escapeHtml(i)}</li>`).join('')}</ul>` : ''}

    <h2>References</h2>
    <ul class="refs">${r.references.map(ref => `<li>${escapeHtml(ref)}</li>`).join('')}</ul>
  `;

  const actions = card.querySelector('.card-actions');
  actions.innerHTML = '';
  const mdBtn = document.createElement('button');
  mdBtn.textContent = 'Export Markdown';
  mdBtn.addEventListener('click', () => exportReport(memoryId, 'markdown'));
  const pdfBtn = document.createElement('button');
  pdfBtn.textContent = 'Export PDF';
  pdfBtn.addEventListener('click', () => exportReport(memoryId, 'pdf'));
  actions.append(mdBtn, pdfBtn);
}

async function exportReport(memoryId, fmt) {
  const report = reportsById.get(memoryId);
  if (!report) return;
  const res = await fetch(`/api/export/${fmt}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(report)
  });

  // Server sends the real name+timestamp filename via Content-Disposition --
  // read it instead of hardcoding a generic name here, or the timestamp
  // (which is what lets two exports of the same query not collide) is lost.
  const disposition = res.headers.get('content-disposition') || '';
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : `research_report.${fmt === 'markdown' ? 'md' : 'pdf'}`;

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------- Running new research ----------

async function runResearch() {
  const query = queryInput.value.trim();
  if (!query) return;

  runBtn.disabled = true;
  hideEmptyState();

  const card = createCard();
  card.querySelector('.card-query').textContent = query;
  card.querySelector('.card-confidence').textContent = '';

  const trace = card.querySelector('.card-trace');
  trace.classList.add('visible');
  const traceLines = document.createElement('div');
  const progressBar = document.createElement('progress');
  progressBar.max = 100;
  progressBar.value = 0;
  trace.appendChild(traceLines);
  trace.appendChild(progressBar);

  queryInput.value = '';

  try {
    const res = await fetch('/api/research/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query })
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const events = buffer.split('\n\n');
      buffer = events.pop();

      for (const evt of events) {
        const line = evt.replace(/^data:\s*/, '');
        if (!line) continue;
        let payload;
        try { payload = JSON.parse(line); } catch { continue; }
        handleStreamEvent(payload, card, traceLines, progressBar);
      }
    }
  } catch (err) {
    trace.innerHTML = `<div class="card-error">Connection error: ${escapeHtml(String(err))}</div>`;
  }

  runBtn.disabled = false;
}

function handleStreamEvent(payload, card, traceLines, progressBar) {
  if (payload.stage === 'error') {
    const line = document.createElement('div');
    line.className = 'card-error';
    line.textContent = `Error: ${payload.message}`;
    traceLines.appendChild(line);
    return;
  }

  document.querySelectorAll('.trace-line.current').forEach(el => el.classList.remove('current'));
  const line = document.createElement('div');
  line.className = 'trace-line current';
  line.textContent = `${payload.percent}%  ${payload.message}`;
  traceLines.appendChild(line);
  progressBar.value = payload.percent;

  if (payload.stage === 'done' && payload.report) {
    const memoryId = payload.report._memory_id;
    delete payload.report._memory_id;
    reportsById.set(memoryId, payload.report);
    card.dataset.memoryId = memoryId;
    renderReportIntoCard(card, payload.report, memoryId);
    loadHistory();  // refresh sidebar so the new run appears immediately
  }
}

// ---------- Utilities ----------

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ---------- Init ----------

runBtn.addEventListener('click', runResearch);
queryInput.addEventListener('keydown', e => { if (e.key === 'Enter') runResearch(); });
loadHistory();
