import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

TEMP = tempfile.TemporaryDirectory()
BASE = Path(TEMP.name)
ROOT = BASE / 'source'
ROOT.mkdir()
(ROOT / 'rezepte').mkdir()
ORIGINAL = '---\ntitle: Testseite\n---\n\n[Gut](rezepte/soljanka.md) [Gesperrt](rezepte/griessbrei.md)\n\n| A | B |\n|---|---|\n| 1 | 2 |\n'
(ROOT / 'index.md').write_text(ORIGINAL, encoding='utf-8')
(ROOT / 'rezepte/soljanka.md').write_text('# Erlaubtes Rezept\n', encoding='utf-8')
(ROOT / 'rezepte/griessbrei.md').write_text('# GEHEIM_SYNTHETISCH\n', encoding='utf-8')
(ROOT / 'rezepte/neu.md').write_text('# NEU_SYNTHETISCH\n', encoding='utf-8')
(BASE / 'policy.json').write_text(json.dumps({'files': ['index.md', 'rezepte/soljanka.md']}), encoding='utf-8')
os.environ.update(KH_SYNTHETIC_ONLY='yes', KH_ROOT=str(ROOT), KH_POLICY=str(BASE / 'policy.json'))
spec = importlib.util.spec_from_file_location('hub', '/app/app.py')
hub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub)
hub.refresh()
server = hub.ThreadingHTTPServer(('127.0.0.1', 0), hub.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
URL = 'http://127.0.0.1:%s' % server.server_port

def req(path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    request = Request(URL + path, data=body, headers={'Content-Type': 'application/json'} if body else {})
    try:
        with urlopen(request) as response: return response.status, response.read()
    except HTTPError as err: return err.code, err.read()

class Prototype(unittest.TestCase):
    def test_01_site_and_policy(self):
        status, body = req('/site/index.html')
        self.assertEqual(status, 200)
        self.assertIn(b'<table>', body)
        self.assertEqual(req('/site/rezepte/soljanka.html')[0], 200)
        self.assertEqual(req('/site/rezepte/griessbrei.html')[0], 404)
        self.assertEqual(req('/site/rezepte/griessbrei.md')[0], 404)
        self.assertEqual(req('/api/file?path=rezepte%2Fgriessbrei.md')[0], 404)
        self.assertEqual(req('/api/file?path=rezepte%2Fneu.md')[0], 404)
        self.assertEqual(req('/site/rezepte/neu.html')[0], 404)
        self.assertNotIn(b'GEHEIM_SYNTHETISCH', req('/site/search/search_index.json')[1])
        self.assertNotIn(b'NEU_SYNTHETISCH', req('/site/search/search_index.json')[1])
        self.assertEqual(req('/api/file?path=..%2Fpolicy.json')[0], 404)
        self.assertEqual(req('/site/%2e%2e/policy.json')[0], 404)

    def test_02_save_conflict_and_restore(self):
        obj = json.loads(req('/api/file?path=index.md')[1])
        updated = ORIGINAL + '\nTeständerung\n'
        status, data = req('/api/save', {'path': 'index.md', 'revision': obj['revision'], 'content': updated})
        self.assertEqual(status, 200)
        self.assertEqual((ROOT / 'index.md').read_text(encoding='utf-8'), updated)
        self.assertIn('Teständerung'.encode(), req('/site/index.html')[1])
        self.assertEqual(req('/api/save', {'path': 'index.md', 'revision': obj['revision'], 'content': 'veraltet'})[0], 409)
        self.assertEqual(json.loads(req('/api/backup?path=index.md')[1])['content'], ORIGINAL)
        current = json.loads(data)['revision']
        self.assertEqual(req('/api/save', {'path': 'index.md', 'revision': current, 'content': ORIGINAL})[0], 200)
        self.assertEqual((ROOT / 'index.md').read_text(encoding='utf-8'), ORIGINAL)
        self.assertNotEqual(req('/api/save', {'path': 'rezepte/griessbrei.md', 'revision': '', 'content': 'x'})[0], 200)

    def test_03_external_change_and_failed_build(self):
        obj = json.loads(req('/api/file?path=index.md')[1])
        (ROOT / 'index.md').write_text(ORIGINAL + '\nExtern\n', encoding='utf-8')
        self.assertEqual(req('/api/save', {'path': 'index.md', 'revision': obj['revision'], 'content': 'veraltet'})[0], 409)
        hub.refresh()
        self.assertIn(b'Extern', req('/site/index.html')[1])
        before = req('/site/index.html')[1]
        (ROOT / 'index.md').write_text(ORIGINAL + '\nNeuer Stand\n', encoding='utf-8')
        build = hub.build
        hub.build = lambda _: (_ for _ in ()).throw(RuntimeError('synthetic failure'))
        try:
            with self.assertRaises(RuntimeError): hub.refresh()
            self.assertEqual(req('/site/index.html')[1], before)
        finally: hub.build = build
        hub.refresh()
        self.assertIn(b'Neuer Stand', req('/site/index.html')[1])

    def test_04_source_unavailable_and_recovery(self):
        path = ROOT / 'rezepte/soljanka.md'
        path.rename(ROOT / 'rezepte/unavailable')
        try:
            with self.assertRaises(OSError): hub.refresh()
            self.assertEqual(req('/site/index.html')[0], 503)
        finally: (ROOT / 'rezepte/unavailable').rename(path)
        hub.refresh()
        self.assertEqual(req('/site/index.html')[0], 200)

    def test_05_symlink_rejected(self):
        path = ROOT / 'rezepte/soljanka.md'
        path.rename(ROOT / 'rezepte/temp')
        path.symlink_to(ROOT / 'rezepte/griessbrei.md')
        try:
            self.assertEqual(req('/api/file?path=rezepte%2Fsoljanka.md')[0], 404)
            with self.assertRaises(OSError): hub.refresh()
        finally:
            path.unlink()
            (ROOT / 'rezepte/temp').rename(path)
        hub.refresh()

    def test_06_competing_api_writes(self):
        revision = json.loads(req('/api/file?path=index.md')[1])['revision']
        gate = threading.Barrier(3)
        results = []
        def save(text):
            gate.wait()
            results.append(req('/api/save', {'path': 'index.md', 'revision': revision, 'content': text})[0])
        a = threading.Thread(target=save, args=('Erster Entwurf',))
        b = threading.Thread(target=save, args=('Zweiter Entwurf',))
        a.start(); b.start(); gate.wait(); a.join(); b.join()
        self.assertEqual(sorted(results), [200, 409])

    def test_07_source_disappears_during_build(self):
        path = ROOT / 'rezepte/soljanka.md'
        original = path.read_bytes()
        path.write_bytes(original + b'\nChanged\n')
        real_build = hub.build
        def build_then_remove(data):
            result = real_build(data)
            path.unlink()
            return result
        hub.build = build_then_remove
        try:
            with self.assertRaises(OSError): hub.refresh()
            self.assertEqual(req('/site/index.html')[0], 503)
        finally:
            hub.build = real_build
            path.write_bytes(original)
            hub.refresh()
        self.assertEqual(req('/site/index.html')[0], 200)

    def test_08_ingress_source_check(self):
        previous = hub.INGRESS_ONLY
        try:
            hub.INGRESS_ONLY = True
            self.assertTrue(hub.Server.verify_request(None, None, ('172.30.32.2', 1234)))
            self.assertFalse(hub.Server.verify_request(None, None, ('127.0.0.1', 1234)))
            self.assertFalse(hub.Server.verify_request(None, None, ('172.30.32.3', 1234)))
        finally:
            hub.INGRESS_ONLY = previous

if __name__ == '__main__':
    try: unittest.main(verbosity=2)
    finally: server.shutdown(); TEMP.cleanup()
