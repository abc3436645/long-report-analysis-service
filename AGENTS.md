# Repository Guidelines

## Project Structure & Document Authority

`GLOSSARY.md` defines business terms. `docs/通用长报告项目-统一架构与业务流程.md` is the architecture baseline; `docs/模块设计-数据与执行契约.md` specifies contracts. `docs/scenarios/` holds business specifications; `docs/adr/` holds accepted decisions. `docs/架构细化-决策树与访谈记录.md` records user confirmations; `docs/需求分析*.md` are earlier inputs. The runnable implementation is in `src/long_report/`, `scenarios/`, and `tests/`. The sole master Skill is [.agents/skills/long-report/SKILL.md](.agents/skills/long-report/SKILL.md). Synthetic four-round CLI regressions cover all three scenarios and have run through the same wheel under Codex, Claude Code and DeepSeek Harness. A full MOCK budget reference draft is published as `pending_review`. Business signoff, live providers and autonomous Agent drafting remain open.

## Build, Test, and Development Commands

Use the uv-created `.venv` in this checkout: install with `uv pip install --python .venv/bin/python -e .`; run `.venv/bin/report scenarios`, `.venv/bin/report scenario <id> --version 0.1.0`, and `.venv/bin/python -m unittest discover -s tests -v`. Use `rg --files GLOSSARY.md docs scenarios src tests` to inspect scope. Search decision IDs with `rg -n 'Q[0-9]+|C[0-9]+' docs` before changing a confirmed rule. Review relative Markdown links and open their targets after editing.

## Writing Style & Naming Conventions

Follow the existing Chinese prose and Markdown style: one `#` title, descriptive numbered sections in design documents, short paragraphs, and tables for contracts or decisions. Preserve terms from `GLOSSARY.md`; distinguish confirmed requirements from proposals and pending questions. Keep business specifications under `docs/scenarios/` with the `-场景规格.md` suffix and executable definitions under `scenarios/<id>/`. Name new ADRs with the next four-digit prefix and record decision status. No formatter or linter is configured.

## Validation Guidelines

For documentation or scenario changes, check terminology against the glossary, trace decision IDs to the interview record, and verify affected specifications and YAML agree. Run the unit tests and `report scenarios`; check links manually. Do not describe proposed acceptance cases as executed tests or a validated config as a generated report.

## Commits & Pull Requests

This directory has no Git history, so no existing commit convention can be inferred. If contributing through Git, use a concise, imperative summary such as `docs: clarify report versioning`. A pull request should state the decision or requirement being changed, list affected documents and decision IDs, and report the checks actually performed. Add an ADR for a consequential new choice; update linked documents when an accepted rule changes.

## Agent skills

### Issue tracker

Issues and specs live as local Markdown under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default triage role names as local status strings. See `docs/agents/triage-labels.md`.

### Domain docs

Use the single-context glossary and ADR layout. See `docs/agents/domain.md`.
