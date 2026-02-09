import re
from typing import Optional, Dict, List, Any
from bs4 import BeautifulSoup
from structlog import get_logger  # type: ignore

logger = get_logger(__name__)


class DataExtractor:
    def extract(self, soup: BeautifulSoup) -> Dict[str, Any]:
        return {
            "title": self._extract_title(soup),
            "meta": self._extract_meta(soup),
            "headings": self._extract_headings(soup),
            "paragraphs": self._extract_paragraphs(soup),
            "spans": self._extract_spans(soup),
            "divs": self._extract_divs(soup),
            "lists": self._extract_lists(soup),
            "tables": self._extract_tables(soup),
            "links": self._extract_links(soup),
            "images": self._extract_images(soup),
            "iframes": self._extract_iframes(soup),
            "map_embeds": self._extract_map_embeds(soup),
        }

    def validate_content(self, data: Dict[str, Any]) -> bool:
        has_title = bool(data.get("title"))
        has_headings = any(
            len(headings) > 0 for headings in data.get("headings", {}).values()
        )
        has_paragraphs = len(data.get("paragraphs", [])) > 0

        return has_title or has_headings or has_paragraphs

    def _extract_title(self, soup: BeautifulSoup) -> str:
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        return ""

    def _extract_meta(self, soup: BeautifulSoup) -> Dict[str, str]:
        meta = {}

        desc_tag = soup.find("meta", attrs={"name": "description"})
        if desc_tag:
            meta["description"] = desc_tag.get("content", "").strip()
        else:
            meta["description"] = ""

        keywords_tag = soup.find("meta", attrs={"name": "keywords"})
        if keywords_tag:
            meta["keywords"] = keywords_tag.get("content", "").strip()
        else:
            meta["keywords"] = ""

        return meta

    def _extract_headings(self, soup: BeautifulSoup) -> Dict[str, List[str]]:
        return {
            tag: [h.get_text(strip=True) for h in soup.find_all(tag)]
            for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]
        }

    def _extract_paragraphs(self, soup: BeautifulSoup) -> List[str]:
        return [
            p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)
        ]

    def _extract_spans(self, soup: BeautifulSoup) -> List[str]:
        return [
            span.get_text(strip=True)
            for span in soup.find_all("span")
            if span.get_text(strip=True)
        ]

    def _extract_divs(self, soup: BeautifulSoup) -> List[str]:
        return [
            div.get_text(strip=True)
            for div in soup.find_all("div")
            if div.get_text(strip=True)
        ]

    def _extract_lists(self, soup: BeautifulSoup) -> Dict[str, List[List[str]]]:
        return {
            "unordered": [
                [li.get_text(strip=True) for li in ul.find_all("li")]
                for ul in soup.find_all("ul")
            ],
            "ordered": [
                [li.get_text(strip=True) for li in ol.find_all("li")]
                for ol in soup.find_all("ol")
            ],
        }

    def _extract_tables(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        return [
            {
                "headers": [th.get_text(strip=True) for th in table.find_all("th")],
                "rows": [
                    [td.get_text(strip=True) for td in row.find_all("td")]
                    for row in table.find_all("tr")
                    if row.find_all("td")
                ],
            }
            for table in soup.find_all("table")
        ]

    def _extract_links(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        return [
            {"text": a.get_text(strip=True), "href": a["href"]}
            for a in soup.find_all("a", href=True)
        ]

    def _extract_images(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        return [
            {"alt": img.get("alt", ""), "src": img["src"]}
            for img in soup.find_all("img", src=True)
        ]

    def _extract_iframes(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        return [
            {"src": iframe.get("src", ""), "title": iframe.get("title", "")}
            for iframe in soup.find_all("iframe", src=True)
        ]

    def _extract_map_embeds(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        map_embeds = []

        for iframe in soup.find_all("iframe", src=True):
            src = iframe.get("src", "")
            if "google.com/maps" in src or "maps.google.com" in src:
                map_embeds.append(
                    {
                        "src": src,
                        "title": iframe.get("title", ""),
                        "coordinates": self._extract_coordinates(src),
                    }
                )

        return map_embeds

    def _extract_coordinates(self, url: str) -> Optional[Dict[str, float]]:
        if not url:
            return None

        match = re.search(r"!2d([-\d.]+)!3d([-\d.]+)", url)
        if match:
            try:
                return {
                    "lng": float(match.group(1)),
                    "lat": float(match.group(2)),
                }
            except ValueError:
                return None

        return None
