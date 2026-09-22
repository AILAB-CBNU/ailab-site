import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"img", "script"} and attributes.get("src"):
            self.values.append(attributes["src"])
        if tag == "link" and attributes.get("href"):
            self.values.append(attributes["href"])
        if tag == "a" and attributes.get("href"):
            self.values.append(attributes["href"])


class StaticSiteTests(unittest.TestCase):
    def test_internal_html_references_exist(self):
        missing = []
        for page in SITE.glob("*.html"):
            parser = References()
            parser.feed(page.read_text(encoding="utf-8"))
            for value in parser.values:
                parsed = urlsplit(value)
                if parsed.scheme or value.startswith(("#", "mailto:", "tel:", "//")):
                    continue
                relative = unquote(parsed.path)
                if not relative:
                    continue
                target = (page.parent / relative).resolve()
                try:
                    target.relative_to(SITE.resolve())
                except ValueError:
                    missing.append((page.name, value, "outside site"))
                    continue
                if not target.exists():
                    missing.append((page.name, value, "missing"))
        self.assertEqual(missing, [])

    def test_professor_photo_and_seminar_page_are_wired(self):
        data = (SITE / "js" / "data.js").read_text(encoding="utf-8")
        navigation = (SITE / "js" / "main.js").read_text(encoding="utf-8")
        self.assertIn('"photo": "assets/people/kmlee.png"', data)
        self.assertTrue((SITE / "assets" / "people" / "kmlee.png").is_file())
        self.assertIn('["seminars.html", "nav_seminars"]', navigation)
        self.assertTrue((SITE / "seminars.html").is_file())

    def test_windows_https_portable_assets(self):
        caddyfile = (ROOT / "Caddyfile").read_text(encoding="utf-8")
        self.assertIn("ailab.cbnu.ac.kr", caddyfile)
        self.assertIn("reverse_proxy 127.0.0.1:8765", caddyfile)
        self.assertTrue((ROOT / "server" / "https_launcher.py").is_file())
        for name in (
            "05-ALLOW-HTTPS-AS-ADMIN.bat",
            "06-START-HTTPS-WEBSITE.bat",
            "07-CHECK-HTTPS.bat",
        ):
            (ROOT / name).read_bytes().decode("ascii")

    def test_admin_editor_is_linked_to_every_public_page(self):
        self.assertTrue((SITE / "admin.html").is_file())
        self.assertTrue((SITE / "js" / "admin.js").is_file())
        self.assertTrue((SITE / "js" / "cms.js").is_file())
        for name in (
            "index.html",
            "research.html",
            "people.html",
            "publications.html",
            "projects.html",
            "news.html",
            "seminars.html",
            "resources.html",
            "contact.html",
        ):
            self.assertIn("js/cms.js", (SITE / name).read_text(encoding="utf-8"), name)
        self.assertIn('["admin.html", lang === "ko" ? "관리자" : "Admin"]', (SITE / "js" / "main.js").read_text(encoding="utf-8"))
        (ROOT / "08-SET-ADMIN-PASSWORD.bat").read_bytes().decode("ascii")


if __name__ == "__main__":
    unittest.main()
