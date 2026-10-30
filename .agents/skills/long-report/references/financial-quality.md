# 财务尽调证据与计算操作

适用于financial_due_diligence 0.3.0及其新项目；旧项目保留冻结配置，不自动升级。业务含义见[场景规格](../../../../docs/scenarios/财务公司授信评审-场景规格.md)，字段与兼容约束见[ADR0017](../../../../docs/adr/0017-financial-evidence-quality.md)。

## 1. 归档和冻结

逐份归档当前原件，包括扫描PDF与JPG/PNG；在task context检查parsed.coverage的page_count、pages和unread_pages。无文本页面需要OCR或人工核读；文件有文本只表示部分可提取，不能认定主表已读取。完成判据是原件逐份有用途及理由，未读页、缺来源及来源冲突分开列明。

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
