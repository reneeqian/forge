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
test_metrics=0.30, complexity=0.15, dependency_health=0.20, requirements_coverage=0.10,
static_analysis=0.10, type_coverage=0.10, dead_code=0.05, mutation_testing=0.00.

**Migration note**: projects using the original 4-collector forge.toml weight layout
(summing to 1.0) must update their weights section to include all 8 collectors.

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

## REQ-011 · Static Analysis Collector
The library SHALL analyse source code using `ruff` (preferred) or `flake8` (fallback).
It SHALL report: total lint errors, total Python lines, error density (errors per 1000
lines), and a normalised score (0–1) where 0 errors = 1.0.

## REQ-012 · Type Coverage Collector
The library SHALL check type annotations using `mypy`. It SHALL report: total type errors,
files checked, and a normalised score (0–1) where 0 errors = 1.0 and 100+ errors = 0.0.

## REQ-013 · Dead Code Collector
The library SHALL detect unused code using `vulture` at ≥80% confidence. It SHALL report:
unused item count, total Python lines, unused density (items per 1000 lines), and a
normalised score (0–1).

## REQ-014 · Mutation Testing Collector
When enabled, the library SHALL compute a mutation score using `mutmut`. It SHALL report:
total mutants generated, killed mutants, and mutation score (killed / total, 0–1).

## REQ-015 · Mutation Testing Opt-In
Mutation testing SHALL be disabled by default due to its long runtime. It SHALL be enabled
per-project via `[collectors.mutation_testing] enabled = true` in `forge.toml`.
