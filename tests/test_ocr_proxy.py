"""A configured proxy must carry OCR traffic without relying on ambient proxies."""
import json
import os
from pathlib import Path
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch
import yaml
from long_report.integrations.ocr import load_ocr_service, request_ocr

class OcrProxyTests(unittest.TestCase):
    def test_explicit_proxy_routes_unreachable_provider_and_changes_binding(self):
        seen=[]
        class Proxy(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                seen.append(self.path)
                raw=json.dumps({'code':0,'data':{'status':'processing'}}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def log_message(self,*args):pass
        with ThreadingHTTPServer(('127.0.0.1',0),Proxy) as server, tempfile.TemporaryDirectory() as tmp:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                config={'schema_version':1,'connections':{'ocr':{'protocol':'http','endpoint':'http://provider.invalid/v1','auth_ref':'env:OCR_TEST_KEY','proxy':f'http://127.0.0.1:{server.server_port}'}},'services':{'s':{'enabled':True,'connection_ref':'ocr','adapter':'somark_http','capability':'document.ocr','contract_version':1,'timeout_seconds':1}}}
                path=Path(tmp)/'service.yaml';path.write_text(yaml.safe_dump(config))
                with patch.dict(os.environ,{'OCR_TEST_KEY':'test'}):
                    binding=load_ocr_service(str(path),'s')
                    raw,response,error=request_ocr(binding,task_id='job')
                    self.assertIsNone(error)
                    self.assertEqual(seen,['http://provider.invalid/v1/parse/async_check'])
                    del config['connections']['ocr']['proxy'];path.write_text(yaml.safe_dump(config))
                    self.assertNotEqual(binding['fingerprint'],load_ocr_service(str(path),'s')['fingerprint'])
            finally:server.shutdown()

    def test_proxy_credentials_query_and_invalid_scheme_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OCR_TEST_KEY':'test'}):
            for proxy in ['https://user:secret@proxy.test','http://proxy.test?key=secret','file:///tmp/proxy','http://127.0.0.1:invalid','http://127.0.0.1:99999']:
                config={'schema_version':1,'connections':{'ocr':{'protocol':'http','endpoint':'http://provider.invalid/v1','auth_ref':'env:OCR_TEST_KEY','proxy':proxy}},'services':{'s':{'enabled':True,'connection_ref':'ocr','adapter':'somark_http','capability':'document.ocr','contract_version':1}}}
                path=Path(tmp)/'service.yaml';path.write_text(yaml.safe_dump(config))
                with self.assertRaisesRegex(ValueError,'proxy'):load_ocr_service(str(path),'s')
