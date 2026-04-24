# Forge — Requirements

## Scope: M1 + M2 (Backend Utilities Only)

These requirements define the minimum viable backend. No dashboard, no GitHub Actions yet.

---

## REQ-001 · Project Health Report
The library SHALL produce a `ProjectHealthReport` for any given local project path.
The report SHALL include: project name, path, timestamp, per-collector results, and an
overall health score (0.0–1.0).

## REQ-002 · Test Metrics Collector
The library SHALL collect test metrics by running `pytest` with `coverage.py` on the
target project. It SHALL report: total tests, passed, failed, skipped, pass rate (0–1),
and line coverage percentage.

## REQ-003 · Code Complexity Collector
The library SHALL analyse code complexity using `radon`. It SHALL report: average
cyclomatic complexity, maintainability index, and a normalised score (0–1) where
higher = simpler/better.

## REQ-004 · Dependency Health Collector
The library SHALL audit dependencies using `pip-audit`. It SHALL report: total
dependencies audited, number with known CVEs, and a normalised score (0–1).

## REQ-005 · Requirements Coverage Collector
The library SHALL scan source and test files for requirement tags matching the pattern
`REQ-\d+`. It SHALL report: total unique tags found in source, how many are referenced
in tests, and a coverage ratio (0–1).

## REQ-006 · Weighted Health Score
The overall health score SHALL be a weighted average of all collector scores.
Weights SHALL be configurable via `forge.toml` per project. Default weights:
test_metrics=0.35, complexity=0.25, dependency_health=0.25, requirements_coverage=0.15.

## REQ-007 · forge.toml Configuration
Each project MAY include a `forge.toml` file. If absent, defaults SHALL be used.
The config SHALL support: custom weights, score thresholds, and requirements tag pattern.

## REQ-008 · CLI — forge health
The CLI SHALL provide a `forge health <path>` command that runs all collectors and
prints a formatted summary to stdout. An `--output json` flag SHALL write the full
report to a JSON file.

## REQ-009 · Project Scaffolding
The CLI SHALL provide a `forge new <name>` command that creates a new project with:
standard folder structure (src, tests, docs), environment.yaml, pyproject.toml,
forge.toml, .gitignore, README.md, and a passing starter test.

## REQ-010 · Graceful Degradation
If a collector cannot run (missing tool, no tests found, etc.) it SHALL return a result
with score=None and a human-readable reason. The overall score SHALL be computed from
available collectors only.
