"""Publish reviewed candidates with final product gates and the unchanged experiment config.
Only scenario resource root is selected explicitly to preserve STFangsong experiment identity.
"""
from pathlib import Path
import json
from long_report import application,scenario
ROOT=Path(__file__).resolve().parents[3]
EXP=ROOT/'.scratch/due-diligence-model-consistency/experiment'
scenario._root=lambda: EXP/'runtime/scenarios'
for arm in ['sol','terra']:
 folder=EXP/arm; workspace=folder/'projects'
 request=json.loads((Path(__file__).parent/f'{arm}-final-review-request.json').read_text())
 response=application.submit_review(workspace,request)
 (folder/'review-response.json').write_text(json.dumps(response,ensure_ascii=False,indent=2))
 validation=application.validate_run(workspace,request)
 (folder/'validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2))
 print(arm,validation,flush=True)
 if not validation['hard_checks_passed']:raise SystemExit(1)
 revision=application.publish_run(workspace,request)
 (folder/'publication.json').write_text(json.dumps(revision,ensure_ascii=False,indent=2))
 print(arm,'published',revision['docx_path'],revision['pdf_path'],flush=True)
