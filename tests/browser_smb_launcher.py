"""Local-only browser harness for the disposable SMB test server."""
import json
import os
from pathlib import Path
import sys
import tempfile

base = Path(tempfile.mkdtemp(prefix='kh-browser-'))
(base / 'policy.json').write_text(json.dumps({'files': ['index.md']}))
(base / 'options.json').write_text(json.dumps({
    'smb_server': os.environ['TEST_SMB_SERVER'], 'smb_share': 'khfixture',
    'smb_username': 'khfixture', 'smb_password': 'fixturepass', 'smb_subdirectory': ''}))
os.environ.update(KH_SYNTHETIC_ONLY='yes', KH_SMB_OPTIONS=str(base / 'options.json'),
                  KH_POLICY=str(base / 'policy.json'), KH_EXCLUSIONS_FILE=str(base / 'excluded.json'),
                  KH_TEST_NO_SUPERVISOR='yes', HOST='0.0.0.0')
os.execv(sys.executable, [sys.executable, '/app/app.py'])
