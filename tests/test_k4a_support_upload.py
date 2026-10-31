"""K4a «Поддержка»: ONE screenshot per request, JPEG / PNG up to 2 MB.  The server block of the product allows 50m for the imports, and nginx buffers a request body before it
forwards it: a 40 MB «screenshot» would be received in full only to be refused by the application.  The upload path therefore has its own location with a 3m limit
(the file + the frame of the form).  The test picks the location nginx would pick in the three server blocks that serve the product API and checks the limit, the
proxying (the same as the prefix location it replaces) and that nothing else lost its 50m."""
import re
import unittest
from pathlib import Path

from test_k2_error_log_masks import CONF, chosen, locations, server_block

UPLOAD = "/api/v1/auth/support/tickets/6f1c2a3e-1111-4222-8333-944455556666/attachments"
OTHER_AUTH = (
    "/api/v1/auth/support/tickets", "/api/v1/auth/support/tickets/6f1c2a3e-1111-4222-8333-944455556666",
    "/api/v1/auth/support/tickets/6f1c2a3e-1111-4222-8333-944455556666/messages", "/api/v1/auth/support/attachments/6f1c2a3e-1111-4222-8333-944455556666",
    "/api/v1/auth/org/import/commit", "/api/v1/auth/org/import/preview", "/api/v1/auth/login",
)
BLOCKS = (
    ("staging.conf", "server_name app.algolab.me;"),
    ("preview.conf", "server_name stage.algolab.me;"),
    ("staging-apex-landing.conf", "server_name algolab.me;\n    access_log /var/log/nginx/access.log landing_prod_safe;"),
)
PROXY_HEADERS = ("Host", "X-Real-IP", "X-Forwarded-For", "X-Forwarded-Proto")


def limit_of(body: str):
    m = re.search(r"client_max_body_size\s+(\d+)([kmg]?)\s*;", body)
    return None if m is None else int(m.group(1)) * {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[m.group(2)]


class SupportUploadHasItsOwnLimit(unittest.TestCase):
    def test_the_upload_path_is_served_by_a_location_with_a_limit_of_at_most_3m_in_every_block(self):
        for conf, marker in BLOCKS:
            block = server_block((CONF / conf).read_text(encoding="utf-8"), marker)
            location = chosen(block, UPLOAD)
            self.assertIsNotNone(location, conf)
            limit = limit_of(location[2])
            self.assertIsNotNone(limit, f"{conf}: the upload location has no client_max_body_size")
            self.assertGreaterEqual(limit, 2 * 1024 * 1024 + 64 * 1024, f"{conf}: a 2 MB file with the frame of the form would not pass")
            self.assertLessEqual(limit, 3 * 1024 * 1024, f"{conf}: nginx would buffer more than a screenshot")

    def test_the_other_paths_keep_the_50m_of_the_server_block_the_imports_need_it(self):
        for conf, marker in BLOCKS:
            block = server_block((CONF / conf).read_text(encoding="utf-8"), marker)
            for path in OTHER_AUTH:
                location = chosen(block, path)
                self.assertIsNotNone(location, f"{conf}: {path}")
                self.assertIsNone(limit_of(location[2]), f"{conf}: {path} is served by `{location[1]}` that sets its own limit")
            if conf != "staging-apex-landing.conf":                                  # the apex block is the landing: the product API there is the transitional alias
                self.assertEqual(limit_of(block.split("location", 1)[0]), 50 * 1024 * 1024, conf)

    def test_the_location_proxies_like_the_prefix_location_it_replaces(self):
        for conf, marker in BLOCKS:
            block = server_block((CONF / conf).read_text(encoding="utf-8"), marker)
            upload = chosen(block, UPLOAD)[2]
            twin = chosen(block, "/api/v1/auth/login")[2]
            for header in PROXY_HEADERS:
                self.assertRegex(upload, rf"proxy_set_header\s+{header}\s", f"{conf}: {header}")
            self.assertRegex(upload, r"limit_req\s+zone=\w+\s+burst=20\s+nodelay;", conf)
            self.assertEqual(re.search(r"limit_req\s+zone=(\w+)", upload).group(1), re.search(r"limit_req\s+zone=(\w+)", twin).group(1), conf)
            self.assertEqual(re.search(r"proxy_pass\s+(\S+?)(/api/v1/auth/)?;", upload).group(1).rstrip("/"), re.search(r"proxy_pass\s+(\S+?)(/api/v1/auth/)?;", twin).group(1).rstrip("/"), conf)

    def test_the_download_and_the_other_methods_of_the_neighbour_paths_are_not_caught_by_the_regex(self):
        regex = next(p for k, p, b in locations(server_block((CONF / "staging.conf").read_text(encoding="utf-8"), "server_name app.algolab.me;")) if "support" in p)
        self.assertTrue(re.search(regex, UPLOAD))
        for path in (UPLOAD + "/extra", "/api/v1/auth/support/attachments/abc", "/api/v1/auth/support/tickets//attachments", "/api/v1/auth/support/tickets/a/b/attachments"):
            self.assertFalse(re.search(regex, path), path)


if __name__ == "__main__":
    unittest.main()
