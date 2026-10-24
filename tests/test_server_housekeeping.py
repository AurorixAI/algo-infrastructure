"""scripts/server_housekeeping.sh: dump cleanup behind the nightly-backup gate; never prunes images."""
import datetime
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
        self.nightly = root / 'prod_nightly'
        self.nightly.mkdir()
        # Fake `docker` that records its argv instead of touching anything.
        self.bin = root / 'bin'
        self.bin.mkdir()
        self.docker_log = root / 'docker.log'
        fake = self.bin / 'docker'
        fake.write_text('#!/bin/sh\necho "$@" >> "%s"\n' % self.docker_log)
        fake.chmod(0o755)

    # ── fixtures ────────────────────────────────────────────────────────────
    def dump(self, name, age_days):
        path = self.dumps / name
        path.write_text('x')
        stamp = time.time() - age_days * DAY
        os.utime(path, (stamp, stamp))

    def nightly_dir(self, days_ago=0, dumps=4, sums=True, empty_dump=False):
        d = self.nightly / (datetime.date.today() - datetime.timedelta(days=days_ago)).strftime('%Y%m%d')
        d.mkdir()
        for i in range(dumps):
            (d / f'algo-staging-db{i}.dump').write_text('' if (empty_dump and i == 0) else 'data')
        if sums:
            (d / 'SHA256SUMS').write_text('abc  file\n')

    def fixture(self):
        self.dump('tails-prod-auth-20261017-1516.sql.gz', 20)      # old -> deleted
        self.dump('prod_auth_pre_release_20261024_0935.sql.gz', 3)  # young -> kept
        self.dump('algo_content_20260801_043527.dump', 60)          # old -> deleted
        self.dump('algo_content_20261022_043527.dump', 2)           # young -> kept
        self.dump('exactly-edge-20261001.sql.gz', 15)               # old -> deleted
        self.dump('notes.txt', 90)                                  # other types never touched
        self.dump('wave.jsonl', 90)
        self.dump('apply.sh', 90)
        self.dump('archive.tar.gz', 90)
        sub = self.dumps / 'subdir'
        sub.mkdir()
        (sub / 'nested.sql.gz').write_text('x')                     # not directly in DUMP_DIR
        old = time.time() - 90 * DAY
        os.utime(sub / 'nested.sql.gz', (old, old))

    OLD = {'tails-prod-auth-20261017-1516.sql.gz', 'algo_content_20260801_043527.dump',
           'exactly-edge-20261001.sql.gz'}

    def run_script(self, *args):
        env = dict(os.environ, DUMP_DIR=str(self.dumps), NIGHTLY_DIR=str(self.nightly),
                   PATH=f'{self.bin}:{os.environ["PATH"]}')
        return subprocess.run(['bash', str(SCRIPT), *args], env=env, capture_output=True, text=True)

    def names(self):
        return {p.name for p in self.dumps.iterdir()}

    def docker_calls(self):
        return self.docker_log.read_text().splitlines() if self.docker_log.exists() else []

    # ── gate ok ─────────────────────────────────────────────────────────────
    def test_gate_ok_deletes_only_old_sql_gz_and_dump(self):
        self.fixture()
        before = self.names()
        self.nightly_dir(days_ago=1)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.names(), before - self.OLD)
        self.assertTrue((self.dumps / 'subdir' / 'nested.sql.gz').exists())
        self.assertIn('dumps deleted: 3', result.stdout)
        self.assertEqual(result.stdout.count('Filesystem'), 2, 'df -h / before and after')
        self.assertNotIn('WARNING', result.stdout)

    def test_dry_run_deletes_nothing_and_prunes_nothing(self):
        self.fixture()
        before = self.names()
        self.nightly_dir(days_ago=0)
        result = self.run_script('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.names(), before)
        self.assertEqual(self.docker_calls(), [])
        self.assertEqual(result.stdout.count('would delete:'), 3)
        for name in self.OLD:
            self.assertIn('would delete: ' + str(self.dumps / name), result.stdout)
        self.assertIn('would run: docker builder prune -af --filter until=168h', result.stdout)

    # ── gate fails: nothing deleted, cache still pruned, exit 0, WARNING ────
    def assert_skipped(self):
        before = self.names()
        self.docker_log.unlink(missing_ok=True)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.names(), before)
        self.assertIn('WARNING', result.stdout)
        self.assertIn('dump cleanup skipped', result.stdout)
        self.assertEqual(self.docker_calls(), ['builder prune -af --filter until=168h'])
        return result

    def test_stale_nightly_skips_dump_cleanup(self):
        self.fixture()
        self.nightly_dir(days_ago=5)
        self.assertIn('older than 2 days', self.assert_skipped().stdout)

    def test_missing_nightly_skips_dump_cleanup(self):
        self.fixture()   # NIGHTLY_DIR exists but has no dated directory
        self.assert_skipped()
        self.nightly.rmdir()   # and NIGHTLY_DIR itself missing
        self.assert_skipped()

    def test_incomplete_nightly_skips_dump_cleanup(self):
        self.fixture()
        for kwargs in ({'sums': False}, {'dumps': 3}, {'empty_dump': True}):
            with self.subTest(**kwargs):
                for d in self.nightly.iterdir():
                    for f in d.iterdir():
                        f.unlink()
                    d.rmdir()
                self.docker_log.unlink(missing_ok=True)
                self.nightly_dir(days_ago=0, **kwargs)
                self.assert_skipped()

    # ── misc ────────────────────────────────────────────────────────────────
    def test_only_build_cache_is_pruned_never_images(self):
        self.fixture()
        self.nightly_dir()
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.docker_calls(), ['builder prune -af --filter until=168h'])
        text = SCRIPT.read_text()
        for forbidden in ('image prune', 'system prune', 'docker rmi', 'docker image rm', 'volume prune'):
            self.assertNotIn(forbidden, text)

    def test_missing_dump_directory_is_not_an_error(self):
        self.dumps.rmdir()
        self.nightly_dir()
        result = self.run_script('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('does not exist', result.stdout)

    def test_unknown_argument_is_rejected(self):
        result = self.run_script('--delete-everything')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.docker_calls(), [])


if __name__ == '__main__':
    unittest.main()
