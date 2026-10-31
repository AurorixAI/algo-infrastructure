"""K4a (R3-4, LESSONS 77): the words after which the next segment of an address is a one-time token or a code live in ONE list in the front (``src/lib/public-pages.ts``,
``TOKEN_SEGMENTS_MASKED_BY_NGINX``).  The support masks the segment after each of them in the page and the failed calls it attaches to a request; nginx must mask the SAME
words in its access logs (and ``error_log crit`` where the token is in the path: ``test_k2_error_log_masks.py``).  This test keeps the literal list; the same list is in
``algo-front-p154/tests/k4a-front.test.cjs`` and ``auth-service-p154/tests/test_k4a_support_unit.py``: change them TOGETHER with public-pages.ts and the maps of nginx."""
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Change together with public-pages.ts (TOKEN_SEGMENTS_MASKED_BY_NGINX), support_rules._TOKEN_PREFIXES and the maps of nginx.
TOKEN_WORDS_MASKED_BY_NGINX = {"invite", "set-password", "confirm-email", "d", "e", "diagnostic", "password-links", "email-change", "by-code"}
# which map line masks the word: a page (/<word>/<token>) or an API route (/api/v1/<...>/<word>/<token>)
PAGES = {"invite", "set-password", "confirm-email", "d", "e", "diagnostic"}
API = {"password-links": "auth/password-links", "email-change": "auth/email-change", "invite": "auth/invite", "diagnostic": "auth/diagnostic", "by-code": "exams/by-code"}


def map_block(text: str, name: str) -> str:
    start = text.index(f"map $uri ${name}")
    return text[start:text.index("\n}\n", start)]


class EveryTokenWordIsMaskedInTheLogs(unittest.TestCase):
    def check(self, conf: str, var: str) -> None:
        block = map_block((ROOT / "nginx" / "conf.d" / conf).read_text(encoding="utf-8"), var)
        pages = set(re.search(r"\(\?<\w+>([^)]*)\)/\[\^/\]\+", block).group(1).split("|"))
        for word in sorted(TOKEN_WORDS_MASKED_BY_NGINX):
            self.assertTrue(word in PAGES or word in API, f"{word}: neither a page nor an API route in this test: add it")
            if word in PAGES:
                self.assertIn(word, pages, f"{conf}: the page /{word}/<token> is not masked")
            if word in API:
                path = API[word]
                masked = re.search(rf"\^/api/v1/(?:\(\?<\w+>[^)]*\)|{re.escape(path.split('/')[0])})/?{re.escape(path.split('/')[1])}/\[\^/\]\+", block) or re.search(rf"\^/api/v1/{re.escape(path)}/\[\^/\]\+", block)
                self.assertIsNotNone(masked, f"{conf}: /api/v1/{path}/<token> is not masked")

    def test_production(self):
        self.check("staging.conf", "prod_safe_uri")

    def test_stage(self):
        self.check("preview.conf", "preview_safe_uri")

    def test_the_session_id_under_a_masked_code_is_masked_too(self):
        for conf, var in (("staging.conf", "prod_safe_uri"), ("preview.conf", "preview_safe_uri")):
            block = map_block((ROOT / "nginx" / "conf.d" / conf).read_text(encoding="utf-8"), var)
            self.assertRegex(block, r"by-code/\[\^/\]\+/session-status/\[\^/\]\+", conf)

    def test_the_list_of_this_test_is_the_list_of_the_front(self):
        front = Path(os.environ.get("ALGO_FRONT_PATH") or ROOT.parent / "algo-front-p154") / "src" / "lib" / "public-pages.ts"
        if not front.exists():                                                   # CI of this repository has no front beside it: the front test compares its side
            self.skipTest("the front is not beside this repository")
        words = set(re.findall(r'"([a-z-]+)"', re.search(r"TOKEN_SEGMENTS_MASKED_BY_NGINX = \[(.*?)\] as const", front.read_text(encoding="utf-8"), re.S).group(1)))
        self.assertEqual(words, TOKEN_WORDS_MASKED_BY_NGINX)


if __name__ == "__main__":
    unittest.main()
