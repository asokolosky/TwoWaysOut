"""Round 2: every About page background fact renders with its own source links, and every fact
(especially any with a number) has at least one linked source."""

import re
from html.parser import HTMLParser

import pytest

from app.content.background import BACKGROUND


class _Background(HTMLParser):
    """Collects each <li> of the Background section: its fact text and the links inside it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_section = False
        self.depth = 0
        self.items: list[dict] = []
        self.link = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section" and a.get("aria-labelledby") == "background-heading":
            self.in_section, self.depth = True, 0
        if not self.in_section:
            return
        if tag == "section":
            self.depth += 1
        elif tag == "li":
            self.items.append({"p": [], "links": []})
            self._p = None
        elif tag == "p" and self.items:
            self.items[-1]["p"].append("")
        elif tag == "a" and self.items:
            self.link = {**a, "text": ""}

    def handle_data(self, data):
        if not self.in_section or not self.items:
            return
        if self.link is not None:
            self.link["text"] += data
        elif self.items[-1]["p"]:
            self.items[-1]["p"][-1] += data

    def handle_endtag(self, tag):
        if not self.in_section:
            return
        if tag == "a" and self.link is not None:
            self.items[-1]["links"].append(self.link)
            self.link = None
        elif tag == "section":
            self.depth -= 1
            if self.depth == 0:
                self.in_section = False


@pytest.fixture
def items(client):
    p = _Background()
    p.feed(client.get("/about").text)
    return p.items


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def test_every_fact_has_a_source():
    assert BACKGROUND
    for item in BACKGROUND:
        assert item.sources, item.fact
        for src in item.sources:
            assert src.name.strip() and src.url.startswith("https://"), src


def test_every_fact_with_a_number_has_a_source():
    numbered = [i for i in BACKGROUND if re.search(r"\d", i.fact)]
    assert numbered  # the page does cite figures
    for item in numbered:
        assert len(item.sources) >= 1, item.fact


def test_about_shows_each_fact_with_its_own_links(items):
    assert len(items) == len(BACKGROUND)
    for rendered, item in zip(items, BACKGROUND, strict=True):
        assert _norm(rendered["p"][0]) == _norm(item.fact)
        links = rendered["links"]
        assert [l["href"] for l in links] == [s.url for s in item.sources], item.fact
        for link, src in zip(links, item.sources, strict=True):
            assert _norm(link["text"]) == f"{src.name} (opens in a new tab)"
            assert link.get("target") == "_blank"
            assert link.get("rel") == "noopener noreferrer"


def test_rendered_facts_follow_ui_style(items):
    for rendered in items:
        text = " ".join(rendered["p"])
        assert "\u2014" not in text and "!" not in text
        assert not re.search(r"\b(is|are) (safe|compliant|up to code)\b", text, re.I)
