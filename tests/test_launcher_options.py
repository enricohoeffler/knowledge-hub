"""The removed legacy option must not affect SMB startup."""
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch


class LauncherOptions(unittest.TestCase):
    def test_legacy_option_is_ignored(self):
        options = {
            'smb_test_enabled': True,
            'smb_server': 'smb.example',
            'smb_share': 'test',
            'smb_username': 'test',
            'smb_password': 'test',
            'allowed_files': 'obsolete-invalid-value',
        }
        with patch.object(Path, 'is_file', return_value=True), \
             patch.object(Path, 'read_text', return_value=json.dumps(options)), \
             patch.object(Path, 'write_text') as write, \
             patch('tempfile.mkdtemp', return_value='/tmp/test-policy'), \
             patch('os.execv') as execute, \
             patch.dict('os.environ', {}, clear=True):
            runpy.run_path('/app/launcher.py')
        self.assertEqual(json.loads(write.call_args.args[0]), {'files': []})
        execute.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
