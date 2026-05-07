from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from dataclasses import dataclass, field

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from ErisPulse import sdk


@dataclass
class FeedItem:
    title: str
    link: str
    summary: str
    author: str
    published: datetime
    source_name: str
    source_url: str = ""
    image: Optional[str] = None

    @property
    def item_hash(self) -> str:
        import hashlib
        return hashlib.sha256(f"{self.link}:{self.title}".encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "link": self.link,
            "summary": self.summary,
            "author": self.author,
            "published": self.published.isoformat() if self.published else "",
            "source_name": self.source_name,
            "source_url": self.source_url,
            "image": self.image,
            "item_hash": self.item_hash,
        }


def _clean_summary(html_text: str, max_length: int = 200) -> str:
    soup = BeautifulSoup(html_text or "", "html.parser")
    text = soup.get_text(separator=" ").strip()
    text = " ".join(text.split())
    return text[:max_length] + "..." if len(text) > max_length else text


def _parse_date(entry) -> datetime:
    from time import mktime
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
            except Exception:
                pass
    for field in ("published", "updated"):
        raw = entry.get(field)
        if raw:
            try:
                return parsedate_to_datetime(raw)
            except Exception:
                pass
    return datetime.now(tz=timezone.utc)


def _extract_image(entry) -> Optional[str]:
    for enclosure in entry.get("links", []):
        if enclosure.get("type", "").startswith("image/"):
            return enclosure.get("href", enclosure.get("url"))
    for content in (entry.get("content", []) or []):
        if isinstance(content, dict) and content.get("value"):
            img = BeautifulSoup(content["value"], "html.parser").find("img")
            if img and img.get("src"):
                return img["src"]
    summary = entry.get("summary", "")
    if summary:
        img = BeautifulSoup(summary, "html.parser").find("img")
        if img and img.get("src"):
            return img["src"]
    return None


async def fetch_rss(url: str, count: int = 10) -> List[FeedItem]:
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "ErisPulse-RssReader/1.0"},
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                content = await resp.text()
    except Exception:
        return []

    parsed = feedparser.parse(content)
    if not parsed.entries:
        return []

    feed_title = parsed.feed.get("title", url)
    feed_link = parsed.feed.get("link", url)
    items = []

    for entry in parsed.entries[:count]:
        summary = ""
        for field in ("summary", "description", "content"):
            val = entry.get(field)
            if isinstance(val, str) and val.strip():
                summary = _clean_summary(val)
                break
            if isinstance(val, list):
                for part in val:
                    if isinstance(part, dict) and part.get("value"):
                        summary = _clean_summary(part["value"])
                        break
                if summary:
                    break

        author = ""
        ad = entry.get("author_detail")
        if isinstance(ad, dict):
            author = ad.get("name", "")
        if not author:
            author = entry.get("author", "")
            if isinstance(author, str):
                author = author.strip()

        items.append(FeedItem(
            title=entry.get("title", "无标题"),
            link=entry.get("link", ""),
            summary=summary,
            author=author,
            published=_parse_date(entry),
            source_name=feed_title,
            source_url=feed_link,
            image=_extract_image(entry),
        ))

    return items


async def probe_rss(url: str) -> Optional[dict]:
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "ErisPulse-RssReader/1.0"},
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                content = await resp.text()
    except Exception:
        return None

    parsed = feedparser.parse(content)
    feed = parsed.feed
    if not feed.get("title") and not parsed.entries:
        return None

    latest = parsed.entries[0] if parsed.entries else {}
    return {
        "name": feed.get("title", url),
        "link": feed.get("link", url),
        "description": feed.get("subtitle", feed.get("description", "")),
        "entry_count": len(parsed.entries),
        "latest_title": latest.get("title", ""),
        "latest_link": latest.get("link", ""),
    }
