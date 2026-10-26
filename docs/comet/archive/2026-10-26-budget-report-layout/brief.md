# 目标

修复预算办经营分析报告生成与交付中的封面、版本元信息、Word样式、目录、章节编号、分页、表格和图表排版缺陷，按用户本轮10.5—10.10要求重新生成完整矿山DOCX/PDF，并使后续预算报告沿同一链路获得相同检查。

# 范围

本轮覆盖边界为用户消息中封面清单、10.5—10.10全部条款及其术语/版本/动态计划依赖。重复句合并记录，示例月份与版本不作为固定值。`results/budget_operations/`的旧样例只作版式与结构参考；`矿山板块_新流程全文验收_20261024/`为缺陷复现与内容回归基准，不从样例复制事实。现有3份根目录DOCX已核对封面、样式与结构；旧验收报告、当前39页PDF和MD用于调查。本次只读检查了PDF封面及第10页图像，不能视为逐页验收。

## 目录结构

### 新建

- docs/comet/changes/budget-report-layout/specs/budget-report-layout/spec.md — 本轮完整目标规格。
- docs/adr/0012-budget-report-layout-contract.md — 记录明确排版要求优先于旧样例字号等冲突及新门禁。
- results/budget_operations/矿山板块_排版修复_20261026/ — 本轮完整报告、变更说明与验收证据，保留历史文件。
- .scratch/budget-report-layout/ — 可重复的本轮生成与验收脚本、局部运行记录（如需要）。

### 修改

- src/long_report/rendering.py — 统一样式、字体、封面、真实目录/收敛兜底、分页表格与排版核验。
- src/long_report/application.py — 项目/发布元信息、快照与可读版本、生成日期及交付门禁，复用现有修订事务。
- src/long_report/charts.py — 仅在缺陷证据需要时完善图文尺寸、字体或标注，仍引用已核验数据。
- tests/test_budget_report_profile_cli.py、tests/test_project_cli.py及相关发布回归测试 — 排版意图和门禁回归，其他场景回归。
- docs/scenarios/预算经营分析-场景规格.md、docs/模块设计-数据与执行契约.md、.agents/skills/long-report/SKILL.md — 同步稳定格式、元信息及交付检查，不加入固定单位/月份/目录。

### 删除

None

### 明确不建

- 独立报告引擎、第四场景、固定矿山profile、网页编辑器或任意企业Word模板导入器 — 复用现有Python核心与CLI、动态计划和源快照即可。

## 来源覆盖

| 来源条目及位置 | 阅读状态 | 保留内容 | Spec位置 | 验收ID | 覆盖状态 | 原因或替代关系 |
| --- | --- | --- | --- | --- | --- | --- |
| 用户消息：封面清单 | complete | 报告名称、统计期间、实际生成日期、分析对象、数据性质、保密说明。 | specs/budget-report-layout/spec.md：封面与版本 | A1 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.5.1 | complete | DOCX/PDF目标兼容Word 2019+、Microsoft 365和常用WPS；仅声明实际执行的兼容测试。 | specs/budget-report-layout/spec.md：验收与交付 | A8 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.5.2 日期 | complete | 区分经营统计期间、材料版本/快照、实际生成日期、报告修订版本；不得以上传日期替代生成日期。 | specs/budget-report-layout/spec.md：封面与版本 | A1 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.5.2 版本 | complete | 使用可读递增修订版本并说明变更；保留内部修订ID用于追溯，不能用随机短ID代替报告版本。 | specs/budget-report-layout/spec.md：封面与版本 | A1 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.5.3 标识 | complete | 封面采用用户指定名称、公司与期间；从有效源数据核实期间，实际/模拟数据明确区分，保密等级依授权。 | specs/budget-report-layout/spec.md：封面与版本 | A1 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.6 样式 | complete | 使用真正的Title、Heading 1—3、Normal、Caption、TOC 1—3和独立表格正文/表头样式；保留已有更深层级。 | specs/budget-report-layout/spec.md：统一样式与字体 | A2 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.6.1 字号 | complete | 封面20—22磅；一级16、二级14、三级12；正文10.5—11、表格9.5—10.5、图表标题10.5、页眉页脚9、目录10.5—11。 | specs/budget-report-layout/spec.md：统一样式与字体 | A2 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.6.1 字体 | complete | 中文正文宋体、标题黑体；英文和数字Times New Roman；正式企业模板可统一覆盖。 | specs/budget-report-layout/spec.md：统一样式与字体 | A2 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.6.2 字体属性 | complete | 覆盖默认样式、标题、正文、表格、页眉页脚、Caption、目录和局部强调的eastAsia/ascii/hAnsi，必要cs与中文语言。 | specs/budget-report-layout/spec.md：统一样式与字体 | A2 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.6.2 环境 | complete | 核查字体安装，缺失时采用已安装可靠CJK字体并实渲染验证；不得缺字、乱码或严重字宽变化。 | specs/budget-report-layout/spec.md：统一样式与字体 | A2 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.6.3 强调 | complete | 正文只对关键利润、重要风险、结论和必要术语有限加粗；禁止无理由整段加粗及滥用装饰，标点数字单位正常间距。 | specs/budget-report-layout/spec.md：统一样式与字体 | A2 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.7 强制目录 | complete | 正式报告必须有完整中文目录，不能交付空白、英文占位符或只有字段的目录。 | specs/budget-report-layout/spec.md：目录 | A3 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.7.1 位置 | complete | 封面第一页，目录第二页起并可延续；目录后进入摘要和分析正文，不覆盖内容。 | specs/budget-report-layout/spec.md：目录 | A3 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.7.2 标题 | complete | 目录标题为“目录”，不得残留Table of Contents。 | specs/budget-report-layout/spec.md：目录 | A3 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.7.3 层级 | complete | 目录依据真实Heading 1—3；保留主模板单位编号、顺序与层级，不以普通段落视觉效果假冒。 | specs/budget-report-layout/spec.md：目录 | A3 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.7.4 动态 | complete | 优先真实TOC字段TOC \o "1-3" \h \z \u，必须实际更新，含页码、点引导线、跳转及正确顺序；仅设置打开更新不算完成。 | specs/budget-report-layout/spec.md：目录 | A3 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.7.5 静态 | complete | 不能可靠更新动态目录时，静态目录从真实结构提取，保留层级、中文标题、真实页码及内部跳转。 | specs/budget-report-layout/spec.md：目录 | A3 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.7.5 收敛 | complete | 目录插入后重新排版测量直到页码一致；禁止预测页数和按章固定页数。 | specs/budget-report-layout/spec.md：目录 | A3 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.7.6 门禁 | complete | 检查目录非空、中文标题、实际层级、顺序与页码匹配、无重复/过期/英文占位，失败阻止正式交付。 | specs/budget-report-layout/spec.md：目录 | A7 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.8.1 封面 | complete | 独立一页，简洁居中或按正式模板；包含标题、期间、编制部门、数据性质、日期、版本、保密说明和分析对象；无正文分析。 | specs/budget-report-layout/spec.md：封面与版本 | A1 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.8.2 正文 | complete | 完整标题只在封面出现；目录后直接进入第一章；元信息集中，必要业务限制仍就地披露。 | specs/budget-report-layout/spec.md：正文与章节 | A4 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.8.3 编号 | complete | 统一第一章/1.1/1.1.1，章节遵从本轮主模板；保留单位原有名称、顺序和已有编号，禁止全局写死目录及单位。 | specs/budget-report-layout/spec.md：正文与章节 | A4 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.9.1 页面 | complete | A4纵向、统一商务页边距、正文1.3—1.5倍行距与分级段间距；超宽表独立横向节或附录，不改变全篇方向。 | specs/budget-report-layout/spec.md：分页与表格 | A5 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.9.2 起页 | complete | 封面、目录、第一章独立起页，主要章节优先另起页；避免标题孤悬、表题分离、单位标题脱离综述及一两行独占页。 | specs/budget-report-layout/spec.md：分页与表格 | A5 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.9.3 段落 | complete | 正确设置keep_with_next、keep_together、page_break_before和widow_control，避免连锁绑定导致不必要空白。 | specs/budget-report-layout/spec.md：分页与表格 | A5 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.9.3 表格 | complete | 重复表头、合理列宽、金额右对齐、文本左对齐；允许合理跨页但重要记录不拆，表格不溢出正文区域。 | specs/budget-report-layout/spec.md：分页与表格 | A5 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.10 协调 | complete | 图表与正文协调，字体清楚，不能方框、缺字、乱码、字号过小、数字单位重叠、图例裁切。 | specs/budget-report-layout/spec.md：图表与单位布局 | A6 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.10.2 图注 | complete | 每张图表包含编号、标题、统计期间、单位、数据来源；模拟数据清楚标注。 | specs/budget-report-layout/spec.md：图表与单位布局 | A6 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.10.3 嵌入 | complete | 图以高清PNG或兼容对象实际嵌入Word，宽度不超过正文；不能只留文件路径。 | specs/budget-report-layout/spec.md：图表与单位布局 | A6 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.10.4 一致 | complete | 图表来自同一已核验数据模型，不另造财务数据；表格保持可编辑。 | specs/budget-report-layout/spec.md：图表与单位布局 | A6 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.10 第四章 | complete | 参考单位标题→综述→利润表→经营变化文字→生产成本表→经营判断关注；保留本轮每户双表及自己的可比图。 | specs/budget-report-layout/spec.md：图表与单位布局 | A6 | covered | 本轮有效要求；优先于旧样例冲突值。 |
| 用户消息：10.10 篇幅 | complete | 完整保留必要单位及表图，不设50页硬上限，不凑页数、不删必备信息；用分页、列宽和图片尺寸改善布局。 | specs/budget-report-layout/spec.md：图表与单位布局 | A6 | covered | 本轮有效要求；优先于旧样例冲突值。 |

# 非目标

不重新编造财务数据、扩展分析对象或模型，不改变经营结论和业务签认状态；不自动合并、提交、推送或覆盖旧已发布版本。不保证未实测Office软件的兼容性，不为控页删除单位表图，不把旧样例固化为全场景默认目录。

# 约束与决策

1. 用户已选择当前目录/分支；实际为`fix/output-format`。保留原有`.gitignore`改动、历史DOCX删除及未跟踪PDF，不纳入本次修复。
2. 单个Native变更完成：问题耦合于同一元信息→渲染→验收链路，拆分子变更会增加共用文件协调成本。
3. 本轮明确字号要求替代旧样例24/15/12.5磅；默认采用22/16/14/12磅。中文字体须检查环境，不机械复制缺字的样例渲染。
4. 报告名称优先保留用户现有明确指定名称；统计期间从本轮原件和冻结证据核实，区分当月7月与累计1—7月。分析对象按实际六矿和专项，不因旧项目organization为“集团合并”就误标为集团全范围。
5. 初始语义版本采用V1.0，修订递增；旧报告只有内部ID时保留旧ID并明确迁移/修订说明，不冒充历史上已经有V1.0。新文件的具体版本在版本来源核验后填写，不硬编码通用发布版本。
6. 当前原件明确含MOCK，保持模拟数据与pending_review。未提供保密授权/等级的项目清楚写明未指定/待确认，不自动编造“秘密”等级；现有参考“内部资料，注意保密”仅为参考措辞。
7. 优先真实动态目录且实际更新；若环境无法可靠更新，沿现有最终PDF实测迭代方案完善静态目录及跳转，并披露采用兜底及依据。
8. 不新增财务结果；允许规范章节编号、图表注记和版式元信息，数值、来源、单位名单及正文分析内容须对照回归。

# 验收示例

- A1：重新生成的矿山报告封面单独一页，完整展示用户指定报告名称、核实后的当月及累计统计期间、实际生成日期、分析对象、编制部门、明确模拟标识、可读修订版本、数据快照身份和保密说明。名称不擅改，日期不取上传日；修订不覆盖20261024历史文件，缺少保密授权不得编造等级。
- A2：DOCX使用统一真实Word样式；封面22、一级16、二级14、三级12、正文10.5、表格10、Caption10.5、页眉页脚9、目录10.5磅，正确设置东西文字体和必要语言，有限强调。字体缺失有可核实替代及渲染证据，无缺字乱码或严重字宽变化。
- A3：封面后第二页起中文目录包含实际Heading 1—3，顺序和层级正确、点引导线、实际页码及内部跳转；优先已更新动态目录，不能可靠更新时使用实测且迭代收敛的静态目录并记录原因；不存在重复、旧项或占位目录。
- A4：目录后直接进入第一章，正文不重复报告总标题；章节编号规范，单位原名原顺序及已有编号保留，当前计划决定章节及对象，既有Heading 4行为不退化，关键业务限制继续在受影响处披露。
- A5：A4纵向及统一页边距、行距、段间距合规；主章分页，标题及表题与紧接内容绑定，控制孤行和无谓空白；表头跨页重复、记录不误拆、列宽不溢出、金额右对齐文本左对齐，超宽表局部处理。
- A6：本次九章、六矿、独立专项、18张表及7张图完整保留，表格可编辑、图实际嵌入，数据与原核验模型一致；每张图表编号、标题、期间、单位、来源及模拟标识齐全；第四章保留逐户综述、利润表、变化分析、生产成本表、判断关注与可比图，不以页数裁剪。
- A7：发布前有封面/样式/目录/分页/表图排版检查；对元信息错配、空或错页目录、样式伪标题、溢出/缺失表图等可判定缺陷有失败用例，失败阻止交付且不破坏既有已发布文件。
- A8：运行相关单元测试、完整unittest与report scenarios，实际渲染并逐页审看重新生成的完整DOCX/PDF，保存结果及变更说明；仅声称实际执行过的Word/Microsoft 365/WPS兼容测试。输出仍明确MOCK与pending_review，业务签认不被排版修复替代。

# 验证要求

测试适当覆盖实测页码收敛、多页目录、重复小节标题跳转、长中文标题、负数及金额对齐、长表重复表头、字体替代及错误元信息阻断。运行`.venv/bin/python -m unittest discover -s tests -v`和`.venv/bin/report scenarios`，任何跳过或环境限制单独披露。最终逐页审看生成PDF，并检查DOCX结构、实际嵌图与目录页码；Word 2019/Microsoft 365/WPS分别记录实际测试状态。
