"""Chapter conclusions must use current upstream drafts and the actual business requirements."""
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import yaml

from long_report import application as app
from long_report.financials import review_requirements
from long_report.scenario import ScenarioError, load_scenario
from credit_test_support import (registration_table, background_details, equity_details,
                                 investment_details, credit_rating_table)


class FinancialRuntimeContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / 'projects'
        scenario = load_scenario('financial_due_diligence')
        self.project = app.create_project(self.workspace, {
            'scenario_id': 'financial_due_diligence', 'scenario_version': scenario.version,
            'credit_application_id': 'SYN-AUDIT', 'evaluation_date': '2026-06-30',
            'subject_scope': {'business_unit': '合成审查公司'}})
        source = self.root / 'application.txt'
        source.write_text('合成申请，业务材料尚未核实。')
        material = app.add_material(self.workspace, {
            'project_id': self.project['id'], 'input_id': 'application', 'path': str(source)})
        self.run = app.start_run(self.workspace, {'project_id': self.project['id']})
        self.base = {'project_id': self.project['id'], 'run_id': self.run['id']}
        for task in app.list_tasks(self.workspace, **self.base):
            app.submit_task(self.workspace, {**self.base, 'task_id': task['id'],
                'input_fingerprint': task['input_fingerprint'], 'candidates': []})
        app.freeze_evidence(self.workspace, self.base)
        app.calculate_run(self.workspace, self.base)
        planned = app.plan_draft(self.workspace, {**self.base, 'report_request': '合成契约核查',
            'outline': {'sections': self.project['effective_config']['outline']['sections']},
            'material_uses': [{'material_id': material['id'], 'use': 'context', 'reason': '合成文本，缺实质证据'}]})
        self.tasks = {task['section_id']: task for task in planned}
        self.bodies = {}
        for section in self.project['effective_config']['outline']['sections']:
            body = '\n\n'.join('## ' + title + '\n\n本节资料待核实。'
                                for title in section.get('subheadings', [])) or '融资资料待核实。'
            if section['id'] == 'company':
                for title, detail in [('一、工商信息', registration_table(section)),
                                      ('二、背景情况', background_details(section)),
                                      ('四、股权、股东及投资情况', equity_details(section)),
                                      ('五、对外投资情况', investment_details(section))]:
                    body = body.replace('## ' + title + '\n\n', '## ' + title + '\n\n' + detail + '\n\n')
            if section['id'] == 'credit':
                body = body.replace('## 一、信用评级\n\n', '## 一、信用评级\n\n' + credit_rating_table(section) + '\n\n')
            if section['id'] == 'risks':
                body = '## 一、资料不足对偿债判断的限制\n\n须结合本轮事实核查。'
            body += ''.join('\n\n资料缺口：' + asset + '：原始资料未提供。'
                            for asset in section['required_assets'] if section['id'] != 'credit')
            self.bodies[section['id']] = body

    def context(self, section_id):
        return app.get_draft_context(self.workspace, self.project['id'], self.tasks[section_id]['id'])

    def submit(self, section_id, body=None, **extra):
        context = self.context(section_id)
        return app.submit_draft(self.workspace, {**self.base, 'task_id': self.tasks[section_id]['id'],
            'author_id': 'synthetic-writer', 'body': body or self.bodies[section_id],
            'dependency_fingerprint': context.get('dependency_fingerprint', 'not-implemented'), **extra})

    def submit_all(self):
        for section_id in self.tasks:
            self.submit(section_id)

    def test_conclusion_receives_only_current_submitted_credit_and_terms_bodies(self):
        self.submit_all()
        context = self.context('conclusion')
        self.assertEqual([item['section_id'] for item in context['upstream_sections']], ['credit', 'terms'])
        for item in context['upstream_sections']:
            self.assertEqual(item['body'], self.bodies[item['section_id']])
            self.assertEqual(item['status'], 'submitted')
            self.assertTrue(item['body_sha256'])
        self.assertTrue(context['dependency_fingerprint'])

    def test_missing_dependency_fingerprint_cannot_silently_skip_upstream_reading(self):
        self.submit('company')
        with self.assertRaisesRegex(ValueError, 'dependency_fingerprint'):
            app.submit_draft(self.workspace, {**self.base, 'task_id': self.tasks['operations']['id'],
                'author_id': 'synthetic-writer', 'body': self.bodies['operations']})
        self.submit('operations')
        with self.assertRaisesRegex(ValueError, 'dependency_fingerprint'):
            app.submit_draft(self.workspace, {**self.base, 'task_id': self.tasks['operations']['id'],
                'author_id': 'synthetic-writer', 'body': self.bodies['operations']})

    def test_legacy_frozen_quality_does_not_require_the_new_submission_field(self):
        with sqlite3.connect(self.workspace / self.project['id'] / 'state.sqlite') as connection:
            run = json.loads(connection.execute('SELECT data FROM run WHERE id = ?', (self.run['id'],)).fetchone()[0])
            for key in ('require_dependency_fingerprint', 'chapter_review_guidance'):
                run['effective_config']['quality'].pop(key)
            connection.execute('UPDATE run SET data = ? WHERE id = ?', (json.dumps(run), self.run['id']))
        for section_id in ('company', 'operations'):
            result = app.submit_draft(self.workspace, {**self.base, 'task_id': self.tasks[section_id]['id'],
                'author_id': 'synthetic-writer', 'body': self.bodies[section_id]})
            self.assertEqual(result['status'], 'submitted')

    def test_upstream_edit_rejects_a_writer_using_the_old_context(self):
        self.submit('company')
        old = self.context('operations').get('dependency_fingerprint', 'old-context')
        self.submit('company', self.bodies['company'] + '\n\n更新后的经营说明。', replace=True)
        with self.assertRaisesRegex(ValueError, 'dependency_fingerprint'):
            self.submit('operations', dependency_fingerprint=old)

    def test_upstream_edit_invalidates_only_descendants_before_rebuild(self):
        self.submit_all()
        self.submit('credit', self.bodies['credit'] + '\n\n征信状态需重新复核。', replace=True)
        with self.assertRaisesRegex(ValueError, 'unfinished'):
            app.build_draft(self.workspace, self.base)
        context = self.context('conclusion')
        self.assertEqual([item['status'] for item in context['upstream_sections']], ['submitted', 'ready'])
        self.assertIsNone(context['upstream_sections'][1]['body'])
        with sqlite3.connect(self.workspace / self.project['id'] / 'state.sqlite') as connection:
            self.assertEqual(connection.execute('SELECT body FROM section_body WHERE task_id = ?',
                                               (self.tasks['terms']['id'],)).fetchone()[0], self.bodies['terms'])
        self.assertEqual(self.context('terms')['previous_body'], self.bodies['terms'])
        self.submit('terms', self.context('terms')['previous_body'])
        self.submit('conclusion')
        self.assertTrue(app.build_draft(self.workspace, self.base)['sha256'])

    def test_locked_downstream_cannot_be_invalidated_by_an_upstream_edit(self):
        self.submit_all()
        database = self.workspace / self.project['id'] / 'state.sqlite'
        with sqlite3.connect(database) as connection:
            run = json.loads(connection.execute('SELECT data FROM run WHERE id = ?', (self.run['id'],)).fetchone()[0])
            run['locked_sections'] = ['conclusion']
            connection.execute('UPDATE run SET data = ? WHERE id = ?', (json.dumps(run), self.run['id']))
        with self.assertRaisesRegex(ValueError, 'locked section'):
            self.submit('credit', self.bodies['credit'] + '\n\n新增信用事项。', replace=True)
        self.assertEqual(self.context('conclusion')['upstream_sections'][0]['body'], self.bodies['credit'])

    def test_identical_replacement_keeps_downstream_submitted_and_other_runs_never_supply_context(self):
        self.submit_all()
        self.submit('credit', replace=True)
        with sqlite3.connect(self.workspace / self.project['id'] / 'state.sqlite') as connection:
            other = {**self.tasks['credit'], 'id': 'foreign-credit', 'run_id': 'foreign-run', 'status': 'submitted'}
            connection.execute('INSERT INTO section_task VALUES (?, ?, ?)', (other['id'], other['run_id'], json.dumps(other)))
            connection.execute('INSERT INTO section_body VALUES (?, ?)', (other['id'], '其他运行的过期结论。'))
        context = self.context('conclusion')
        self.assertTrue(all(item['status'] == 'submitted' for item in context['upstream_sections']))
        self.assertTrue(all(item['task_id'] != 'foreign-credit' for item in context['upstream_sections']))
        self.assertTrue(app.build_draft(self.workspace, self.base)['sha256'])


class BusinessReviewGuidanceTests(unittest.TestCase):
    def test_business_criteria_are_taken_from_the_same_guidance_as_the_writer(self):
        outline = {'sections': [{'id': 'conclusion', 'title': '综合结论'}]}
        quality = {'chapter_expression_review': True,
                   'chapter_review_guidance': {'conclusion': ['conclusion', 'conclusion_traceability']}}
        analysis = {'writing_guidance': {'conclusion': ['七项方案字段逐项承接上游。'],
                                        'conclusion_traceability': ['保留未决条件与金额身份。']}}
        requirements = review_requirements('# 综合结论\n\n本轮意见。', outline, quality, analysis)
        item = next(x for x in requirements if x['id'] == 'expression:conclusion')
        self.assertIn('conclusion：七项方案字段逐项承接上游。', item['criteria'])
        self.assertIn('conclusion_traceability：保留未决条件与金额身份。', item['criteria'])
        with self.assertRaisesRegex(ValueError, 'chapter_review_guidance'):
            review_requirements('# 综合结论\n\n本轮意见。', outline, quality)

    def test_all_nine_chapters_have_business_review_references_and_missing_refs_fail(self):
        scenario = load_scenario('financial_due_diligence')
        mapping = scenario.quality.get('chapter_review_guidance', {})
        self.assertEqual(set(mapping), set(scenario.quality['required_sections']))
        for bad in ({}, {**mapping, 'credit': ['missing_guidance']}, {**mapping, 'credit': []},
                    {**mapping, 'credit': ['credit', 'credit']}):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(Path(__file__).resolve().parents[1] / 'scenarios/financial_due_diligence',
                                root / 'financial_due_diligence')
                path = root / 'financial_due_diligence/quality.yaml'
                quality = yaml.safe_load(path.read_text())
                quality['chapter_review_guidance'] = bad
                path.write_text(yaml.safe_dump(quality, allow_unicode=True))
                with self.assertRaisesRegex(ScenarioError, 'chapter_review_guidance'):
                    load_scenario('financial_due_diligence', root)

    def test_legacy_review_shape_stays_unchanged_without_the_new_mapping(self):
        outline = {'sections': [{'id': 'company', 'title': '公司'}]}
        quality = {'chapter_expression_review': True}
        legacy = review_requirements('# 公司\n\n资料。', outline, quality)
        current = review_requirements('# 公司\n\n资料。', outline, quality, {'writing_guidance': {'company': ['新指引']}})
        self.assertEqual(legacy, current)


class FinancialReferenceUnitTests(unittest.TestCase):
    def test_ratio_results_cannot_be_relabelled_as_percent_or_turnover_days(self):
        from long_report.financials import validate_reference_units
        values = {'quick': {'unit': '倍'}, 'margin': {'unit': '%'}, 'turnover': {'unit': '次'}}
        validate_reference_units('速动比率{{calc:quick}}倍；净利率{{calc:margin}}%。', values)
        for body in ('速动比率{{calc:quick}}%', '| 速动比率 | {{calc:quick|2}}% |',
                     '周转{{calc:turnover}}天', '利润率{{fact:margin}}倍'):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, 'reference unit mismatch'):
                validate_reference_units(body, values)

    def test_percent_points_stay_percent_points_and_fullwidth_percent_is_equivalent(self):
        from long_report.financials import validate_reference_units
        item = {'unit': '%', 'value': '0.11'}
        validate_reference_units('利润率{{calc:margin}}％', {'margin': item})
        self.assertEqual(item, {'unit': '%', 'value': '0.11'})
