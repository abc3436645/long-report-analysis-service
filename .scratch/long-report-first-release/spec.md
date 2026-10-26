# 首期工程验收规格：主控 Skill、三场景与 Python CLI

Status: ready-for-agent

依据：Q1—Q60、C01—C06、ADR-0001—0008。当前 `0.1.0` 为 M0 配置骨架；本规格定义后续 M1—M4 的首期工程验收，不表示这些能力已经实现。

## Problem Statement

分析人员需要针对预算经营分析、财务公司授信评审和人力薪酬分析，从多份异构材料形成有证据、可核对、可多轮修订的完整长报告。现有 M0 只能加载和校验场景配置：它不会登记报告项目和上传材料，不会保存可用证据或报告版本，也不能执行计算、任务、审阅及完整 Markdown/DOCX 交付。若由不同宿主 Agent 各自拼接提示词和文件，事实、口径、章节依赖、敏感信息展示和失败恢复容易漂移，配置能加载也容易被误认为报告已经可用。

首期需要可安装、可恢复且可跨宿主验证的工程能力。真实企业政策、薪酬参数与专业服务端点仍未齐备，因此本规格的验收使用口径明确、答案可人工核对的合成或脱敏材料；工程验收通过不等于正式业务投用，也不等于真实供应商联调完成。

## Solution

保留一个主控 Skill、三个版本化分析场景包和一个 Python 核心引擎。宿主 Agent 依据 Skill 完成材料理解、事实候选提取、分析判断、章节写作和独立语义审阅；它通过唯一的北向 Python CLI 读取任务上下文并提交结果。核心引擎负责报告项目与报告版本的权威状态、配置冻结、来源与证据处理、确定性计算、章节依赖和影响传播、验收及原子发布。场景包声明分析要求、允许的算子、章节、质量规则与版本化 Word 模板，不执行任意场景脚本。

按 M1—M4 逐步验收：先让预算经营分析完成首次完整交付，再完成补件、更正、指定章节修改及恢复；随后用授信和薪酬验证同一引擎。授信所需的通用南向 HTTP/MCP 提供者契约用合成服务验证，真实供应商联调单列。最后由 Codex、Claude Code 和 DeepSeek Harness 使用同一 CLI、场景版本和合成材料实跑，比较事实、数值、章节覆盖、版本身份及完整文件。

## User Stories

1. As a 报告编制人, I want to select one of the three analysis scenarios, so that the report uses the right business questions and quality rules.
2. As a 报告编制人, I want to see the selected scenario version and unresolved business definitions, so that I know which analyses can proceed.
3. As a 报告编制人, I want to create a report project with an explicit subject scope and report period or evaluation date, so that different reports do not mix facts.
4. As a 报告编制人, I want a new report period or credit application to create a related project, so that previous material is not silently treated as current fact.
5. As a 报告编制人, I want to register uploaded materials without overwriting originals, so that every source version remains traceable.
6. As a 报告编制人, I want every uploaded file to have a processing result or explicit error, so that no source is silently skipped.
7. As a 报告编制人, I want spreadsheet, document and text evidence to retain source locations, so that claims can be checked against the original material.
8. As a 报告编制人, I want candidate facts separated from usable evidence, so that extraction alone does not establish a business fact.
9. As a 报告编制人, I want conflicting sources to remain unresolved until a valid replacement rule or decision exists, so that upload order does not decide truth.
10. As a 报告编制人, I want material gaps, business definition gaps, numeric zero and inapplicability represented separately, so that the report does not misstate missing information.
11. As a 报告编制人, I want each update to freeze its material, retrieval and effective configuration scope, so that resumed tasks use the same basis.
12. As a 报告编制人, I want project adjustments accepted only where the scenario permits them, so that local preferences cannot disable hard quality checks.
13. As a 预算经营分析人员, I want actuals compared with the applicable budget version and same-period basis, so that a numeric variance is meaningful.
14. As a 预算经营分析人员, I want monthly and year-to-date results distinguished, so that one period is not presented as another.
15. As a 预算经营分析人员, I want annual budgets and progress budgets distinguished, so that missing monthly plans are not invented by division.
16. As a 预算经营分析人员, I want group figures and unit summaries distinguished, so that an unverified sum is not labelled consolidated data.
17. As a 预算经营分析人员, I want every in-scope unit covered with a comparison table or a stated gap, so that quieter units are not omitted.
18. As a 预算经营分析人员, I want causes, risks and proposed actions linked to evidence and limitations, so that the report does not treat hypotheses as facts.
19. As a 财务公司评审人员, I want the credit application, reviewed business unit and evaluation date kept distinct, so that the report addresses the correct matter.
20. As a 财务公司评审人员, I want financial, cash-flow, guarantee, litigation, related-party and control topics reviewed when applicable, so that relevant risks are visible.
21. As a 财务公司评审人员, I want in-construction business projects reviewed when present, so that their funding and progress effects are considered without confusing them with report projects.
22. As a 财务公司评审人员, I want search hits and summaries treated as leads until verified against original or professional records, so that unsupported claims do not become usable evidence.
23. As a 财务公司评审人员, I want missing professional information reported with its effect on conclusions, so that retrieval failure does not imply low risk or absence of an event.
24. As a 财务公司评审人员, I want supplied credit amount, grade and term checked against the correct source and subject, so that the report does not replace the external credit model or grading process.
25. As a 财务公司评审人员, I want the risk report to proceed when external credit results are absent, so that later supplied results can produce a traceable new report version.
26. As a 财务公司评审人员, I want risk findings deduplicated across materials, so that the same matter is not counted multiple times.
27. As a 财务公司评审人员, I want strategy recommendations to cite findings, evidence, conditions and unresolved items, so that they are not mistaken for implemented measures or approval decisions.
28. As a 薪酬分析人员, I want pay components, accounting basis, currency, period and workforce scope declared, so that group comparisons use a defined compensation basis.
29. As a 薪酬分析人员, I want transfers, concurrent roles and cross-period bonuses handled by stated rules, so that people or amounts are not counted twice.
30. As a 薪酬分析人员, I want productivity metrics calculated only when numerator, denominator, period and subject are defined, so that an appealing but unsupported ratio is not published.
31. As a 薪酬分析人员, I want missing productivity inputs or business definitions disclosed, so that the report does not fabricate a result.
32. As a 薪酬分析人员, I want personal pay and ranking excluded from the main report by default, so that the output stays within the approved display scope.
33. As a 薪酬分析人员, I want small groups hidden or combined under an explicit rule, so that group tables and totals cannot reveal an individual by subtraction.
34. As a 报告读者, I want all required sections in a complete Markdown and DOCX report, so that a revision is understandable without assembling chat fragments.
35. As a 报告读者, I want key limitations shown both near affected conclusions and in the evidence appendix, so that a polished summary does not hide gaps.
36. As a 报告编制人, I want the executive summary generated after supporting analyses, so that it reflects the same evidence and conclusions.
37. As a 报告编制人, I want independent review of key conclusions and checks of numbers, citations, section coverage and rendered files, so that a successful export is not mistaken for a valid formal report.
38. As a 报告编制人, I want a complete pending-review version when evidence is insufficient but hard checks pass, so that work can continue without pretending that gaps are resolved.
39. As a 报告编制人, I want wrong calculations, broken citations, missing required sections or unreadable files to block publication, so that a pending-review label cannot excuse a damaged report.
40. As a 报告编制人, I want to add material or correct data and see only dependent analyses and sections reevaluated, so that unrelated wording and assets retain their identity.
41. As a 报告编制人, I want a wording-only edit to update the requested section, so that unrelated sections remain unchanged.
42. As a 报告编制人, I want a locked section conflict surfaced when a factual change requires it to move, so that the system does not silently overwrite an explicit lock.
43. As a 报告编制人, I want to resume an interrupted run and reject late or duplicate results against old inputs, so that stale Agent work cannot publish.
44. As a 报告编制人, I want replacement or cancellation of an unpublished run to revoke its publication eligibility, so that a superseded request cannot become the current report.
45. As a 报告编制人, I want failed validation or export to leave the latest delivered version untouched, so that I can recover without losing a valid report.
46. As a 报告编制人, I want the CLI to return structured task, error and file information, so that a host Agent can drive the workflow and show accessible artifacts.
47. As a 场景维护人, I want versioned configurations to reference tested shared operators, so that a new scenario does not need a copied business engine or executable formulas.
48. As a 场景维护人, I want the installed scenario resources to load independently of the working directory, so that the same package works in each host environment.
49. As a 验收人员, I want a synthetic HTTP/MCP professional-source service to exercise the shared retrieval contract, so that provider behavior can be checked without claiming a real supplier connection.
50. As a 验收人员, I want the same operations and materials run under Codex, Claude Code and DeepSeek Harness, so that host compatibility is demonstrated by artifacts rather than Skill discovery alone.
51. As a 项目负责人, I want M0, engineering acceptance and formal business use reported separately, so that a valid configuration or synthetic test is not sold as production readiness.

## Implementation Decisions

1. **Scope and layering.** Use one Python distribution, one master Skill, three parallel scenario packages and the CLI as the only first-release northbound entry. The CLI maps inputs, JSON results and errors to one application service; the core interprets configuration and owns state, planning, calculations, validation and publication. A northbound HTTP or MCP wrapper can later call the same service without a second state machine.
2. **M0 boundary.** The existing `0.1.0` release is an M0 configuration skeleton. It lists and validates installed scenarios, versions, basic references, operator IDs, the section DAG and template presence. It does not satisfy Q56 engineering acceptance or claim report generation.
3. **Scenario contract.** Each package has four versioned configuration documents for identity/materials/resources, stable section IDs and dependencies, evidence selectors/metrics/Agent tasks, and quality/delivery rules. A scenario may reference only registered shared operators and package-contained resources. Configuration is data, not executable Python.
4. **Effective configuration.** Project overrides are allowed only for declared paths with types and ranges. Reject an invalid override as a whole, freeze the resulting effective configuration for each run, and record its source, version and fingerprint. A missing business definition is a typed gap affecting only dependent operations; it is not filled by the Agent.
5. **Project identity.** A report project binds one scenario, subject scope and period or evaluation baseline; the credit scenario also binds the application. Related periods or applications create related projects. A project has one active update run, immutable source versions and immutable delivered revisions.
6. **Source and evidence lifecycle.** Register uploaded materials with hashes and replacement relations; parse each with source location and an explicit processing status. Keep original material, candidate facts, usable evidence, source conflicts, definition gaps and material gaps distinct. An external search result starts as a lead; a verified original or professional record can become usable evidence for a stated scope.
7. **Two freezes.** Freeze the update's material set and retrieval requirements before work begins. Archive planned retrieval results and gaps, then freeze the evidence snapshot used by calculation and writing. Later results enter a new run or an explicit rebuild of the snapshot; they do not alter an active draft invisibly.
8. **Tasks and Agent boundary.** The application service produces version-bound extraction, analysis, writing and independent-review tasks. The host Agent submits judged outputs against a specific run, task and input version. Programs determine readiness, deterministic conversion, calculation, retry limits and result eligibility.
9. **CLI operations.** The first executable vertical slice fixes the command spellings and JSON envelope for project creation, material registration, starting an update, listing tasks, reading context, submitting results, building, validating and publishing a revision, and reading status. Relevant responses carry project, run, task and base-revision identity. Invalid input and stale submissions return explicit errors and nonzero exit status.
10. **Deterministic calculation.** Registered operators execute only after subject, period, metric, unit and applicable budget or workforce basis are checked. Keep numeric zero distinct from missing input; preserve unrounded values for calculations and apply display precision only at presentation. Unknown operators or parameters fail validation rather than being ignored.
11. **Section planning and change propagation.** Section IDs remain stable independently of display order. `depends_on` expresses input dependencies, including repeated unit identities. Dependency propagation covers evidence selectors, metrics, findings and sections; it accounts for newly matched objects and selection-range changes. An unchanged input fingerprint allows asset reuse, while a changed factual conclusion dirties its actual dependents.
12. **Budget scenario.** Implement the six confirmed default parts, monthly and cumulative comparisons, budget-version identity, same-basis variance, full in-scope unit coverage and the distinction between group data and unit summary. Do not infer a monthly budget from an annual plan or a consolidated figure from a unit sum.
13. **Credit scenario.** Implement seven confirmed default parts and applicable review topics, including in-construction business projects. Keep risk severity separate from external credit grade, and keep the report separate from the credit model, grading process and decision to grant credit. Missing external amount/grade/term can be disclosed in a complete pending-review report and later supplied as a new revision.
14. **Compensation scenario.** Implement group analysis with declared pay components, accounting period, workforce mapping and optional productivity formula. Detailed person-level records may be inputs, but the main report displays only permitted aggregates. If the small-group rule is undefined, suppress affected display and disclose the limitation; do not invent a threshold.
15. **Southern retrieval contract.** The shared retrieval capability is enabled by scenario policy and calls configured HTTP/MCP providers, archives raw results and status, and verifies subject/time/provenance before facts are used. First-release engineering acceptance uses synthetic services and tests failure, absence, partial results, refresh and reuse. Real supplier endpoints, credentials and live interoperation have separate acceptance; uploaded professional records are a valid sourced input but do not count as a live service call.
16. **Revision and publication.** Assemble a full candidate from current sections and assets, run data, content, semantic-review and presentation gates, then publish atomically. The latest delivered revision changes only after all required checks and MD/DOCX exports succeed. Pending-review is a complete report identity with disclosed gaps; it cannot bypass wrong calculations, missing chapters, invalid citations or broken files.
17. **Update semantics.** Material addition, correction, changed definitions and factual conclusions trigger dependent reassessment. Wording-only edits change the target section. An explicit manual lock creates a conflict requiring resolution if affected content must change. Replacement or cancellation revokes the old unpublished run's submission and publication rights while preserving audit history.
18. **Templates and output.** Each scenario has a versioned built-in Word template; rendering uses it to create an openable DOCX with editable tables, real embedded figures where required, source/caption information and the complete set of required sections. Markdown and DOCX are required; PDF is optional where configured. User-provided Word may guide style or revisions but does not automatically become a trusted template or overwrite a revision.
19. **Storage and deployment.** Keep each report project's structured state as the sole authority; derived manifests and latest pointers are projections. Package scenario resources so installed operation is independent of the current directory. Each host uses the same package version, scenario version and CLI contract, with host-specific setup limited to Skill discovery, command launch and artifact access.
20. **Information boundary.** The engineering fixtures are synthetic or deidentified. The project records which source material the configured host model may process. A later requirement to technically prevent the host from reading originals requires a real storage/permission boundary; a Skill instruction alone cannot enforce that isolation.
21. **Delivery sequence.** M1 proves the budget first complete report. M2 proves four-round updates, idempotency and recovery. M3 proves the same core with credit, compensation and synthetic southern retrieval. M4 proves the three-host CLI flow and artifact reachability. These phases are dependency order, not time estimates.

## Testing Decisions

1. **Primary seam:** exercise the installed `report` CLI as the single main behavioral seam. Give it fixed synthetic materials, scenario version and operations; assert JSON responses, project/revision identities, persisted source and evidence references, calculated values, complete output files and unchanged latest revision on failure. Run from a directory outside the source tree.
2. A good test fails when a business rule or observable contract is broken. It checks source identity, numeric expectation, gap classification, affected sections and delivered artifacts; it does not merely mirror configuration fields or call an internal helper with the same implementation logic.
3. Existing M0 tests are prior art for rejecting unknown operators, invalid references, section cycles, unsafe resources, missing hard checks and wrong scenario versions. Keep small lower-level tests for operator arithmetic and configuration validation where they isolate a fault; do not multiply parallel end-to-end test harnesses.
4. Prepare one manually checkable synthetic fixture per scenario, with source materials, explicit scenario/project business parameters, expected facts and amounts, expected missing items, expected section coverage and display expectations. Fixture rules are examples, not claims about enterprise policy.
5. Budget M1 tests cover monthly and cumulative periods, valid and changed budget versions, positive/zero/negative comparison bases, missing progress budget, group-versus-unit distinction, full unit coverage, source citations and openable MD/DOCX.
6. M2 tests cover the four-round path of first report, supplement, correction and targeted edit; newly selected evidence; unrelated section body hashes staying unchanged; explicit lock conflicts; duplicate and stale submission rejection; cancellation/replacement and crash recovery without replacing the last delivered revision.
7. Credit tests cover external results absent and later supplied, separate credit amount/grade/term identities, professional search lead versus verified record, subject and evaluation-date mismatch, risk-finding deduplication, in-construction business projects, and policy gaps that prevent invented severity or decisions.
8. Compensation tests cover component and period definitions, cross-period bonus, transfer or concurrent role, missing productivity denominator, a defined small-group rule, cross-tab and total-based re-identification checks, and the absence of individual pay from all delivered report text and assets.
9. Synthetic HTTP and MCP provider tests exercise the common southbound task/result contract, provenance, archival before evidence freeze, failure and partial-result status, refresh and reuse rules, and disabled retrieval not creating tasks. They do not count as real supplier integration tests.
10. Quality tests distinguish complete pending-review delivery from formal delivery and ensure bad calculation, broken reference, omitted required section, missing independent review or invalid MD/DOCX prevents formal publication as specified.
11. Packaging tests check that the wheel and source distribution contain the three scene definitions and templates, load outside the repository, and exclude business materials, results and project workspaces.
12. Cross-host acceptance repeats the same fixture, scenario and CLI operation sequence in Codex, Claude Code and DeepSeek Harness. Record host/model version, package/scene/template identity, input hashes, accessible output files, facts, metrics, coverage, status and recovery results. Wording may differ; contract outcomes must agree.
13. Report automated contract tests and manual document/host checks separately. A template opening or Skill being discoverable does not prove complete report generation or host interoperability.

## Out of Scope

- A northbound HTTP API or northbound MCP report server in the first engineering release.
- Live integration with a real professional-source supplier, its credentials, enterprise access rules or a claim of formal business readiness.
- Rebuilding the credit amount model, grading workflow, grade-to-term policy, approval process or automatic grant/rejection action.
- Inferring missing company budgets, compensation definitions, productivity formulas, small-group thresholds or risk policies from model memory.
- Treating arbitrary user Word files as automatically imported, trusted report templates; lossless round-trip of external Word edits.
- PDF output unless a scenario explicitly enables it; OCR or complex layout features unless required by the accepted fixture.
- Multiple simultaneous active update runs for one report project, implicit cross-project fact sharing, or a second state machine per Agent host.
- Technical isolation of real originals from a host with direct filesystem access without an approved deployment permission boundary.

## Further Notes

- M0 already provides a packaged scenario loader, a `scenario_contract_only` CLI response, three four-document configurations, three versioned Word starter templates and structural tests. The templates and named quality checks are not yet a functioning renderer or validator.
- Decisions Q59—Q60 separate synthetic southern-provider contract evidence, the M0 skeleton, full first-release engineering acceptance and real supplier integration. Report these four statuses independently.
- Some enterprise business parameters are explicitly undefined. The effective project configuration and fixture may supply approved example definitions under Q54; absent definitions remain gaps under Q55. A synthetic example is not an enterprise standard.
- The spec follows the project glossary and accepted ADR-0001—0008. Command spelling and exact JSON fields should be fixed by the first complete CLI vertical slice while preserving the operation and version identities above.
