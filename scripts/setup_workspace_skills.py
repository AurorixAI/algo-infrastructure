#!/usr/bin/env python3
"""Connect versioned ALGO instructions to a sibling-repository workspace."""
import argparse
import os
from pathlib import Path

SKILLS = ("algo-feature-delivery", "algo-diagnostic-evidence", "algo-git-release")


def setup(workspace: Path, infrastructure: Path) -> list[str]:
    workspace = workspace.resolve()
    infrastructure = infrastructure.resolve()
    links = [(workspace / "AGENTS.md", infrastructure / "docs/engineering/WORKSPACE_AGENTS.md")]
    links += [(workspace / ".agents/skills" / name, infrastructure / ".agents/skills" / name) for name in SKILLS]
    # Preflight every destination before creating anything; never replace user files.
    for destination, source in links:
        required = source if source.suffix == ".md" else source / "SKILL.md"
        if not required.is_file():
            raise ValueError(f"Missing canonical instruction: {required}")
        if destination.exists() or destination.is_symlink():
            if not destination.is_symlink() or destination.resolve() != source:
                raise ValueError(f"Existing instruction would be replaced: {destination}")
    installed = []
    for destination, source in links:
        if not destination.is_symlink():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(os.path.relpath(source, destination.parent), target_is_directory=source.is_dir())
        installed.append(str(destination))
    return installed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        for path in setup(args.workspace, Path(__file__).resolve().parents[1]):
            print(path)
    except ValueError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
