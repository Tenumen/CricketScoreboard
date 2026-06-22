#include "debug_server.h"

#include <fcntl.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <array>
#include <chrono>
#include <cstdio>
#include <cstdint>
#include <ctime>
#include <fstream>
#include <sstream>
#include <string>

#include "httplib.h"
#include "json.hpp"

#ifndef BUILD_GIT_HASH
#define BUILD_GIT_HASH "unknown"
#endif

namespace cricketboard {

namespace {

using json = nlohmann::json;

// RFC 4648 base64 decode for the basic-auth credential parse. Lenient: stops
// at the first invalid char rather than throwing, which is sufficient here —
// the constant-time compare downstream is what decides accept vs reject.
std::string Base64Decode(const std::string& in) {
    static const int8_t kTable[256] = {
        // 0..63 chars map to their 6-bit values; -1 for invalid.
        -1,-1,-1,-1, -1,-1,-1,-1, -1,-1,-1,-1, -1,-1,-1,-1,
        -1,-1,-1,-1, -1,-1,-1,-1, -1,-1,-1,-1, -1,-1,-1,-1,
        -1,-1,-1,-1, -1,-1,-1,-1, -1,-1,-1,62, -1,-1,-1,63,
        52,53,54,55, 56,57,58,59, 60,61,-1,-1, -1,-1,-1,-1,
        -1, 0, 1, 2,  3, 4, 5, 6,  7, 8, 9,10, 11,12,13,14,
        15,16,17,18, 19,20,21,22, 23,24,25,-1, -1,-1,-1,-1,
        -1,26,27,28, 29,30,31,32, 33,34,35,36, 37,38,39,40,
        41,42,43,44, 45,46,47,48, 49,50,51,-1, -1,-1,-1,-1,
        // 128..255 all -1
    };
    std::string out;
    out.reserve((in.size() / 4) * 3);
    int val = 0, bits = 0;
    for (unsigned char c : in) {
        if (c == '=' || c == '\n' || c == '\r' || c == ' ') continue;
        const int8_t v = kTable[c];
        if (v < 0) break;
        val = (val << 6) | v;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out.push_back(static_cast<char>((val >> bits) & 0xFF));
        }
    }
    return out;
}

// Constant-time string compare. Returns true iff `a` and `b` are exactly equal.
// Always inspects max(|a|, |b|) bytes so timing doesn't leak length.
bool ConstantTimeEq(const std::string& a, const std::string& b) {
    const size_t n = a.size() > b.size() ? a.size() : b.size();
    uint8_t diff = static_cast<uint8_t>(a.size() ^ b.size());
    for (size_t i = 0; i < n; ++i) {
        const uint8_t ca = i < a.size() ? static_cast<uint8_t>(a[i]) : 0;
        const uint8_t cb = i < b.size() ? static_cast<uint8_t>(b[i]) : 0;
        diff |= ca ^ cb;
    }
    return diff == 0;
}

const char* PhaseString(MatchPhase p) {
    switch (p) {
        case MatchPhase::NO_MATCH:   return "NO_MATCH";
        case MatchPhase::PRE_MATCH:  return "PRE_MATCH";
        case MatchPhase::IN_MATCH:   return "IN_MATCH";
        case MatchPhase::POST_MATCH: return "POST_MATCH";
    }
    return "UNKNOWN";
}

json InningsToJson(const InningsSummary& inn) {
    return json{
        {"valid",     inn.valid},
        {"team_name", inn.team_name},
        {"runs",      inn.runs},
        {"wkts",      inn.wkts},
        {"overs",     inn.overs},
    };
}

// State directory mirrors what scripts/update.sh and scripts/rollback.sh use.
constexpr const char* kStateDir          = "/var/lib/scoreboard24";
constexpr const char* kPrevCommitPath    = "/var/lib/scoreboard24/prev_commit";
constexpr const char* kPrevBinaryPath    = "/var/lib/scoreboard24/scoreboard24.prev";

bool FileExists(const char* path) {
    struct stat st{};
    return ::stat(path, &st) == 0;
}

std::string ReadFirstLine(const char* path) {
    std::ifstream in(path);
    if (!in) return {};
    std::string line;
    std::getline(in, line);
    while (!line.empty() && (line.back() == '\n' || line.back() == '\r'))
        line.pop_back();
    return line;
}

// Run `git -C <repo_dir> <args...>`, capture stdout, trim trailing whitespace.
// Returns empty string on failure (treated as "unknown" by callers).
std::string RunGitCapture(const std::string& repo_dir,
                          const std::string& args_quoted) {
    // Construct command. repo_dir comes from config, not from user request,
    // so shell quoting is sufficient — no untrusted input reaches the shell.
    // -c safe.directory='*' so this works when the service runs as root against
    // a repo owned by 'tenumen' (git otherwise refuses with "dubious ownership"
    // and every field reads back as "unknown").
    std::string cmd = "git -c safe.directory='*' -C '" + repo_dir + "' "
                    + args_quoted + " 2>/dev/null";
    FILE* p = popen(cmd.c_str(), "r");
    if (!p) return {};
    std::array<char, 512> buf{};
    std::string out;
    while (fgets(buf.data(), static_cast<int>(buf.size()), p)) {
        out.append(buf.data());
    }
    pclose(p);
    while (!out.empty() && (out.back() == '\n' || out.back() == '\r' || out.back() == ' '))
        out.pop_back();
    return out;
}

// Fork + setsid + exec the named script, fully detached so it survives the
// scoreboard24 service restart it will itself trigger.
//
// We belt-and-braces close all inherited fds beyond stdio in the child,
// because the listening HTTP socket would otherwise stay bound through
// the child's lifetime and block the next scoreboard24's bind() on 8080.
bool SpawnDetachedScript(const std::string& script_path) {
    pid_t pid = fork();
    if (pid < 0) return false;
    if (pid > 0) return true;  // parent — return success immediately

    // --- child ---
    setsid();
    // The server process sets SIGCHLD to SIG_IGN (see constructor) so it never
    // accumulates zombies for these detached scripts. That disposition is
    // inherited across fork+exec, and git's own waitpid() calls on its helper
    // processes (git-remote-https, unpack-objects) then fail with ECHILD —
    // which breaks `git pull` inside update.sh ("fatal: unpack-objects failed").
    // Restore default child handling so the spawned script and its descendants
    // reap their own children normally.
    ::signal(SIGCHLD, SIG_DFL);
    // Close every fd above stdio. closefrom() isn't portable on glibc; an
    // explicit loop up to a conservative ceiling is.
    for (int fd = 3; fd < 256; ++fd) ::close(fd);
    // Redirect stdio to /dev/null so the script never tries to write to a
    // socket inherited from cpp-httplib.
    int devnull = ::open("/dev/null", O_RDWR);
    if (devnull >= 0) {
        ::dup2(devnull, 0);
        ::dup2(devnull, 1);
        ::dup2(devnull, 2);
        if (devnull > 2) ::close(devnull);
    }
    ::execl("/usr/bin/bash", "bash", script_path.c_str(),
            static_cast<char*>(nullptr));
    _exit(127);  // exec failed
}

json StateToJson(const MatchState& s) {
    return json{
        {"phase",              PhaseString(s.phase)},
        {"generation",         s.generation},
        {"home_club_name",     s.home_club_name},
        {"home_team_name",     s.home_team_name},
        {"away_club_name",     s.away_club_name},
        {"away_team_name",     s.away_team_name},
        {"chasing",            s.chasing},
        {"target",             s.target},
        {"runs",               s.runs},
        {"wkts",               s.wkts},
        {"overs",              s.overs},
        {"bat1_name",          s.bat1_name},
        {"bat1_score",         s.bat1_score},
        {"bat2_name",          s.bat2_name},
        {"bat2_score",         s.bat2_score},
        {"on_strike",          s.on_strike},
        {"last_inn_runs",      s.last_inn_runs},
        {"last_inn_wkts",      s.last_inn_wkts},
        {"total_extras",       s.total_extras},
        {"result_description", s.result_description},
        {"inn1",               InningsToJson(s.inn1)},
        {"inn2",               InningsToJson(s.inn2)},
        {"innings_summary", {
            {"active",      s.innings_summary.active},
            {"team_name",   s.innings_summary.team_name},
            {"runs",        s.innings_summary.runs},
            {"wkts",        s.innings_summary.wkts},
            {"has_extras",  s.innings_summary.has_extras},
            {"extras",      s.innings_summary.extras},
            {"overs",       s.innings_summary.overs},
            {"bat1_name",   s.innings_summary.bat1_name},
            {"bat1_score",  s.innings_summary.bat1_score},
            {"bat2_name",   s.innings_summary.bat2_name},
            {"bat2_score",  s.innings_summary.bat2_score},
        }},
    };
}

// Minimal mobile-friendly HTML. Polls /api/state every 2 s. Plain CSS, no
// external resources — Pi has no outbound CDN dependency.
constexpr const char* kIndexHtml = R"HTML(<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aston on Trent Scoreboard Console</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         background:#111; color:#eee; margin:0; padding:16px; }
  h1 { margin:0 0 12px; font-size:18px; }
  .meta { color:#9aa; font-size:12px; margin-bottom:16px; }
  .phase { display:inline-block; padding:2px 8px; border-radius:4px;
           font-weight:600; font-size:12px; letter-spacing:0.05em; }
  .phase-NO_MATCH   { background:#444;  }
  .phase-PRE_MATCH  { background:#264; color:#cfc; }
  .phase-IN_MATCH   { background:#246; color:#cef; }
  .phase-POST_MATCH { background:#642; color:#fdb; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { padding:6px 8px; text-align:left; border-bottom:1px solid #222; }
  th { color:#9aa; font-weight:500; width:42%; }
  td { font-family: "SF Mono", Menlo, Consolas, monospace; word-break: break-word; }
  .section { margin: 18px 0 8px; color:#9aa; font-size:11px;
             text-transform:uppercase; letter-spacing:0.08em; }
  .stale { color:#f88; }
  .actions { margin: 12px 0 0; display:flex; gap:10px; flex-wrap:wrap; }
  button { padding: 10px 16px; font-size:14px; border:1px solid #555;
           background:#222; color:#eee; border-radius:4px; cursor:pointer; }
  button:hover:not(:disabled) { background:#2a2a2a; }
  button:disabled { opacity:0.4; cursor:not-allowed; }
  #btn-rollback { border-color:#844; }
  button.danger { border-color:#a44; background:#2a1a1a; }
  button.danger:hover:not(:disabled) { background:#3a1f1f; }
  .banner { padding: 8px 12px; border-radius:4px; margin-top:10px;
            background:#234; color:#cef; font-size:13px; }
  .banner.error { background:#422; color:#fcc; }
  .banner.hidden { display:none; }
  .build-match { color:#7d7; }
  .build-mismatch { color:#fb8; }
  .tabs { display:flex; gap:6px; margin:0 0 12px; border-bottom:1px solid #333; }
  .tab { padding:9px 16px; font-size:14px; border:none; border-bottom:2px solid transparent;
         background:none; color:#9aa; border-radius:0; cursor:pointer; }
  .tab:hover:not(.active) { color:#cde; }
  .tab.active { color:#eee; border-bottom-color:#4a9; }
  .tab-panel.hidden { display:none; }
  input[type="text"] { width:100%; box-sizing:border-box; padding:8px 10px;
         font-size:14px; border:1px solid #555; background:#222; color:#eee;
         border-radius:4px; }
  .hint { color:#9aa; font-size:12px; margin-top:8px; }
</style>
</head>
<body>
<h1>Aston on Trent Scoreboard Console</h1>
<div class="meta">
  <span id="updated">connecting…</span>
  <span style="margin:0 6px">·</span>
  <span class="phase" id="phase">—</span>
</div>

<div class="tabs">
  <button class="tab active" data-tab="companion">Scoreboard Companion</button>
  <button class="tab" data-tab="admin">Admin Console</button>
</div>

<div id="action-banner" class="banner hidden"></div>

<div class="tab-panel" id="tab-companion">

  <div class="section">Match identity</div>
  <table>
    <tr><th>Home club</th><td id="home_club_name">—</td></tr>
    <tr><th>Home team</th><td id="home_team_name">—</td></tr>
    <tr><th>Away club</th><td id="away_club_name">—</td></tr>
    <tr><th>Away team</th><td id="away_team_name">—</td></tr>
  </table>

  <div class="section">Team names (manual override)</div>
  <table>
    <tr><th>Home name</th><td><input id="in-home-name" type="text" placeholder="—"></td></tr>
    <tr><th>Away name</th><td><input id="in-away-name" type="text" placeholder="—"></td></tr>
  </table>
  <div class="actions">
    <button id="btn-set-names">Apply names</button>
  </div>
  <div class="hint">Type a name to override the scorer app for that side. Leave a
    box blank and Apply to fall back to the app’s name (or “Team ?” until it arrives).</div>

  <div class="section">Live state</div>
  <table>
    <tr><th>Runs</th>        <td id="runs">—</td></tr>
    <tr><th>Wickets</th>     <td id="wkts">—</td></tr>
    <tr><th>Overs</th>       <td id="overs">—</td></tr>
    <tr><th>Chasing</th>     <td id="chasing">—</td></tr>
    <tr><th>Target</th>      <td id="target">—</td></tr>
    <tr><th>Bat 1</th>       <td id="bat1">—</td></tr>
    <tr><th>Bat 2</th>       <td id="bat2">—</td></tr>
    <tr><th>On strike</th>   <td id="on_strike">—</td></tr>
    <tr><th>Last innings</th><td id="last_inn">—</td></tr>
    <tr><th>Total extras</th><td id="total_extras">—</td></tr>
  </table>

  <div class="section">Result</div>
  <table>
    <tr><th>Description</th><td id="result_description">—</td></tr>
    <tr><th>Innings 1</th>  <td id="inn1">—</td></tr>
    <tr><th>Innings 2</th>  <td id="inn2">—</td></tr>
  </table>
  <div class="actions">
    <button id="btn-finish">Match finished</button>
    <button id="btn-reopen">Re-open match</button>
  </div>

  <div class="section">Interval</div>
  <div class="actions">
    <button id="btn-innings-finished">Innings finished</button>
  </div>

  <div class="section">Display control</div>
  <div class="actions">
    <button id="btn-blank">Blank scoreboard</button>
    <button id="btn-clear" class="danger">Clear / reset to logo</button>
  </div>

</div>

<div class="tab-panel hidden" id="tab-admin">

  <div class="section">Connection</div>
  <div class="actions">
    <button id="btn-reset-bt" class="danger">Reset Bluetooth</button>
    <button id="btn-forget-bt" class="danger">Forget paired devices</button>
  </div>

  <div class="section">Internal</div>
  <table>
    <tr><th>Generation</th><td id="generation">—</td></tr>
  </table>

  <div class="section">Diagnostics</div>
  <div class="actions">
    <button id="btn-email-logs">Email match logs</button>
  </div>

  <div class="section">Build</div>
  <table>
    <tr><th>Build commit</th>   <td id="build_commit">—</td></tr>
    <tr><th>HEAD commit</th>    <td id="head_commit">—</td></tr>
    <tr><th>HEAD subject</th>   <td id="head_subject">—</td></tr>
    <tr><th>Latest on GitHub</th><td id="remote_commit">— (press Check)</td></tr>
    <tr><th>Rollback target</th><td id="prev_commit">—</td></tr>
  </table>
  <div class="actions">
    <button id="btn-check-update">Check for updates</button>
    <button id="btn-update">Update from git</button>
    <button id="btn-rollback" disabled>Roll back</button>
    <button id="btn-reboot" class="danger">Reboot Pi</button>
    <button id="btn-shutdown" class="danger">Shut down Pi</button>
  </div>

</div>

<script>
function fmtInnings(inn) {
  if (!inn || !inn.valid) return '—';
  return `${inn.team_name}  ${inn.runs}/${inn.wkts}  (${inn.overs})`;
}
function fmtBatter(name, score) {
  return name ? `${name} (${score})` : '—';
}
let lastVersion = null;
function showBanner(msg, isError) {
  const b = document.getElementById('action-banner');
  b.textContent = msg;
  b.classList.remove('hidden');
  b.classList.toggle('error', !!isError);
}
async function fetchJson(url, opts) {
  const r = await fetch(url, Object.assign({ cache: 'no-store' }, opts || {}));
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
async function refresh() {
  const updated = document.getElementById('updated');
  try {
    const [s, v] = await Promise.all([fetchJson('/api/state'), fetchJson('/api/version')]);
    lastVersion = v;

    const ph = document.getElementById('phase');
    ph.className = 'phase phase-' + s.phase;
    ph.textContent = s.phase;

    const set = (id, val) => document.getElementById(id).textContent = (val ?? '—');
    set('home_club_name', s.home_club_name);
    set('home_team_name', s.home_team_name);
    set('away_club_name', s.away_club_name);
    set('away_team_name', s.away_team_name);

    // Show the live names as placeholders so the operator sees what's on the
    // wall without overwriting anything they're typing into the boxes.
    document.getElementById('in-home-name').placeholder = s.home_team_name || '—';
    document.getElementById('in-away-name').placeholder = s.away_team_name || '—';

    set('runs', s.runs);
    set('wkts', s.wkts);
    set('overs', s.overs || '—');
    set('chasing', s.chasing ? 'yes' : 'no');
    set('target', s.target || '—');
    document.getElementById('bat1').textContent = fmtBatter(s.bat1_name, s.bat1_score);
    document.getElementById('bat2').textContent = fmtBatter(s.bat2_name, s.bat2_score);
    set('on_strike', s.on_strike);
    document.getElementById('last_inn').textContent =
      (s.last_inn_runs || s.last_inn_wkts) ? `${s.last_inn_runs}/${s.last_inn_wkts}` : '—';
    set('total_extras', s.total_extras);

    set('result_description', s.result_description || '—');
    document.getElementById('inn1').textContent = fmtInnings(s.inn1);
    document.getElementById('inn2').textContent = fmtInnings(s.inn2);

    set('generation', s.generation);

    set('build_commit', v.build_commit);
    const headEl = document.getElementById('head_commit');
    const match = v.build_commit === v.head_commit;
    headEl.innerHTML = `${v.head_commit} <span class="${match ? 'build-match' : 'build-mismatch'}">` +
                      `${match ? '✓ matches build' : '⚠ source ahead of build'}</span>`;
    set('head_subject', v.head_subject || '—');
    set('prev_commit',  v.prev_commit  || '—');
    document.getElementById('btn-rollback').disabled = !v.has_rollback;

    updated.textContent = 'Updated ' + new Date().toLocaleTimeString();
    updated.classList.remove('stale');
  } catch (err) {
    updated.textContent = 'Error: ' + err.message;
    updated.classList.add('stale');
  }
}

document.getElementById('btn-check-update').addEventListener('click', async () => {
  const btn  = document.getElementById('btn-check-update');
  const cell = document.getElementById('remote_commit');
  const orig = btn.textContent;
  btn.disabled = true; btn.textContent = 'Checking…';
  try {
    const r = await fetch('/api/check-update', { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) {
      showBanner('Update check failed: ' + (d && d.error ? d.error : `HTTP ${r.status}`), true);
      cell.textContent = 'check failed';
    } else if (d.up_to_date) {
      showBanner('Up to date — origin/main = ' + d.remote_commit + '.');
      cell.textContent = d.remote_commit + ' ';
      const span = document.createElement('span');
      span.className = 'build-match'; span.textContent = '✓ up to date';
      cell.append(span);
    } else {
      const plural = d.behind === 1 ? '' : 's';
      showBanner('Update available: ' + d.remote_commit + ' — ' + d.remote_subject
               + ' (' + d.behind + ' commit' + plural + ' behind). '
               + 'Press "Update from git" to install.');
      // Build with DOM nodes (not innerHTML) so a commit subject can't inject markup.
      cell.textContent = d.remote_commit + ' — ' + d.remote_subject + ' ';
      const span = document.createElement('span');
      span.className = 'build-mismatch'; span.textContent = '▲ ' + d.behind + ' behind';
      cell.append(span);
    }
  } catch (err) {
    showBanner('Update check failed: ' + err.message, true);
    cell.textContent = 'check failed';
  } finally {
    btn.disabled = false; btn.textContent = orig;
  }
});

document.getElementById('btn-update').addEventListener('click', async () => {
  const v = lastVersion;
  const msg = v
    ? `Pull latest from GitHub, rebuild, and restart?\n\nCurrent build: ${v.build_commit}\nCurrent HEAD: ${v.head_commit}`
    : `Pull latest from GitHub, rebuild, and restart?`;
  if (!confirm(msg)) return;
  try {
    const r = await fetch('/api/update', { method: 'POST' });
    if (r.status === 202) {
      showBanner('Update started. The scoreboard will restart in ~30 s. Page will reconnect.');
    } else {
      showBanner(`Update request failed (HTTP ${r.status}).`, true);
    }
  } catch (err) {
    showBanner('Update request failed: ' + err.message, true);
  }
});

document.getElementById('btn-rollback').addEventListener('click', async () => {
  const v = lastVersion;
  if (!v || !v.has_rollback) return;
  if (!confirm(`Revert to ${v.prev_commit} and restart?`)) return;
  try {
    const r = await fetch('/api/rollback', { method: 'POST' });
    if (r.status === 202) {
      showBanner('Rollback started. Page will reconnect shortly.');
    } else {
      showBanner(`Rollback request failed (HTTP ${r.status}).`, true);
    }
  } catch (err) {
    showBanner('Rollback request failed: ' + err.message, true);
  }
});

document.getElementById('btn-shutdown').addEventListener('click', async () => {
  if (!confirm('Shut down the Pi?\n\nThe scoreboard will stop and the LED wall will go dark. '
             + 'Power-cycle the Pi to bring it back.')) return;
  try {
    const r = await fetch('/api/shutdown', { method: 'POST' });
    if (r.status === 202) {
      showBanner('Shutdown started. The LED wall will go dark in ~10 s. '
               + 'A session report email will be sent before power-off.');
    } else {
      showBanner(`Shutdown request failed (HTTP ${r.status}).`, true);
    }
  } catch (err) {
    showBanner('Shutdown request failed: ' + err.message, true);
  }
});

document.getElementById('btn-reboot').addEventListener('click', async () => {
  if (!confirm('Reboot the Pi?\n\nThe scoreboard will stop and the LED wall '
             + 'will go dark for ~30-60 s while the Pi restarts, then come '
             + 'back automatically.')) return;
  try {
    const r = await fetch('/api/reboot', { method: 'POST' });
    if (r.status === 202) {
      showBanner('Reboot started. The LED wall will go dark shortly and the '
               + 'scoreboard will return automatically after the Pi restarts.');
    } else {
      showBanner(`Reboot request failed (HTTP ${r.status}).`, true);
    }
  } catch (err) {
    showBanner('Reboot request failed: ' + err.message, true);
  }
});

document.getElementById('btn-finish').addEventListener('click', async () => {
  if (!confirm('Mark the match as finished and show the winner splash?\n\n'
             + 'The result line is computed from the score. Use "Re-open match" to undo.')) return;
  try {
    const r = await fetch('/api/finish', { method: 'POST' });
    if (r.ok) {
      const j = await r.json().catch(() => ({}));
      showBanner('Match finished. ' + (j.result_description || 'Winner splash shown.'));
    } else {
      showBanner(`Match-finish request failed (HTTP ${r.status}).`, true);
    }
  } catch (err) {
    showBanner('Match-finish request failed: ' + err.message, true);
  }
});

document.getElementById('btn-innings-finished').addEventListener('click', async () => {
  if (!confirm('Show the innings summary on the wall?\n\n'
             + 'Press this once the first innings has finished, before the next '
             + 'innings starts. The wall shows the total, extras, wickets and the '
             + 'two top scorers. It clears automatically when the next innings '
             + 'starts scoring, or press "Blank scoreboard" to clear it now.')) return;
  try {
    const r = await fetch('/api/innings-finished', { method: 'POST' });
    if (r.ok) {
      showBanner('Innings summary shown on the wall.');
    } else {
      showBanner(`Innings-finished request failed (HTTP ${r.status}).`, true);
    }
  } catch (err) {
    showBanner('Innings-finished request failed: ' + err.message, true);
  }
});

document.getElementById('btn-reopen').addEventListener('click', async () => {
  if (!confirm('Re-open the match and return to the live scoreboard?')) return;
  try {
    const r = await fetch('/api/reopen', { method: 'POST' });
    if (r.ok) {
      showBanner('Match re-opened. Back to the live scoreboard.');
    } else {
      showBanner(`Re-open request failed (HTTP ${r.status}).`, true);
    }
  } catch (err) {
    showBanner('Re-open request failed: ' + err.message, true);
  }
});

document.getElementById('btn-blank').addEventListener('click', async () => {
  if (!confirm('Show a blank 0/0 scoreboard (no batter names)?\n\n'
             + 'Use this at the start of a match, before Play Cricket has sent '
             + 'the score. The board fills in live as data arrives.')) return;
  try {
    const r = await fetch('/api/blank', { method: 'POST' });
    if (r.ok) {
      showBanner('Blank scoreboard shown. Waiting for live data.');
    } else {
      showBanner(`Blank-scoreboard request failed (HTTP ${r.status}).`, true);
    }
  } catch (err) {
    showBanner('Blank-scoreboard request failed: ' + err.message, true);
  }
});

document.getElementById('btn-clear').addEventListener('click', async () => {
  if (!confirm('Clear the game and return to the logo?\n\n'
             + 'This wipes the current match so a new game can start. Use it to '
             + 'remove a frozen score after the Bluetooth link drops, or to '
             + 'abandon a test match before a real one.')) return;
  try {
    const r = await fetch('/api/clear', { method: 'POST' });
    if (r.ok) {
      showBanner('Game cleared. Wall is back on the logo, ready for a new match.');
    } else {
      showBanner(`Clear request failed (HTTP ${r.status}).`, true);
    }
  } catch (err) {
    showBanner('Clear request failed: ' + err.message, true);
  }
});

document.getElementById('btn-set-names').addEventListener('click', async () => {
  const home = document.getElementById('in-home-name').value.trim();
  const away = document.getElementById('in-away-name').value.trim();
  try {
    const r = await fetch('/api/team-names', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ home_team_name: home, away_team_name: away }),
    });
    if (r.ok) {
      const j = await r.json().catch(() => ({}));
      const h = j.home_team_name || '—', a = j.away_team_name || '—';
      showBanner(`Team names applied — home: ${h}, away: ${a}. ` +
                 `Blank a box and Apply to revert to the app’s name.`);
    } else {
      showBanner(`Set-names request failed (HTTP ${r.status}).`, true);
    }
  } catch (err) {
    showBanner('Set-names request failed: ' + err.message, true);
  }
});

document.getElementById('btn-reset-bt').addEventListener('click', async () => {
  if (!confirm('Reset the Bluetooth connection?\n\n'
             + 'Use this if the phone can no longer connect and the scoreboard '
             + 'has stopped receiving data. The Bluetooth stack and the data '
             + 'bridge restart (~10 s) while the LED wall keeps running. Any '
             + 'in-progress score clears and rebuilds when the phone reconnects.')) return;
  try {
    const r = await fetch('/api/reset-bt', { method: 'POST' });
    if (r.status === 202) {
      showBanner('Bluetooth reset started. The phone should be able to connect '
               + 'again in ~10 s. Re-open the scorer app’s external-scoreboard '
               + 'connection if it doesn’t reconnect on its own.');
    } else {
      showBanner(`Bluetooth-reset request failed (HTTP ${r.status}).`, true);
    }
  } catch (err) {
    showBanner('Bluetooth-reset request failed: ' + err.message, true);
  }
});

document.getElementById('btn-forget-bt').addEventListener('click', async () => {
  if (!confirm('Forget all paired phones/tablets on the scoreboard?\n\n'
             + 'Use this if a device says it is connected but no score shows, or '
             + 'it can see the scoreboard but will not connect (a stale pairing). '
             + 'This clears the scoreboard side only and disconnects any device.\n\n'
             + 'IMPORTANT: you must ALSO "Forget" the scoreboard in the phone/'
             + 'tablet Bluetooth settings, then pair again — clearing one side '
             + 'alone leaves a mismatch.')) return;
  try {
    const r = await fetch('/api/forget-bt', { method: 'POST' });
    if (r.status === 202) {
      showBanner('Scoreboard-side pairings cleared. Now "Forget" the scoreboard '
               + 'on the phone/tablet and pair again, then re-open the scorer '
               + 'app’s external-scoreboard connection.');
    } else {
      showBanner(`Forget-devices request failed (HTTP ${r.status}).`, true);
    }
  } catch (err) {
    showBanner('Forget-devices request failed: ' + err.message, true);
  }
});

document.getElementById('btn-email-logs').addEventListener('click', async () => {
  try {
    const r = await fetch('/api/email-logs', { method: 'POST' });
    if (r.status === 202) {
      showBanner('Log email requested. The discovery log should arrive by email '
               + 'within a minute or two. If nothing arrives, the mailer '
               + 'credentials may not be set up on the Pi.');
    } else {
      showBanner(`Email-logs request failed (HTTP ${r.status}).`, true);
    }
  } catch (err) {
    showBanner('Email-logs request failed: ' + err.message, true);
  }
});

document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
  t.classList.add('active');
  document.getElementById('tab-' + t.dataset.tab).classList.remove('hidden');
}));

refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
)HTML";

}  // namespace

DebugServer::DebugServer(const SharedMatchState* state,
                         std::string password,
                         int port,
                         std::string repo_dir,
                         std::string scripts_dir,
                         std::string bridge_base_url)
    : state_(state),
      password_(std::move(password)),
      port_(port),
      repo_dir_(std::move(repo_dir)),
      scripts_dir_(std::move(scripts_dir)),
      bridge_base_url_(std::move(bridge_base_url)),
      server_(std::make_unique<httplib::Server>()) {

    // Avoid SIGCHLD becoming a zombie collector problem when the update
    // script eventually exits without us wait()ing on it.
    ::signal(SIGCHLD, SIG_IGN);

    const std::string expected = "admin:" + password_;

    // Pre-routing handler: enforced before every endpoint.
    server_->set_pre_routing_handler(
        [this, expected](const httplib::Request& req, httplib::Response& res) {
            const std::string auth = req.get_header_value("Authorization");
            const std::string prefix = "Basic ";
            if (auth.size() <= prefix.size() ||
                auth.compare(0, prefix.size(), prefix) != 0) {
                res.set_header("WWW-Authenticate", "Basic realm=\"raspscoreboard\"");
                res.status = 401;
                res.set_content("auth required\n", "text/plain");
                return httplib::Server::HandlerResponse::Handled;
            }
            const std::string decoded = Base64Decode(auth.substr(prefix.size()));
            if (!ConstantTimeEq(decoded, expected)) {
                res.set_header("WWW-Authenticate", "Basic realm=\"raspscoreboard\"");
                res.status = 401;
                res.set_content("auth required\n", "text/plain");
                return httplib::Server::HandlerResponse::Handled;
            }
            return httplib::Server::HandlerResponse::Unhandled;
        });

    server_->Get("/", [](const httplib::Request&, httplib::Response& res) {
        res.set_content(kIndexHtml, "text/html; charset=utf-8");
    });

    server_->Get("/api/state", [this](const httplib::Request&, httplib::Response& res) {
        const MatchState s = state_->snapshot();
        res.set_content(StateToJson(s).dump(), "application/json");
    });

    server_->Get("/api/version", [this](const httplib::Request&, httplib::Response& res) {
        const std::string head_commit  = RunGitCapture(repo_dir_, "rev-parse --short HEAD");
        const std::string head_subject = RunGitCapture(repo_dir_, "log -1 --pretty=%s");
        const std::string prev_commit  = ReadFirstLine(kPrevCommitPath);
        const bool        has_rollback = FileExists(kPrevBinaryPath) && !prev_commit.empty();
        const json out = {
            {"build_commit", BUILD_GIT_HASH},
            {"head_commit",  head_commit.empty()  ? "unknown" : head_commit},
            {"head_subject", head_subject},
            {"prev_commit",  prev_commit},
            {"has_rollback", has_rollback},
        };
        res.set_content(out.dump(), "application/json");
    });

    // Read-only "is there a newer build on GitHub?" check. Fetches the remote
    // and compares the Pi's HEAD to origin/main, WITHOUT pulling. The operator
    // then presses "Update from git" to actually install.
    server_->Post("/api/check-update", [this](const httplib::Request&, httplib::Response& res) {
        // `git fetch` spawns git-remote-https and waitpid()s on it internally.
        // Under the server's SIGCHLD=SIG_IGN that returns ECHILD and the fetch
        // fails — the same root cause as the historical update.sh bug. Reset
        // SIGCHLD to default for the duration of these git calls, then restore
        // SIG_IGN (which on Linux also reaps any child that exited meanwhile, so
        // no zombies leak).
        struct SigchldGuard {
            SigchldGuard()  { ::signal(SIGCHLD, SIG_DFL); }
            ~SigchldGuard() { ::signal(SIGCHLD, SIG_IGN); }
        } sigchld_guard;

        // Bounded transfer time so an unreachable GitHub can't hang the thread
        // mid-transfer. Output is discarded (RunGitCapture appends 2>/dev/null).
        RunGitCapture(repo_dir_,
            "-c http.lowSpeedLimit=1000 -c http.lowSpeedTime=10 fetch --quiet origin");

        const std::string remote_commit = RunGitCapture(repo_dir_, "rev-parse --short origin/main");
        if (remote_commit.empty()) {
            res.status = 502;
            res.set_content("{\"ok\":false,\"error\":\"could not reach GitHub\"}",
                            "application/json");
            return;
        }
        const std::string behind_str     = RunGitCapture(repo_dir_, "rev-list --count HEAD..origin/main");
        const std::string remote_subject = RunGitCapture(repo_dir_, "log -1 --pretty=%s origin/main");
        int behind = 0;
        try { if (!behind_str.empty()) behind = std::stoi(behind_str); } catch (...) {}
        const json out = {
            {"ok",             true},
            {"behind",         behind},
            {"up_to_date",     behind == 0},
            {"remote_commit",  remote_commit},
            {"remote_subject", remote_subject},
        };
        res.set_content(out.dump(), "application/json");
    });

    server_->Post("/api/update", [this](const httplib::Request&, httplib::Response& res) {
        const std::string script = scripts_dir_ + "/update.sh";
        std::fprintf(stderr, "POST /api/update → spawning %s\n", script.c_str());
        if (!SpawnDetachedScript(script)) {
            res.status = 500;
            res.set_content("{\"error\":\"fork failed\"}", "application/json");
            return;
        }
        res.status = 202;
        res.set_content("{\"started\":true}", "application/json");
    });

    server_->Post("/api/rollback", [this](const httplib::Request&, httplib::Response& res) {
        if (!FileExists(kPrevBinaryPath)) {
            res.status = 409;
            res.set_content("{\"error\":\"no rollback target available\"}", "application/json");
            return;
        }
        const std::string script = scripts_dir_ + "/rollback.sh";
        std::fprintf(stderr, "POST /api/rollback → spawning %s\n", script.c_str());
        if (!SpawnDetachedScript(script)) {
            res.status = 500;
            res.set_content("{\"error\":\"fork failed\"}", "application/json");
            return;
        }
        res.status = 202;
        res.set_content("{\"started\":true}", "application/json");
    });

    server_->Post("/api/shutdown", [this](const httplib::Request&, httplib::Response& res) {
        const std::string script = scripts_dir_ + "/shutdown_pi.sh";
        std::fprintf(stderr, "POST /api/shutdown → spawning %s\n", script.c_str());
        if (!SpawnDetachedScript(script)) {
            res.status = 500;
            res.set_content("{\"error\":\"fork failed\"}", "application/json");
            return;
        }
        res.status = 202;
        res.set_content("{\"started\":true}", "application/json");
    });

    server_->Post("/api/reboot", [this](const httplib::Request&, httplib::Response& res) {
        const std::string script = scripts_dir_ + "/reboot_pi.sh";
        std::fprintf(stderr, "POST /api/reboot → spawning %s\n", script.c_str());
        if (!SpawnDetachedScript(script)) {
            res.status = 500;
            res.set_content("{\"error\":\"fork failed\"}", "application/json");
            return;
        }
        res.status = 202;
        res.set_content("{\"started\":true}", "application/json");
    });

    server_->Post("/api/reset-bt", [this](const httplib::Request&, httplib::Response& res) {
        const std::string script = scripts_dir_ + "/reset_bluetooth.sh";
        std::fprintf(stderr, "POST /api/reset-bt → spawning %s\n", script.c_str());
        if (!SpawnDetachedScript(script)) {
            res.status = 500;
            res.set_content("{\"error\":\"fork failed\"}", "application/json");
            return;
        }
        res.status = 202;
        res.set_content("{\"started\":true}", "application/json");
    });

    server_->Post("/api/forget-bt", [this](const httplib::Request&, httplib::Response& res) {
        const std::string script = scripts_dir_ + "/forget_bluetooth.sh";
        std::fprintf(stderr, "POST /api/forget-bt → spawning %s\n", script.c_str());
        if (!SpawnDetachedScript(script)) {
            res.status = 500;
            res.set_content("{\"error\":\"fork failed\"}", "application/json");
            return;
        }
        res.status = 202;
        res.set_content("{\"started\":true}", "application/json");
    });

    // Email the BLE bridge's logs (discovery.log + today/latest match logs)
    // off the Pi. Detached like the other admin scripts; the actual SMTP send
    // happens asynchronously, so the inbox is the real confirmation. Reuses the
    // shutdown mailer's encrypted credential (CREDENTIALS_DIRECTORY is set for
    // the whole unit and inherited by the spawned child).
    server_->Post("/api/email-logs", [this](const httplib::Request&, httplib::Response& res) {
        const std::string script = scripts_dir_ + "/mail_logs.sh";
        std::fprintf(stderr, "POST /api/email-logs → spawning %s\n", script.c_str());
        if (!SpawnDetachedScript(script)) {
            res.status = 500;
            res.set_content("{\"error\":\"fork failed\"}", "application/json");
            return;
        }
        res.status = 202;
        res.set_content("{\"started\":true}", "application/json");
    });

    // Match-finish / reopen: proxy to the BLE bridge, which owns the result
    // state. We can't write it into our own SharedMatchState — the next poll
    // would clobber it — so the source of truth must be the bridge.
    auto proxy_to_bridge = [this](const char* path, httplib::Response& res) {
        if (bridge_base_url_.empty()) {
            res.status = 503;
            res.set_content("{\"error\":\"bridge url not configured\"}", "application/json");
            return;
        }
        httplib::Client cli(bridge_base_url_);
        cli.set_connection_timeout(3, 0);
        cli.set_read_timeout(3, 0);
        auto up = cli.Post(path, "", "application/json");
        if (!up) {
            std::fprintf(stderr, "proxy %s -> bridge failed: no response\n", path);
            res.status = 502;
            res.set_content("{\"error\":\"bridge unreachable\"}", "application/json");
            return;
        }
        res.status = up->status;
        res.set_content(up->body, "application/json");
    };

    server_->Post("/api/finish", [this, proxy_to_bridge](const httplib::Request&, httplib::Response& res) {
        std::fprintf(stderr, "POST /api/finish -> bridge /api/admin/finish\n");
        proxy_to_bridge("/api/admin/finish", res);
    });

    server_->Post("/api/reopen", [this, proxy_to_bridge](const httplib::Request&, httplib::Response& res) {
        std::fprintf(stderr, "POST /api/reopen -> bridge /api/admin/reopen\n");
        proxy_to_bridge("/api/admin/reopen", res);
    });

    server_->Post("/api/innings-finished", [this, proxy_to_bridge](const httplib::Request&, httplib::Response& res) {
        std::fprintf(stderr, "POST /api/innings-finished -> bridge /api/admin/innings-finished\n");
        proxy_to_bridge("/api/admin/innings-finished", res);
    });

    server_->Post("/api/blank", [this, proxy_to_bridge](const httplib::Request&, httplib::Response& res) {
        std::fprintf(stderr, "POST /api/blank -> bridge /api/admin/blank\n");
        proxy_to_bridge("/api/admin/blank", res);
    });

    server_->Post("/api/clear", [this, proxy_to_bridge](const httplib::Request&, httplib::Response& res) {
        std::fprintf(stderr, "POST /api/clear -> bridge /api/admin/reset\n");
        proxy_to_bridge("/api/admin/reset", res);
    });

    // Like proxy_to_bridge, but forwards the request body so the operator's
    // typed team names reach the bridge (the names live there — see /api/state).
    server_->Post("/api/team-names", [this](const httplib::Request& req, httplib::Response& res) {
        std::fprintf(stderr, "POST /api/team-names -> bridge /api/admin/team-names\n");
        if (bridge_base_url_.empty()) {
            res.status = 503;
            res.set_content("{\"error\":\"bridge url not configured\"}", "application/json");
            return;
        }
        httplib::Client cli(bridge_base_url_);
        cli.set_connection_timeout(3, 0);
        cli.set_read_timeout(3, 0);
        auto up = cli.Post("/api/admin/team-names", req.body, "application/json");
        if (!up) {
            std::fprintf(stderr, "proxy /api/team-names -> bridge failed: no response\n");
            res.status = 502;
            res.set_content("{\"error\":\"bridge unreachable\"}", "application/json");
            return;
        }
        res.status = up->status;
        res.set_content(up->body, "application/json");
    });

    (void)kStateDir;  // currently only used by the scripts via env var
}

DebugServer::~DebugServer() {
    stop();
}

void DebugServer::start() {
    if (started_.exchange(true)) return;
    thread_ = std::thread([this]{ run(); });
}

void DebugServer::stop() {
    if (server_) server_->stop();
    if (thread_.joinable()) thread_.join();
}

void DebugServer::run() {
    std::fprintf(stderr, "Debug server listening on 0.0.0.0:%d\n", port_);
    if (!server_->listen("0.0.0.0", port_)) {
        std::fprintf(stderr,
                     "Debug server failed to bind 0.0.0.0:%d "
                     "(port in use? permission?).\n", port_);
    }
}

}  // namespace cricketboard
