"""Opt-in test launcher: bundled fixtures or a dedicated SMB test share."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import re

options_path = Path('/data/options.json')
if options_path.is_file():
    options = json.loads(options_path.read_text(encoding='utf-8'))
    synthetic = options.get('synthetic_ha_test') is True
    smb_test = options.get('smb_test_enabled') is True
    if synthetic and smb_test:
        raise SystemExit('Select only one test source')
    if synthetic:
        base = Path(tempfile.mkdtemp(prefix='knowledge-hub-fixtures-'))
        shutil.copytree('/app/fixtures/source', base / 'source')
        shutil.copyfile('/app/fixtures/policy.json', base / 'policy.json')
        os.environ.update(KH_SYNTHETIC_ONLY='yes', KH_INGRESS_ONLY='yes',
                          KH_ROOT=str(base / 'source'), KH_POLICY=str(base / 'policy.json'),
                          HOST='0.0.0.0')
    elif smb_test:
        server = options.get('smb_server', '')
        share = options.get('smb_share', '')
        username = options.get('smb_username', '')
        password = options.get('smb_password', '')
        subdir = options.get('smb_subdirectory', '')
        files = options.get('allowed_files', [])
        if not isinstance(server, str) or not re.fullmatch(r'[A-Za-z0-9.-]+', server):
            raise SystemExit('Invalid SMB server')
        if not isinstance(share, str) or not re.fullmatch(r'[A-Za-z0-9_. -]+', share) or share.startswith('.'):
            raise SystemExit('Invalid SMB share')
        if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
            raise SystemExit('SMB credentials are required')
        if not isinstance(subdir, str) or (subdir and any(not re.fullmatch(r'[^\\/:*?"<>|\x00-\x1f]+', p) or p.startswith('.') or p.endswith((' ', '.')) for p in subdir.split('/'))):
            raise SystemExit('Invalid test subdirectory')
        if not isinstance(files, list) or not files or not all(isinstance(p, str) for p in files):
            raise SystemExit('Configure an explicit test file allowlist')
        base = Path(tempfile.mkdtemp(prefix='knowledge-hub-policy-'))
        policy = base / 'policy.json'
        policy.write_text(json.dumps({'files': files}), encoding='utf-8')
        os.environ.update(KH_SYNTHETIC_ONLY='yes', KH_INGRESS_ONLY='yes',
                          KH_POLICY=str(policy), HOST='0.0.0.0', KH_SMB_OPTIONS=str(options_path))
os.execv(sys.executable, [sys.executable, '/app/app.py'])
