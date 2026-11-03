# 财务尽调证据与计算操作

适用于financial_due_diligence 0.3.0及其新项目；旧项目保留冻结配置，不自动升级。业务含义见[场景规格](../../../../docs/scenarios/财务公司授信评审-场景规格.md)，字段与兼容约束见[ADR0017](../../../../docs/adr/0017-financial-evidence-quality.md)。

## 1. 归档和冻结

逐份归档当前原件，包括扫描PDF与JPG/PNG；在task context检查parsed.coverage的page_count、pages和unread_pages。无文本页面需要OCR或人工核读；文件有文本只表示部分可提取，不能认定主表已读取。完成判据是原件逐份有用途及理由，未读页、缺来源及来源冲突分开列明。

财务场景0.3.2已配置SoMark OCR槽位。material add归档后、run start之前，先按第4节判断相关内容确实无法直接读取，再对选定原件执行`report material ocr --workspace <项目目录> --services-config <部署服务YAML> --request <JSON>`；请求填写project_id、material_id，可用wait_seconds明确等待预算，SOMARK_API_KEY由部署环境提供。pending时重复同一请求恢复远端任务；succeeded/partial时读取derived_material_id及derivation.block_map核对页/坐标；failed时保留last_error及未读页缺口。活动运行先结束或取消，再继续OCR；识别文本仍须核读后进入候选，不将未读页为空当作内容已核验。

使用OCR/归一CSV时，material add提交derivation={source_id, source_sha256, method, locator_map}。原件必须先归档；locator_map覆盖衍生物全部非空单元格/文本行，值为原件合法sheet:名称/cell:A1、page:N或原始文本定位。method说明核读、转换和缓存限制。系统验证链接、哈希和定位存在性，不自动证明转录语义或单位正确。重试同字节且不同来源关系或不同解析格式必须报告，不能改写原件。归一CSV保留业务字段名和原始定位列，避免不同含义的单一数字产生同字节材料碰撞。

先完整梳理每份材料的候选再task submit，提交后不可追加同一任务的提取。原文/检索型字段的metric_id使用包含source_id及原定位的确定性名称，避免不同合同或CSV行误碰撞；fin.字段保留真实业务身份用于发现来源冲突，不靠随机名称掩盖差异。发现提取遗漏时用标准cancel/start重建本轮，保留旧记录。原文片段可用source_span=[起点,终点]选择原始source_value中的精确子串（Unicode码点、起点含终点不含）；程序核对定位、全文和片段一致；数值片段保留完整符号和小数，不裁掉负号或只取金额一部分。用此方式取清晰姓名、日期或条款，完整source_value继续留在证据，不将截断或乱码长段作为正文。金额归一仍保留转换方法与原定位。所有任务提交后核对候选来源、范围、单位及公式状态，再decide/freeze。未用材料可提交空候选，并在draft plan的material_uses中逐份说明analysis/context/excluded及reason；有已接受事实的必须analysis。analysis材料正文须fact/calc使用，或具名“材料缺口：原文件名：影响和待补内容”；仅ev引用不代表实质分析。

## 2. 描述性财务计算

按本轮检查过的原字段提交fin.revenue、fin.net_profit、fin.cost、fin.assets、fin.liabilities、fin.current_assets、fin.current_liabilities、fin.inventory，以及fin.receivables_open/close、fin.inventory_open/close、fin.equity_open/close。金额单位保留元/万元/亿元；同一期间的平均余额字段都绑定该期间身份。所有参与字段明确financial_scope=standalone或consolidated、period=期末日期、period_start=期间起日、period_days=明确天数；不同正式版本用financial_version区分。缺口径时保留未知。

report calculate生成注册的净利率、毛利率、负债率、流动/速动比率、应收/存货周转及天数、ROE，结果保留formula_version、input_evidence_ids、unit、annualization及34位Decimal计算precision。仅引用status=calculated；缺输入、分母零、范围不明或冲突使用状态说明。结果为未年化值，period_days采用实际天数或明确业务口径后披露，不能将年化误称未年化，亦不将半年数与全年数直接比作同比。

外部额度模型及评级结果按材料身份核对。多套结果、收入目标、保证金和报表列报差异保留来源及影响，交相应业务流程裁决；描述性财务计算不重建额度或评级模型。

封面额度使用application_credit_amount选择器：事实metric_id=credit_amount、basis=application、unit明确为元/万元/亿元，subject_id与项目主体、period与project.evaluation_date关联键一致。该关联键不代替申请书真实签章日；申请日另存事实并在正文区分财务基准、资料形成日和评审日。已知申请额却未匹配选择器时应修复事实绑定，不能把封面“待核实”当作真实金额缺件。

## 3. 起草和独立审阅

每个固定标题回答业务问题；required_assets有数据呈表，无资料用“资料缺口：表格契约名称：影响和所需材料”。表题为“表章号-序号 表格契约名称”，下一空行紧接表格。财务数字均引用fact/calc，含表头已有单位的表内数值、百分数、倍次和天数；日期、标题与表序号有结构例外。来源用ev。产品型号中的数字也从原文事实引用，避免绕开来源。

build后把review_requirements和完整候选交独立审阅者。每个coverage条目填写id、locator=line:N、quote（该行真实片段）、result=passed/gap/needs_changes、assessment和evidence_refs。passed需本轮事实/计算引用；gap说明判断限制，needs_changes修复后重建候选。系统核对31个固定小节、融资章、实际表格及capability/risk/mitigation/credit_terms四类结论的记录覆盖及位置；真实性与内容充分性仍由审阅者判断，不以异名ID或填完表代替独立审阅。

validate核对material_disposition、analysis_material_coverage、financial_binding、financial_review_coverage、candidate_integrity；失败修复后再publish。保留材料覆盖、计算及审阅缺口，pending_review不表示批准。金额或期间错误修复后同步重审风险、还款来源与综合结论。

## 4. 选择性 OCR 与最终底稿写作

先直接读取文件并检查相关章节、表格和字段的实际可辨性。`report material prepare`默认只检查，Agent结合本轮业务问题判断`needs_reading_decision`；原生未读页、PDF后缀或扫描外观不自动触发OCR。可直接取得且足以分析的文件继续提取事实；已存在可追溯有效文本优先复用。相关内容仍不能读取时，Agent在本轮底稿记录材料ID、页号、已尝试读取方式、所缺内容及选择理由，自行用`ocr_material_ids`选择原件调用prepare，无需用户逐份确认。mode=auto仅在选择OCR后决定同步/异步。partial保留未读页，pending恢复原任务，failed/submitting不批量重传；命令非零退出仍须读取data中的逐项结果。可用`run start --prepare-materials`衔接，awaiting_materials时没有活动运行，不能继续任务流程。无关空白页、视觉可核读项及明确缺口分别记录，不为清除计数调用服务。活动运行内新发现漏读先cancel，补充后重开；来源不在冻结后追加。

用户要求可直接修改的最终底稿时，逐条读取参考Word的批注和对应正文/表格，将要求映射到本轮证据和正文位置。先建逐节分析底稿，再提交章节。每个有数据的表格紧邻写关键变化及量级、已证原因/企业解释/待核假设、经营或现金传导、局部判断及必要动作；不得以“应分析”“需关注”等操作提醒替代现有事实的评价。重大余额即使变化小也分析，余额下降不自动表示风险消失；四类比率均用本轮计算结果及定义解释趋势。

所有可核实的正面基础、反向证据、相关方身份和跨章影响均保留；将原始人员履历整理为专业叙述，不逐行粘贴；已知的申请、存量、外部模型值、拟议条件逐项呈现并解释，缺政策不吞掉现有结果。报告正文不夹带服务故障排查、命令或工程验收文字；OCR调用轨迹、材料清单、公式勾稽和批注落点放配套底稿，业务事实缺口的补件与核查细节放锚定批注；影响判断的实质限制在正文简明保留。文稿完成不等于评级、额度或放款批准。

原生解析虽有文字但只有页码、乱码或缺少关键表格时，Agent可对单文件`material ocr`显式提交`pages: [页号]`选择补充页；它与默认未读页选择分别保存调用身份，原生结果不覆盖。服务收到整份文件，只有指定页内容注册为补充片段。页集合改变会形成另一调用，不应通过改变页集合规避已有任务恢复或制造重复请求；先核对现有调用及派生文字。

## 5. 业务正文与审阅批注（0.3.3）

读取analysis.writing_guidance.body_and_annotations及chapter_body_focus。先写主题事实与分析，再将资料核查、交叉核对、编辑提醒和补件要求分到对应的独立`<!-- review-note: 提示 -->`块（块内无空行）；Word渲染成前一可见块的原生批注。`ev`来源定位也转为批注，原始MD、事实绑定和审阅哈希仍保留全部内容。工商直接呈登记信息；股东分户介绍；财务保留表后解读；授信要素缺少依据时简写“待确定”，具体原因及待办放批注。

批注不是隐藏风险的通道。资金受限、回款压力、关联占用、减值及影响最终方案的未决条件须在业务正文表达其影响。每章新增expression审阅项，独立审阅者检查主题充分、分层恰当和风险完整；不允许用批注中的分析替代正文，不以关键词自动裁决。具名表格/材料缺口可在批注块内独立一行保留；正文仍应呈现已有事实或简明未定状态。
