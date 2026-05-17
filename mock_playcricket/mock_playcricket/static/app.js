// Scoring page logic. Polls /api/ui/state and renders. Single-file vanilla JS.

const $ = sel => document.querySelector(sel);
const $$ = sel => document.querySelectorAll(sel);
const el = (tag, attrs = {}, ...children) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k === 'onclick') e.onclick = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return e;
};

let state = null;
let mode = 'bbb';                  // 'bbb' or 'edit'
let pendingExtra = null;           // {kind: 'wide'|'no_ball'|'bye'|'leg_bye'}
let editDirty = false;
let editBuffer = null;             // local copy of innings being edited
let recentByOver = {};             // { innings_no: [{over_no, balls: ['1','W','wd',...]}] }

// ------------------ API helpers ------------------

async function apiGet(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

async function apiPost(url, body) {
  const res = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const j = await res.json().catch(() => ({}));
  if (!res.ok || j.ok === false) throw new Error(j.error || `${url}: ${res.status}`);
  return j;
}

// ------------------ Polling ------------------

async function refresh() {
  try {
    state = await apiGet('/api/ui/state');
  } catch (e) {
    console.error('refresh failed', e);
    return;
  }
  render();
}

setInterval(refresh, 1000);
refresh();

// ------------------ Render ------------------

function render() {
  if (!state) return;

  // Match picker
  const picker = $('#match-picker');
  picker.innerHTML = '';
  for (const m of state.matches) {
    const o = el('option', { value: m.id }, `[${m.id}] ${m.home_team_name} v ${m.away_team_name} — ${m.status}`);
    if (m.id === state.active_match_id) o.selected = true;
    picker.appendChild(o);
  }
  $('#delete-match-btn').classList.toggle('hidden', !state.active_match_id);

  const m = state.match;
  const v = state.view;

  if (!m) {
    $('#no-match').classList.remove('hidden');
    $('#scorecard').classList.add('hidden');
    $('#lifecycle').classList.add('hidden');
    $('#mode-toggle').classList.add('hidden');
    $('#bbb-pane').classList.add('hidden');
    $('#edit-pane').classList.add('hidden');
    $('#players-panel').classList.add('hidden');
    $('#match-status').textContent = '';
    return;
  }

  $('#no-match').classList.add('hidden');
  $('#scorecard').classList.remove('hidden');
  $('#lifecycle').classList.remove('hidden');
  $('#players-panel').classList.remove('hidden');

  // Match title + status
  $('#match-title').textContent = `${m.home_team_name} v ${m.away_team_name} — ${m.no_of_overs} overs`;
  $('#match-status').textContent = `Status: ${m.status} · Toss: ${m.toss || '—'}${m.batted_first ? ` · ${m.batted_first} batted first` : ''}`;

  // Scorecard summary
  const sum = $('#scorecard-summary');
  sum.innerHTML = '';
  for (const inn of m.innings) {
    const extras = `b${inn.extra_byes} lb${inn.extra_leg_byes} w${inn.extra_wides} nb${inn.extra_no_balls}`;
    const line = el('div', {}, `Inn ${inn.innings_number}: ${inn.team_batting_name} ${inn.runs}/${inn.wickets} (${inn.overs}) · Extras ${inn.total_extras} (${extras})${inn.declared ? ' DEC' : ''}${inn.forfeited_innings ? ' FF' : ''}`);
    sum.appendChild(line);
  }

  // Target line (chasing)
  if (v && v.target != null) {
    $('#target-line').classList.remove('hidden');
    const need = v.target - parseInt(m.innings[m.innings.length - 1].runs, 10);
    $('#target-line').textContent = `CHASING — target ${v.target}, need ${need} more`;
  } else {
    $('#target-line').classList.add('hidden');
  }

  // Lifecycle buttons
  const hasOpenInnings = v && !v.closed;
  const allClosed = m.innings.length > 0 && m.innings.every(i => i.declared || i.forfeited_innings || _isAllOut(i, m) || _oversExhausted(i, m));
  $('#start-innings-btn').classList.toggle('hidden', hasOpenInnings || m.status === 'Result');
  $('#end-innings-btn').classList.toggle('hidden', !hasOpenInnings);
  $('#end-match-btn').classList.toggle('hidden', m.status === 'Result' || !m.innings.length);

  // Mode + panes
  if (hasOpenInnings) {
    $('#mode-toggle').classList.remove('hidden');
    if (mode === 'bbb') {
      $('#bbb-pane').classList.remove('hidden');
      $('#edit-pane').classList.add('hidden');
      renderBbb(m, v);
    } else {
      $('#bbb-pane').classList.add('hidden');
      $('#edit-pane').classList.remove('hidden');
      renderEdit(m, v);
    }
  } else {
    $('#mode-toggle').classList.add('hidden');
    $('#bbb-pane').classList.add('hidden');
    $('#edit-pane').classList.add('hidden');
  }

  // Players panel
  renderPlayers(m);
}

function _isAllOut(inn) {
  return parseInt(inn.wickets, 10) >= 10;
}
function _oversExhausted(inn, m) {
  const [whole, rest] = String(inn.overs).split('.');
  const balls = parseInt(whole, 10) * 6 + parseInt(rest || '0', 10);
  return balls >= m.no_of_overs * 6;
}

function renderBbb(m, v) {
  const strikerCard = $('#striker-card');
  const nonCard = $('#non-striker-card');
  strikerCard.querySelector('.name').textContent = v.striker ? v.striker.name : '—';
  strikerCard.querySelector('.score').textContent = v.striker ? `${v.striker.runs} (${v.striker.balls})` : '';
  nonCard.querySelector('.name').textContent = v.non_striker ? v.non_striker.name : '—';
  nonCard.querySelector('.score').textContent = v.non_striker ? `${v.non_striker.runs} (${v.non_striker.balls})` : '';
  strikerCard.classList.add('on-strike');
  nonCard.classList.remove('on-strike');

  const bowler = $('#bowler-card');
  bowler.querySelector('.name').textContent = v.bowler ? v.bowler.name : '—';
  bowler.querySelector('.figs').textContent = v.bowler ?
    `${v.bowler.overs} - ${v.bowler.maidens} - ${v.bowler.runs} - ${v.bowler.wickets}` : '';

  // Recent balls (client-side log of this over)
  const innNo = v.innings_number;
  const overNo = Math.floor(v.legal_balls / 6);
  const log = recentByOver[innNo] || [];
  const thisOver = log.find(o => o.over_no === overNo);
  $('#recent-balls').innerHTML = '';
  $('#recent-balls').textContent = `Over ${overNo + 1}: ${thisOver ? thisOver.balls.join(' ') : '(new)'}  — ${v.balls_this_over}/6`;
}

function renderEdit(m, v) {
  const inn = m.innings.find(i => i.innings_number === v.innings_number);
  if (!editDirty) editBuffer = JSON.parse(JSON.stringify(inn));
  $('#edit-innings-no').textContent = inn.innings_number;

  // Batters table
  const tbody = $('#edit-batters tbody');
  tbody.innerHTML = '';
  for (const b of editBuffer.bat) {
    const tr = el('tr', {},
      el('td', {}, String(b.position)),
      el('td', {}, b.batsman_name),
      _ni(b, 'runs'),
      _ni(b, 'balls'),
      _ni(b, 'fours'),
      _ni(b, 'sixes'),
      _ti(b, 'how_out'),
      _ti(b, 'bowler_name'),
      _ti(b, 'fielder_name'),
    );
    tbody.appendChild(tr);
  }
  const btbody = $('#edit-bowlers tbody');
  btbody.innerHTML = '';
  for (const bo of editBuffer.bowl) {
    const tr = el('tr', {},
      el('td', {}, bo.bowler_name),
      el('td', {}, bo.overs),
      _ni(bo, 'maidens'),
      _ni(bo, 'runs'),
      _ni(bo, 'wickets'),
      _ni(bo, 'wides'),
      _ni(bo, 'no_balls'),
    );
    btbody.appendChild(tr);
  }
  $('#ex-b').value = editBuffer.extra_byes;
  $('#ex-lb').value = editBuffer.extra_leg_byes;
  $('#ex-w').value = editBuffer.extra_wides;
  $('#ex-nb').value = editBuffer.extra_no_balls;
  $('#ex-pen').value = editBuffer.extra_penalty_runs;
  $('#ed-legal').value = v.legal_balls;
  $('#ed-striker').value = v.striker_pos;
  $('#ed-non').value = v.non_striker_pos;
  $('#ed-bowler-idx').value = m.innings.find(i => i.innings_number === v.innings_number) ? 0 : 0;
  $('#ed-declared').checked = editBuffer.declared;
  $('#ed-forfeited').checked = editBuffer.forfeited_innings;
}

function _ni(obj, field) {
  const td = el('td');
  const input = el('input', { type: 'number', min: '0', value: obj[field] });
  input.addEventListener('input', () => { obj[field] = parseInt(input.value, 10) || 0; editDirty = true; });
  td.appendChild(input);
  return td;
}
function _ti(obj, field) {
  const td = el('td');
  const input = el('input', { type: 'text', value: obj[field] || '' });
  input.addEventListener('input', () => { obj[field] = input.value; editDirty = true; });
  td.appendChild(input);
  return td;
}

function renderPlayers(m) {
  const h = $('#players-home'); const a = $('#players-away');
  h.innerHTML = `<strong>${m.home_team_name}:</strong>`;
  a.innerHTML = `<strong>${m.away_team_name}:</strong>`;
  const ph = m.players[0]?.home_team || [];
  const pa = m.players[1]?.away_team || [];
  const olh = el('ol'); for (const p of ph) olh.appendChild(el('li', {}, p.player_name));
  const ola = el('ol'); for (const p of pa) ola.appendChild(el('li', {}, p.player_name));
  h.appendChild(olh); a.appendChild(ola);
}

// ------------------ Match picker / lifecycle ------------------

$('#match-picker').addEventListener('change', async (e) => {
  await apiPost('/api/ui/set-active-match', { match_id: parseInt(e.target.value, 10) });
  refresh();
});

$('#new-match-btn').addEventListener('click', () => openNewMatchModal());
$('#delete-match-btn').addEventListener('click', async () => {
  if (!state || !state.active_match_id) return;
  if (!confirm(`Delete match ${state.active_match_id}? This cannot be undone.`)) return;
  await apiPost('/api/ui/delete-match', { match_id: state.active_match_id });
  refresh();
});

$('#start-innings-btn').addEventListener('click', () => openStartInningsModal());
$('#end-innings-btn').addEventListener('click', async () => {
  const declared = confirm('Declare? (Cancel = normal end-of-innings)');
  await apiPost('/api/ui/end-innings', { declared });
  refresh();
});
$('#end-match-btn').addEventListener('click', () => openEndMatchModal());

// ------------------ Ball-by-ball buttons ------------------

$$('#run-buttons button').forEach(btn => {
  btn.addEventListener('click', async () => {
    const runs = parseInt(btn.dataset.runs, 10);
    await postBall({ kind: 'legal', runs });
  });
});

$$('#extras-buttons button').forEach(btn => {
  btn.addEventListener('click', async () => {
    const kind = btn.dataset.kind;
    if (kind === 'wicket') {
      openWicketModal();
    } else {
      pendingExtra = { kind };
      $('#extras-runs').classList.remove('hidden');
    }
  });
});
$('#extras-cancel').addEventListener('click', () => {
  pendingExtra = null;
  $('#extras-runs').classList.add('hidden');
});
$$('#extras-runs button[data-extras-runs]').forEach(btn => {
  btn.addEventListener('click', async () => {
    const runs = parseInt(btn.dataset.extrasRuns, 10);
    const kind = pendingExtra?.kind;
    pendingExtra = null;
    $('#extras-runs').classList.add('hidden');
    if (kind) await postBall({ kind, runs });
  });
});

$('#swap-strike-btn').addEventListener('click', async () => {
  // Use direct edit to swap pos
  const v = state?.view;
  if (!v) return;
  await apiPost('/api/ui/edit', {
    innings_number: v.innings_number,
    patch: { _striker_pos: v.non_striker_pos, _non_striker_pos: v.striker_pos },
  });
  refresh();
});

async function postBall(body) {
  const v = state?.view; if (!v) return;
  const innNo = v.innings_number;
  const overNo = Math.floor(v.legal_balls / 6);
  if (!recentByOver[innNo]) recentByOver[innNo] = [];
  let entry = recentByOver[innNo].find(o => o.over_no === overNo);
  if (!entry) { entry = { over_no: overNo, balls: [] }; recentByOver[innNo].push(entry); }
  entry.balls.push(_ballSymbol(body));
  try {
    await apiPost('/api/ui/ball', body);
  } catch (e) {
    alert('Ball error: ' + e.message);
    entry.balls.pop();
  }
  // If the over just ended, prompt for the new bowler
  await refresh();
  const v2 = state?.view;
  if (v2 && v2.balls_this_over === 0 && v2.legal_balls > 0 && !v2.closed) {
    openChangeBowlerModal();
  }
}

function _ballSymbol(b) {
  if (b.kind === 'legal') return String(b.runs);
  if (b.kind === 'wide') return `wd${b.runs || ''}`;
  if (b.kind === 'no_ball') return `nb${b.runs || ''}`;
  if (b.kind === 'bye') return `b${b.runs}`;
  if (b.kind === 'leg_bye') return `lb${b.runs}`;
  if (b.kind === 'wicket') return 'W';
  return '?';
}

// ------------------ Mode toggle ------------------

$$('#mode-toggle input').forEach(r => r.addEventListener('change', e => {
  if (editDirty && mode === 'edit' && e.target.value === 'bbb') {
    if (!confirm('Discard direct-edit changes?')) { e.target.checked = false; $$('#mode-toggle input[value=edit]')[0].checked = true; return; }
    editDirty = false; editBuffer = null;
  }
  mode = e.target.value;
  render();
}));

$('#edit-discard').addEventListener('click', () => {
  editDirty = false; editBuffer = null;
  refresh();
});

$('#edit-save').addEventListener('click', async () => {
  const v = state.view;
  const patch = {
    extras: {
      b: parseInt($('#ex-b').value, 10) || 0,
      lb: parseInt($('#ex-lb').value, 10) || 0,
      w: parseInt($('#ex-w').value, 10) || 0,
      nb: parseInt($('#ex-nb').value, 10) || 0,
      pen: parseInt($('#ex-pen').value, 10) || 0,
    },
    _legal_balls: parseInt($('#ed-legal').value, 10) || 0,
    _striker_pos: parseInt($('#ed-striker').value, 10) || 1,
    _non_striker_pos: parseInt($('#ed-non').value, 10) || 2,
    _current_bowler_idx: parseInt($('#ed-bowler-idx').value, 10) || 0,
    declared: $('#ed-declared').checked,
    forfeited_innings: $('#ed-forfeited').checked,
    bat: editBuffer.bat.map(b => ({
      position: b.position, batsman_name: b.batsman_name, batsman_id: parseInt(b.batsman_id, 10),
      runs: parseInt(b.runs, 10) || 0, balls: parseInt(b.balls, 10) || 0,
      fours: parseInt(b.fours, 10) || 0, sixes: parseInt(b.sixes, 10) || 0,
      how_out: b.how_out || '', bowler_name: b.bowler_name || '', fielder_name: b.fielder_name || '',
    })),
    bowl: editBuffer.bowl.map(b => ({
      bowler_id: parseInt(b.bowler_id, 10),
      bowler_name: b.bowler_name,
      maidens: parseInt(b.maidens, 10) || 0,
      runs: parseInt(b.runs, 10) || 0,
      wickets: parseInt(b.wickets, 10) || 0,
      wides: parseInt(b.wides, 10) || 0,
      no_balls: parseInt(b.no_balls, 10) || 0,
    })),
  };
  await apiPost('/api/ui/edit', { innings_number: v.innings_number, patch });
  editDirty = false; editBuffer = null;
  refresh();
});

// ------------------ Modals ------------------

function showModal(title, bodyEl, onOk, onCancel) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = '';
  $('#modal-body').appendChild(bodyEl);
  $('#modal-root').classList.remove('hidden');
  const okBtn = $('#modal-ok');
  const cancelBtn = $('#modal-cancel');
  const close = () => { $('#modal-root').classList.add('hidden'); okBtn.onclick = null; cancelBtn.onclick = null; };
  okBtn.onclick = async () => { try { await onOk(); close(); } catch (e) { alert(e.message || e); } };
  cancelBtn.onclick = () => { if (onCancel) onCancel(); close(); };
}

function openNewMatchModal() {
  const body = el('div', {},
    _lbl('Home team name', _inp('text', 'nm-home', 'Aston on Trent')),
    _lbl('Away team name', _inp('text', 'nm-away', 'Visitors')),
    _lbl('Overs',          _inp('number', 'nm-overs', '20')),
    _lbl('Toss won by (team name)', _inp('text', 'nm-toss', 'Aston on Trent')),
    _lbl('Batted first (team name)', _inp('text', 'nm-batted', 'Aston on Trent')),
    el('label', {}, 'Home players (one per line)',
       el('textarea', { id: 'nm-home-players' }, 'J. Smith\nA. Jones\nR. Patel\nT. Brown\nM. Khan\nB. Allen\nC. Davies\nD. Evans\nE. Hughes\nF. Ireland\nG. Jackson')),
    el('label', {}, 'Away players (one per line)',
       el('textarea', { id: 'nm-away-players' }, 'V1 Player\nV2 Player\nV3 Player\nV4 Player\nV5 Player\nV6 Player\nV7 Player\nV8 Player\nV9 Player\nV10 Player\nV11 Player')),
  );
  showModal('New match', body, async () => {
    await apiPost('/api/ui/new-match', {
      home_team_name: $('#nm-home').value,
      away_team_name: $('#nm-away').value,
      no_of_overs:    parseInt($('#nm-overs').value, 10) || 20,
      toss:           $('#nm-toss').value,
      batted_first:   $('#nm-batted').value,
      home_players:   $('#nm-home-players').value.split('\n'),
      away_players:   $('#nm-away-players').value.split('\n'),
    });
    refresh();
  });
}

function openStartInningsModal() {
  const m = state.match;
  const inningsNo = (m.innings.length) + 1;
  // Determine batting team
  const battingTeamName = (inningsNo === 1) ? m.batted_first
    : (m.batted_first === m.home_team_name ? m.away_team_name : m.home_team_name);
  const battingRoster = (battingTeamName === m.home_team_name) ? (m.players[0]?.home_team || []) : (m.players[1]?.away_team || []);
  const bowlingRoster = (battingTeamName === m.home_team_name) ? (m.players[1]?.away_team || []) : (m.players[0]?.home_team || []);
  const mkSel = (id, list) => {
    const s = el('select', { id });
    for (const p of list) s.appendChild(el('option', { value: p.player_id }, `${p.position}. ${p.player_name}`));
    return s;
  };
  const body = el('div', {},
    el('p', {}, `Innings ${inningsNo} — ${battingTeamName} batting`),
    _lbl('Striker (on strike)',  mkSel('si-striker', battingRoster)),
    _lbl('Non-striker',           mkSel('si-non',      battingRoster)),
    _lbl('Opening bowler',        mkSel('si-bowler',  bowlingRoster)),
  );
  showModal(`Start innings ${inningsNo}`, body, async () => {
    const striker = parseInt($('#si-striker').value, 10);
    const non     = parseInt($('#si-non').value, 10);
    const bowler  = parseInt($('#si-bowler').value, 10);
    if (striker === non) throw new Error('Striker and non-striker must differ');
    await apiPost('/api/ui/start-innings', {
      innings_number: inningsNo,
      opening_bat_ids: [striker, non],
      opening_bowler_id: bowler,
    });
    refresh();
  });
}

function openWicketModal() {
  const m = state.match; const v = state.view;
  const inn = m.innings.find(i => i.innings_number === v.innings_number);
  const battingRoster = (inn.team_batting_name === m.home_team_name)
    ? (m.players[0]?.home_team || []) : (m.players[1]?.away_team || []);
  const fieldingRoster = (inn.team_batting_name === m.home_team_name)
    ? (m.players[1]?.away_team || []) : (m.players[0]?.home_team || []);
  const used = new Set(inn.bat.map(b => b.batsman_id));
  const incoming = battingRoster.filter(p => !used.has(String(p.player_id)) && !used.has(p.player_id));
  const mkSel = (id, list, allowEmpty) => {
    const s = el('select', { id });
    if (allowEmpty) s.appendChild(el('option', { value: '' }, '(none)'));
    for (const p of list) s.appendChild(el('option', { value: p.player_id }, p.player_name));
    return s;
  };
  const howSel = el('select', { id: 'wk-how' },
    el('option', {}, 'Bowled'),
    el('option', {}, 'Caught'),
    el('option', {}, 'LBW'),
    el('option', {}, 'Stumped'),
    el('option', {}, 'Run out'),
    el('option', {}, 'Hit wicket'),
  );
  const body = el('div', {},
    _lbl('How out', howSel),
    _lbl('Fielder (if any)', mkSel('wk-fielder', fieldingRoster, true)),
    _lbl('Runs scored on this delivery', _inp('number', 'wk-runs', '0')),
    _lbl('Which batter is out',
      el('select', { id: 'wk-outpos' },
        el('option', { value: String(v.striker_pos) }, `Striker (pos ${v.striker_pos})`),
        el('option', { value: String(v.non_striker_pos) }, `Non-striker (pos ${v.non_striker_pos})`),
      )),
    _lbl('New batter', mkSel('wk-new', incoming, false)),
  );
  showModal('Wicket', body, async () => {
    const dismissal = {
      how_out: $('#wk-how').value,
      out_pos: parseInt($('#wk-outpos').value, 10),
      new_batsman_id: parseInt($('#wk-new').value, 10),
    };
    const fid = $('#wk-fielder').value;
    if (fid) dismissal.fielder_id = parseInt(fid, 10);
    const runs = parseInt($('#wk-runs').value, 10) || 0;
    await postBall({ kind: 'wicket', runs, dismissal });
  });
}

function openChangeBowlerModal() {
  const m = state.match; const v = state.view;
  const inn = m.innings.find(i => i.innings_number === v.innings_number);
  const fieldingRoster = (inn.team_batting_name === m.home_team_name)
    ? (m.players[1]?.away_team || []) : (m.players[0]?.home_team || []);
  const sel = el('select', { id: 'cb-bowler' });
  for (const p of fieldingRoster) sel.appendChild(el('option', { value: p.player_id }, p.player_name));
  const body = el('div', {},
    el('p', {}, 'Over complete — pick the next bowler.'),
    _lbl('Bowler', sel),
  );
  showModal('Change bowler', body, async () => {
    await apiPost('/api/ui/change-bowler', { bowler_id: parseInt(sel.value, 10) });
    refresh();
  });
}

function openEndMatchModal() {
  const body = el('div', {},
    _lbl('Result description', _inp('text', 'em-desc', '')),
    _lbl('Applied to (team name)', _inp('text', 'em-applied', '')),
  );
  showModal('End match', body, async () => {
    await apiPost('/api/ui/end-match', {
      result: 'Win',
      result_description: $('#em-desc').value,
      result_applied_to: $('#em-applied').value,
    });
    refresh();
  });
}

function _lbl(text, inp) { return el('label', {}, text, inp); }
function _inp(type, id, val) { const i = el('input', { type, id }); if (val != null) i.value = val; return i; }
