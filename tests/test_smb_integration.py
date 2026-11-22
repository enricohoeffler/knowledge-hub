"""Run only against a disposable Samba server containing synthetic data."""
import hashlib
import os
import unittest
from smb_storage import SMBStorage, Conflict

digest = lambda value: hashlib.sha256(value).hexdigest()


class SMBIntegration(unittest.TestCase):
    def test_read_write_conflict_and_path_restrictions(self):
        storage = SMBStorage({'smb_server': os.environ['TEST_SMB_SERVER'],
                              'smb_share': 'khfixture', 'smb_username': 'khfixture',
                              'smb_password': 'fixturepass', 'smb_subdirectory': ''})
        before = storage.read('index.md')
        updated = before + b'\nSynthetic test update\n'
        storage.write('index.md', updated, digest(before), digest)
        self.assertEqual(storage.read('index.md'), updated)
        with self.assertRaises(Conflict):
            storage.write('index.md', b'outdated', digest(before), digest)
        self.assertEqual(storage.read('index.md'), updated)
        for path in ('../index.md', '/index.md', 'other\\index.md', 'index.md:stream'):
            with self.subTest(path=path), self.assertRaises((OSError, ValueError)):
                storage.read(path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
