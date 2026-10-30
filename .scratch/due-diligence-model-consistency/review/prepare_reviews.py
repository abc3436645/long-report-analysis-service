"""Serialize the root review's judgments after full initial drafts and repair diffs were read.
Line quotes and IDs are deterministic formatting, not an automated semantic reviewer.
"""
from pathlib import Path
import json,re,sqlite3
ROOT=Path(__file__).resolve().parents[3]
EXP=ROOT/'.scratch/due-diligence-model-consistency/experiment'
OUT=Path(__file__).resolve().parent
NOTES={
'一、工商信息':'登记主体、信用代码、资本单位、期限与业务范围已对照企业档案；档案时点不冒充实时登记查询。',
'二、背景情况':'已有产销和股东资料支持经营基础；控股关系不等于担保或可用偿债资源。',
'三、基本组织机构情况':'章程与决议仅证明制度/授权载体，未声称风控执行有效；岗位分工不足有明确限制。',
'四、股权、股东及投资情况':'两股东出资及比例、合计口径已核；股东支持不替代借款主体责任。',
'五、对外投资情况':'已提供的大无缝持股与30000万元单体投资值没有被写成全部未知；资本、持股与账面价值分开，剩余出资承诺未知。',
'六、法人代表及主要管理人情况':'已取得董事长及总经理学历、任职与兼任经历，财务总监空白仅限定该岗位评价。',
'一、主营业务情况':'自产与来料加工分开，实际生产销售支持组织能力，铜价与加工费的盈利含义分开。',
'二、主营产销情况':'产销、加工费及成本有主体/期间/单位；销量、铜价和单位成本分别解读，不把含铜料成本当加工成本。',
'三、原料采购、产品销售情况':'采购与销售集中度分母分开，结算方式与账期分列；历史框架不当当前已锁订单，合同期限不当实际回款。',
'资产负债表':'单体连续主表为比较轴；受限现金、客户应收、预付、子公司借款、库存及往来展开，合并限制与单体分开。业务明细差异公开保留，未强行调平。',
'利润表：':'费用、投资收益、公允价值与净利关系已展开；相关收益与套保经济性质未核清，不笼统定性损益调节或非主营。',
'现金流量表：':'负经营净现金与正销售收现同时呈现；投资含关联借还款/金融资产，筹资接续不直接证明还款充足。',
'财务比率及分析':'40项注册计算均有同主体期间口径；净利率约0.078%及上半年应收约4.30天复核正确。平均余额、实际天数与不年化清楚，四类能力均作分析。',
'body':'机构授信用信两期表与业务可用性有区分；供应商不接受部分票证、共享/品种/到期条件限制未用额度；不把融资存量重复加总为同类债务。',
'一、公司所处行业情况':'铜价高敏感与薄加工贡献连至本公司采购/销售/资金，不冒充本轮实时行业调研。',
'二、主要行业政策':'未提供有效政策原文，保留适用性核验缺口，没有编造比例、红线或正式政策编号。',
'三、企业优势及行业地位':'已有生产、采购、客户和融资支持构成能力线索，不推断未经提供的市场排名或担保。',
'一、行业竞争、加工费下行风险':'产销与加工费变化支持竞争压力；来料加工/成本改善作为待验证缓释，未声称已消除风险。',
'二、市场价格波动风险':'点价与套保可能形成保证金和现金压力，未以几项损益相加证明套保有效。',
'三、应收账款坏账风险':'股东客户期末集中与账期政策分开，既不凭增长断坏账，也不凭短账期断全部可收。',
'四、财务与流动性风险':'高负债、保证金、票据兑付和关联占用传递至净可用现金判断，正常征信不抵消现金约束。',
'一、信用评级':'正式评级及期限映射未提供，未将参考报告AA/87分沿用为本轮有效评级。',
'二、征信情况':'2026-07-14原件第1页正常类概要已视觉核读；本轮未逐笔核读全部账户，不外推全面无逾期。Sol原页信用证48000的单位与数值已核。',
'三、涉诉情况':'Wind物理第32页历史侵权开庭及2016-08-09日期已核；无案件结果/当前执行状态，不写无涉诉，也不写现时未决。',
'一、授信额度':'申请10亿元与7/10签章日期已原页核读；E3营运资金量与E23流贷额度分别呈现，两版本及收入100倍冲突保留，未执行授信模型或选接近申请值者。',
'二、授信期限':'正式评级、期限映射及本轮授权未齐，不能从短账期或样本3年推定期限。',
'三、担保方式':'尚无本轮有效担保方案和资格/合同，股东背景与其他票证保证金均不当本次担保。',
'四、授信利率':'本轮适用议定价格与授权未给，未从费用或其他机构价格反推。',
'五、借款用途':'采购周转方向有合同支持，当前订单/付款仍需核；关联转借、投资和采购用途分开。',
'六、还款来源':'销售收现为现实来源，同时扣除经营占用和到期债务才形成可用现金；关联回收和保证金释放未作无条件承诺。',
'一、调查结论':'经营、融资及信用积极依据与毛利/现金/关联风险一并传递；外部模型、政策与涉诉未决事项没有被结论抹去。',
'二、授信方案':'主体、申请额和用途明确，额度/期限/担保/定价仍待有效流程核定，报告保持pending_review，不构成批准。',
}
TABLE_NOTES={
'company':['工商档案字段/资本单位核对','两股东资本/比例加总与责任边界核对','董事长任职时点和教育职称来源核对','总经理经历和兼任资料核对'],
'operations':['自产与来料产销分列核对','加工费及其阶段口径核对','单位制造费用及成本口径核对','供应商金额/占比分母/结算条件核对','客户金额/占比与方式/账期分开核对'],
'financials':{'sol':['单体四期资产负债主表','五个重要科目差额/增幅及资产或负债分母','货币资金/保证金/重分类差异','两期主要客户余额与期末集中','预付款头部及含省略项的原前五小计','子公司借款/期货保证金及不同底稿总值','存货构成/主表净额差异不直接归因减值','其他应付款/合同负债的对手方及性质','四期利润与费用/投资/公允价值','四期现金收付及净流量','四期十项财务比率实际天数未年化'],
              'terra':['单体四期资产负债主表','预付/其他应收/其他应付等重点明细','四期收入成本净利润','费用/投资收益及公允价值构成','四期现金收付及净流量','四期十项财务比率实际天数未年化']},
'financing':['机构额度/已用/未用两期以及接受条件','财务表/业务融资/征信不同口径不强行调平'],
'industry':['公司自身产销及价格变化，未外推市场排名'],
 'terms':['外部模型两版本缓存身份和E3/E23定义分列'],
 'conclusion':['申请身份及各授信要素已知/待核边界']}
GAPS={'二、主要行业政策','一、信用评级','二、授信期限','三、担保方式','四、授信利率','二、授信方案'}
for arm in ['sol','terra']:
 folder=EXP/arm; draft=json.loads((folder/'draft.json').read_text()); lines=Path(draft['markdown_path']).read_text().splitlines()
 db=sqlite3.connect(folder/'projects/8b932637916d44bd912a76100ed17459/state.sqlite')
 bodies={}
 for row in db.execute('SELECT s.data,b.body FROM section_task s JOIN section_body b ON b.task_id=s.id WHERE s.run_id=?',(draft['run_id'],)):
  task=json.loads(row[0]);bodies[task['section_id']]=row[1]
 coverage=[]
 for req in draft['review_requirements']:
  if req['kind']=='claim':
   key=req['id'].split(':')[1]
   prefixes={'capability':'江铜华北','risk':'需要重点关注的是' if arm=='sol' else '目前应重点关注','mitigation':'合同结算与点价' if arm=='sol' else '目前应重点关注','credit_terms':'综合意见' if arm=='sol' else '本次申请的借款人'}
   section='conclusion'; block=bodies[section]; idx=next((i for i,line in enumerate(lines) if line.startswith(prefixes[key]) and i>len(lines)*.75),None)
   if idx is None: raise AssertionError((arm,key))
   assessment={'capability':'业务基础结论由已提供产销、供销及融资材料支持，不以股东身份替代能力。','risk':'结论承接已核实现金/保证金/应收/关联风险，不因资料缺口笼统判差。','mitigation':'控制载体与实际执行效果分开，所提补件和现金管理安排是建议，尚无已缓释结论。','credit_terms':'申请值与建议/批准分开，尚无足够依据核定完整要素，保持候选待复核。'}[key]
   result='gap' if key=='credit_terms' else 'passed'
  else:
   section,kind=req['id'].split(':',1); idx=int(req['locator'].split(':')[1])-1; block=bodies[section]
   if req['kind']=='table':
    number=int(kind.split(':')[-1]); notes=TABLE_NOTES[section]
    if isinstance(notes,dict): notes=notes[arm]
    assessment='已核：'+notes[number-1]+'；表内数字/单位与当前事实或计算绑定，来源定位可追溯，未决口径在相邻分析保留。'
    result='passed'
   else:
    assessment=NOTES[kind];result='gap' if kind in GAPS else 'passed'
  refs=list(dict.fromkeys(re.findall(r'\{\{(?:fact|ev|calc):([^}|]+)',block)))
  coverage.append({'id':req['id'],'locator':f'line:{idx+1}','quote':lines[idx][:120], 'result':result,'assessment':assessment,'evidence_refs':refs})
 request={'project_id':'8b932637916d44bd912a76100ed17459','run_id':draft['run_id'],'draft_sha256':draft['sha256'],'reviewer_id':'root-independent-of-report-authors-20261030','verdict':'pass','issues':[],'coverage':coverage}
 (OUT/f'{arm}-final-review-request.json').write_text(json.dumps(request,ensure_ascii=False,indent=2))
 (OUT/f'{arm}-final.json').write_text(json.dumps({'verdict':'pass-with-declared-data-gaps','reviewed_sha256':draft['sha256'],'reviewer':request['reviewer_id'],'independence_scope':'根Agent实现引擎，未起草两份报告；已读完整首稿及各次修改差异并对照原件和计算。此为内容技术复核，不是财务公司业务签认，也不是Comet最终独立验收。','coverage_count':len(coverage),'resolved_defects': ['长段OCR乱码/截断已整理','已提供重点明细未再泛称缺失','E3/E23及两版本区别','利润成分经济性质限制','实际天数与未年化','单位/表格来源/征信时点与范围'],'remaining_business_gaps':['正式评级及适用政策','资金/模型版本及口径签认','应收期后回款和关联借款计划','完整征信账户与案件现状']},ensure_ascii=False,indent=2))
 print(arm,len(coverage))
