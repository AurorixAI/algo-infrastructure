"""Real Git tests for the boundary between reviewed sources and build input."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_git_release.py"
spec = importlib.util.spec_from_file_location("prepare_git_release", SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, check=True).stdout.strip()


class GitSourceReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "algo-front"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "CEO")
        git(self.repo, "config", "user.email", "release-test@example.invalid")
        git(self.repo, "config", "user.name", "Release tests")
        (self.repo / ".gitignore").write_text(".env.private\nignored-cache/\n")
        (self.repo / "source.txt").write_text("reviewed source\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "First reviewed source")
        self.sha = git(self.repo, "rev-parse", "HEAD")
        self.remote = self.base / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)],
                       check=True, capture_output=True)
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "origin", "CEO")

    def test_only_pushed_full_sha_is_accepted(self):
        result = release.validate_source(self.repo, self.sha)
        self.assertEqual(result["observed_origin_CEO_sha"], self.sha)
        with self.assertRaises(release.ReleaseError):
            release.validate_source(self.repo, self.sha[:12])
        (self.repo / "source.txt").write_text("unpublished source\n")
        git(self.repo, "commit", "-am", "Not pushed")
        with self.assertRaises(release.ReleaseError):
            release.validate_source(self.repo, git(self.repo, "rev-parse", "HEAD"))

    def test_dirty_tracked_and_untracked_sources_are_rejected(self):
        (self.repo / "source.txt").write_text("pending source\n")
        with self.assertRaises(release.ReleaseError):
            release.validate_source(self.repo, self.sha)
        git(self.repo, "checkout", "--", "source.txt")
        (self.repo / "unreviewed.py").write_text("# pending\n")
        with self.assertRaises(release.ReleaseError):
            release.validate_source(self.repo, self.sha)

    def test_clean_ignored_files_cannot_enter_archive(self):
        (self.repo / ".env.private").write_text("synthetic-private-value\n")
        cache = self.repo / "ignored-cache"
        cache.mkdir()
        (cache / "unreviewed.txt").write_text("ignored source\n")
        output = self.base / "prepared"
        with patch.object(release, "REPOSITORIES", ("algo-front",)):
            result = release.prepare(self.base, output, {"algo-front": self.sha})
        source = result["sources"]["algo-front"]
        archive = output / source["archive"]
        with tarfile.open(archive) as tar:
            self.assertEqual(set(tar.getnames()), {".gitignore", "source.txt"})
            self.assertEqual(tar.extractfile("source.txt").read(), b"reviewed source\n")
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), source["archive_sha256"])
        self.assertFalse(result["deployment_performed"])
        with patch.object(release, "REPOSITORIES", ("algo-front",)):
            with self.assertRaises(release.ReleaseError):
                release.prepare(self.base, output, {"algo-front": self.sha})

    def test_pushed_ancestor_does_not_follow_newer_branch_tip(self):
        (self.repo / "source.txt").write_text("later branch tip\n")
        git(self.repo, "commit", "-am", "Later source")
        latest = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "push", "origin", "CEO")
        result = release.validate_source(self.repo, self.sha)
        self.assertEqual(result["commit_sha"], self.sha)
        self.assertEqual(result["observed_origin_CEO_sha"], latest)

    def test_tracked_private_config_is_rejected(self):
        (self.repo / ".env.dev").write_text("synthetic-test-only\n")
        git(self.repo, "add", ".env.dev")
        git(self.repo, "commit", "-m", "Tracked private filename")
        git(self.repo, "push", "origin", "CEO")
        with self.assertRaises(release.ReleaseError):
            release.validate_source(self.repo, git(self.repo, "rev-parse", "HEAD"))

    def test_safe_env_examples_remain_versioned_build_inputs(self):
        for name in (".env.production.example", ".env.demo.example"):
            (self.repo / name).write_text("SYNTHETIC_PLACEHOLDER=replace-on-server\n")
            git(self.repo, "add", name)
        git(self.repo, "commit", "-m", "Document safe env schema")
        git(self.repo, "push", "origin", "CEO")
        result = release.validate_source(self.repo, git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(result["tracked_file_count"], 4)

    def test_non_CEO_checkout_is_rejected(self):
        git(self.repo, "checkout", "-b", "develop")
        with self.assertRaises(release.ReleaseError):
            release.validate_source(self.repo, self.sha)


if __name__ == "__main__":
    unittest.main()
