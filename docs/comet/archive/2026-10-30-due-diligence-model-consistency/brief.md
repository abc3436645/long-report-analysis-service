# Outcome

解释江铜华北两款模型报告差异，修复能够确定复现的材料覆盖、计算与交付门禁问题，使财务尽调报告的关键事实、比率、材料缺口和授信建议有一致的核验基础。保留综合能力评价目的以及额度、等级、期限职责边界。

用户原始请求：当前我使用/Users/a123/Downloads/workspace/jxcc_harness_project/jxcc_analysis_report_skills_project/data/scenarios/financial_due_diligence/江铜华北 原始数据作为输入,使用不同模型(deepseek-v4-flash-0731和deepseek-v4-flash-1017)测试财务公司尽调报告场景,两个模型跑出的结果相差很大, /Users/a123/Downloads/workspace/jxcc_harness_project/jxcc_analysis_report_skills_project/workspace/jiangtong_huabei_20261029这是deepseek-v4-flash-0731跑出的结果,/Users/a123/Downloads/workspace/jxcc_harness_project/jxcc_analysis_report_skills_project/workspace/jiangtong_huabei/deliverables这是deepseek-v4-flash-1017版本跑出的结果, /Users/a123/Downloads/workspace/jxcc_harness_project/jxcc_analysis_report_skills_project/results/financial_due_diligence/关于2026年江铜华北（天津）铜业有限公司10亿.docx这是财务公司提供的分析报告,请仔细对比并审查原因并修复是否场景分析要求等是否需要更新.

# Scope

在用户已选择的新worktree内调查和修复；原目录材料与历史输出只读引用。调查结果见[差异审查](../../../scenarios/财务公司授信评审-江铜华北双模型差异审查.md)。先统一证据、计算及门禁，再评估模型，不能从现有两稿直接作模型版本优劣排序。

材料路径用于调试、对照与回归参考，不将整份财务公司报告升级为需求或权威事实来源；不移植其评级、政策、期限、人员、金额及业务结论。覆盖用户指定两份完整报告与参考稿的正文表格，原材料核查围绕已发现差异，扫描原件未核读部分公开披露。

## Directory structure

### Created

- docs/scenarios/财务公司授信评审-江铜华北双模型差异审查.md — 逐章对照、复算与根因；已形成调查稿。
- .scratch/due-diligence-model-consistency/ — 本地问题、原始哈希与可复现审查证据，不嵌入可发布场景事实。
- src/long_report/financials.py — 明确口径的描述性财务计算及引用检查；若可在已有模块内保持更小实现则复用现有模块。
- tests/test_financial_quality_cli.py — 财务场景输入、计算、交付门禁的失败和恢复路径。
- docs/adr/0017-financial-evidence-quality.md — 记录新增契约、兼容边界及依据。

### Modified

- src/long_report/application.py — PDF提取覆盖、财务材料用途、计算/起草/审阅/校验接入。
- src/long_report/scenario.py — 新财务计算与质量配置的确定性契约检查。
- scenarios/financial_due_diligence/ — 增补可执行计算和质量契约及针对性分析要求，必要时升级场景版本；固定目录与字体保持现有契约。
- .agents/skills/long-report/SKILL.md — 补材料覆盖、计算及审阅的操作步骤。
- docs/scenarios/财务公司授信评审-场景规格.md、docs/scenarios/财务公司授信评审-逐章分析指引.md、docs/模块设计-数据与执行契约.md — 同步新契约与已确认C02/C03/C08、Q42/Q44/Q46/Q47的关系。
- tests/test_credit_report_cli.py、tests/test_scenarios.py及直接受影响既有测试 — 更新契约并保留三个场景回归。

### Deleted

None

### Not created

- 新的授信模型、评级模型和通用OCR平台 — 不属于报告职责；扫描件使用有来源关系及核读状态的衍生物或明确缺口。
- 模型厂商适配器和付费批量评测系统 — 当前缺共同调用配置；本次记录可复现实验条件及未执行边界。

# Non-goals

不决定真实授信金额、等级、期限或政策阈值；不把财务公司参考稿当标准答案；不覆盖历史报告、不修改原件、不自动查询付费数据。暂不保证两模型措辞相同或无依据地要求同结论。不因当前资料缺失停止可完成分析，不将pending_review用于掩盖错算、丢章或错误引用。

# Acceptance examples

- A1：完成可追溯三稿对照，记录30份原始输入与指定交付哈希，定位可复现的数值、来源及结构错误；明确模型因果不可识别及未OCR/未执行部分，不将参考稿错误移植为正确事实。
- A2：财务场景逐份记录材料analysis/context/excluded及理由；PDF返回逐页提取覆盖，混合扫描页不能静默消失；材料未使用、未核页和真实未提供分别进入任务上下文/缺口；保留原件与衍生物关系，资料不足允许完整待复核交付。
- A3：注册明确的财务描述计算口径，净利率、毛利率、资产负债率、流动/速动比率、平均应收/存货周转率及天数、平均权益ROE由程序产生并留事实引用、主体期间单位及年化身份；同口径0.0779%和4.2746天复算通过，缺分母/基期/口径返回明确状态；已有外部额度结果与其双版本冲突照实核对，不重建额度模型。
- A4：财务章节的表内金额、百分数、倍次及关键派生值绑定本轮事实或计算，裸数不能利用表头单位绕过检查；年份、编号和标题等结构数字有明确例外；固定标题及必备表或具名缺口在标准提交、组装与发布流程保持一致，手工渲染不能冒称publish成功。
- A5：财务审阅提交要求覆盖31个固定二级小节和融资章、每张实际表格与重要结论的具体正文位置及依据；缺项、自审、过期草稿、开放问题阻断通过；记录不冒充平台独立性证明，真正独立审阅仍必需；更新针对性指引约束合并/单体、套保因果、历史案件、无依据阈值与冲突跨章传播。
- A6：执行针对性失败/修复CLI回归、三个场景加载与完整unit回归，检查改动文档术语及链接；用实际执行记录报告通过/失败/未执行，原始输入及两份历史交付哈希不变；独立Verifier逐项验收。两模型真实重跑仅在原调用工具、权限和凭据可用时执行，否则明确未执行，不以模拟冒称质量提升。

# Decisions

- 用户已选择worktree隔离：comet/due-diligence-model-consistency，以main为目标分支；原workspace及projects未跟踪材料保持原位。
- 单一变更：输入、计算、引用和审阅共同决定一份报告的可信度，接口依赖紧密，不拆Supervisor子变更。
- 现有规则优先：C08综合评价与C02/C03职责边界、ADR0014固定目录、ADR0015字体、ADR0016封面继续有效；本次将已有要求落实到操作和门禁，不预设支持授信或风险偏高。
- 当前调查没有证明独立渲染后的DOCX/PDF全部内容与MD数值完全一致；尚未进行完整视觉验收，不作相应完成声明。

- 2026-10-30用户明确确认进入Build，并指定真实双模型测试为gpt-6.1-sol medium与gpt-6.1-terra medium；取代原DeepSeek两版本重跑。两模型用相同提示、材料快照、配置及工具权限，独立输出，不共享对方结果。
