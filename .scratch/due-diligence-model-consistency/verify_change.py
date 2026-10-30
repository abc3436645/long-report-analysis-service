"""Read-only acceptance checks over original bytes, current contracts and real model artifacts."""
from pathlib import Path
from hashlib import sha256
import json
import re
import sqlite3
import yaml
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT.parents[1]
EVIDENCE = ROOT / '.scratch/due-diligence-model-consistency'
EXP = EVIDENCE / 'experiment'

def digest(path):
    return sha256(path.read_bytes()).hexdigest()

def main():
    evidence = json.loads((EVIDENCE / 'evidence.json').read_text())
    original_files = evidence['inputs'] + evidence['artifacts']
    changed = [item['path'] for item in original_files if digest(BASE / item['path']) != item['sha256']]
    assert not changed, changed
    manifest = yaml.safe_load((ROOT / 'scenarios/financial_due_diligence/scenario.yaml').read_text())
    assert manifest['version'] == '0.3.0'
    assert manifest['presentation']['body_font'] == '仿宋'
    assert manifest['presentation']['allow_font_fallback'] is False
    original_manifest = yaml.safe_load((BASE / 'scenarios/financial_due_diligence/scenario.yaml').read_text())
    assert manifest['presentation'] == original_manifest['presentation']
    current_outline = yaml.safe_load((ROOT / 'scenarios/financial_due_diligence/outline.yaml').read_text())
    original_outline = yaml.safe_load((BASE / 'scenarios/financial_due_diligence/outline.yaml').read_text())
    assert {key: value for key, value in current_outline.items() if key != 'planning_guidance'} == {key: value for key, value in original_outline.items() if key != 'planning_guidance'}
    assert digest(ROOT / 'scenarios/financial_due_diligence/templates/default-v0.2.0.docx') == digest(BASE / 'scenarios/financial_due_diligence/templates/default-v0.2.0.docx')
    paths = [ROOT / '.agents/skills/long-report/SKILL.md', ROOT / '.agents/skills/long-report/references/financial-quality.md',
             ROOT / 'docs/adr/0017-financial-evidence-quality.md', ROOT / 'docs/模块设计-数据与执行契约.md',
             *sorted((ROOT / 'docs/scenarios').glob('财务公司*.md'))]
    for path in paths:
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if target.startswith(('https:', 'http:', '#')):
                continue
            assert (path.parent / target.split('#', 1)[0]).exists(), (path, target)
    experiment = json.loads((EXP / 'manifest.json').read_text())
    assert len(experiment['input_hashes']) == 30
    for relative, expected in experiment['code_hashes'].items():
        assert digest(Path(experiment['runtime']) / relative) == expected, relative
    arms = []
    comparison = {}
    for arm, expected_model in [('sol', 'gpt-6.1-sol'), ('terra', 'gpt-6.1-terra')]:
        folder = EXP / arm
        execution = json.loads((folder / 'execution.json').read_text())
        assert execution.get('actual_model', execution.get('model')) == expected_model
        assert execution['reasoning_effort'] == 'medium'
        draft = json.loads((folder / 'draft.json').read_text())
        content = Path(draft['markdown_path']).read_text()
        assert digest(Path(draft['markdown_path'])) == draft['sha256']
        assert len(re.findall(r'(?m)^# ', content)) == 9
        assert len(re.findall(r'(?m)^## ', content)) == 31
        assert '{{' not in content
        assert draft['review_requirements']
        database = folder / 'projects' / experiment['project_id'] / 'state.sqlite'
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as connection:
            row = connection.execute('SELECT data FROM run WHERE id = ?', (draft['run_id'],)).fetchone()
            run = json.loads(row[0])
            material_count = len(run['material_ids'])
            assert material_count >= 51
            assert run['evidence_snapshot_id']
            snapshot = json.loads(connection.execute('SELECT data FROM evidence_snapshot WHERE id = ?', (run['evidence_snapshot_id'],)).fetchone()[0])
            assert snapshot['material_coverage']
            review = json.loads(connection.execute('SELECT data FROM review WHERE run_id = ?', (run['id'],)).fetchone()[0])
            assert review['verdict'] == 'pass' and review['coverage'] and review['draft_sha256'] == draft['sha256']
            assert run['status'] == 'published'
            revision = next(item for row in connection.execute('SELECT data FROM revision')
                            if (item := json.loads(row[0]))['run_id'] == run['id'])
            assert revision['status'] == 'pending_review'
            assert revision['report_metadata']['授信额度'] == '10亿元'
            assert Path(revision['docx_path']).is_file()
            assert Path(revision['pdf_path']).is_file()
            calculations = [item for row in connection.execute('SELECT data FROM calculation WHERE run_id = ?', (run['id'],))
                            if (item := json.loads(row[0]))['status'] == 'calculated']
            assert len(calculations) == 40
            critical = {(item['metric_id'], item['period']): Decimal(item['value']) for item in calculations}
            assert Decimal('.0779') < critical['net_margin', '2025-12-31'] < Decimal('.0780')
            assert Decimal('4.29') < critical['receivables_days', '2026-06-30'] < Decimal('4.31')
            comparison[arm] = critical
            for key, extension in [('markdown_path', 'md'), ('docx_path', 'docx'), ('pdf_path', 'pdf')]:
                assert digest(Path(revision[key])) == digest(EVIDENCE / 'deliverables' / arm / f'江铜华北_财务尽调_{arm}.{extension}')
        arms.append({'arm': arm, 'requested_model': expected_model, 'reasoning_effort': 'medium', 'run_id': draft['run_id'],
                     'material_count': material_count, 'fact_count': len(snapshot['evidence_ids']), 'draft_sha256': draft['sha256'],
                     'docx_path': revision['docx_path'], 'pdf_path': revision['pdf_path']})
    assert comparison['sol'].keys() == comparison['terra'].keys()
    assert all(abs(value - comparison['terra'][key]) < Decimal('.00000001') for key, value in comparison['sol'].items())
    print(json.dumps({'original_files_unchanged': len(original_files), 'linked_documents_checked': len(paths),
                      'official_font_unchanged': True, 'shared_author_runtime_unchanged': True, 'arms': arms}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
