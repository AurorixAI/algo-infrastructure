"""K2-2 (F; LESSONS 68): the pages of a one-time token are listed in ONE place in the front (``src/lib/public-pages.ts``: invite, set-password, confirm-email) and
nginx must hide the token of EVERY one of them (and of the API calls behind them) in the access logs of both stacks. This test keeps the literal list; the front test
``tests/k2-2-front.test.cjs`` keeps the same list: change both together. Also: the Turnstile site key reaches the front build and the hosts list names both hosts' env."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_PAGES = ("invite", "set-password", "confirm-email")
API_TOKEN_PATHS = ("auth/password-links", "auth/invite", "auth/email-change")


def map_block(text: str, name: str) -> str:
    start = text.index(f"map $uri ${name}")
    return text[start:text.index("\n}\n", start)]


class TokenPagesAreMasked(unittest.TestCase):
    def check(self, conf: str, var: str) -> None:
        block = map_block((ROOT / "nginx" / "conf.d" / conf).read_text(encoding="utf-8"), var)
        pages = re.search(r"\(\?<\w+>([^)]*)\)/\[\^/\]\+", block).group(1).split("|")
        for page in TOKEN_PAGES:
            self.assertIn(page, pages, f"{conf}: the page /{page}/<token> is not masked")
        for path in API_TOKEN_PATHS:
            self.assertRegex(block, rf"\^/api/v1/{re.escape(path)}/\[\^/\]\+", f"{conf}: /api/v1/{path}/<token> is not masked")

    def test_production_masks_every_token_page(self):
        self.check("staging.conf", "prod_safe_uri")

    def test_stage_masks_every_token_page(self):
        self.check("preview.conf", "preview_safe_uri")


class TurnstileReachesTheFront(unittest.TestCase):
    def test_both_stacks_pass_the_site_key_to_the_front_build_and_the_env_example_documents_it(self):
        for name in ("docker-compose.staging.yml", "docker-compose.preview.yml"):
            text = (ROOT / "compose" / name).read_text(encoding="utf-8")
            self.assertIn("NEXT_PUBLIC_TURNSTILE_SITE_KEY: ${NEXT_PUBLIC_TURNSTILE_SITE_KEY:-}", text, name)
            self.assertIn("TURNSTILE_HOSTNAMES=${TURNSTILE_HOSTNAMES:-}", text, name)
        example = (ROOT / "compose" / ".env.example").read_text(encoding="utf-8")
        self.assertIn("NEXT_PUBLIC_TURNSTILE_SITE_KEY=", example)
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("NEXT_PUBLIC_TURNSTILE_SITE_KEY:", ci)


if __name__ == "__main__":
    unittest.main()
