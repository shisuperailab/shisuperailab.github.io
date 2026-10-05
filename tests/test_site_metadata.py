"""Offline checks for canonical URLs, structured data, and local references."""

import json
from html.parser import HTMLParser
from pathlib import Path
import unittest
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://shisuperailab.github.io"
PAGES = [
    "index.html", "research.html", "people.html", "publications.html",
    "openings.html", "news.html", "contact.html",
    "news/ai-lightning-talk.html", "news/jiale-shi-joins-utoledo.html",
]


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.canonicals = []
        self.meta = {}
        self.ids = []
        self.links = []
        self.schemas = []
        self.schema_text = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "meta":
            self.meta[attrs.get("name", attrs.get("property"))] = attrs.get("content")
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs["href"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.schema_text = ""

    def handle_data(self, data):
        if self.schema_text is not None:
            self.schema_text += data

    def handle_endtag(self, tag):
        if tag == "script" and self.schema_text is not None:
            self.schemas.append(json.loads(self.schema_text))
            self.schema_text = None


class SiteMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {name: Page((ROOT / name).read_text()) for name in PAGES}

    def test_canonical_and_social_urls(self):
        for name, page in self.pages.items():
            with self.subTest(page=name):
                url = BASE + ("/" if name == "index.html" else "/" + name)
                self.assertEqual(page.canonicals, [url])
                self.assertEqual(page.meta["og:url"], url)
                self.assertEqual(page.meta["description"], page.meta["og:description"])
                self.assertTrue(page.meta["description"])
                self.assertNotIn("noindex", page.meta["robots"])
                image = page.meta["og:image"]
                self.assertTrue(image.startswith(BASE + "/"))
                self.assertTrue((ROOT / unquote(urlsplit(image).path).lstrip("/")).is_file())

    def test_structured_data(self):
        for name, page in self.pages.items():
            with self.subTest(page=name):
                self.assertEqual(len(page.schemas), 1)
                schema = page.schemas[0]
                self.assertEqual(schema["@context"], "https://schema.org")
                graph = schema["@graph"]
                self.assertEqual(graph[0]["url"], page.canonicals[0])
                self.assertEqual(graph[0]["description"], page.meta["description"])
                self.assertEqual(graph[0]["publisher"]["@id"], BASE + "/#organization")
                for node in graph:
                    self.assertTrue(node["@id"].startswith(BASE + "/"))

    def test_local_links_and_fragments(self):
        for name, page in self.pages.items():
            self.assertEqual(len(page.ids), len(set(page.ids)), name)
            for href in page.links:
                parsed = urlsplit(href)
                if parsed.scheme or parsed.netloc:
                    continue
                with self.subTest(page=name, href=href):
                    target = ((ROOT / name).parent / unquote(parsed.path)).resolve() if parsed.path else ROOT / name
                    self.assertTrue(target.is_file())
                    if parsed.fragment and target.suffix == ".html":
                        target_page = self.pages.get(str(target.relative_to(ROOT)))
                        if target_page is None:
                            target_page = Page(target.read_text())
                        self.assertIn(unquote(parsed.fragment), target_page.ids)

    def test_sitemap_and_robots(self):
        tree = ET.parse(ROOT / "sitemap.xml")
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [node.text for node in tree.findall("s:url/s:loc", ns)]
        self.assertCountEqual(urls, [page.canonicals[0] for page in self.pages.values()])
        robots = (ROOT / "robots.txt").read_text()
        self.assertIn("User-agent: *\nAllow: /", robots)
        self.assertIn("Sitemap: " + BASE + "/sitemap.xml", robots)

    def test_paper_metadata_matches_visible_citations(self):
        source = (ROOT / "publications.html").read_text().split("</head>", 1)[1]
        papers = self.pages["publications.html"].schemas[0]["@graph"][1:]
        self.assertEqual(len(papers), 2)
        for paper in papers:
            self.assertEqual(paper["@type"], "ScholarlyArticle")
            self.assertIn(paper["name"], source)
            self.assertIn(paper["identifier"], source)
            self.assertIn(paper["pagination"], source)
            self.assertIn(paper["subjectOf"]["codeRepository"], source)
            pdf = unquote(urlsplit(paper["encoding"]["contentUrl"]).path).lstrip("/")
            self.assertTrue((ROOT / pdf).is_file())
            self.assertIn(pdf, source)
            self.assertIn(paper["@id"].split("#")[1], self.pages["publications.html"].ids)


if __name__ == "__main__":
    unittest.main()
