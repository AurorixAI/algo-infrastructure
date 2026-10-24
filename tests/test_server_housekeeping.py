"""scripts/server_housekeeping.sh: dump retention and the "never prune images" rule."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'server_housekeeping.sh'
DAY = 86400


class HousekeepingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.dumps = root / 'release_dumps'
        self.dumps.mkdir()
        # Fake `docker` that records its argv instead of touching anything.
        self.bin = root / 'bin'
        self.bin.mkdir()
        self.docker_log = root / 'docker.log'
        fake = self.bin / 'docker'
        fake.write_text('#!/bin/sh\necho "$@" >> "%s"\n' % self.docker_log)
        fake.chmod(0o755)

    def dump(self, name, age_days):
        path = self.dumps / name
        path.write_text('x')
        stamp = time.time() - age_days * DAY
        os.utime(path, (stamp, stamp))
        return path

    def run_script(self, *args):
        env = dict(os.environ, DUMP_DIR=str(self.dumps), PATH=f'{self.bin}:{os.environ["PATH"]}')
        return subprocess.run(['bash', str(SCRIPT), *args], env=env, capture_output=True, text=True)

    def names(self):
        return sorted(p.name for p in self.dumps.iterdir())

    def docker_calls(self):
        return self.docker_log.read_text().splitlines() if self.docker_log.exists() else []

    def fixture(self):
        # prod_auth: 4 dumps, 3 older than 14 days -> the 2 newest survive regardless of age.
        self.dump('prod_auth_20260901_0300.sql.gz', 50)
        self.dump('prod_auth_20260910_0300.sql.gz', 40)
        self.dump('prod_auth_20260920_0300.sql.gz', 30)
        self.dump('prod_auth_20261020_0300.sql.gz', 3)
        # prod_exam: 3 dumps, third is old; 2nd is young.
        self.dump('prod_exam_20260905_0300.sql.gz', 45)
        self.dump('prod_exam_20261015_0300.sql.gz', 8)
        self.dump('prod_exam_20261022_0300.sql.gz', 2)
        # prod_diag: exactly two, both old -> both kept (two newest rule).
        self.dump('prod_diag_20260801_0300.sql.gz', 80)
        self.dump('prod_diag_20260802_0300.sql.gz', 79)
        # 3 dumps, the oldest is only 10 days old: young, kept.
        self.dump('prod_x_20261001_0300.sql.gz', 10)
        self.dump('prod_x_20261010_0300.sql.gz', 5)
        self.dump('prod_x_20261012_0300.sql.gz', 4)
        # Other files must never be touched.
        self.dump('algo_content_20260801_0300.dump', 90)
        self.dump('notes.txt', 90)
        self.dump('undated.sql.gz', 90)

    def test_dry_run_deletes_nothing_and_prunes_nothing(self):
        self.fixture()
        before = self.names()
        result = self.run_script('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.names(), before)
        self.assertEqual(self.docker_calls(), [])
        out = result.stdout
        self.assertIn('would delete: ' + str(self.dumps / 'prod_auth_20260901_0300.sql.gz'), out)
        self.assertIn('would delete: ' + str(self.dumps / 'prod_auth_20260910_0300.sql.gz'), out)
        self.assertIn('would delete: ' + str(self.dumps / 'prod_exam_20260905_0300.sql.gz'), out)
        self.assertEqual(out.count('would delete:'), 3)
        self.assertIn('would run: docker builder prune -af --filter until=168h', out)
        self.assertEqual(out.count('Filesystem'), 2, 'df -h / before and after')

    def test_real_run_keeps_two_newest_per_prefix_and_other_files(self):
        self.fixture()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.names(), sorted([
            'prod_auth_20260920_0300.sql.gz', 'prod_auth_20261020_0300.sql.gz',
            'prod_exam_20261015_0300.sql.gz', 'prod_exam_20261022_0300.sql.gz',
            'prod_diag_20260801_0300.sql.gz', 'prod_diag_20260802_0300.sql.gz',
            'prod_x_20261001_0300.sql.gz', 'prod_x_20261010_0300.sql.gz', 'prod_x_20261012_0300.sql.gz',
            'algo_content_20260801_0300.dump', 'notes.txt', 'undated.sql.gz',
        ]))

    def test_only_build_cache_is_pruned_never_images(self):
        self.fixture()
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.docker_calls(), ['builder prune -af --filter until=168h'])
        text = SCRIPT.read_text()
        for forbidden in ('image prune', 'system prune', 'docker rmi', 'docker image rm', 'volume prune'):
            self.assertNotIn(forbidden, text)

    def test_missing_dump_directory_is_not_an_error(self):
        self.dumps.rmdir()
        result = self.run_script('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('does not exist', result.stdout)

    def test_unknown_argument_is_rejected(self):
        result = self.run_script('--delete-everything')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.docker_calls(), [])


if __name__ == '__main__':
    unittest.main()
