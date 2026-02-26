from __future__ import annotations

import xml.etree.ElementTree as ET

from app.services.domains.arxiv.errors import ArxivParseError
from app.services.domains.arxiv.types import ArxivEntry, ArxivFeed, ArxivOpenSearchMeta
from app.services.domains.publication_identifiers.normalize import normalize_arxiv_id

_NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def parse_arxiv_feed(payload: str) -> ArxivFeed:
    root = _parse_xml_root(payload)
    opensearch = ArxivOpenSearchMeta(
        total_results=_opensearch_int(root, "opensearch:totalResults"),
        start_index=_opensearch_int(root, "opensearch:startIndex"),
        items_per_page=_opensearch_int(root, "opensearch:itemsPerPage"),
    )
    entries = [_parse_entry(entry_elem) for entry_elem in root.findall("atom:entry", _NAMESPACES)]
    return ArxivFeed(entries=entries, opensearch=opensearch)


def _parse_xml_root(payload: str) -> ET.Element:
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ArxivParseError(f"Invalid arXiv XML payload: {exc}") from exc


def _opensearch_int(root: ET.Element, path: str) -> int:
    text = _optional_text(root, path)
    if text is None:
        return 0
    try:
        return int(text.strip())
    except ValueError as exc:
        raise ArxivParseError(f"Invalid integer value at {path}: {text!r}") from exc


def _parse_entry(entry_elem: ET.Element) -> ArxivEntry:
    entry_id_url = _required_text(entry_elem, "atom:id").strip()
    arxiv_id = normalize_arxiv_id(entry_id_url)
    title = _required_text(entry_elem, "atom:title").strip()
    summary = (_optional_text(entry_elem, "atom:summary") or "").strip()
    published = _optional_text(entry_elem, "atom:published")
    updated = _optional_text(entry_elem, "atom:updated")
    return ArxivEntry(
        entry_id_url=entry_id_url,
        arxiv_id=arxiv_id,
        title=title,
        summary=summary,
        published=published,
        updated=updated,
        authors=_authors(entry_elem),
        links=_links(entry_elem),
        categories=_categories(entry_elem),
        primary_category=_primary_category(entry_elem),
    )


def _required_text(elem: ET.Element, path: str) -> str:
    text = _optional_text(elem, path)
    if text is None or not text.strip():
        raise ArxivParseError(f"Missing required field: {path}")
    return text


def _optional_text(elem: ET.Element, path: str) -> str | None:
    node = elem.find(path, _NAMESPACES)
    if node is None or node.text is None:
        return None
    return str(node.text)


def _authors(entry_elem: ET.Element) -> list[str]:
    authors: list[str] = []
    for author in entry_elem.findall("atom:author", _NAMESPACES):
        name = _optional_text(author, "atom:name")
        if name:
            authors.append(name.strip())
    return authors


def _links(entry_elem: ET.Element) -> list[str]:
    values: list[str] = []
    for link in entry_elem.findall("atom:link", _NAMESPACES):
        href = str(link.attrib.get("href") or "").strip()
        if href:
            values.append(href)
    return values


def _categories(entry_elem: ET.Element) -> list[str]:
    values: list[str] = []
    for cat in entry_elem.findall("atom:category", _NAMESPACES):
        term = str(cat.attrib.get("term") or "").strip()
        if term:
            values.append(term)
    return values


def _primary_category(entry_elem: ET.Element) -> str | None:
    node = entry_elem.find("arxiv:primary_category", _NAMESPACES)
    if node is None:
        return None
    value = str(node.attrib.get("term") or "").strip()
    return value or None
