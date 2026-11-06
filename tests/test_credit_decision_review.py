"""A complete chapter checklist must not bypass the credit decision review."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from long_report.financials import review_requirements, validate_review_coverage
from long_report.scenario import ScenarioError, load_scenario


class CreditDecisionReviewTests(unittest.TestCase):
    markdown = '# 调查结论\n\n现金不足，新增提款取决于回款落实。\n\n存量到期安排尚缺证据。'
    outline = {'sections': [{'id': 'conclusion', 'title': '调查结论'}]}

    def entries(self, requirements):
        return [{'id': r['id'], 'locator': r['locator'],
                 'quote': self.markdown.splitlines()[int(r['locator'][5:]) - 1],
                 'result': 'gap', 'assessment': '到期债务表未提供，无法确认存量到期覆盖，意见保留。',
                 'evidence_refs': []} for r in requirements]

    def test_five_decision_reviews_cannot_be_replaced_by_chapter_coverage(self):
        scenario = load_scenario('financial_due_diligence')
        current = review_requirements(self.markdown, self.outline, scenario.quality, scenario.analysis)
        decisions = [r for r in current if r['id'].startswith('decision:')]
        self.assertEqual({r['id'] for r in decisions}, {
            'decision:facility', 'decision:earnings_cash', 'decision:liquidity',
            'decision:repayment', 'decision:conditions'})
        self.assertTrue(all(r['criteria'] for r in decisions))
        entries = self.entries(current)
        validate_review_coverage(entries, current, self.markdown, set())
        for decision in decisions:
            with self.subTest(missing=decision['id']), self.assertRaisesRegex(ValueError, 'coverage'):
                validate_review_coverage([r for r in entries if r['id'] != decision['id']],
                                         current, self.markdown, set())

    def test_decision_review_binds_real_claim_and_current_evidence(self):
        quality = {'decision_reviews': [{'id': 'repayment', 'criteria': ['验证到期现金缺口及其对意见的影响']} ]}
        requirements = review_requirements(self.markdown, self.outline, quality)
        entries = self.entries(requirements)
        decision = next(r for r in entries if r['id'] == 'decision:repayment')
        decision.update(locator='line:5', quote='存量到期安排尚缺证据。', result='passed', evidence_refs=['current'])
        validate_review_coverage(entries, requirements, self.markdown, {'current'})
        for change in ({'evidence_refs': ['stale']}, {'evidence_refs': []}, {'quote': '未出现在正文的判断'}):
            invalid = copy.deepcopy(entries)
            next(r for r in invalid if r['id'] == decision['id']).update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_review_coverage(invalid, requirements, self.markdown, {'current'})

    def test_frozen_old_configuration_keeps_its_review_contract(self):
        old = review_requirements(self.markdown, self.outline, {'chapter_expression_review': True})
        self.assertFalse(any(r['id'].startswith('decision:') for r in old))
        validate_review_coverage(self.entries(old), old, self.markdown, set())

    def test_invalid_decision_criteria_are_rejected_at_configuration_boundary(self):
        valid = {'id': 'repayment', 'criteria': ['复核偿债安排']}
        for invalid in (None, {}, [valid, valid], [{'id': 'bad id', 'criteria': ['判断']}],
                        [{'id': 'repayment', 'criteria': []}], [{'id': 'repayment', 'criteria': [' ']}]):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(Path(__file__).resolve().parents[1] / 'scenarios/financial_due_diligence',
                                root / 'financial_due_diligence')
                path = root / 'financial_due_diligence/quality.yaml'
                quality = yaml.safe_load(path.read_text())
                quality['decision_reviews'] = invalid
                path.write_text(yaml.safe_dump(quality, allow_unicode=True))
                with self.assertRaisesRegex(ScenarioError, 'decision_reviews'):
                    load_scenario('financial_due_diligence', root)

    def test_expression_criteria_cannot_be_malformed_or_silently_disabled(self):
        for invalid, enabled in ((None, True), ('判断', True), ([], True), ([' '], True), (['判断'], False)):
            with self.subTest(invalid=invalid, enabled=enabled), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(Path(__file__).resolve().parents[1] / 'scenarios/financial_due_diligence',
                                root / 'financial_due_diligence')
                path = root / 'financial_due_diligence/quality.yaml'
                quality = yaml.safe_load(path.read_text())
                quality.update(chapter_expression_criteria=invalid, chapter_expression_review=enabled)
                path.write_text(yaml.safe_dump(quality, allow_unicode=True))
                with self.assertRaisesRegex(ScenarioError, 'chapter_expression_criteria'):
                    load_scenario('financial_due_diligence', root)
