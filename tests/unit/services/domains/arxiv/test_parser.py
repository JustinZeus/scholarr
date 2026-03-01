from __future__ import annotations

import pytest

from app.services.arxiv.errors import ArxivParseError
from app.services.arxiv.parser import parse_arxiv_feed

_VALID_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>2</opensearch:totalResults>
  <opensearch:startIndex>0</opensearch:startIndex>
  <opensearch:itemsPerPage>2</opensearch:itemsPerPage>
  <entry>
    <id>http://arxiv.org/abs/1234.5678v2</id>
    <updated>2020-01-01T00:00:00Z</updated>
    <published>2019-12-31T00:00:00Z</published>
    <title>Test Entry</title>
    <summary>Example summary</summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Grace Hopper</name></author>
    <link href="http://arxiv.org/abs/1234.5678v2" />
    <category term="cs.AI" />
    <category term="stat.ML" />
    <arxiv:primary_category term="cs.AI" />
  </entry>
</feed>
"""


def test_parse_arxiv_feed_extracts_entries_and_opensearch_meta() -> None:
    feed = parse_arxiv_feed(_VALID_FEED_XML)
    assert feed.opensearch.total_results == 2
    assert feed.opensearch.start_index == 0
    assert feed.opensearch.items_per_page == 2
    assert len(feed.entries) == 1
    entry = feed.entries[0]
    assert entry.arxiv_id == "1234.5678v2"
    assert entry.title == "Test Entry"
    assert entry.summary == "Example summary"
    assert entry.authors == ["Ada Lovelace", "Grace Hopper"]
    assert entry.primary_category == "cs.AI"
    assert entry.categories == ["cs.AI", "stat.ML"]


def test_parse_arxiv_feed_raises_on_invalid_xml() -> None:
    with pytest.raises(ArxivParseError):
        parse_arxiv_feed("<feed><entry></feed>")


def test_parse_arxiv_feed_raises_on_invalid_opensearch_integer() -> None:
    payload = _VALID_FEED_XML.replace(
        "<opensearch:totalResults>2</opensearch:totalResults>", "<opensearch:totalResults>x</opensearch:totalResults>"
    )
    with pytest.raises(ArxivParseError):
        parse_arxiv_feed(payload)
