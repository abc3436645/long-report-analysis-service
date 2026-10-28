# 长报告分析项目

一个主控 Skill、三个场景包和一个 Python 核心，首期由 CLI 执行。Skill 根据每次用户需求与上传材料规划报告；场景包只保存稳定的计算口径、分析要点、质量和 Word 样式。旧版三场景脚本化回归与四份预算 MOCK 报告见[首期工程验收记录](.scratch/long-report-first-release/acceptance-2026-10-23.md)，它们早于动态规划与指标图表改动，不能作为当前版本的业务交付验收。

## 安装与调用

需要 Python 3.12 或更新版本，以及可在命令行调用的 LibreOffice（`soffice`），用于从最终 Word 测量目录页码并生成 PDF。在项目根目录使用 uv 创建的当前虚拟环境：

```sh
uv pip install --python .venv/bin/python -e .
.venv/bin/report scenarios
.venv/bin/report scenario budget_operations --version 0.2.0
.venv/bin/report scenario financial_due_diligence --version 0.2.0
.venv/bin/report scenario compensation_analysis --version 0.2.0
```

也可使用 `.venv/bin/python -m long_report` 代替 `report`。业务命令成功时在 stdout 输出含 `ok: true`、`capability` 和 `data` 的 JSON；运行错误时在 stderr 输出 `ok: false`，退出码为 1。参数格式错误由 argparse 输出帮助和退出码 2。`report scenario` 返回四份配置和内容指纹，不依赖当前工作目录。

| 场景 ID | 用途 | 当前定义缺口 |
|---|---|---|
| `budget_operations` | 预算经营分析 | 预算版本规则、合并口径、计量单位 |
| `financial_due_diligence` | 财务公司授信评审 | 授信政策、专业来源接入、等级期限映射 |
| `compensation_analysis` | 人力薪酬分析 | 薪酬组成与期间、人数口径、人效公式、小样本阈值 |

授信场景 ID 已统一为 `financial_due_diligence`，调用方需使用新 ID；历史 `credit_review` 项目和验收记录保留原始身份，本次不自动迁移，见 [ADR 0013](docs/adr/0013-financial-due-diligence-scenario-id.md)。

财务公司尽调按真实交付样本固定9章和31个二级标题，见[场景规格第10节](docs/scenarios/财务公司授信评审-场景规格.md#10-真实交付样本固定结构与字体)及[ADR 0014](docs/adr/0014-financial-due-diligence-fixed-report-contract.md)。每轮计划提交已加载的`outline.sections`；正文保留各章`subheadings`，缺材料写缺口。正文、标题和拉丁字符指定仿宋，主机缺该字体时渲染明确失败；字体字号按[ADR 0015](docs/adr/0015-scenario-document-typography.md)统一配置：封面26磅、章标题15磅、二级标题和正文14磅，工商表五号样式集中定义；未宣称完整版式复刻。

配置在 `scenarios/<id>/`，每个场景有 `scenario.yaml`、`outline.yaml`、`analysis.yaml`、`quality.yaml` 和版本化 Word 模板。`outline.yaml` 只含稳定的规划要点，不含默认章节或单位名单。主控 Skill 的维护源是 [.agents/skills/long-report/SKILL.md](.agents/skills/long-report/SKILL.md)；Claude Code 入口链接到同一文件。场景配置只引用核心注册算子，不执行场景脚本。

尽调封面按[ADR 0016](docs/adr/0016-financial-cover-bindings.md)生成公司＋额度标题，呈报部门／客户经理默认XXXX，呈报时间取本轮北京时间；缺可核验额度时显式待核实。

## 当前 CLI 工作流

项目和运行命令均需 `--workspace <目录>`；写操作另需 `--request <UTF-8 JSON 文件>`。完整输入结构可对照 [CLI 纵向测试](tests/test_budget_calculation_cli.py)。

1. `report project create`、`report material add` 建立项目并归档原件；CSV/XLSX、TXT、DOCX 和可提取文字的 PDF 保留来源定位。
2. `report run start` 固定本轮材料和配置；`report task list/context/submit` 领取任务并从当前原件提交带定位的候选事实。表格材料可以把本轮检查过的行列规则作为 `mapping` 传入 `report task auto-submit`；场景包不提供预制映射。若映射的原表行不在项目主体范围，自动提取要求 `scope_exclusion_reason`，并记录排除行供审阅；发现应纳入的单位时应更正项目范围。候选仍须逐条决定是否接受。
3. `report evidence decide/freeze` 显式确认并冻结证据，`report calculate` 从冻结证据计算注册指标；预算场景可得年度计划时计算剩余月份月均利润目标，不直接由 Agent 心算。
4. 首次 `report draft plan` 必须提交本轮 `report_request` 和 `outline`（`sections`、可选 `unit_names` 与 `unit_levels`）；预算场景还要提交覆盖全部当前材料的 `material_uses`，逐份说明用于分析、仅作背景或排除的原因。预算计划须逐户覆盖 `subject_scope.units`，已接受证据的材料须用于分析。Skill 根据需求、取证结果和场景稳定规则制定章节及依赖 DAG；同一预算场景可规划矿山、冶炼、铜加工或其他范围。后续 `draft context/submit/build` 按任务顺序编写。`report chart create` 从同主体、同指标、同期间和同单位的冻结证据生成图表，自动标出相关注册计算与来源。
5. 独立审阅者用 `report review submit` 提交结论；`report validate` 检查门禁，`report publish` 生成不可变版本的 Markdown、DOCX 与 PDF。发布时读取实际 DOCX，核对标题、表格内容和嵌入图像；经 LibreOffice 渲染 PDF 后测量标题所在页，写回带页码的 Word 目录并再次渲染至页码稳定。校验结果写入 `qa/render_qa.json`；失败不切换最新版本。定义或材料缺口会使版本标为 `pending_review`。当前自动检查尚未覆盖 PDF 每页的图表可读性，需在交付验收时逐页复核。

`project create` 的 `subject_scope.units` 来自本轮材料识别与用户要求；不再使用 `report_profile`。预算 `draft plan` 请求示例：`{"project_id":"...","run_id":"...","report_request":"分析矿山板块七月经营与成本风险","material_uses":[{"material_id":"src_...","use":"analysis","reason":"已确认本轮成本数据"}],"outline":{"unit_names":["甲矿"],"sections":[{"id":"scope","title":"资料与口径","display_order":1,"repeat_for":null,"depends_on":[],"evidence_refs":[],"analysis_refs":[]},{"id":"units","title":"矿山单位分析","display_order":2,"repeat_for":"unit","depends_on":["scope"],"evidence_refs":["actual_amount"],"analysis_refs":["budget_difference"]}]}}`。`material_uses` 必须与本轮所有材料 ID 一一对应；`unit_names` 与项目单位同序，缩小范围应在建项时依据用户需求确定。该请求须在证据冻结后提交；`analysis_refs` 也可引用本轮 `calculate` 已算出的逐单位指标 ID。`chart create` 请求包含 `project_id`、`run_id`、`title` 和 2—12 个带 `label`、`evidence_id` 的 `series`；图表 ID 在章节正文中写为 `{{chart:<id>}}`。见[动态计划测试](tests/test_dynamic_report_plan_cli.py)与[预算 CLI 测试](tests/test_budget_calculation_cli.py)。

授信场景可在创建项目时设置 `overrides: {"retrieval.enabled": true}`。启用后 `report run start` 请求需提供 `retrieval_provider_id`；`task list` 返回 `retrieve` 任务，由 `report retrieval execute` 调用同一逻辑提供者 ID 的合成 HTTP 或 MCP 服务。原始响应先归档，主体、日期、出处核对通过才产生专业记录材料及提取任务；失败、空结果、部分结果和不匹配会进入证据快照缺口。后续运行可在七天场景时效内复用完整结果，`refresh_retrieval: true` 强制刷新。当前 MCP 适配器只处理 JSON 响应，真实服务的 SSE 与认证接入尚待联调。

下表是**改造前**的历史输出，均为 `pending_review`，未覆盖 `results/budget_operations/` 参考文件。抽查发现：预算办稿无内嵌图，板块图多为两条原值柱，缺少注册变化率和完成率，部分正文搬运来源表。它们证明旧版取证与版本链路，尚未达到参考报告的专业叙事和图表要求。源单元格等旧版工程检查见[四报告验收结果](projects/four_report_acceptance_2026-10-23.json)。

| 报告 | Markdown | Word |
|---|---|---|
| 预算办月度 | [全文](projects/real_budget_acceptance_v8/projects/8317c0e18aa34726bfe233700a131f30/revisions/d2dc8f8473fd4ed7a93da65891699dd7/dist/full_report.md) | [DOCX](projects/real_budget_acceptance_v8/projects/8317c0e18aa34726bfe233700a131f30/revisions/d2dc8f8473fd4ed7a93da65891699dd7/dist/full_report.docx) |
| 矿山板块 | [全文](projects/real_budget_board_acceptance_v5/projects/99d33ad3ab8c42d5b3b5a518a8b9d468/revisions/d91fc3375be247349d3aeef2d993e09a/dist/full_report.md) | [DOCX](projects/real_budget_board_acceptance_v5/projects/99d33ad3ab8c42d5b3b5a518a8b9d468/revisions/d91fc3375be247349d3aeef2d993e09a/dist/full_report.docx) |
| 冶炼板块 | [全文](projects/real_budget_board_acceptance_v5/projects/9191c6df820b4b9882377b9ac1e168d4/revisions/af8b280c2a59463d974f162291e61c77/dist/full_report.md) | [DOCX](projects/real_budget_board_acceptance_v5/projects/9191c6df820b4b9882377b9ac1e168d4/revisions/af8b280c2a59463d974f162291e61c77/dist/full_report.docx) |
| 铜加工板块 | [全文](projects/real_budget_board_acceptance_v5/projects/3d1cd7957a0f45f79a2867c7c0e088cb/revisions/22ba935bbc8449779ff96e5b1b4735e0/dist/full_report.md) | [DOCX](projects/real_budget_board_acceptance_v5/projects/3d1cd7957a0f45f79a2867c7c0e088cb/revisions/22ba935bbc8449779ff96e5b1b4735e0/dist/full_report.docx) |

## 开发验证

当前仓库使用 uv 创建的 `.venv`，开发验证直接调用其中的 Python 和 CLI：

```sh
uv pip install --python .venv/bin/python -e .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/report scenarios
```

已有 `data/` 和 `results/` 可能含业务材料或生成结果，不纳入发行包；新运行项目放在被忽略的 `projects/` 下。`uv build` 生成的 wheel 与源码包包含三场景和三个 Word 模板，仓库外虚拟环境已加载验证。Q59 的南向 HTTP/MCP 用本地合成服务验证；真实供应商联调、`dsh web` 界面操作及宿主自主撰写与复核仍待验收。上传专业记录不等于实时服务接入。
