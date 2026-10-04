#!/usr/bin/env python3
"""Export pushed CEO commits as immutable build inputs; never deploy anything."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

REPOSITORIES = (
    "algo-front", "auth-service", "diagnostic-service", "exam-service",
    "content-service", "algo-infrastructure",
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ReleaseError(RuntimeError):
    pass


def git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, env=env, text=True,
            capture_output=True, timeout=45, check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        # Never forward stderr: credential helpers/remote URLs can contain secrets.
        raise ReleaseError(f"Git validation failed in {repo.name}: {args[0]}") from exc
    return result.stdout.strip()


def validate_source(repo: Path, sha: str) -> dict:
    if not SHA_RE.fullmatch(sha):
        raise ReleaseError(f"{repo.name}: require a full lowercase 40-character Git SHA")
    if git(repo, "branch", "--show-current") != "CEO":
        raise ReleaseError(f"{repo.name}: select the existing CEO branch first")
    if git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise ReleaseError(f"{repo.name}: commit reviewed changes before preparing a release")
    git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
    remote_line = git(repo, "ls-remote", "--exit-code", "origin", "refs/heads/CEO")
    fields = remote_line.split()
    if len(fields) != 2 or fields[1] != "refs/heads/CEO" or not SHA_RE.fullmatch(fields[0]):
        raise ReleaseError(f"{repo.name}: origin/CEO identity is unavailable")
    remote_head = fields[0]
    # This fails closed if the observed remote tip is absent locally. Fetch CEO
    # explicitly, then repeat; do not silently rely on a stale tracking ref.
    git(repo, "cat-file", "-e", f"{remote_head}^{{commit}}")
    git(repo, "merge-base", "--is-ancestor", sha, remote_head)
    files = git(repo, "ls-tree", "-r", "--name-only", sha).splitlines()
    for filename in files:
        name = Path(filename).name
        is_env = name == ".env" or name.startswith(".env.")
        is_example = name.endswith((".example", ".sample", ".template"))
        if (is_env and not is_example) or name in {"id_rsa", "id_ed25519"} or name.endswith(".key"):
            raise ReleaseError(f"{repo.name}: a private config/key filename is tracked")
    return {
        "commit_sha": sha, "git_tree": git(repo, "rev-parse", f"{sha}^{{tree}}"),
        "source_ref": "CEO", "observed_origin_CEO_sha": remote_head,
        "pushed_commit_verified": True, "tracked_file_count": len(files),
    }


def prepare(workspace: Path, output: Path, commits: dict[str, str]) -> dict:
    if set(commits) != set(REPOSITORIES):
        raise ReleaseError("Supply exactly one --commit NAME=SHA for each of the six repositories")
    if output.exists():
        raise ReleaseError("Output already exists; use a new release directory")
    sources = {}
    # Validate all sources before writing any output or archive.
    for name in REPOSITORIES:
        sources[name] = validate_source(workspace / name, commits[name])
    output.mkdir(parents=True, exist_ok=False)
    for name, source in sources.items():
        archive = output / f"{name}-{source['commit_sha']}.tar"
        git(workspace / name, "archive", "--format=tar", source["commit_sha"], f"--output={archive}")
        source["archive"] = archive.name
        source["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        source["archive_bytes"] = archive.stat().st_size
    manifest = {
        "schema_version": 1,
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": {"domain": "stage.algolab.me", "compose_project": "algo-preview"},
        "status": "prepared_git_sources_only",
        "sources": sources,
        "requires_before_stage_switch": [
            "CI and release tests for these exact commits/images",
            "built image ID or registry digest and dependency identity",
            "recorded migration heads and code/schema compatibility",
            "stage-only DB backups, content/figure fingerprint and previous images",
            "reviewed exact image override and operator authorization",
            "post-switch readiness, revision and browser acceptance",
        ],
        "deployment_performed": False,
        "secrets_included": False,
    }
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    (output / "source-manifest.json").write_text(text)
    (output / "source-manifest.sha256").write_text(
        hashlib.sha256(text.encode()).hexdigest() + "  source-manifest.json\n"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", action="append", required=True, metavar="NAME=FULL_SHA")
    args = parser.parse_args()
    commits = {}
    for item in args.commit:
        if "=" not in item:
            parser.error("--commit must be NAME=FULL_SHA")
        name, sha = item.split("=", 1)
        if name in commits:
            parser.error(f"duplicate --commit for {name}")
        commits[name] = sha
    try:
        manifest = prepare(args.workspace.resolve(), args.output.resolve(), commits)
    except ReleaseError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"manifest": str(args.output.resolve() / "source-manifest.json"),
                      "sources": len(manifest["sources"]), "deployment_performed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
