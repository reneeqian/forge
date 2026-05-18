'use strict';
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

function pct(v) { return `${Math.round((v ?? 0) * 100)}%`; }
function skipReason(r) { return r?.skip_reason ? `(${r.skip_reason.split(';')[0].slice(0, 40)})` : '—'; }

// ── Provider ──────────────────────────────────────────────────────────────────

class ForgeWebviewProvider {
  static viewType = 'forgeSidebar';

  constructor(extensionUri) {
    this._extensionUri = extensionUri;
    this._view = null;
    this._cachedHtml = null;
  }

  resolveWebviewView(webviewView) {
    this._view = webviewView;
    webviewView.webview.options = { enableScripts: true };
    webviewView.webview.html = loadingHtml('Initialising…');

    webviewView.webview.onDidReceiveMessage(msg => {
      if (msg.command === 'openExternal') {
        vscode.env.openExternal(vscode.Uri.parse(msg.url));
      }
      if (msg.command === 'selectEnv') {
        const cfg = vscode.workspace.getConfiguration('forge');
        const overrides = { ...cfg.get('repoPythonPaths', {}) };
        if (msg.python) {
          overrides[msg.repo] = msg.python;
        } else {
          delete overrides[msg.repo];
        }
        cfg.update('repoPythonPaths', overrides, vscode.ConfigurationTarget.Global)
          .then(() => this.refresh());
      }
    });

    webviewView.onDidChangeVisibility(() => {
      if (webviewView.visible) {
        if (this._cachedHtml) {
          webviewView.webview.html = this._cachedHtml;
        } else {
          this.refresh();
        }
      }
    });

    this.refresh();
  }

  refresh() {
    if (!this._view) return;
    this._cachedHtml = null;
    this._view.webview.html = loadingHtml('Running forge…');
    this._run().catch(err => {
      if (this._view) this._view.webview.html = errorHtml(err.message);
    });
  }

  // ── Config helpers ───────────────────────────────────────────────────────────

  _resolveWorkspaceConfig() {
    const setting = vscode.workspace.getConfiguration('forge').get('workspaceConfig', '');
    if (setting && fs.existsSync(setting)) return setting;

    const candidates = [];
    for (const folder of vscode.workspace.workspaceFolders ?? []) {
      let dir = folder.uri.fsPath;
      for (let i = 0; i < 8; i++) {
        candidates.push(path.join(dir, 'workspace.toml'));
        const parent = path.dirname(dir);
        if (parent === dir) break;
        dir = parent;
      }
    }
    for (const c of candidates) if (fs.existsSync(c)) return c;
    return null;
  }

  _resolveForge() {
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

  // Returns { python: '/path/to/python', envName: 'name', source: 'setting'|'env_yml'|null }
  _resolveProjectPython(repoName, localPath) {
    const cfg = vscode.workspace.getConfiguration('forge');

    // 1. Explicit setting takes priority.
    const overrides = cfg.get('repoPythonPaths', {});
    if (overrides[repoName]) {
      const p = overrides[repoName];
      if (fs.existsSync(p)) return { python: p, envName: repoName, source: 'setting' };
    }

    // 2. Parse environment.yml to get the conda env name.
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

  // ── Conda env discovery ───────────────────────────────────────────────────────

  _discoverCondaEnvs() {
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

  // ── TOML parser ───────────────────────────────────────────────────────────────

  _parseWorkspaceToml(tomlPath) {
    const repos = [];
    let cur = null;
    for (const raw of fs.readFileSync(tomlPath, 'utf8').split('\n')) {
      const line = raw.trim();
      if (line === '[[repos]]') { if (cur) repos.push(cur); cur = {}; }
      else if (cur) {
        const m = line.match(/^(\w+)\s*=\s*"([^"]*)"$/);
        if (m) cur[m[1]] = m[2];
      }
    }
    if (cur) repos.push(cur);
    return repos;
  }

  // ── Main runner ───────────────────────────────────────────────────────────────

  async _run() {
    const forgePath = this._resolveForge();
    const configPath = this._resolveWorkspaceConfig();
    const q = s => `"${s}"`;

    let codeRepos, workspaceMd;

    if (configPath) {
      // Mode B: workspace.toml drives the repo list
      const repos = this._parseWorkspaceToml(configPath);
      codeRepos = repos.filter(r => r.type === 'code' && r.local_path);
      workspaceMd = await execCmd(`${q(forgePath)} workspace ${q(configPath)} --markdown --no-health`);
    } else {
      // Mode A: use the folders open in the current VS Code workspace
      const folders = vscode.workspace.workspaceFolders ?? [];
      if (!folders.length) {
        throw new Error(
          'No folders are open in this VS Code workspace.\n\n' +
          'Open a folder or .code-workspace file to use the Forge Dashboard.'
        );
      }
      codeRepos = folders.map(f => ({ name: f.name, local_path: f.uri.fsPath }));
      workspaceMd = null;
    }

    const repoPythonInfo = {};
    for (const repo of codeRepos) {
      repoPythonInfo[repo.name] = this._resolveProjectPython(repo.name, repo.local_path);
    }

    const [condaEnvs, ...healthArr] = await Promise.all([
      this._discoverCondaEnvs(),
      ...codeRepos.map(repo => {
        const { python } = repoPythonInfo[repo.name];
        const pythonFlag = python ? `--python ${q(python)}` : '';
        return execCmd(`${q(forgePath)} health ${q(repo.local_path)} --json ${pythonFlag}`)
          .then(out => ({ name: repo.name, data: JSON.parse(out) }))
          .catch(err => ({ name: repo.name, error: err.message }));
      }),
    ]);

    const healthMap = {};
    for (const r of healthArr) healthMap[r.name] = { ...r, pythonInfo: repoPythonInfo[r.name] };

    const html = this._buildDashboard(workspaceMd, healthMap, codeRepos, configPath, condaEnvs);
    this._cachedHtml = html;
    if (this._view) this._view.webview.html = html;
  }

  // ── Markdown helpers ──────────────────────────────────────────────────────────

  _extractSection(md, heading) {
    const re = new RegExp(`## ${heading}([\\s\\S]*?)(?=\\n## |$)`);
    return (md.match(re)?.[1] ?? '').trim();
  }

  _mdTableToHtml(md, hideColumns = new Set()) {
    const rows = md.split('\n').filter(l => /^\s*\|/.test(l));
    if (!rows.length) return '<p class="muted">No data.</p>';

    let hideIndices = null;
    let html = '<table class="md-table"><thead>';
    let headerDone = false;

    for (const row of rows) {
      if (/^\s*\|[\s\-:|]+\|\s*$/.test(row)) {
        if (!headerDone) { html += '</thead><tbody>'; headerDone = true; }
        continue;
      }
      const cells = row.split('|').slice(1, -1).map(c => c.trim());
      if (hideIndices === null) {
        hideIndices = new Set(cells.map((c, i) => hideColumns.has(c) ? i : -1).filter(i => i >= 0));
      }
      const visible = hideIndices.size ? cells.filter((_, i) => !hideIndices.has(i)) : cells;
      const tag = headerDone ? 'td' : 'th';
      html += `<tr>${visible.map(c => `<${tag}>${inlineMd(c)}</${tag}>`).join('')}</tr>`;
    }

    html += headerDone ? '</tbody></table>' : '</thead></table>';
    return html;
  }

  _extractIssues(md) {
    const detailsSection = this._extractSection(md, 'Project Details');
    if (!detailsSection) return '';

    let html = '';
    for (const block of detailsSection.split(/\n(?=### )/)) {
      const lines = block.split('\n');
      const repoName = lines[0].replace(/^###\s*/, '').match(/`([^`]+)`/)?.[1]
        ?? lines[0].replace(/^###\s*/, '').split('·')[0].trim();

      const issueLines = lines.filter(l => /^\s*- \*\*\w+\*\*/.test(l));
      if (!issueLines.length) continue;

      const items = issueLines.map(l => {
        const sev = l.match(/\*\*(\w+)\*\*/)?.[1] ?? 'INFO';
        const msg = l.replace(/^\s*- \*\*\w+\*\*:?\s*/, '').trim();
        const cls = sev === 'CRITICAL' ? 'crit' : sev === 'WARNING' ? 'warn' : 'info';
        return `<div class="issue ${cls}"><span class="sev">${sev}</span><span>${escHtml(msg)}</span></div>`;
      }).join('');

      html += `<div class="issue-group"><div class="issue-repo">${escHtml(repoName)}</div>${items}</div>`;
    }
    return html;
  }

  // ── Health card ───────────────────────────────────────────────────────────────

  _healthCard(name, result, condaEnvs) {
    const pi = result?.pythonInfo ?? { python: null, envName: null, source: null };

    // Build the env picker: a <select> with all discovered conda envs.
    const envPickerHtml = this._envPickerHtml(name, pi, condaEnvs);

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

  // ── Env picker HTML ───────────────────────────────────────────────────────────

  _envPickerHtml(repoName, pi, condaEnvs) {
    if (!condaEnvs.length) {
      // Conda not available — fall back to read-only badge.
      if (pi.python) {
        const label = pi.envName ?? path.basename(path.dirname(pi.python));
        return `<span class="env-tag env-ok" title="${escHtml(pi.python)}">🐍 ${escHtml(label)}</span>`;
      }
      const warnMsg = pi.envName
        ? `⚠ ${escHtml(pi.envName)} not found — tests may use wrong env`
        : '⚠ no environment.yml — using default Python';
      return `<span class="env-tag env-warn">${warnMsg}</span>`;
    }

    // Build options. Value="" means "auto-detect" (remove from repoPythonPaths).
    const autoLabel = pi.source === 'env_yml' && pi.envName
      ? `auto (${pi.envName})`
      : 'auto-detect';
    let options = `<option value="">${escHtml(autoLabel)}</option>`;

    for (const env of condaEnvs) {
      const sel = (pi.python === env.python) ? ' selected' : '';
      options += `<option value="${escHtml(env.python)}"${sel}>🐍 ${escHtml(env.name)}</option>`;
    }

    // Source badge shown next to the picker.
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

  // ── Dashboard assembly ────────────────────────────────────────────────────────

  _buildDashboard(workspaceMd, healthMap, codeRepos, configPath, condaEnvs) {
    const overviewHtml = workspaceMd
      ? this._mdTableToHtml(this._extractSection(workspaceMd, 'Repository Overview'), new Set(['Visibility', 'Description']))
      : null;
    const issuesHtml = workspaceMd ? this._extractIssues(workspaceMd) : null;
    const healthHtml = codeRepos.length
      ? codeRepos.map(r => this._healthCard(r.name, healthMap[r.name], condaEnvs)).join('')
      : '<p class="muted">No folders found in this workspace.</p>';

    const configLabel = configPath
      ? path.basename(path.dirname(configPath)) + '/workspace.toml'
      : 'VS Code Workspace';
    const configTitle = configPath ?? 'Derived from open workspace folders';
    const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const body = `
      <div class="toolbar">
        <span class="ts">Updated ${now}</span>
        <span class="cfg" title="${escHtml(configTitle)}">${escHtml(configLabel)}</span>
      </div>

      ${overviewHtml ? `<section>
        <div class="section-title">Repository Overview</div>
        <div class="tscroll">${overviewHtml}</div>
      </section>` : ''}

      <section>
        <div class="section-title">Health Details</div>
        ${healthHtml}
      </section>

      ${issuesHtml ? `<section>
        <div class="section-title">Issues</div>
        ${issuesHtml}
      </section>` : ''}
    `;

    return wrapHtml(body);
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────────

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
    python: select.value,  // "" means "remove override / auto-detect"
  });
}
</script>
</body>
</html>`;
}

module.exports = { ForgeWebviewProvider };
