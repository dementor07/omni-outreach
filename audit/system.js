/* System & pipeline visualisations for the audit control plane.
 *
 * Four live panels, all driven by the control server's viz endpoints:
 *   - Process pipeline  (/api/process)     : SVG flow graph, finding stall-points in red
 *   - DB projections    (/api/db)          : omni_* row counts
 *   - Redpanda topics   (/api/topics)      : partitions + consumer-group lag
 *   - Run trace         (/api/trace/{cid}) : per-correlation timeline
 *
 * Each panel degrades to a clear "unavailable" note when its backend is down,
 * so the System view is honest whether or not the stack is running.
 */
window.SYSTEM = { refresh, _timer: null, _selectedCid: null };

function _esc(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
async function _get(path){
  try { const r = await fetch(path, {cache:'no-store'}); if(!r.ok) return null; return await r.json(); }
  catch(e){ return null; }
}

async function refresh(){
  if (!(window.CONTROL && window.CONTROL.server)){
    ['processViz','dbViz','topicsViz','traceViz'].forEach(id=>{
      const el=document.getElementById(id);
      if(el) el.innerHTML='<div class="vizunavail">Control server not running — start <code>python audit/server.py</code> to see the live stack.</div>';
    });
    return;
  }
  renderProcess();
  renderDb();
  renderTopics();
  renderCorrelations();
}

/* ── Process flow graph (SVG, left-to-right layered) ─────────────────────────── */
async function renderProcess(){
  const el = document.getElementById('processViz'); if(!el) return;
  const [proc, topics] = await Promise.all([_get('/api/process'), _get('/api/topics')]);
  if(!proc){ el.innerHTML='<div class="vizunavail">pipeline topology unavailable</div>'; return; }

  // message counts per topic (from topics endpoint) to annotate edges/nodes
  const topicInfo = {};
  if(topics && topics.topics) topics.topics.forEach(t=>topicInfo[t.name]={missing:t.missing});

  // Layered layout via BFS from "nodes". The topology has a cycle
  // (transitions -> omni.events -> dispatcher -> ... -> transitions), so a naive
  // longest-path relaxation runs columns to infinity. Use first-visit BFS depth
  // (each node's column is fixed the first time it's reached) which breaks cycles.
  const adj = {}; proc.edges.forEach(e=>{ (adj[e.from]=adj[e.from]||[]).push(e.to); });
  const col = {}; const queue=[['nodes',0]]; col['nodes']=0;
  while(queue.length){
    const [id,d]=queue.shift();
    (adj[id]||[]).forEach(to=>{ if(col[to]===undefined){ col[to]=d+1; queue.push([to,d+1]); }});
  }
  // any node not reached (shouldn't happen) gets column 0
  proc.nodes.forEach(n=>{ if(col[n.id]===undefined) col[n.id]=0; });
  // group by column for vertical stacking
  const byCol={}; proc.nodes.forEach(n=>{ const c=col[n.id]||0; (byCol[c]=byCol[c]||[]).push(n); });
  const COLW=150, ROWH=64, PADX=20, PADY=24, NW=120, NH=38;
  const pos={};
  Object.keys(byCol).forEach(c=>{ byCol[c].forEach((n,r)=>{ pos[n.id]={x:PADX+c*COLW, y:PADY+r*ROWH}; }); });
  const maxCol=Math.max(...Object.keys(byCol).map(Number));
  const maxRow=Math.max(...Object.values(byCol).map(a=>a.length));
  const W=PADX*2+maxCol*COLW+NW, H=PADY*2+maxRow*ROWH;

  // Only unresolved overlays (status still VERIFIED) paint a hop red. A
  // FIXED/DISMISSED finding is resolved — its hop is no longer a stall-point.
  const overlaysByTarget={};
  (proc.overlays||[]).filter(o=>!o.resolved).forEach(o=>{ (overlaysByTarget[o.target]=overlaysByTarget[o.target]||[]).push(o); });
  const openCount=(proc.overlays||[]).filter(o=>!o.resolved).length;
  const COLOR={produce:'#1f6feb',topic:'#8957e5',worker:'#238636',store:'#9e6a03'};

  const edgeP = proc.edges.map(e=>{
    const a=pos[e.from], b=pos[e.to]; if(!a||!b) return '';
    const x1=a.x+NW, y1=a.y+NH/2, x2=b.x, y2=b.y+NH/2;
    const mx=(x1+x2)/2;
    return `<path class="pg-edge" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"/>`;
  }).join('');

  const nodeP = proc.nodes.map(n=>{
    const p=pos[n.id]; const warn=overlaysByTarget[n.id];
    const fill = n.kind==='topic'
      ? (topicInfo[n.id] && topicInfo[n.id].missing ? '#21262d' : '#161b22')
      : '#161b22';
    const stroke = warn ? 'var(--crit)' : (COLOR[n.kind]||'#30363d');
    const title = warn ? warn.map(w=>w.finding+': '+w.note).join(' | ') : (n.label);
    return `<g class="pg-node" transform="translate(${p.x},${p.y})"><title>${_esc(title)}</title>`+
      `<rect width="${NW}" height="${NH}" rx="7" fill="${fill}" stroke="${stroke}"/>`+
      `<text x="${NW/2}" y="${NH/2+4}" text-anchor="middle">${_esc(n.label)}</text>`+
      (warn?`<circle cx="${NW-8}" cy="8" r="5" class="pg-warn"/>`:'')+
      `</g>`;
  }).join('');

  el.innerHTML =
    `<svg id="processSvg" viewBox="0 0 ${W} ${H}">`+
    `<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">`+
    `<path d="M0,0 L7,3 L0,6 Z" fill="#30363d"/></marker></defs>`+
    edgeP+nodeP+`</svg>`+
    `<div style="margin-top:10px;font-size:11px;color:var(--muted)">`+
    `<span style="color:var(--crit)">●</span> red = a HIGH/MEDIUM finding still stalls work at this hop — hover for which. `+
    `${openCount} open / ${(proc.overlays||[]).length} historical stall-points.</div>`+
    `<div style="margin-top:6px;font-size:11px">`+
    (proc.overlays||[]).map(o=>{
      const resolved=!!o.resolved;
      const color=resolved?'var(--ok,#3fb950)':'var(--crit)';
      const mark=resolved?'✓ ':'';
      const deco=resolved?'text-decoration:line-through;opacity:.7':'';
      return `<div style="${deco}"><b style="color:${color}">${mark}${_esc(o.finding)}</b> `+
        `<span style="color:var(--muted)">[${_esc(o.status||'?')}]</span> @ <code>${_esc(o.target)}</code> — ${_esc(o.note)}</div>`;
    }).join('')+
    `</div>`;
}

/* ── DB projections ──────────────────────────────────────────────────────────── */
async function renderDb(){
  const el=document.getElementById('dbViz'); if(!el) return;
  const d=await _get('/api/db');
  if(!d || !d.available){ el.innerHTML=`<div class="vizunavail">DB unavailable${d&&d.error?': '+_esc(d.error):''}</div>`; return; }
  const rows=d.tables.map(t=>{
    const c=t.count==null?'err':t.count;
    const cls=(typeof t.count==='number'&&t.count>0)?'tcount nonzero':'tcount';
    return `<div class="tname">${_esc(t.table)}</div><div class="${cls}">${c}</div>`;
  }).join('');
  const recent=(d.recent_events||[]).slice(0,5).map(e=>
    `<div class="te">${_esc(e.event_type)} <span class="tt">${_esc(e.at||'')}</span></div>`).join('');
  el.innerHTML=`<div class="dbtable">${rows}</div>`+
    (recent?`<div style="margin-top:10px"><div class="phint">recent events</div>${recent}</div>`:
      `<div class="phint" style="margin-top:10px">no events archived yet — drive a run to populate</div>`);
}

/* ── Redpanda topics + lag ───────────────────────────────────────────────────── */
async function renderTopics(){
  const el=document.getElementById('topicsViz'); if(!el) return;
  const d=await _get('/api/topics');
  if(!d || !d.available){ el.innerHTML=`<div class="vizunavail">broker unreachable${d&&d.error?': '+_esc(d.error):''}</div>`; return; }
  const rows=d.topics.map(t=>
    `<div class="topicrow ${t.missing?'missing':''}"><span class="tn">${_esc(t.name)}</span>`+
    `<span>${t.missing?'<span class="lagpill">not created</span>':`${t.partitions}p`}</span></div>`).join('');
  const lag=(d.consumer_groups||[]).map(g=>
    `<div class="topicrow"><span class="tn">${_esc(g.group)}</span>`+
    `<span class="lagpill ${g.total_lag>0?'lag':''}">lag ${g.total_lag}</span></div>`).join('');
  el.innerHTML=rows+(lag?`<div style="margin-top:10px"><div class="phint">consumer groups</div>${lag}</div>`:'');
}

/* ── Run trace ───────────────────────────────────────────────────────────────── */
async function renderCorrelations(){
  const el=document.getElementById('traceViz'); if(!el) return;
  const d=await _get('/api/correlations');
  if(!d || !d.available){ el.innerHTML=`<div class="vizunavail">trace store unavailable</div>`; return; }
  if(!d.correlations.length){ el.innerHTML='<div class="phint">no runs traced yet — drive a workflow to see a timeline.</div>'; return; }
  const sel=window.SYSTEM._selectedCid;
  const picker=d.correlations.map(c=>
    `<button class="cidbtn${c.correlation_id===sel?' active':''}" onclick="SYSTEM_trace('${_esc(c.correlation_id)}')" title="${c.events} events, last ${c.last}">`+
    `${_esc(c.correlation_id.slice(0,8))} (${c.events})</button>`).join('');
  el.innerHTML=`<div class="tracepick">${picker}</div><div id="traceTimeline" class="tracebox"><div class="phint">pick a run above</div></div>`;
  // Preserve the selected run across auto-refreshes (don't wipe the timeline).
  if(sel) SYSTEM_trace(sel);
}

window.SYSTEM_trace = async function(cid){
  window.SYSTEM._selectedCid = cid;
  document.querySelectorAll('.cidbtn').forEach(b=>b.classList.toggle('active', b.textContent.startsWith(cid.slice(0,8))));
  const tl=document.getElementById('traceTimeline'); if(!tl) return;
  tl.innerHTML='<div class="phint">loading…</div>';
  const d=await _get('/api/trace/'+encodeURIComponent(cid));
  if(!d || !d.available){ tl.innerHTML='<div class="vizunavail">trace unavailable</div>'; return; }
  if(!d.events.length){ tl.innerHTML='<div class="phint">no archived events for this correlation_id (it may have forked — see DATAFLOW-001).</div>'; return; }
  // e.at is a preformatted time string from the server (e.g. "06:33:57.679"),
  // not an ISO timestamp — render it verbatim.
  tl.innerHTML=d.events.map(e=>
    `<div class="traceev"><span class="tt">${_esc(e.at||'—')}</span>`+
    `<span class="te">${_esc(e.event_type)}</span>`+
    `<span class="tt">${_esc((e.entity_type||'')+':'+(e.entity_id||'').slice(0,8))}</span></div>`).join('');
};

// auto-refresh the system view every 8s while it's visible
setInterval(()=>{
  const sv=document.getElementById('view-system');
  if(sv && sv.style.display!=='none' && window.CONTROL && window.CONTROL.server) refresh();
}, 8000);
