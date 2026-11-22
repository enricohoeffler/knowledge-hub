"""Explicit opt-in HA test launcher. Never connects to user data."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

options_path = Path('/data/options.json')
if options_path.is_file():
    options = json.loads(options_path.read_text(encoding='utf-8'))
    if options.get('synthetic_ha_test') is True:
        base = Path(tempfile.mkdtemp(prefix='knowledge-hub-fixtures-'))
        shutil.copytree('/app/fixtures/source', base / 'source')
        shutil.copyfile('/app/fixtures/policy.json', base / 'policy.json')
        os.environ.update(KH_SYNTHETIC_ONLY='yes', KH_INGRESS_ONLY='yes',
                          KH_ROOT=str(base / 'source'), KH_POLICY=str(base / 'policy.json'),
                          HOST='0.0.0.0')
os.execv(sys.executable, [sys.executable, '/app/app.py'])
