"""Exercise the guard against a disposable repository, including staged content."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys


class PublicationGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'scripts').mkdir()
        source = Path(__file__).resolve().parents[2] / 'scripts/check-publication.py'
        shutil.copy(source, self.root / 'scripts/check-publication.py')
        self.git('init', '-q')

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True)

    def check(self, *args):
        return subprocess.run([sys.executable, str(self.root / 'scripts/check-publication.py'), *args], capture_output=True, text=True)

    def test_database_with_innocent_extension_is_blocked(self):
        (self.root / 'export.bin').write_bytes(b'SQLite format 3' + bytes([0]))
        self.assertNotEqual(self.check().returncode, 0)

    def test_forced_database_in_index_is_blocked(self):
        (self.root / '.gitignore').write_text('*.db\n')
        (self.root / 'players.db').write_bytes(b'private')
        self.git('add', '-f', 'players.db')
        self.assertNotEqual(self.check('--staged').returncode, 0)

    def test_staged_secret_cannot_be_hidden_by_clean_working_file(self):
        secret = 'ghp_' + 'A' * 36
        p = self.root / 'config.txt'
        p.write_text(secret)
        self.git('add', 'config.txt')
        p.write_text('safe')
        result = self.check('--staged')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(secret, result.stdout)
        self.assertEqual(self.check().returncode, 0)

    def test_shareable_example_is_allowed(self):
        (self.root / '.env.example').write_text('GAME_ADMIN_PLAYER_ID=\n')
        self.assertEqual(self.check().returncode, 0)
