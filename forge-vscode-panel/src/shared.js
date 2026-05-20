'use strict';
// Shared utilities imported by both forge-vscode-panel and regulatory-tools-vscode-panel.
// Changes here automatically apply to both panels.

const vscode = require('vscode');
const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');

// ── Constants ──────────────────────────────────────────────────────────────────

const GRADE_COLOR = { A: '#4EC9B0', B: '#DCDCAA', C: '#CE9178', D: '#F44747', F: '#F44747' };

const COLLECTORS = [
  {
    key: 'test_metrics', label: 'Tests', icon: '🧪',
    detail: r => r && !r.skipped
      ? `${pct(r.pass_rate)} pass · ${Math.round(r.line_coverage ?? 0)}% cov`
      : skipReason(r),
  },
  {
    key: 'complexity', label: 'Complexity', icon: '🔀',
    detail: r => r && !r.skipped
      ? `MI ${Math.round(r.maintainability_index ?? 0)} · CC ${(r.avg_cyclomatic ?? 0).toFixed(1)}`
      : skipReason(r),
  },
  {
    key: 'dependency_health', label: 'Dependencies', icon: '📦',
    detail: r => r && !r.skipped
      ? `${r.vulnerable_packages ?? 0} vuln / ${r.total_packages ?? 0} pkgs`
      : skipReason(r),
  },
  {
    key: 'requirements_coverage', label: 'Req Coverage', icon: '📋',
    detail: r => r && !r.skipped
      ? `${r.covered_requirements ?? 0} / ${r.total_requirements ?? 0} reqs`
      : skipReason(r),
  },
  {
    key: 'static_analysis', label: 'Linting', icon: '🔍',
    detail: r => r && !r.skipped
      ? `${r.total_errors ?? 0} errors · density ${(r.error_density ?? 0).toFixed(2)}/kloc`
      : skipReason(r),
  },
  {
    key: 'type_coverage', label: 'Type Check', icon: '🏷️',
    detail: r => r && !r.skipped
      ? `${r.total_errors ?? 0} mypy errors`
      : skipReason(r),
  },
  {
    key: 'dead_code', label: 'Dead Code', icon: '💀',
    detail: r => r && !r.skipped
      ? `${r.unused_items ?? 0} unused · density ${(r.unused_density ?? 0).toFixed(1)}/kloc`
      : skipReason(r),
  },
  {
    key: 'mutation_testing', label: 'Mutation', icon: '🧬',
    detail: r => r && !r.skipped
      ? `${pct(r.mutation_score)} killed`
      : skipReason(r),
  },
];

// ── Pure utilities ─────────────────────────────────────────────────────────────

function pct(v) { return `${Math.round((v ?? 0) * 100)}%`; }
function skipReason(r) { return r?.skip_reason ? `(${r.skip_reason.split(';')[0].slice(0, 40)})` : '—'; }

function execCmd(cmd) {
  return new Promise((resolve, reject) => {
    exec(cmd, { maxBuffer: 20 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err) reject(new Error(stderr || stdout || err.message));
      else resolve(stdout);
    });
  });
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function inlineMd(text) {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, t, u) =>
      `<a href="#" data-url="${u.replace(/"/g, '&quot;')}">${t}</a>`)
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

// ── Config resolution ──────────────────────────────────────────────────────────

function resolveForge() {
  const setting = vscode.workspace.getConfiguration('forge').get('forgePath', '');
  if (setting && fs.existsSync(setting)) return setting;

  const home = process.env.HOME ?? process.env.USERPROFILE ?? '';
  const candidates = [
    path.join(home, 'miniconda3/envs/medimg-coronary-v1/bin/forge'),
    path.join(home, 'opt/miniconda3/envs/medimg-coronary-v1/bin/forge'),
    path.join(home, 'anaconda3/envs/medimg-coronary-v1/bin/forge'),
    '/usr/local/bin/forge',
    '/opt/homebrew/bin/forge',
  ];
  for (const c of candidates) if (fs.existsSync(c)) return c;
  return 'forge';
}

// Returns { python, envName, source: 'setting'|'env_yml'|null }
function resolveProjectPython(repoName, localPath) {
  const overrides = vscode.workspace.getConfiguration('forge').get('repoPythonPaths', {});
  if (overrides[repoName]) {
    const p = overrides[repoName];
    if (fs.existsSync(p)) return { python: p, envName: repoName, source: 'setting' };
  }

  const envYml = path.join(localPath, 'environment.yml');
  if (!fs.existsSync(envYml)) return { python: null, envName: null, source: null };

  const nameMatch = fs.readFileSync(envYml, 'utf8').match(/^name:\s*(.+)$/m);
  if (!nameMatch) return { python: null, envName: null, source: null };

  const envName = nameMatch[1].trim();
  const home = process.env.HOME ?? process.env.USERPROFILE ?? '';
  const condaRoots = [
    path.join(home, 'miniconda3'),
    path.join(home, 'opt/miniconda3'),
    path.join(home, 'anaconda3'),
    path.join(home, 'opt/anaconda3'),
    '/opt/homebrew/Caskroom/miniconda/base',
    '/opt/miniconda3',
  ];
  for (const root of condaRoots) {
    const pyPath = path.join(root, 'envs', envName, 'bin', 'python');
    if (fs.existsSync(pyPath)) return { python: pyPath, envName, source: 'env_yml' };
  }
  return { python: null, envName, source: 'env_yml' };
}

// ── Async data helpers ─────────────────────────────────────────────────────────

function discoverCondaEnvs() {
  return new Promise(resolve => {
    exec('conda env list --json', { timeout: 10000 }, (err, stdout) => {
      if (err) { resolve([]); return; }
      try {
        const data = JSON.parse(stdout);
        const rootPrefix = data.root_prefix ?? '';
        const envs = (data.envs ?? []).map(envPath => {
          const python = path.join(envPath, 'bin', 'python');
          if (!fs.existsSync(python)) return null;
          const name = envPath === rootPrefix ? 'base' : path.basename(envPath);
          return { name, python };
        }).filter(Boolean);
        resolve(envs);
      } catch { resolve([]); }
    });
  });
}

async function gatherRepoMeta(codeRepos) {
  const results = await Promise.all(codeRepos.map(async repo => {
    const base = { name: repo.name, branch: null, aheadMain: null, behindMain: null,
                   prs: [], ciPassed: null, ciTotal: null };
    try {
      const p = repo.local_path;

      const statusOut = await execCmd(
        `git -C "${p}" status --porcelain=v2 --branch 2>/dev/null || echo ''`
      );
      for (const line of statusOut.split('\n')) {
        const headM = line.match(/^# branch\.head (.+)$/);
        if (headM && headM[1] !== '(detached)') base.branch = headM[1];
      }

      const abOut = await execCmd(
        `git -C "${p}" rev-list --left-right --count origin/main...HEAD 2>/dev/null || echo ''`
      );
      const abM = abOut.trim().match(/^(\d+)\t(\d+)$/);
      if (abM) { base.behindMain = +abM[1]; base.aheadMain = +abM[2]; }

      const remoteOut = await execCmd(
        `git -C "${p}" remote get-url origin 2>/dev/null || echo ''`
      );
      const slugM = remoteOut.trim().match(/github\.com[:/](.+?\/.+?)(?:\.git)?\s*$/);
      const slug = slugM?.[1] ?? null;

      if (slug && base.branch) {
        const owner = slug.split('/')[0];
        await execCmd(`gh api "repos/${slug}/pulls?state=open&head=${owner}:${base.branch}&per_page=10"`)
          .then(out => {
            const items = JSON.parse(out) ?? [];
            base.prs = items.map(pr => ({ number: pr.number, url: pr.html_url }));
          }).catch(() => {});
        await execCmd(`gh api "repos/${slug}/commits/${base.branch}/check-runs"`)
          .then(out => {
            const runs = JSON.parse(out)?.check_runs ?? [];
            if (runs.length) {
              base.ciTotal = runs.length;
              base.ciPassed = runs.filter(r => r.conclusion === 'success').length;
            }
          }).catch(() => {});
        if (base.ciTotal === null) {
          await execCmd(`gh api "repos/${slug}/actions/runs?branch=${base.branch}&per_page=1"`)
            .then(out => {
              const run = JSON.parse(out)?.workflow_runs?.[0];
              if (run) {
                base.ciTotal = 1;
                base.ciPassed = run.conclusion === 'success' ? 1 : 0;
              }
            }).catch(() => {});
        }
      }
    } catch {}
    return base;
  }));

  return Object.fromEntries(results.map(r => [r.name, r]));
}

// ── HTML builders ─────────────────────────────────────────────────────────────

function buildRepoOverview(metaMap, healthMap, codeRepos) {
  const rows = codeRepos.map(repo => {
    const meta   = metaMap[repo.name] ?? {};
    const health = healthMap[repo.name];
    const grade  = health?.data?.grade ?? (health?.error ? 'ERR' : '?');
    const col    = GRADE_COLOR[grade] ?? '#888';

    const brRaw  = meta.branch ?? '';
    const brText = brRaw ? brRaw.slice(0, 18) + (brRaw.length > 18 ? '…' : '') : '—';

    let syncHtml = '—';
    if (meta.aheadMain !== null && meta.aheadMain !== undefined &&
        meta.behindMain !== null && meta.behindMain !== undefined) {
      syncHtml = escHtml(`↑${meta.aheadMain} ↓${meta.behindMain}`);
    }

    let prHtml = '—';
    if (meta.prs && meta.prs.length) {
      prHtml = meta.prs.map(pr =>
        `<a href="#" data-url="${escHtml(pr.url)}">#${pr.number}</a>`
      ).join(', ');
    }

    let ciHtml = '—';
    if (meta.ciTotal !== null) {
      const cls = meta.ciPassed === meta.ciTotal ? 'ov-pass'
                : meta.ciPassed === 0            ? 'ov-fail' : 'ov-warn';
      ciHtml = `<span class="${cls}">${meta.ciPassed}/${meta.ciTotal}</span>`;
    }

    return `<tr data-repo-path="${escHtml(repo.local_path)}" data-repo-name="${escHtml(repo.name)}">
      <td class="sum-name">${escHtml(repo.name)}</td>
      <td class="sum-grade"><span class="sum-badge" style="background:${col}">${escHtml(grade)}</span></td>
      <td class="ov-br">${escHtml(brText)}</td>
      <td class="ov-sync">${syncHtml}</td>
      <td class="ov-pr">${prHtml}</td>
      <td class="ov-ci">${ciHtml}</td>
    </tr>`;
  }).join('');

  return `<table class="sum-table">
    <thead><tr>
      <th>Repo</th><th>Grade</th><th>Br</th><th>± main</th><th>PR</th><th>CI</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function buildEnvPickerHtml(repoName, pi, condaEnvs) {
  if (!condaEnvs.length) {
    if (pi.python) {
      const label = pi.envName ?? path.basename(path.dirname(pi.python));
      return `<span class="env-tag env-ok" title="${escHtml(pi.python)}">🐍 ${escHtml(label)}</span>`;
    }
    const warnMsg = pi.envName
      ? `⚠ ${escHtml(pi.envName)} not found — tests may use wrong env`
      : '⚠ no environment.yml — using default Python';
    return `<span class="env-tag env-warn">${warnMsg}</span>`;
  }

  const autoLabel = pi.source === 'env_yml' && pi.envName
    ? `auto (${pi.envName})`
    : 'auto-detect';
  let options = `<option value="">${escHtml(autoLabel)}</option>`;
  for (const env of condaEnvs) {
    const sel = (pi.python === env.python) ? ' selected' : '';
    options += `<option value="${escHtml(env.python)}"${sel}>🐍 ${escHtml(env.name)}</option>`;
  }

  const sourceBadge = pi.source === 'setting'
    ? '<span class="src-badge src-set" title="Set via forge.repoPythonPaths">pinned</span>'
    : pi.source === 'env_yml'
      ? '<span class="src-badge src-auto" title="Resolved from environment.yml">env.yml</span>'
      : '<span class="src-badge src-none" title="No environment resolved">none</span>';

  return `<div class="env-row">
    <select class="env-select" data-repo="${escHtml(repoName)}" onchange="onEnvChange(this)">
      ${options}
    </select>
    ${sourceBadge}
  </div>`;
}

function buildHealthCard(name, result, condaEnvs) {
  const pi = result?.pythonInfo ?? { python: null, envName: null, source: null };
  const envPickerHtml = buildEnvPickerHtml(name, pi, condaEnvs);

  if (!result || result.error) {
    const msg = result?.error ?? 'No data';
    return `<div class="health-card err">
      <div class="card-header"><span class="repo-name">${escHtml(name)}</span>
        <span class="grade-badge" style="background:#555;color:#ccc">ERR</span></div>
      ${envPickerHtml}
      <pre class="err-pre">${escHtml(msg.slice(0, 400))}</pre>
    </div>`;
  }

  const d = result.data;
  const grade = d.grade ?? '?';
  const score = d.overall_score ?? 0;
  const col = GRADE_COLOR[grade] ?? '#888';

  const rows = COLLECTORS.map(c => {
    const r = d[c.key];
    const skipped = !r || r.skipped;
    const status = skipped ? '—' : r.score >= 0.7 ? '✓' : '✗';
    const cls = skipped ? 'na' : r.score >= 0.7 ? 'pass' : 'fail';
    const scoreTxt = (!skipped && r.score != null) ? pct(r.score) : '—';
    return `<tr>
      <td class="cl">${c.icon} ${c.label}</td>
      <td class="cs ${cls}">${status}</td>
      <td class="ck">${scoreTxt}</td>
      <td class="cd">${c.detail(r)}</td>
    </tr>`;
  }).join('');

  const pctVal = Math.round(score * 100);
  const barCol = score >= 0.9 ? '#4EC9B0' : score >= 0.7 ? '#DCDCAA' : score >= 0.5 ? '#CE9178' : '#F44747';

  return `<div class="health-card">
    <div class="card-header">
      <span class="repo-name">${escHtml(name)}</span>
      <span class="grade-badge" style="background:${col}">${escHtml(grade)}</span>
    </div>
    ${envPickerHtml}
    <div class="bar-wrap">
      <div class="bar-bg"><div class="bar-fg" style="width:${pctVal}%;background:${barCol}"></div></div>
      <span class="bar-pct">${pctVal}%</span>
    </div>
    <table class="coll-table">${rows}</table>
  </div>`;
}

// ── Page shell ─────────────────────────────────────────────────────────────────

function loadingHtml(msg) {
  return wrapHtml(`<div class="loading">
    <div class="spinner"></div>
    <p>${escHtml(msg)}</p>
  </div>`);
}

function errorHtml(msg) {
  return wrapHtml(`<div class="err-box">
    <div class="err-title">⚠ Error</div>
    <pre class="err-pre">${escHtml(msg)}</pre>
  </div>`);
}

function wrapHtml(body) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy"
  content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--vscode-font-family, -apple-system, sans-serif);
  font-size: var(--vscode-font-size, 12px);
  color: var(--vscode-foreground, #ccc);
  background: var(--vscode-sideBar-background, #1e1e1e);
  padding: 8px;
  line-height: 1.45;
}
a { color: var(--vscode-textLink-foreground, #4ec9b0); text-decoration: none; cursor: pointer; }
a:hover { text-decoration: underline; }
code {
  background: var(--vscode-textCodeBlock-background, #2d2d2d);
  padding: 1px 4px; border-radius: 3px;
  font-family: var(--vscode-editor-font-family, monospace); font-size: 0.9em;
}
strong { font-weight: 600; }

/* Toolbar */
.toolbar {
  display: flex; justify-content: space-between; align-items: center;
  padding-bottom: 8px; margin-bottom: 10px;
  border-bottom: 1px solid var(--vscode-panel-border, #333);
  font-size: 0.82em; color: var(--vscode-descriptionForeground, #888);
}
.cfg { font-family: monospace; }

/* Section */
section { margin-bottom: 14px; }
.section-title {
  font-size: 0.78em; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.09em; color: var(--vscode-descriptionForeground, #888);
  margin-bottom: 7px; padding-bottom: 3px;
  border-bottom: 1px solid var(--vscode-panel-border, #333);
}

/* Workspace overview table */
.tscroll { margin-bottom: 4px; }
.md-table {
  width: 100%; border-collapse: collapse; font-size: 0.82em; table-layout: auto; word-break: break-word;
}
.md-table th, .md-table td {
  padding: 4px 8px;
  border-bottom: 1px solid var(--vscode-panel-border, #2a2a2a);
  text-align: left;
}
.md-table th {
  background: var(--vscode-list-hoverBackground, #252526);
  font-weight: 600; position: sticky; top: 0;
}
.md-table tr:hover td { background: var(--vscode-list-hoverBackground, #2a2a2a); }

/* Health cards */
.health-card {
  background: var(--vscode-editor-background, #1e1e1e);
  border: 1px solid var(--vscode-panel-border, #333);
  border-radius: 5px; margin-bottom: 8px; padding: 10px;
}
.health-card.err { border-color: #F44747; }
.card-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 7px;
}
.repo-name { font-weight: 700; font-size: 0.95em; }
.grade-badge {
  display: inline-flex; align-items: center; justify-content: center;
  width: 26px; height: 26px; border-radius: 50%;
  font-weight: 800; font-size: 0.88em; color: #1a1a1a;
  flex-shrink: 0;
}

/* Env picker row */
.env-row {
  display: flex; align-items: center; gap: 5px;
  margin-bottom: 8px;
}
.env-select {
  flex: 1; min-width: 0;
  background: var(--vscode-dropdown-background, #252526);
  color: var(--vscode-dropdown-foreground, #ccc);
  border: 1px solid var(--vscode-dropdown-border, #3c3c3c);
  border-radius: 3px;
  padding: 2px 4px;
  font-size: 0.82em;
  font-family: inherit;
  cursor: pointer;
  appearance: auto;
}
.env-select:hover { border-color: var(--vscode-focusBorder, #4ec9b0); }
.env-select:focus { outline: 1px solid var(--vscode-focusBorder, #4ec9b0); outline-offset: -1px; }

/* Source badge next to picker */
.src-badge {
  flex-shrink: 0; font-size: 0.72em; padding: 1px 5px; border-radius: 3px;
  font-weight: 600; white-space: nowrap;
}
.src-set  { background: rgba(78,201,176,.18); color: #4EC9B0; }
.src-auto { background: rgba(220,220,170,.12); color: #DCDCAA; }
.src-none { background: rgba(100,100,100,.2);  color: #888; }

/* Fallback env tag (no conda) */
.env-tag {
  display: inline-block; font-size: 0.78em; padding: 1px 6px; border-radius: 3px;
  margin-bottom: 7px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.env-ok   { background: rgba(78,201,176,.12); color: #4EC9B0; }
.env-warn { background: rgba(220,220,170,.12); color: #DCDCAA; }

/* Score bar */
.bar-wrap { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }
.bar-bg { flex: 1; height: 4px; background: var(--vscode-panel-border, #333); border-radius: 2px; overflow: hidden; }
.bar-fg { height: 100%; border-radius: 2px; }
.bar-pct { font-size: 0.8em; color: var(--vscode-descriptionForeground, #888); width: 32px; text-align: right; }

/* Collector table */
.coll-table { width: 100%; border-collapse: collapse; font-size: 0.82em; }
.coll-table td { padding: 2px 3px; vertical-align: top; }
.cl { color: var(--vscode-foreground, #ccc); white-space: nowrap; }
.cs { font-weight: 700; width: 16px; text-align: center; }
.cs.pass { color: #4EC9B0; }
.cs.fail { color: #F44747; }
.cs.na  { color: #555; }
.ck { color: var(--vscode-descriptionForeground, #888); width: 34px; text-align: right; font-variant-numeric: tabular-nums; }
.cd { color: var(--vscode-descriptionForeground, #777); padding-left: 8px; word-break: break-word; }

/* Error pre */
.err-pre { font-size: 0.8em; white-space: pre-wrap; word-break: break-word; margin-top: 6px; }

/* Issues */
.issue-group { margin-bottom: 10px; }
.issue-repo { font-weight: 600; font-size: 0.85em; margin-bottom: 4px; }
.issue {
  display: flex; gap: 6px; align-items: flex-start;
  padding: 3px 7px; border-radius: 3px; margin-bottom: 3px; font-size: 0.82em;
}
.issue.crit { background: rgba(244,71,71,.15); border-left: 3px solid #F44747; }
.issue.warn { background: rgba(220,220,170,.12); border-left: 3px solid #DCDCAA; }
.issue.info { background: rgba(78,201,176,.09); border-left: 3px solid #4EC9B0; }
.sev { font-weight: 700; font-size: 0.8em; opacity: .85; white-space: nowrap; padding-top: 1px; }

/* Error box */
.err-box {
  background: rgba(244,71,71,.1); border: 1px solid #F44747;
  border-radius: 5px; padding: 12px; margin: 8px 0;
}
.err-title { color: #F44747; font-weight: 700; margin-bottom: 8px; }

/* Loading */
.loading { text-align: center; padding: 40px 20px; color: var(--vscode-descriptionForeground, #888); }
@keyframes spin { to { transform: rotate(360deg); } }
.spinner {
  width: 22px; height: 22px; margin: 0 auto 12px;
  border: 2px solid var(--vscode-panel-border, #333);
  border-top-color: var(--vscode-textLink-foreground, #4ec9b0);
  border-radius: 50%; animation: spin .7s linear infinite;
}

.muted { color: var(--vscode-descriptionForeground, #888); font-size: 0.85em; }

/* Repository overview table */
.sum-table {
  width: 100%; border-collapse: collapse; font-size: 0.82em; table-layout: auto;
}
.sum-table th, .sum-table td {
  padding: 3px 6px;
  border-bottom: 1px solid var(--vscode-panel-border, #2a2a2a);
  text-align: left;
}
.sum-table th {
  background: var(--vscode-list-hoverBackground, #252526);
  font-weight: 600;
}
.sum-table tr:hover td { background: var(--vscode-list-hoverBackground, #2a2a2a); }
.sum-name  { font-weight: 600; white-space: nowrap; }
.sum-grade { text-align: center; width: 44px; }
.sum-badge {
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: 50%;
  font-weight: 800; font-size: 0.8em; color: #1a1a1a;
}
.ov-br   { white-space: nowrap; font-family: monospace; font-size: 0.85em; }
.ov-sync { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; width: 52px; }
.ov-pr   { text-align: center; width: 40px; }
.ov-ci   { text-align: right; font-variant-numeric: tabular-nums; width: 36px; }
.ov-pass { color: #4EC9B0; }
.ov-fail { color: #F44747; }
.ov-warn { color: #DCDCAA; }

/* Toolbar sync button */
.sync-btn {
  background: var(--vscode-button-secondaryBackground, #3c3c3c);
  color: var(--vscode-button-secondaryForeground, #ccc);
  border: 1px solid var(--vscode-panel-border, #555);
  border-radius: 3px;
  padding: 1px 8px;
  font-size: 0.8em;
  cursor: pointer;
  font-family: inherit;
}
.sync-btn:hover { background: var(--vscode-button-secondaryHoverBackground, #4a4a4a); }

/* Right-click context menu */
.ctx-menu {
  display: none;
  position: fixed;
  z-index: 9999;
  background: var(--vscode-menu-background, #252526);
  border: 1px solid var(--vscode-menu-border, #454545);
  border-radius: 4px;
  padding: 3px 0;
  min-width: 130px;
  box-shadow: 0 4px 12px rgba(0,0,0,.4);
}
.ctx-item {
  padding: 5px 14px;
  font-size: 0.85em;
  cursor: pointer;
  color: var(--vscode-menu-foreground, #ccc);
}
.ctx-item:hover { background: var(--vscode-menu-selectionBackground, #094771); }
</style>
</head>
<body>
${body}
<script>
const vscode = acquireVsCodeApi();

document.addEventListener('click', e => {
  const a = e.target.closest('a[data-url]');
  if (a) { e.preventDefault(); vscode.postMessage({ command: 'openExternal', url: a.dataset.url }); }
});

function onEnvChange(select) {
  vscode.postMessage({
    command: 'selectEnv',
    repo: select.dataset.repo,
    python: select.value,
  });
}

function onSyncAll() {
  vscode.postMessage({ command: 'gitsync', target: 'all' });
}

(function () {
  let activeMenu = null;

  document.addEventListener('contextmenu', e => {
    const tr = e.target.closest('tr[data-repo-path]');
    const menu = document.getElementById('ctx-menu');
    if (!menu) return;
    menu.style.display = 'none';
    if (!tr) return;
    e.preventDefault();
    activeMenu = { path: tr.dataset.repoPath, name: tr.dataset.repoName };
    menu.style.left = e.clientX + 'px';
    menu.style.top  = e.clientY + 'px';
    menu.style.display = 'block';
  });

  document.addEventListener('click', () => {
    const menu = document.getElementById('ctx-menu');
    if (menu) menu.style.display = 'none';
  });

  document.getElementById('ctx-gitsync')?.addEventListener('click', () => {
    if (!activeMenu) return;
    vscode.postMessage({ command: 'gitsync', target: 'single',
                         path: activeMenu.path, name: activeMenu.name });
    activeMenu = null;
  });
})();
</script>
</body>
</html>`;
}

module.exports = {
  // Constants
  GRADE_COLOR, COLLECTORS,
  // Pure utilities
  pct, skipReason, execCmd, escHtml, inlineMd,
  // Config resolution
  resolveForge, resolveProjectPython,
  // Async data helpers
  discoverCondaEnvs, gatherRepoMeta,
  // HTML builders
  buildRepoOverview, buildEnvPickerHtml, buildHealthCard,
  loadingHtml, errorHtml, wrapHtml,
};
