'use strict';
const vscode = require('vscode');
const path = require('path');

const {
  execCmd, escHtml, loadingHtml, errorHtml, wrapHtml,
  resolveForge, resolveProjectPython, discoverCondaEnvs, gatherRepoMeta,
  buildRepoOverview, buildHealthCard,
} = require('./shared');

// ── Provider ──────────────────────────────────────────────────────────────────

class ForgeWebviewProvider {
  static viewType = 'forgeSidebar';

  constructor(extensionUri) {
    this._extensionUri = extensionUri;
    this._view = null;
    this._cachedHtml = null;
    this._lastForgePath = null;
    this._lastCodeRepos = [];
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
      if (msg.command === 'gitsync') {
        const fp = this._lastForgePath ?? resolveForge();
        const repos = this._lastCodeRepos ?? [];
        const q = s => `"${s}"`;
        const terminal = vscode.window.terminals.find(t => t.name === 'Forge')
          ?? vscode.window.createTerminal({ name: 'Forge' });
        terminal.show();
        if (msg.target === 'single') {
          terminal.sendText(`${q(fp)} gitsync ${q(msg.path)}`);
        } else {
          const cmds = repos.map(r => `${q(fp)} gitsync ${q(r.local_path)}`).join(' && ');
          if (cmds) terminal.sendText(cmds);
        }
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

  // ── Main runner ───────────────────────────────────────────────────────────────

  async _run() {
    const forgePath = resolveForge();
    this._lastForgePath = forgePath;
    const q = s => `"${s}"`;

    const folders = vscode.workspace.workspaceFolders ?? [];
    if (!folders.length) {
      throw new Error(
        'No folders are open in this VS Code workspace.\n\n' +
        'Open a folder or .code-workspace file to use the Forge Dashboard.'
      );
    }
    const codeRepos = folders.map(f => ({ name: f.name, local_path: f.uri.fsPath }));
    this._lastCodeRepos = codeRepos;

    const repoPythonInfo = {};
    for (const repo of codeRepos) {
      repoPythonInfo[repo.name] = resolveProjectPython(repo.name, repo.local_path);
    }

    const [condaEnvs, metaMap, ...healthArr] = await Promise.all([
      discoverCondaEnvs(),
      gatherRepoMeta(codeRepos),
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

    const html = this._buildDashboard(healthMap, metaMap, codeRepos, condaEnvs);
    this._cachedHtml = html;
    if (this._view) this._view.webview.html = html;
  }

  // ── Dashboard assembly ────────────────────────────────────────────────────────

  _buildDashboard(healthMap, metaMap, codeRepos, condaEnvs) {
    const overviewHtml = this._buildRepoOverview(metaMap, healthMap, codeRepos);
    const healthHtml = codeRepos.length
      ? codeRepos.map(r => this._healthCard(r.name, healthMap[r.name], condaEnvs)).join('')
      : '<p class="muted">No folders found in this workspace.</p>';

    const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const body = `
      <div class="toolbar">
        <span class="ts">Updated ${now}</span>
        <button class="sync-btn" onclick="onSyncAll()" title="Run forge gitsync for all repos">↻ Sync</button>
        <span class="cfg">VS Code Workspace</span>
      </div>

      <div id="ctx-menu" class="ctx-menu">
        <div class="ctx-item" id="ctx-gitsync">↻ Git Sync</div>
      </div>

      ${overviewHtml ? `<section>
        <div class="section-title">Repository Overview</div>
        <div class="tscroll">${overviewHtml}</div>
      </section>` : ''}

      <section>
        <div class="section-title">Health Details</div>
        ${healthHtml}
      </section>
    `;

    return wrapHtml(body);
  }

  // Thin wrappers over shared functions — preserves existing test interface
  // and ensures changes to shared.js propagate here automatically.
  _buildRepoOverview(metaMap, healthMap, codeRepos) {
    return buildRepoOverview(metaMap, healthMap, codeRepos);
  }
  _healthCard(name, result, condaEnvs) {
    return buildHealthCard(name, result, condaEnvs);
  }
}

module.exports = { ForgeWebviewProvider };
