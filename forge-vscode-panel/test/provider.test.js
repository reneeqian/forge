'use strict';
// REQ-EXT-004: VS Code Panel Repository Overview Table

// Mock vscode before loading any module that requires it
const Module = require('module');
const _origLoad = Module._load;
Module._load = function (request, ...args) {
  if (request === 'vscode') {
    return {
      workspace: { getConfiguration: () => ({ get: () => '' }), workspaceFolders: [] },
      env: {},
      ConfigurationTarget: { Global: 1 },
    };
  }
  return _origLoad.call(this, request, ...args);
};

const assert = require('assert');
const { buildRepoOverview } = require('../src/shared');
const { ForgeWebviewProvider } = require('../src/provider');

const provider = new ForgeWebviewProvider({ fsPath: '/fake/ext' });

function ov(metaMap, healthMap, repos) {
  return provider._buildRepoOverview(metaMap, healthMap, repos);
}

function repo(name) { return { name, local_path: `/fake/${name}` }; }

function meta(branch, ahead = 0, behind = 0, prNumber = null, prUrl = null, ciPassed = null, ciTotal = null) {
  return { branch, ahead, behind, prNumber, prUrl, ciPassed, ciTotal };
}

function health(grade, score = 0.9) {
  return { data: { grade, overall_score: score } };
}

let passed = 0, failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`  ✓ ${name}`);
    passed++;
  } catch (e) {
    console.error(`  ✗ ${name}\n    ${e.message}`);
    failed++;
  }
}

// ── shared.js import ──────────────────────────────────────────────────────────

console.log('\nshared.js');

test('buildRepoOverview is exported from shared.js', () => {
  assert.strictEqual(typeof buildRepoOverview, 'function');
});

test('provider._buildRepoOverview delegates to shared buildRepoOverview', () => {
  const fromProvider = provider._buildRepoOverview(
    { r: meta('dev') }, { r: health('A') }, [repo('r')]
  );
  const fromShared = buildRepoOverview(
    { r: meta('dev') }, { r: health('A') }, [repo('r')]
  );
  assert.strictEqual(fromProvider, fromShared);
});

// ── Column headers ────────────────────────────────────────────────────────────

console.log('\n_buildRepoOverview — headers');

test('renders all six column headers', () => {
  const html = ov({ r: meta('dev') }, { r: health('A') }, [repo('r')]);
  for (const h of ['Repo', 'Grade', 'Br', '±', 'PR', 'CI'])
    assert.ok(html.includes(`<th>${h}</th>`), `missing header: ${h}`);
});

// ── Repo name ─────────────────────────────────────────────────────────────────

console.log('\n_buildRepoOverview — repo name');

test('shows repo name in row', () => {
  const html = ov({ myrepo: meta('main') }, { myrepo: health('A') }, [repo('myrepo')]);
  assert.ok(html.includes('myrepo'));
});

// ── Grade badge ───────────────────────────────────────────────────────────────

console.log('\n_buildRepoOverview — grade');

test('shows grade letter inside badge', () => {
  const html = ov({ r: meta('main') }, { r: health('B') }, [repo('r')]);
  assert.ok(html.includes('>B<'), 'badge should contain grade letter');
});

test('shows ERR when health errored', () => {
  const html = ov({ r: meta('main') }, { r: { error: 'forge not found' } }, [repo('r')]);
  assert.ok(html.includes('ERR'));
});

// ── Branch ────────────────────────────────────────────────────────────────────

console.log('\n_buildRepoOverview — branch');

test('shows branch name', () => {
  const html = ov({ r: meta('feature-abc') }, { r: health('A') }, [repo('r')]);
  assert.ok(html.includes('feature-abc'));
});

test('truncates branch longer than 18 chars', () => {
  const html = ov({ r: meta('very-long-branch-name-xyz') }, { r: health('A') }, [repo('r')]);
  assert.ok(html.includes('very-long-branch-n…'), 'should truncate at 18 + ellipsis');
  assert.ok(!html.includes('very-long-branch-name-xyz'), 'should not show full name');
});

test('shows dash when no branch (detached or null)', () => {
  const html = ov({ r: meta(null) }, { r: health('A') }, [repo('r')]);
  assert.ok(html.includes('—'));
});

// ── Ahead/behind ──────────────────────────────────────────────────────────────

console.log('\n_buildRepoOverview — ahead/behind');

test('shows ↑N when ahead', () => {
  const html = ov({ r: meta('dev', 3, 0) }, { r: health('A') }, [repo('r')]);
  assert.ok(html.includes('↑3'));
});

test('shows ↓M when behind', () => {
  const html = ov({ r: meta('dev', 0, 2) }, { r: health('A') }, [repo('r')]);
  assert.ok(html.includes('↓2'));
});

test('shows both ↑N ↓M when diverged', () => {
  const html = ov({ r: meta('dev', 4, 1) }, { r: health('A') }, [repo('r')]);
  assert.ok(html.includes('↑4') && html.includes('↓1'));
});

test('shows ✓ when in sync with upstream', () => {
  const html = ov({ r: meta('dev', 0, 0) }, { r: health('A') }, [repo('r')]);
  assert.ok(html.includes('✓'));
});

test('shows dash when branch is null (no upstream context)', () => {
  const html = ov({ r: meta(null) }, { r: health('A') }, [repo('r')]);
  const dashCount = (html.match(/—/g) ?? []).length;
  assert.ok(dashCount >= 1, 'should have at least one dash for missing branch');
});

// ── PR ────────────────────────────────────────────────────────────────────────

console.log('\n_buildRepoOverview — PR');

test('shows #N link when PR exists', () => {
  const html = ov(
    { r: meta('dev', 0, 0, 42, 'https://github.com/x/y/pull/42') },
    { r: health('A') }, [repo('r')]
  );
  assert.ok(html.includes('#42'), 'should show PR number');
  assert.ok(html.includes('https://github.com/x/y/pull/42'), 'should include PR URL in data-url');
});

test('shows dash when no open PR', () => {
  const html = ov({ r: meta('dev', 0, 0, null) }, { r: health('A') }, [repo('r')]);
  assert.ok(html.includes('—'));
});

// ── CI ────────────────────────────────────────────────────────────────────────

console.log('\n_buildRepoOverview — CI');

test('shows N/M with ov-pass when all checks pass', () => {
  const html = ov({ r: meta('dev', 0, 0, null, null, 5, 5) }, { r: health('A') }, [repo('r')]);
  assert.ok(html.includes('5/5'));
  assert.ok(html.includes('ov-pass'));
});

test('shows N/M with ov-warn when partial pass', () => {
  const html = ov({ r: meta('dev', 0, 0, null, null, 3, 5) }, { r: health('A') }, [repo('r')]);
  assert.ok(html.includes('3/5'));
  assert.ok(html.includes('ov-warn'));
});

test('shows N/M with ov-fail when none pass', () => {
  const html = ov({ r: meta('dev', 0, 0, null, null, 0, 4) }, { r: health('A') }, [repo('r')]);
  assert.ok(html.includes('0/4'));
  assert.ok(html.includes('ov-fail'));
});

test('shows dash when CI data unavailable', () => {
  const html = ov({ r: meta('dev', 0, 0, null, null, null, null) }, { r: health('A') }, [repo('r')]);
  assert.ok(html.includes('—'));
});

// ── Multiple repos ────────────────────────────────────────────────────────────

console.log('\n_buildRepoOverview — multiple repos');

test('renders all repos in a single table', () => {
  const html = ov(
    {
      repo_a: meta('main', 0, 0, null, null, 3, 3),
      repo_b: meta('dev',  2, 0, 7, 'https://github.com/x/y/pull/7', null, null),
    },
    { repo_a: health('A', 0.95), repo_b: health('C', 0.72) },
    [repo('repo_a'), repo('repo_b')]
  );
  assert.ok(html.includes('repo_a') && html.includes('repo_b'));
  assert.ok(html.includes('>A<') && html.includes('>C<'));
  assert.ok(html.includes('#7'));
  assert.ok(html.includes('3/3'));
});

// ── Gitsync attributes ────────────────────────────────────────────────────────

console.log('\n_buildRepoOverview — gitsync attributes');

test('rows have data-repo-path attribute', () => {
  const html = ov({ r: meta('dev') }, { r: health('A') }, [{ name: 'r', local_path: '/repos/r' }]);
  assert.ok(html.includes('data-repo-path="/repos/r"'));
});

test('rows have data-repo-name attribute', () => {
  const html = ov({ r: meta('dev') }, { r: health('A') }, [{ name: 'r', local_path: '/repos/r' }]);
  assert.ok(html.includes('data-repo-name="r"'));
});

test('escapes special chars in repo path attribute', () => {
  const html = ov({ r: meta('dev') }, { r: health('A') }, [{ name: 'r', local_path: '/path with "quotes"' }]);
  assert.ok(!html.includes('"/path with "quotes""'), 'unescaped quotes would break HTML attribute');
  assert.ok(html.includes('&quot;'), 'quotes should be HTML-escaped');
});

// ── Summary ───────────────────────────────────────────────────────────────────

console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`);
if (failed) process.exit(1);
