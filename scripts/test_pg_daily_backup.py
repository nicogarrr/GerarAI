"""Behavior tests: injected command failures must never become verified backups."""
import gzip
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / 'ops' / 'pg-daily-backup.sh'
MOCK = '''#!/usr/bin/env python3
import os,sys
from pathlib import Path
args=sys.argv[1:]; mode=os.environ.get('MOCK_MODE','ok')
with open(os.environ['CALLS'],'a') as f: f.write(repr(args)+'\\n')
joined=' '.join(args)
if args[0]=='run': print('container');sys.exit(0)
if args[0]=='rm': sys.exit(1 if mode=='cleanup' else 0)
if 'pg_isready' in args: sys.exit(1 if mode=='ready' else 0)
if 'pg_database_size' in joined: print('10');sys.exit(0)
if 'pg_dump' in joined:
 print('CREATE TABLE example (id int);')
 sys.exit(1 if mode=='dump' else 0)
if 'count(*)' in joined:
 print('0' if mode=='count' and 'cavaai-postgres' not in args else '1');sys.exit(0)
if 'psql' in args:
 sys.stdin.read()
 if mode=='restore': print('ERROR: invalid SQL',file=sys.stderr);sys.exit(1)
 sys.exit(0)
sys.exit(2)
'''


class BackupTests(unittest.TestCase):
    def run_case(self, mode='ok', keep='1', free='100000'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        binpath = root / 'bin'
        binpath.mkdir()
        for name, content in {
            'docker': MOCK,
            'df': '#!/bin/sh\nprintf "Filesystem MB Used Available Capacity Mounted\\nmock 100000 0 ' + free + ' 0 /\\n"\n',
            'sleep': '#!/bin/sh\nexit 0\n',
        }.items():
            path = binpath / name
            path.write_text(content)
            path.chmod(0o755)
        backup = root / 'backup'
        backup.mkdir()
        for name in ['pg-daily-20000101.sql.gz', 'pg-daily-20000102.sql.gz']:
            (backup / name).write_bytes(gzip.compress(b'old'))
            (backup / (name + '.verified')).write_text('strict_restore=ok\n')
        (backup / 'pg-daily-unverified.sql.gz').write_bytes(b'leave me')
        env = dict(os.environ, PATH=str(binpath)+':'+os.environ['PATH'],
                   BACKUP_DIR=str(backup), LOCKFILE=str(root / 'lock'),
                   BACKUP_KEEP=keep, MOCK_MODE=mode, CALLS=str(root / 'calls'))
        result = subprocess.run(['bash', str(SCRIPT)], env=env, capture_output=True, text=True)
        calls = (root / 'calls').read_text() if (root / 'calls').exists() else ''
        return result, backup, calls

    def test_success_strict_portable_and_rotation(self):
        result, backup, calls = self.run_case()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--no-owner --no-privileges', calls)
        self.assertIn('ON_ERROR_STOP=1', calls)
        self.assertIn('--single-transaction', calls)
        self.assertIn("'pg_isready', '-h', '127.0.0.1'", calls)
        self.assertIn("'--network', 'none'", calls)
        self.assertEqual(len(list(backup.glob('*.verified'))), 1)
        self.assertTrue((backup / 'pg-daily-unverified.sql.gz').exists())
        self.assertEqual(len(list(backup.glob('*.sha256'))), 1)

    def test_failures_retain_previous_and_no_success_marker(self):
        for mode in ['restore', 'dump', 'ready', 'count', 'cleanup']:
            with self.subTest(mode=mode):
                result, backup, calls = self.run_case(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(list(backup.glob('*.verified'))), 2)
                self.assertNotIn('OK ', (backup / 'pg-daily.log').read_text())
                self.assertEqual(list(backup.glob('*.part')), [])
                if mode not in ['dump']:
                    self.assertIn("'rm', '-fv'", calls)

    def test_insufficient_disk_never_dumps(self):
        result, backup, calls = self.run_case(free='100')
        self.assertEqual(result.returncode, 3)
        self.assertNotIn('pg_dump', calls)
        self.assertEqual(len(list(backup.glob('*.verified'))), 2)

    def test_invalid_retention_stops_early(self):
        result, _, calls = self.run_case(keep='0')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, '')


if __name__ == '__main__':
    unittest.main()
