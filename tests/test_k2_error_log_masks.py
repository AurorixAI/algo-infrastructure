"""K2-2 (stage walk): the access log hides the token of a path, but nginx writes the WHOLE request line into error.log when an upstream is down during a release
(`connect() failed … request: "GET /set-password/<token>"`). Every path that carries a one-time token must therefore be served by a location that has
``error_log … crit;`` (the 502 stays visible in the masked access log). The test picks the location nginx would pick (the longest prefix, then the first matching
regex) in the three server blocks that serve the product: app.algolab.me, stage.algolab.me, and the transitional API alias on algolab.me (API only)."""
import re
import unittest
from pathlib import Path

CONF = Path(__file__).resolve().parents[1] / "nginx" / "conf.d"
# the token pages (src/lib/public-pages.ts of the front: TOKEN_PAGES + CODE_PAGES) and the API paths whose mask `$..._safe_uri` hides
PAGES = ("/invite/CODE1", "/set-password/TOKEN1", "/confirm-email/TOKEN2", "/d/CODE2", "/e/CODE3", "/diagnostic/CODE4")
APIS = (
    "/api/v1/auth/password-links/TOKEN3", "/api/v1/auth/email-change/TOKEN4", "/api/v1/auth/invite/CODE5", "/api/v1/auth/diagnostic/CODE6",
    "/api/v1/exams/by-code/CODE7", "/api/v1/exams/by-code/CODE7/session-status/SESSION1",
)
NOT_TOKEN = ("/api/v1/auth/login", "/api/v1/auth/me", "/login", "/owner/dashboard")   # no token: the ordinary log level stays


def server_block(text: str, marker: str) -> str:
    start = text.index(marker)
    start = text.rfind("\nserver {", 0, start) + 1
    depth, i = 0, text.index("{", start)
    for j in range(i, len(text)):
        depth += text[j] == "{"
        depth -= text[j] == "}"
        if depth == 0:
            return text[start:j + 1]
    raise AssertionError("unbalanced server block")


def locations(block: str):
    """[(kind, pattern, body)] in file order; kind is 'prefix' or 'regex' (``~``)."""
    out = []
    for m in re.finditer(r"^    location\s+(~\*?\s+|\^~\s+|=\s+)?(\S+)\s*\{", block, re.M):
        depth, i = 0, m.end() - 1
        for j in range(i, len(block)):
            depth += block[j] == "{"
            depth -= block[j] == "}"
            if depth == 0:
                break
        kind = "regex" if (m.group(1) or "").startswith("~") else "prefix"
        out.append((kind, m.group(2), block[i:j + 1]))
    return out


def chosen(block: str, path: str):
    locs = locations(block)
    prefixes = [(len(p), (k, p, b)) for k, p, b in locs if k == "prefix" and path.startswith(p)]
    best = max(prefixes, key=lambda x: x[0])[1] if prefixes else None
    for k, p, b in locs:
        if k == "regex" and re.search(p, path):
            return (k, p, b)
    return best


class ErrorLogDoesNotCarryTheToken(unittest.TestCase):
    def check(self, conf, marker, paths):
        block = server_block((CONF / conf).read_text(encoding="utf-8"), marker)
        for path in paths:
            location = chosen(block, path)
            self.assertIsNotNone(location, f"{conf}: no location for {path}")
            self.assertRegex(location[2], r"error_log\s+\S+\s+crit\s*;", f"{conf}: {path} is served by `{location[1]}` that keeps the ordinary error_log level (the token would be written to error.log)")

    def test_the_app_host_of_production(self):
        self.check("staging.conf", "server_name app.algolab.me;", PAGES + APIS)

    def test_the_stage_host(self):
        self.check("preview.conf", "server_name stage.algolab.me;", PAGES + APIS)

    def test_the_api_alias_on_the_apex_host(self):
        self.check("staging-apex-landing.conf", "server_name algolab.me;\n    access_log /var/log/nginx/access.log landing_prod_safe;", APIS)

    def test_the_paths_without_a_token_keep_the_ordinary_level_and_the_same_proxying_as_before(self):
        for conf, marker in (("staging.conf", "server_name app.algolab.me;"), ("preview.conf", "server_name stage.algolab.me;")):
            block = server_block((CONF / conf).read_text(encoding="utf-8"), marker)
            for path in NOT_TOKEN:
                location = chosen(block, path)
                self.assertIsNotNone(location)
                self.assertNotRegex(location[2], r"error_log\s+\S+\s+crit", f"{conf}: {path}")
            # the regex locations only ADD the log level: every proxy_set_header of the prefix twin is there too
            by_pattern = {p: b for k, p, b in locations(block)}
            twin = by_pattern["/api/v1/auth/"]
            token_auth = next(b for k, p, b in locations(block) if k == "regex" and "password-links" in p)
            for header in re.findall(r"proxy_set_header\s+\S+\s+\S+;", twin):
                self.assertIn(header, token_auth, f"{conf}: the token location lost `{header}`")
            self.assertIn("limit_req", token_auth)                        # the rate limit of the auth API is kept on the token paths


if __name__ == "__main__":
    unittest.main()
