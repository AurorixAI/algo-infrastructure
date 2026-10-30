"""K2-1 (L2, m8, m9): the letters' settings of the two stacks must not drift apart, and the stage guard must not be lost.

* ``MAIL_REPLY_TO`` is the same expression in the prod and the stage compose (the support alias, not a personal address);
* ``MAIL_STAGE_MODE=true`` is in the stage (preview) compose and NOT in the prod one: without it the stage would send to everybody once SMTP keys appear
  (both stacks run APP_ENV=staging, the environment name cannot tell them apart);
* ``MAIL_ALLOWLIST`` and ``JWT_REFRESH_TTL_DAYS=14`` reach auth-service on both stacks; ``compose/.env.example`` documents all four.
Plain text parsing of the ``auth-service`` block (no YAML library in the CI image of this job)."""
import re
import unittest
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[1] / "compose"


def auth_env(name: str) -> dict:
    lines = (COMPOSE / name).read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if re.fullmatch(r"  auth-service:\s*", line))
    out = {}
    for line in lines[start + 1:]:
        if re.fullmatch(r"  [A-Za-z0-9_-]+:\s*", line):          # the next service
            break
        m = re.match(r"\s+- ([A-Z][A-Z0-9_]*)=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


class MailEnvTests(unittest.TestCase):
    def setUp(self):
        self.prod = auth_env("docker-compose.staging.yml")       # (the file called «staging» is PRODUCTION)
        self.stage = auth_env("docker-compose.preview.yml")

    def test_reply_to_is_the_same_support_alias_on_both_stacks(self):
        self.assertEqual(self.prod["MAIL_REPLY_TO"], self.stage["MAIL_REPLY_TO"])
        self.assertEqual(self.prod["MAIL_REPLY_TO"], "${MAIL_REPLY_TO:-support@algolab.me}")

    def test_the_stage_is_marked_and_prod_is_not(self):
        self.assertEqual(self.stage.get("MAIL_STAGE_MODE"), "true")
        self.assertNotIn("MAIL_STAGE_MODE", self.prod)

    def test_the_allow_list_and_the_session_length_reach_both_stacks(self):
        for env in (self.prod, self.stage):
            self.assertEqual(env["MAIL_ALLOWLIST"], "${MAIL_ALLOWLIST:-}")
            self.assertEqual(env["JWT_REFRESH_TTL_DAYS"], "${JWT_REFRESH_TTL_DAYS:-14}")

    def test_the_stage_mails_only_behind_the_stage_guard(self):
        # lead 30.10: the stage walk needs real letters (owner's Zoho), so the stage has the prod relay; then the guard is the stage mode
        # (auth sends only to MAIL_ALLOWLIST, nothing while it is empty; checked twice in auth, send() and deliver())
        if "SMTP_HOST" in self.stage:
            self.assertEqual(self.stage.get("MAIL_STAGE_MODE"), "true")
            self.assertEqual(self.stage.get("MAIL_ALLOWLIST"), "${MAIL_ALLOWLIST:-}")

    def test_the_env_example_documents_the_four_variables(self):
        text = (COMPOSE / ".env.example").read_text(encoding="utf-8")
        for name in ("MAIL_REPLY_TO=support@algolab.me", "MAIL_ALLOWLIST=", "JWT_REFRESH_TTL_DAYS=14", "MAIL_STAGE_MODE"):
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
