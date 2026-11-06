"""Editorial notes stay available to reviewers without becoming report prose."""
import tempfile
import unittest
from pathlib import Path
from docx import Document
from long_report.annotations import annotated_blocks, verify_comments
from long_report.rendering import render_docx, report_fonts
from long_report.financials import review_requirements, validate_review_coverage


class ReportAnnotationTests(unittest.TestCase):
    def test_pdf_radicals_use_normal_han_in_body_while_raw_source_stays_traceable(self):
        md = '流动资⾦不得⽤于股东分红，比例①为10%。〔来源：资⾦规定〔2024〕.pdf，page:1〕'
        blocks = annotated_blocks(md, {'annotations': 'word_comments'})
        self.assertEqual(blocks, [('流动资金不得用于股东分红，比例①为10%。',
                                   ['来源：资⾦规定〔2024〕.pdf，page:1'])])
        self.assertEqual(annotated_blocks(md, {}), [(md, [])])

    def test_bracketed_policy_year_stays_in_comment_without_leaking_filename(self):
        source = '来源：江铜财务司字〔2024〕55号附件.pdf，page:2/line:6'
        md = '评级有效期与贷款期限不同。〔' + source + '〕另有条件。〔来源：申请书.pdf，page:1〕'
        blocks = annotated_blocks(md, {'annotations': 'word_comments'})
        self.assertEqual(blocks, [('评级有效期与贷款期限不同。另有条件。',
                                   [source, '来源：申请书.pdf，page:1'])])
        with tempfile.TemporaryDirectory() as tmp:
            template, output = Path(tmp)/'template.docx', Path(tmp)/'report.docx'
            Document().save(template)
            render_docx(md, template, output, '报告', presentation={**report_fonts(), 'annotations': 'word_comments'})
            doc = Document(output)
            self.assertFalse(any('55号附件' in p.text for p in doc.paragraphs))
            verify_comments(doc, blocks)

    def test_professional_expression_criteria_reach_every_chapter_without_changing_old_reviews(self):
        md = '# 公司\n\n履历不代表经营绩效。\n\n# 财务\n\n余额下降尚未确认为现金回收。'
        outline = {'sections': [{'id': 'company', 'title': '公司'}, {'id': 'financials', 'title': '财务'}]}
        old = review_requirements(md, outline, {'chapter_expression_review': True})
        criteria = ['每项结论有足以支持该结论的证据，余额减少不直接等于现金回收。']
        current = review_requirements(md, outline, {'chapter_expression_review': True,
                                                   'chapter_expression_criteria': criteria})
        self.assertEqual(len(current), len(old))
        self.assertEqual(sum(r['kind'] == 'expression' for r in current), 2)
        for before, after in zip(old, current):
            if after['kind'] == 'expression':
                self.assertEqual(after['criteria'], before['criteria'] + criteria)
            else:
                self.assertEqual(before, after)

    def test_empty_table_corner_uses_visible_header_and_wrong_block_anchor_is_rejected(self):
        md = '# 财务\n\n| | 本期 |\n| --- | --- |\n| 风险 | 资金受限 |\n\n<!-- review-note: 请确认释放时间。 -->'
        profile = {**report_fonts(), 'annotations': 'word_comments'}
        with tempfile.TemporaryDirectory() as tmp:
            template, output = Path(tmp)/'template.docx', Path(tmp)/'report.docx'
            Document().save(template)
            render_docx(md, template, output, '报告', presentation=profile)
            doc = Document(output)
            blocks = annotated_blocks(md, profile)
            verify_comments(doc, blocks)
            start = doc.element.xpath('//w:commentRangeStart')[0]
            end = doc.element.xpath('//w:commentRangeEnd')[0]
            reference = doc.element.xpath('//w:commentReference')[0].getparent()
            cover = doc.paragraphs[0]._p
            cover.insert(1, start)
            cover.append(end)
            cover.append(reference)
            with self.assertRaisesRegex(ValueError, 'reviewed report block'):
                verify_comments(doc, blocks)

    def test_source_and_review_note_keep_business_conclusion_and_anchor(self):
        md = '# 企业情况\n\n公司资金受限。〔来源：资金表，sheet:资金/cell:A1〕\n\n<!-- review-note: 请补充解押日期。 -->'
        blocks = annotated_blocks(md, {'annotations': 'word_comments'})
        self.assertEqual(blocks, [('# 企业情况', []), ('公司资金受限。', ['来源：资金表，sheet:资金/cell:A1', '审阅提示：请补充解押日期。'])])
        with tempfile.TemporaryDirectory() as tmp:
            template, output = Path(tmp)/'template.docx', Path(tmp)/'report.docx'
            Document().save(template)
            render_docx(md, template, output, '报告', presentation={**report_fonts(), 'annotations': 'word_comments'})
            doc = Document(output)
            self.assertIn('公司资金受限。', [p.text for p in doc.paragraphs])
            self.assertFalse(any('请补充' in p.text or '来源：' in p.text for p in doc.paragraphs))
            verify_comments(doc, blocks)
            doc.comments.get(0).text  # Source is preserved as a real comment.
            doc.element.xpath('//w:commentReference')[0].getparent().remove(doc.element.xpath('//w:commentReference')[0])
            with self.assertRaisesRegex(ValueError, 'comment'):
                verify_comments(doc, blocks)

    def test_malformed_or_unanchored_note_fails_instead_of_disappearing(self):
        for md in ['<!-- review-note: 未锚定 -->', '# 公司\n\n<!-- review-note: -->', '# 公司\n\n<!-- review-note: 未闭合']:
            with self.assertRaises(ValueError):
                annotated_blocks(md, {'annotations': 'word_comments'})
        with self.assertRaisesRegex(ValueError, 'annotations'):
            annotated_blocks('# 公司\n\n<!-- review-note: 提醒 -->', {})

    def test_old_reports_keep_inline_sources(self):
        md = '# 公司\n\n情况。〔来源：原件，page:1〕'
        self.assertEqual(annotated_blocks(md, {}), [('# 公司', []), ('情况。〔来源：原件，page:1〕', [])])

    def test_each_chapter_requires_expression_review_when_enabled(self):
        md = '# 公司\n\n经营情况。\n\n# 财务\n\n现金承压。'
        outline = {'sections': [{'id': 'company', 'title': '公司'}, {'id': 'financials', 'title': '财务'}]}
        old = review_requirements(md, outline)
        current = review_requirements(md, outline, {'chapter_expression_review': True})
        self.assertEqual([r['id'] for r in current if r['kind'] == 'expression'], ['expression:company', 'expression:financials'])
        entries = [{'id': r['id'], 'locator': r['locator'], 'quote': md.splitlines()[int(r['locator'][5:])-1], 'result': 'gap', 'assessment': '测试缺口', 'evidence_refs': []} for r in old]
        with self.assertRaisesRegex(ValueError, 'coverage'):
            validate_review_coverage(entries, current, md, set())
