# 江铜华北财务尽调真实模型对比 统一作者任务

你是本实验的独立报告作者。目标是依据同一原始材料快照生成可追溯、实质分析充分的财务公司授信评审报告，必须实际完成标准CLI归档后流程：run start、task submit、evidence decide/freeze、calculate、draft plan/context/submit/build。这是实际模型执行，不是模拟或现有报告改名。你只负责自己的实验目录，不能修改共享runtime、共同材料、产品源码或其他作者目录；你不是唯一在工作的Agent，不要覆盖或回滚其他人的文件。不要读取另一作者或用户旧报告、历史报告正文或参考稿。

工作位置：本文件所在目录为experiment；manifest.json保存python、runtime及基准项目id。模型gpt-6.1-sol用sol/；gpt-6.1-terra用terra/。各自projects/已从同一仅完成材料归档的项目复制，项目id相同，数据库及后续run独立。common/corpus中的51份material JSON为同一标准CLI实际返回，包含全部原件及可追溯OCR衍生物。原始来源和存档材料只读。原始30份文件以及21份OCR的哈希由bootstrap核对；OCR为历史衍生物复用，本次未重新OCR，也不冒称已逐页核读。

执行统一命令：manifest.python -m long_report ... --workspace <你的目录/projects> --request <你的UTF-8 JSON>，进程环境PYTHONPATH必须是manifest.runtime/src，以使用共同冻结代码，而不是宿主默认代码。可以写Python驱动脚本用subprocess调用上述CLI、保存请求响应。所有正文均由你判断起草，脚本只用于确定性提取、引用替换、CLI编排；不能用循环拼通用句、模板填充器或已有报告代替模型逐章分析。

在你的目录保存：execution.json（实际模型和medium设置、调用/时间/代码与材料哈希、失败及修复次数、边界）、所有CLI请求响应日志、完整候选MD、draft.json（build响应）、author-notes.md。最终只交接候选及问题清单，**不自审、不提交review、不publish**。审阅由作者外执行。出现引擎阻断，保留原始错误，通知主Agent，不能篡改共享引擎或数据库绕过。

## 证据与计算

先阅读runtime/scenarios/financial_due_diligence的四个YAML和common/corpus。材料源定位在parsed内；按本轮检查的实际单元格或文本行提交候选，value=source_value；不能伪造定位。为没有选取事实的材料提交candidates=[]并在material_uses标注context/excluded及具体理由。已接受事实的材料必须analysis；analysis材料需正文事实/calc引用（含衍生物对应原件）或“材料缺口：原文件名：具体影响”一行，不能仅ev引用替代实际使用。

原始XLSX中跨表公式可能被标cached_unverified、pending_verify或cache_mismatch，不能直接accept这些源值。可编程从本轮已检查的原单元格/缓存生成归一CSV，material add时提供derivation={source_id,source_sha256,method,locator_map}，locator_map必须覆盖CSV所有非空单元格，每个值定位回原件合法locator（原文件的sheet:.../cell:...，或PDF page:N）。方法明确单位转换、原缓存尚未原生复算等限制；不能把未知缓存标成验证通过。根据原始表、审计附注、OCR主表交叉核对数值，存在差异并列披露。

财务计算注册在analysis.financial_metrics；引擎使用以下metric_id：fin.revenue、fin.net_profit、fin.cost、fin.assets、fin.liabilities、fin.current_assets、fin.current_liabilities、fin.inventory、fin.receivables_open、fin.receivables_close、fin.inventory_open、fin.inventory_close、fin.equity_open、fin.equity_close。每个候选明确unit（元/万元/亿元）、financial_scope（standalone/consolidated）、period（期末YYYY-MM-DD）、period_start、period_days（明确采用实际或180/360等的口径）、financial_version（如区分同一期间不同报表版本时）。同一期平均余额的opening/closing用相同期间身份，不混合单体和合并。calculate自动生成净利率、毛利率、负债率、流动/速动、应收/存货周转次数及天数和ROE，基期或分母缺失返回缺口状态，不引用value=None的记录。计算结果annualization=none，不能将中期未年化指标与全年直接比下降速度。新增其他派生数值须用可复算归一CSV入库并说明方法，不能让语言模型口算填表。

已有营运资金两sheet结果是外部业务模型结果，仅核对来源/定义/版本，不在本项目重建授信模型。材料中有收入目标冲突、保证金/列报差异、合并与单体等，实质解释并限定判断，不强行消差。评级、期限/利率/担保政策未取得则对应保留，不自己制定数值红线，不以股东背景代替担保。

## 正文与质量

固定九章及31个二级标题与三级子标题、工商股权两类表格严格按场景outline；每章正文按##提交小节且各Markdown块空行分隔，第四章无二级标题。正文应评价真实经营能力、有据优势、发展条件和风险，不能只写缺件或风险清单，也不能预设正面结论。尽量用已有供销、产销、财务、融资明细逐表解释机制及现金意义。适用基础表必须提供实数；某表确实未取得，使用“资料缺口：<required_assets原名>：具体影响与所需材料”完整一行。表标题格式“表3-1 财务比率表”，下一空行紧接Markdown表（标题须含required_assets的名称），不伪造空数据。

数字通过{{fact:id}}或{{calc:id|精度}}引用，包括无单位表内金额、百分比、倍次、天数和产品数据；来源用{{ev:id}}。年份、日期、Markdown标题和表序号可直接写，其余阿拉伯数字不得裸写（如产品8.0mm、T1R等也可作为原件事实片段引用；表内序号用汉字或合法引用）。引用整段原文不得带入冲突标题或未核因果。引用值若需万元换算应先建立正确的归一衍生事实，不能取原始元值直接标万元。

第二至五章每表有专属解读，不按表数代表深度。区分期末余额与销售流量、含税与未税、净额与毛额、关联方穿透与控制、已执行与建议、历史案件与当前状态。三项损益加总不能单独证明套保有效；负经营现金流不能推出没有销售收现/第一还款来源完全失效。阅读真实万得档案中的开庭信息；原件可读程度由逐页覆盖提供，不凭PDF格式判断整个文件不可读。正文不介绍内部CLI实现细节，技术限制集中在来源或说明，综合结论回指实质发现。

报告允许pending_review，缺口清楚即可继续其他分析。封面及字体由共同runtime配置决定；实验字体STFangsong是公开例外，正式配置仿宋未通过。不得自行改为其他字体或手工绕过标准build。不要为压缩时间省略分析维度；不新增报告页数或事实条数硬指标。

完成draft build后停止报告流程。向主Agent返回候选MD、draft.json、工作项目/run id、日志和未解决限制；不伪造独立审阅或业务签认。
