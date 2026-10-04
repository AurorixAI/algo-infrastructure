import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("setup_workspace_skills", Path(__file__).resolve().parents[1] / "scripts/setup_workspace_skills.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class WorkspaceSkillsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.infrastructure = self.workspace / "algo-infrastructure"
        instructions = self.infrastructure / "docs/engineering/WORKSPACE_AGENTS.md"
        instructions.parent.mkdir(parents=True)
        instructions.write_text("Canonical instructions")
        for name in module.SKILLS:
            source = self.infrastructure / ".agents/skills" / name / "SKILL.md"
            source.parent.mkdir(parents=True)
            source.write_text(name)

    def test_install_and_repeat_use_canonical_files(self):
        first = module.setup(self.workspace, self.infrastructure)
        self.assertEqual(first, module.setup(self.workspace, self.infrastructure))
        self.assertEqual(len(first), 4)
        for path in first:
            self.assertTrue(Path(path).is_symlink())
            self.assertTrue(Path(path).exists())
        source = self.infrastructure / ".agents/skills" / module.SKILLS[0] / "SKILL.md"
        source.write_text("Updated in Git")
        self.assertEqual((self.workspace / ".agents/skills" / module.SKILLS[0] / "SKILL.md").read_text(), "Updated in Git")

    def test_conflict_is_preserved_before_any_links_created(self):
        destination = self.workspace / ".agents/skills" / module.SKILLS[-1]
        destination.mkdir(parents=True)
        (destination / "SKILL.md").write_text("User instructions")
        with self.assertRaises(ValueError):
            module.setup(self.workspace, self.infrastructure)
        self.assertFalse((self.workspace / "AGENTS.md").exists())
        self.assertEqual((destination / "SKILL.md").read_text(), "User instructions")

    def test_missing_canonical_skill_does_not_install_partial_instructions(self):
        (self.infrastructure / ".agents/skills" / module.SKILLS[0] / "SKILL.md").unlink()
        with self.assertRaises(ValueError):
            module.setup(self.workspace, self.infrastructure)
        self.assertFalse((self.workspace / "AGENTS.md").exists())


if __name__ == "__main__":
    unittest.main()
