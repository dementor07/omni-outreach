/* Audit control-plane client.
 *
 * Layers interactivity ON TOP of the static viewer (index.html) WITHOUT
 * breaking its read-only mode. When the local control server (server.py) is
 * reachable it exposes: a live health panel, per-finding "Run test" buttons
 * with last-run badges, and inline status editing. When the server is absent
 * the page falls back to fetching findings.json directly and hides all controls.
 *
 * index.html defines: DATA, active, render(), renderList(), esc().
 * This file overrides load() and renderList() to add control affordances and
 * defines window.CONTROL = { server, tests }.
 */
window.CONTROL = { server: false, tests: {} };

async function load() {
  // Try the control server first; fall back to the static file.
  try {
    const res = await fetch('/api/state', { cache: 'no-store' });
    if (res.ok) {
      const s = await res.json();
      DATA = { meta: s.meta, findings: s.findings };
      window.CONTROL.server = true;
      window.CONTROL.tests = s.tests || {};
      render();
      pollHealth();
      return;
    }
  } catch (e) { /* server not running — fall through to read-only */ }
  try {
    const res = await fetch('findings.json?t=' + Date.now());
    DATA = await res.json();
    window.CONTROL.server = false;
    render();
  } catch (e) {
    document.getElementById('list').innerHTML =
      '<div class="err">Could not load findings. Serve this folder ' +
      '(<code>python audit/server.py</code> for the control plane, or ' +
      '<code>python -m http.server</code> for read-only).<br><br>' + e + '</div>';
  }
}

/* ── Live health panel ─────────────────────────────────────────────────────── */
async function pollHealth() {
  const el = document.getElementById('healthPanel');
  if (!el) return;
  try {
    const h = await (await fetch('/api/health', { cache: 'no-store' })).json();
    const svcs = (h.compose && h.compose.services) || [];
    const dot = (up) => `<span class="hdot ${up ? 'up' : 'down'}"></span>`;
    el.innerHTML =
      `<div class="hrow"><b>Stack</b> ${h.stack_up
        ? '<span class="up">up</span>' : '<span class="down">down</span>'} ` +
      `<span class="hts">checked ${new Date(h.checked_at).toLocaleTimeString()}</span></div>` +
      (svcs.length
        ? svcs.map(s => `<div class="hrow">${dot(s.up)}${esc(s.name)} <span class="hts">${esc(s.status)}</span></div>`).join('')
        : '<div class="hrow hts">no v2 services running (start the local stack to run stack/e2e tests)</div>');
  } catch (e) {
    el.innerHTML = '<div class="hrow down">health probe failed: ' + esc(String(e)) + '</div>';
  }
}

/* ── Status write-back ─────────────────────────────────────────────────────── */
async function setStatus(fid, status) {
  if (!window.CONTROL.server) return;
  const r = await fetch('/api/finding/' + encodeURIComponent(fid), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, actor: 'operator' }),
  });
  if (r.ok) {
    const { finding } = await r.json();
    const f = DATA.findings.find(x => x.id === fid);
    if (f) { f.status = finding.status; f.history = finding.history; }
    render();
  } else {
    alert('status update failed: ' + r.status);
  }
}

/* ── Run a bound test ──────────────────────────────────────────────────────── */
async function runTest(fid, testName, btn) {
  if (!window.CONTROL.server) return;
  btn.disabled = true; btn.textContent = 'running…';
  try {
    const r = await fetch('/api/run/' + encodeURIComponent(testName), { method: 'POST' });
    const d = await r.json();
    if (!r.ok) { alert('run failed: ' + (d.detail || r.status)); return; }
    // Reload state so last_run badges refresh on every bound finding.
    const s = await (await fetch('/api/state', { cache: 'no-store' })).json();
    DATA = { meta: s.meta, findings: s.findings };
    window.CONTROL.tests = s.tests || {};
    render();
    // auto-open the finding so the result is visible
    const card = document.getElementById('f-' + fid);
    if (card) card.classList.add('open');
  } finally {
    btn.disabled = false; btn.textContent = '▶ run';
  }
}

/* ── List rendering with control affordances (overrides index.html's) ───────── */
function renderList() {
  const fs = DATA.findings.filter(matches)
    .sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity] || a.id.localeCompare(b.id));
  const list = document.getElementById('list');
  if (!fs.length) { list.innerHTML = '<div class="err">No findings match the current filters.</div>'; return; }
  const srv = window.CONTROL.server;
  const STATUSES = ['VERIFIED', 'SUSPECTED', 'FIXED', 'DISMISSED'];

  list.innerHTML = fs.map(f => {
    const tests = (window.CONTROL.tests && window.CONTROL.tests[f.id]) || [];
    const lr = f.last_run;
    const lrBadge = lr
      ? `<span class="pill lr-${lr.result}" title="${esc(lr.test)} @ ${esc(lr.at)}">` +
        `${lr.result === 'PASS' ? '✓' : '✗'} ${lr.result}` +
        (srv ? ` <a class="artifact" href="/api/runs/${esc(lr.run_id)}" target="_blank">log↗</a>` : '') +
        `</span>`
      : (tests.length ? '<span class="pill lr-NONE">untested</span>'
                      : '<span class="pill lr-NONE" title="no test bound to this finding">unproven</span>');

    const runBtns = (srv && tests.length)
      ? tests.map(t => `<button class="runbtn" onclick="runTest('${f.id}','${esc(t.name)}',this)" ` +
          `title="${esc(t.summary)}${t.needs_stack ? ' (needs local stack)' : ''}">▶ run ${esc(t.kind)}</button>`).join('')
      : '';

    const statusCtl = srv
      ? `<div class="statusctl">set: ${STATUSES.map(s =>
          `<button class="stbtn${f.status === s ? ' cur' : ''}" onclick="setStatus('${f.id}','${s}')">${s}</button>`).join('')}</div>`
      : '';

    const historyHtml = (f.history && f.history.length)
      ? `<dt>History</dt><dd>${f.history.map(h =>
          `<div class="hist">${esc(h.at)} — <b>${esc(h.status)}</b> by ${esc(h.actor)}${h.note ? ' · ' + esc(h.note) : ''}</div>`).join('')}</dd>`
      : '';

    return `
    <div class="finding" id="f-${f.id}">
      <div class="fhead" onclick="if(event.target.tagName!=='BUTTON'&&event.target.tagName!=='A')document.getElementById('f-${f.id}').classList.toggle('open')">
        <span class="id">${f.id}</span>
        <span class="pill sev-${f.severity}">${f.severity}</span>
        <span class="pill st-${f.status}">${f.status}</span>
        ${lrBadge}
        <span class="ftitle">${esc(f.title)}</span>
        ${runBtns}
        <span class="farea">${f.area}</span>
      </div>
      <div class="fbody">
        <dt>Location</dt><dd><span class="file">${esc(f.file)}${f.line ? ':' + f.line : ''}</span></dd>
        <dt>Evidence</dt><dd>${esc(f.evidence)}</dd>
        <dt>Recommendation</dt><dd>${esc(f.recommendation)}</dd>
        ${tests.length ? `<dt>Bound tests</dt><dd>${tests.map(t => `<code>${esc(t.name)}</code> <span class="hts">(${esc(t.kind)})</span>`).join(' ')}</dd>` : ''}
        ${historyHtml}
        ${statusCtl}
      </div>
    </div>`;
  }).join('');
}

// Re-poll health every 10s while the server is up.
setInterval(() => { if (window.CONTROL.server) pollHealth(); }, 10000);
