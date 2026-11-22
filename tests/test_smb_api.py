"""Exercise the editor API over a disposable Samba share."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

temp = tempfile.TemporaryDirectory()
base = Path(temp.name)
options = {'smb_server': os.environ['TEST_SMB_SERVER'], 'smb_share': 'khfixture',
           'smb_username': 'khfixture', 'smb_password': 'fixturepass', 'smb_subdirectory': ''}
(base / 'options.json').write_text(json.dumps(options))
(base / 'policy.json').write_text(json.dumps({'files': ['index.md', 'zweite.md']}))
os.environ.update(KH_SYNTHETIC_ONLY='yes', KH_SMB_OPTIONS=str(base / 'options.json'), KH_POLICY=str(base / 'policy.json'), KH_EXCLUSIONS_FILE=str(base / 'excluded.json'))
spec = importlib.util.spec_from_file_location('hub_smb', '/app/app.py')
hub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub)
hub.refresh()
server = hub.ThreadingHTTPServer(('127.0.0.1', 0), hub.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = 'http://127.0.0.1:%s' % server.server_port


def request(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    try:
        with urlopen(Request(url + path, data=data, headers={'X-Knowledge-Hub': '1'} if path == '/api/exclusions' else {})) as response:
            return response.status, response.read()
    except HTTPError as err:
        return err.code, err.read()


class SMBEditorAPI(unittest.TestCase):
    def test_save_switch_conflict_and_access(self):
        first = json.loads(request('/api/file?path=index.md')[1])
        content = '# Synthetic first page\n\nChanged over SMB\n'
        status, _ = request('/api/save', {'path': 'index.md', 'revision': first['revision'], 'content': content})
        self.assertEqual(status, 200)
        self.assertIn(b'Changed over SMB', request('/site/index.html')[1])
        self.assertEqual(request('/api/save', {'path': 'index.md', 'revision': first['revision'], 'content': 'old'})[0], 409)
        second = json.loads(request('/api/file?path=zweite.md')[1])
        self.assertEqual(request('/api/save', {'path': 'zweite.md', 'revision': second['revision'], 'content': '# Second changed\n'})[0], 200)
        self.assertIn(b'Second changed', request('/site/zweite.html')[1])
        self.assertEqual(request('/api/file?path=hidden.md')[0], 200)
        self.assertEqual(request('/api/exclusions', {'path': 'hidden.md', 'action': 'exclude'})[0], 200)
        self.assertEqual(json.loads((base / 'excluded.json').read_text()), ['hidden.md'])
        self.assertEqual(request('/api/file?path=hidden.md')[0], 404)
        self.assertEqual(request('/site/hidden.html')[0], 404)
        self.assertNotIn(b'Synthetic blocked', request('/site/search/search_index.json')[1])
        self.assertEqual(request('/api/exclusions', {'path': 'index.md', 'action': 'exclude'})[0], 400)
        self.assertEqual(request('/api/exclusions', {'path': 'hidden.md', 'action': 'restore'})[0], 200)
        self.assertEqual(request('/api/file?path=hidden.md')[0], 200)


if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        server.shutdown()
        temp.cleanup()
