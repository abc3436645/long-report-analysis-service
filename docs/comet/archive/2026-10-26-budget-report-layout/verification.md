---
generated_from_state_version: 11
---

# 验证

## 当前结果

- 结果: **已归档**
- 验证情况: **已完成检查，验证结果已确认**
- 目标周期: 1
- 迭代: 2
- 验证器尝试次数: 1
- 完成时间: 2026-10-26T08:13:07.089Z
- 摘要: A1—A8逐项独立核查通过。当前候选55项完整单测无skip、三场景加载及交付/返修门禁均通过；补充Runtime明确缺陷探针和116块非空内容/原件/历史哈希复核通过。已查看当前绑定的全部34页PNG，41项目录及PDF跳转对应实测页，18表7图及九章六矿完整保留。保留静态目录编辑后重生、Office未实测、MOCK/pending_review和核查过程偏差披露。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1：重新生成的矿山报告封面单独一页，完整展示用户指定报告名称、核实后的当月及累计统计期间、实际生成日期、分析对象、编制部门、明确模拟标识、可读修订版本、数据快照身份和保密说明。名称不擅改，日期不取上传日；修订不覆盖20261024历史文件，缺少保密授权不得编造等级。 | 当前DOCX/PDF封面独立第一页，用户原指定完整标题保留；统计期间为当月2026年7月及累计1—7月，实际生成日2026-10-26，六矿及独立专项分析对象、预算办、MOCK、V1.0、冻结快照f7fad1805acc4eddbe5f791d6a68ce43及保密待确认齐全。_cover_metadata与版本回归验证生成日和递增版本，独立Runtime verifier-source-fidelity-exact核对冻结month/ytd、13份原件及旧MD/DOCX/PDF manifest哈希未变；变更说明明确历史只有内部修订ID，不伪造历史版本。 |
| A2 | passed | brief.md | A2：DOCX使用统一真实Word样式；封面22、一级16、二级14、三级12、正文10.5、表格10、Caption10.5、页眉页脚9、目录10.5磅，正确设置东西文字体和必要语言，有限强调。字体缺失有可核实替代及渲染证据，无缺字乱码或严重字宽变化。 | 独立读取最终DOCX真实Title/Heading1—4/Normal/Caption/TOC1—3/Table Body/Table Header/Header/Footer样式、字号及东亚/西文/语言属性；22/16/14/12/10.5/10/10.5/9/10.5磅符合要求。实现覆盖docDefaults、明确字体及主题清理，实际解析Songti SC、Heiti SC、Times New Roman；当前55项全回归中的字体缺失与替代、真实样式、局部强调测试通过。已查看全部34页PNG，无可见缺字乱码、异常整段强调或严重字宽变化。 |
| A3 | passed | brief.md | A3：封面后第二页起中文目录包含实际Heading 1—3，顺序和层级正确、点引导线、实际页码及内部跳转；优先已更新动态目录，不能可靠更新时使用实测且迭代收敛的静态目录并记录原因；不存在重复、旧项或占位目录。 | 最终PDF第2—3页为中文目录，第4页进入第一章；41项来源为真实Heading1—3，层级、顺序、点引导线与正文实测页码一致。render_paginated_docx以最终PDF反复测量至收敛，兜底原因和正文编辑后需重生限制已披露。当前Runtime delivery通过结构与链接计数检查；Verifier另按目录页链接矩形阅读顺序核对41个PDF跳转目标，均指向对应测得页；重复小节使用不同书签目标，未见旧项或英文占位。 |
| A4 | passed | brief.md | A4：目录后直接进入第一章，正文不重复报告总标题；章节编号规范，单位原名原顺序及已有编号保留，当前计划决定章节及对象，既有Heading 4行为不退化，关键业务限制继续在受影响处披露。 | 最终目录后直接第一章，无重复报告总标题；九章及六矿原名、顺序和局部业务限制均保留。修复现位于共用application._number_budget_headings/build_draft，并由本次生成脚本复用；当前55项中的编号幂等、原章号/单位标识/附录、Heading4、不同动态计划及CLI正文组装回归通过，不是仅改交付脚本。116个正文/表格内容块与旧MD非空逐项比较一致。 |
| A5 | passed | brief.md | A5：A4纵向及统一页边距、行距、段间距合规；主章分页，标题及表题与紧接内容绑定，控制孤行和无谓空白；表头跨页重复、记录不误拆、列宽不溢出、金额右对齐文本左对齐，超宽表局部处理。 | 独立检查最终DOCX为A4纵向、左右2.3/上2.15/下2.0cm及正文1.3倍行距，标题/表题绑定、主章另起页、widow控制、重复表头、cantSplit、数值右对齐和文字左对齐符合实现与页图。完整34页未见孤悬表题、裁切或仅一两行独页，原29页19698.31/19405.62完整显示。当前Runtime wide-table-local-layout通过；完整55项含真实PDF10列局部横向后恢复纵向的4页回归及连续宽表不产生空节回归，修复不将全篇改横向。 |
| A6 | passed | brief.md | A6：本次九章、六矿、独立专项、18张表及7张图完整保留，表格可编辑、图实际嵌入，数据与原核验模型一致；每张图表编号、标题、期间、单位、来源及模拟标识齐全；第四章保留逐户综述、利润表、变化分析、生产成本表、判断关注与可比图，不以页数裁剪。 | 当前Runtime delivery及独立verifier-source-fidelity-exact确认九章、六矿、七宝山等独立专项、18张可编辑表与7张实际嵌图完整保留；116个正文/表格块、全部表单元格及7图原字节与旧核验交付一致，13份原件哈希有效。表图编号、标题、期间、单位、来源及MOCK注记齐全；全部7张图所在页均独立查看。第四章每户综述、利润表/图、变化分析、生产成本表、管理关注及人工确认保留，无按页数删减。 |
| A7 | passed | brief.md | A7：发布前有封面/样式/目录/分页/表图排版检查；对元信息错配、空或错页目录、样式伪标题、溢出/缺失表图等可判定缺陷有失败用例，失败阻止交付且不破坏既有已发布文件。 | publish_run在stage生效前调用verify_docx及verify_pdf_charts；失败清理暂存且不切换latest。当前55项中的失败发布保护与V1.0→V1.1回归通过。当前Runtime layout-gate-contract确认35cm纸宽、取消标题绑定、0.5正文行距均被拒绝；Verifier新增Runtime verifier-explicit-layout-failures确认封面错配、缺目录项、错页目录、伪标题、表溢出、缺表和缺图均抛错阻断。当前交付门禁通过，不以旧候选探针替代。 |
| A8 | passed | brief.md | A8：运行相关单元测试、完整unittest与report scenarios，实际渲染并逐页审看重新生成的完整DOCX/PDF，保存结果及变更说明；仅声称实际执行过的Word/Microsoft 365/WPS兼容测试。输出仍明确MOCK与pending_review，业务签认不被排版修复替代。 | 独立读取当前候选fc3d0738-d9ec-44d1-aa25-9e6d922157db的Runtime记录及全部6条原日志：完整unittest为55项/228.415秒、全部OK且无skip；report scenarios列出三场景；delivery、diff及两项返修探针通过。新增明确失败门禁及严格非空保真检查也由Runtime执行通过。最终34页PNG逐页查看，visual_qa绑定当前DOCX/PDF哈希且PNG逐张哈希匹配。完整MD/DOCX/PDF、变更说明和逐页核查均已保存；Word2019/M365/WPS明确未实测，MOCK、保密待确认与pending_review未被排版通过替代。 |

## 检查

| 检查 | 命令 | 工作目录 | 状态 | 退出码 | 耗时 |
| --- | --- | --- | --- | ---: | ---: |
| 完整单元测试 | -m unittest discover -s tests -v | . | passed | 0 | 228634 ms |
| 三场景加载 | scenarios | . | passed | 0 | 193 ms |
| 完整矿山交付与文档链接检查 | .scratch/budget-report-layout/verify_delivery.py | . | passed | 0 | 3640 ms |
| 补丁空白检查 | diff --check | . | passed | 0 | 37 ms |
| 错误页面尺寸与分页属性阻断检查 | -c import json from pathlib import Path from unittest.mock import patch from docx import Document from docx.shared import Cm from long_report.rendering import verify_docx out=Path('results/budget_operations/矿山板块_排版修复_20261026') qa=json.loads((out/'render_qa.json').read_text()) word=out/'矿山板块月度经营分析报告.docx' pdf=word.with_suffix('.pdf') markdown=word.with_suffix('.md').read_text() mutations=[('page_size',lambda d:setattr(d.sections[0],'page_width',Cm(35))), ('heading_binding',lambda d:setattr(d.styles['Heading 1'].paragraph_format,'keep_with_next',False)), ('line_spacing',lambda d:setattr(d.styles['Normal'].paragraph_format,'line_spacing',0.5))] rejected={} for name,mutate in mutations: document=Document(word) mutate(document) with patch('long_report.rendering.Document',return_value=document): try: verify_docx(markdown,word,qa['verified_chart_hashes'],metadata=qa['report_metadata'],toc_entries=[tuple(x) for x in qa['toc_entries']],pdf=pdf) except ValueError: rejected[name]=True else: rejected[name]=False print(json.dumps({'invalid_layout_rejected':rejected})) assert all(rejected.values()), 'publish layout gate accepted invalid page size, heading binding or body line spacing' | . | passed | 0 | 335 ms |
| 超宽财务表局部横向或附录处理 | -c from pathlib import Path from unittest.mock import patch from docx import Document from long_report.rendering import render_docx root=Path.cwd() template=root/'scenarios/budget_operations/templates/default-v0.2.0.docx' document=Document(template) headers=['指标']+[f'金额{i}（万元）' for i in range(1,10)] values=['经营指标']+['19698.31']*9 markdown='# 第一章 财务附表\n\n表1-1 宽表\n\n\| '+' \| '.join(headers)+' \|\n\| '+' \| '.join(['---']*10)+' \|\n\| '+' \| '.join(values)+' \|' error=None with patch('long_report.rendering.Document',return_value=document), patch('docx.document.Document.save'): try: render_docx(markdown,template,Path('/tmp/unused-budget-wide-probe.docx'),'宽表测试') except ValueError as exception: error=str(exception) local_layout=any(s.page_width>s.page_height for s in document.sections) or len(document.tables)>1 print({'wide_table_error':error,'local_landscape_or_split_appendix':local_layout}) assert error is None and local_layout, 'valid ten-column financial table was rejected instead of using local landscape or appendix' | . | passed | 0 | 225 ms |
| 独立核对明确排版失败门禁 | -c import json from pathlib import Path from unittest.mock import patch from docx import Document from docx.shared import Cm from long_report.rendering import verify_docx out=Path('results/budget_operations/矿山板块_排版修复_20261026') qa=json.loads((out/'render_qa.json').read_text()) word=out/'矿山板块月度经营分析报告.docx' markdown=word.with_suffix('.md').read_text() def first_toc(d): return next(p for p in d.paragraphs if p.style.name=='TOC 1') def empty_toc(d): p=first_toc(d);p._p.getparent().remove(p._p) def wrong_page(d): first_toc(d)._p.xpath('.//w:t')[-1].text='99' def fake_heading(d): next(p for p in d.paragraphs if p.style.name=='Heading 1').style=d.styles['Normal'] def missing_table(d): t=d.tables[0]._tbl;t.getparent().remove(t) def overflow(d): d.tables[0].columns[0].width=Cm(40) def missing_chart(d): i=d.inline_shapes[0]._inline;i.getparent().remove(i) def mismatched_cover(d): next(p for p in d.paragraphs if p.style.name=='Cover Metadata').text='统计期间：2099年7月' rejected={} for name,mutate in [('cover_mismatch',mismatched_cover),('empty_directory',empty_toc),('wrong_directory_page',wrong_page),('fake_heading_style',fake_heading),('table_overflow',overflow),('missing_table',missing_table),('missing_chart',missing_chart)]: document=Document(word);mutate(document) with patch('long_report.rendering.Document',return_value=document): try: verify_docx(markdown,word,qa['verified_chart_hashes'],metadata=qa['report_metadata'],toc_entries=[tuple(x) for x in qa['toc_entries']],pdf=word.with_suffix('.pdf')) except ValueError as error: rejected[name]=str(error) else: rejected[name]=None print(json.dumps({'rejected_mutations':rejected},ensure_ascii=False)) assert all(rejected.values()),'determinable layout defect was accepted' | . | passed | 0 | 2040 ms |
| 独立核对冻结材料与旧交付保真 | -c import json,re,sqlite3 from pathlib import Path from hashlib import sha256 from docx import Document root=Path.cwd();out=root/'results/budget_operations/矿山板块_排版修复_20261026';old=root/'results/budget_operations/矿山板块_新流程全文验收_20261024';name='矿山板块月度经营分析报告' a=(old/(name+'.md')).read_text();b=(out/(name+'.md')).read_text() def analysis(t): return [p for p in t.strip().split('\n\n') if not p.startswith(('#','![','表'))] assert analysis(a)==analysis(b) assert re.findall(r'assets/(chart_[0-9a-f]{24})\.png',a)==re.findall(r'assets/(chart_[0-9a-f]{24})\.png',b) work=root/'projects/mining_board_full_delivery_v3_2026_07';session=json.loads((work/'session.json').read_text());project=work/'projects'/session['project_id'];base=project/'revisions/1f984988b1de4d3ab9e36f57f0be5b4a' assert (base/'dist/full_report.md').read_text()==a manifest=json.loads((base/'manifest.json').read_text()) for key,ext in [('markdown','.md'),('docx','.docx'),('pdf','.pdf')]: assert sha256((old/(name+ext)).read_bytes()).hexdigest()==manifest['file_hashes'][key] with sqlite3.connect(f'file:{project / "state.sqlite"}?mode=ro',uri=True) as db: run=json.loads(db.execute('SELECT data FROM run WHERE id=?',(session['run_id'],)).fetchone()[0]) snapshot=json.loads(db.execute('SELECT data FROM evidence_snapshot WHERE id=?',(run['evidence_snapshot_id'],)).fetchone()[0]) materials=[m for row in db.execute('SELECT data FROM material') if (m:=json.loads(row[0]))['id'] in run['material_ids']] evidence=[e for row in db.execute('SELECT data FROM evidence') if (e:=json.loads(row[0]))['id'] in snapshot['evidence_ids']] for m in materials: assert sha256(Path(m['archived_path']).read_bytes()).hexdigest()==m['fingerprint'] qa=json.loads((out/'render_qa.json').read_text()) assert qa['report_metadata']['数据版本']==snapshot['id'] assert {'month','ytd'} <= {e.get('window') for e in evidence if e.get('period')=='2026-07' and e.get('basis')=='actuals'} for asset in (out/'assets').glob('*.png'): assert asset.read_bytes()==(base/'dist/assets'/asset.name).read_bytes() print(json.dumps({'analysis_blocks_identical':True,'original_delivery_hashes_verified':True,'archived_sources_verified':len(materials),'snapshot_and_period_windows_verified':True,'chart_bytes_identical':True},ensure_ascii=False)) | . | passed | 0 | 61 ms |
| 正文非空比较与冻结材料保真复核 | -c import json,re,sqlite3 from pathlib import Path from hashlib import sha256 from docx import Document root=Path.cwd();out=root/'results/budget_operations/矿山板块_排版修复_20261026';old=root/'results/budget_operations/矿山板块_新流程全文验收_20261024';name='矿山板块月度经营分析报告' a=(old/(name+'.md')).read_text();b=(out/(name+'.md')).read_text() def analysis(t): return [p for p in t.strip().split('\n\n') if not p.startswith(('#','![','表'))] assert len(analysis(a)) > 40, 'analysis comparison must not be empty' assert analysis(a)==analysis(b) chart_ids=re.findall(r'assets/(chart_[0-9a-f]{24})\.png',a) assert len(chart_ids)==7 assert chart_ids==re.findall(r'assets/(chart_[0-9a-f]{24})\.png',b) work=root/'projects/mining_board_full_delivery_v3_2026_07';session=json.loads((work/'session.json').read_text());project=work/'projects'/session['project_id'];base=project/'revisions/1f984988b1de4d3ab9e36f57f0be5b4a' assert (base/'dist/full_report.md').read_text()==a manifest=json.loads((base/'manifest.json').read_text()) for key,ext in [('markdown','.md'),('docx','.docx'),('pdf','.pdf')]: assert sha256((old/(name+ext)).read_bytes()).hexdigest()==manifest['file_hashes'][key] with sqlite3.connect(f'file:{project / "state.sqlite"}?mode=ro',uri=True) as db: run=json.loads(db.execute('SELECT data FROM run WHERE id=?',(session['run_id'],)).fetchone()[0]) snapshot=json.loads(db.execute('SELECT data FROM evidence_snapshot WHERE id=?',(run['evidence_snapshot_id'],)).fetchone()[0]) materials=[m for row in db.execute('SELECT data FROM material') if (m:=json.loads(row[0]))['id'] in run['material_ids']] evidence=[e for row in db.execute('SELECT data FROM evidence') if (e:=json.loads(row[0]))['id'] in snapshot['evidence_ids']] for m in materials: assert sha256(Path(m['archived_path']).read_bytes()).hexdigest()==m['fingerprint'] qa=json.loads((out/'render_qa.json').read_text()) assert qa['report_metadata']['数据版本']==snapshot['id'] assert {'month','ytd'} <= {e.get('window') for e in evidence if e.get('period')=='2026-07' and e.get('basis')=='actuals'} for asset in (out/'assets').glob('*.png'): assert asset.read_bytes()==(base/'dist/assets'/asset.name).read_bytes() print(json.dumps({'analysis_blocks_identical':True,'compared_analysis_blocks':len(analysis(a)),'original_delivery_hashes_verified':True,'archived_sources_verified':len(materials),'snapshot_and_period_windows_verified':True,'chart_bytes_identical':True},ensure_ascii=False)) | . | passed | 0 | 85 ms |

### Builder 报告的证据

以下为 Builder 报告，不等同于 Runtime 检查凭据或独立验收结果。

- 当前修复目标回归: passed — 排版相关16项加连续宽表1项、共用编号补充断言通过；预算计算2项通过。
- 独立失败探针复现后验证: passed — layout-gate-contract三项均拒绝；wide-table-local-layout错误为None且存在局部横向。
- 完整交付与视觉证据: passed — 34页/41标题/18表/7图/41链接；重新生成PNG与逐页审看版本逐张一致，当前SHA已更新。
- 当前完整unittest/scenarios: not-run — 由Runtime冻结修复候选后执行，不以旧候选51项替代。
- 已知限制: 未实际测试Word 2019/Microsoft 365/WPS；仅目标兼容环境。
- 已知限制: 目录采用实测收敛静态方案，在Word编辑后需重新生成。
- 已知限制: MOCK、保密未指定和原业务签认事项继续pending_review。
- 已知限制: 本次重新生成交付目录未修改历史项目数据库；既有CLI发布链路由合成回归验证。
- 已知限制: 如果表格连A4横向也无法完整显示数值，须先按列拆分源表为附录面板；不自动缩小数字或丢列。

## 阻塞项

_无。_

## 风险与跳过的工作

- Word 2019+、Microsoft 365 Word及WPS Office未实际测试；仅验证本机既有LibreOffice转换及生成文件，不能宣称这些Office兼容性已通过。
- 目录为实测收敛静态目录，带41个内部跳转；在Word中修改正文后须重新生成并核验页码，不是动态自动更新目录。
- 材料为MOCK，保密要求/等级未指定，原预算口径、合并抵销等业务签认事项仍待确认，交付保持pending_review。
- 本次完整矿山交付保存到新结果目录，未更新历史项目数据库；通用CLI发布事务由当前合成全回归验证。超过A4横向可读宽度的源表仍需先按列拆成附录面板，系统会明确报错。
- 本Verifier未重跑已绑定通过的完整测试或重渲染DOCX；复用当前Runtime证据并独立查看全部34页PNG。初版新增保真探针有转义错误，其正文比较结论已废弃；以verifier-source-fidelity-exact的116块非空比较取代。
- 核查顺序偏差：初次展开package的nested details时意外提前显示Builder handoff；随后独立核查实现、原件/历史哈希、当前Runtime日志及全部页图，并在结论前再次完整读handoff，未以Builder声明替代证据。

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 1 | fail | A4, A5, A7 | 本次矿山交付的封面、样式、目录和内容保真已改善；完整51项测试通过，但A4共用编号、A5超宽表局部处理、A7页面/分页门禁三个实现缺口需要返工。 | 2026-10-26T07:32:01.562Z |
| 1 | 2 | 1 | pass | — | A1—A8逐项独立核查通过。当前候选55项完整单测无skip、三场景加载及交付/返修门禁均通过；补充Runtime明确缺陷探针和116块非空内容/原件/历史哈希复核通过。已查看当前绑定的全部34页PNG，41项目录及PDF跳转对应实测页，18表7图及九章六矿完整保留。保留静态目录编辑后重生、Office未实测、MOCK/pending_review和核查过程偏差披露。 | 2026-10-26T08:13:07.089Z |



## 结论

A1—A8逐项独立核查通过。当前候选55项完整单测无skip、三场景加载及交付/返修门禁均通过；补充Runtime明确缺陷探针和116块非空内容/原件/历史哈希复核通过。已查看当前绑定的全部34页PNG，41项目录及PDF跳转对应实测页，18表7图及九章六矿完整保留。保留静态目录编辑后重生、Office未实测、MOCK/pending_review和核查过程偏差披露。
