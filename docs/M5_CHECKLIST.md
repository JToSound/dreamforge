# M5 Release Checklist — v0.1.0 PUBLISHED 2026-08-24

Owner decisions recorded: **MIT license**; RESEARCH.md wording review delegated
to the agent reviewer (passed — no overstated claims, every row carries an
evidence grade + limitation); release authorized.

Legend: ✅ done with observed evidence · ⏳ pending (owner action or external event) · ❌ not applicable

## Completed this session

- ✅ LICENSE: MIT, copyright 2026 JToSound; `pyproject.toml` license field +
  author updated; README license section finalized.
- ✅ Wheel rebuilt after metadata change; METADATA verified:
  `Author: JToSound`, `License: MIT License`, `License-File: LICENSE`.
- ✅ CHANGELOG.md: Keep a Changelog format, full 0.1.0 entry.
- ✅ CI workflow `.github/workflows/ci.yml`: ruff / black / mypy strict /
  pytest with `--cov-fail-under=85` on Python 3.11+3.12 matrix; separate
  build + clean-venv vector-smoke job. Local equivalents all executed and
  green (see release report); the workflow itself runs on first GitHub push.
- ✅ Coverage gate measured locally: **91.74%** core line coverage
  (`--cov-fail-under=85` passed), 147 tests.
- ✅ Demo export regenerated + inspected: trace hash unchanged across sessions
  (`e86cd3402307ae91…`), manifest hash stable, 22/22 import checks pass,
  7 artifacts present (incl. report.json).
- ✅ Container smoke: Dockerfile written (multi-stage, slim python:3.12, test
  target runs the suite). **Docker daemon was NOT running on the host**
  (CLI present, Docker Desktop engine unreachable), so the in-container run
  is NOT EXECUTED — recorded honestly; rerun `docker build --target test . &&
  docker run --rm dreamforge:0.1.0` when the daemon is up.
- ✅ Dependency audit: pip-audit over constraints.txt found PYSEC-2026-1845
  (pytest <9.0.3, local tmp-dir issue) → **pytest upgraded to 9.0.3**, full
  suite re-run green (147 passed), re-audit clean: **61 packages, 0 known
  vulnerabilities**; JSON committed at `artifacts/pip-audit-0.1.0.json`
  (command: `python -m pip_audit -r constraints.txt --format json`).

## Pending owner action / external events

- ⏳ Create GitHub repository + push (CI activates on push; no remote exists by
  current setup). Suggested remote: `JToSound/dreamforge`.
- ⏳ SBOM / audit artifact retention: pip-audit JSON IS committed at
  `artifacts/pip-audit-0.1.0.json` (clean, 61 packages) with the command line
  recorded in the release report. Re-run at each future release tag.
- ⏳ PyPI publication (if desired): needs owner PyPI account, trusted-publishing
  environment, and an explicit go-ahead. Not started by design.
- ⏳ SECURITY.md maintainer contact address (currently generic placeholder text).
- ⏳ Final review pass of RESEARCH.md wording by a human before tagging v0.1.0.

## Deliberately deferred (tracked elsewhere)

- ❌ Real narrative-provider adapters — ADR 0003 (contract must be offline-
  testable first); NOT part of 0.1.0 claims.
- ❌ Multi-run dashboard views beyond current scope — future minor releases.

## Release tag procedure (when owner approves)

1. Re-run local gates: ruff · black · mypy strict · pytest --cov-fail-under=85.
2. Re-run demo; confirm trace hash `e86cd3402307ae91…afee27b` unchanged.
3. Commit CHANGELOG date if moved; tag `v0.1.0`; push (activates CI).
4. Attach wheel from a fresh `python -m build --wheel` to the GitHub release;
   record its SHA-256 in the release notes.
