import httpx
from bs4 import BeautifulSoup
from typing import Optional

VALID_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _looks_like_image(url: str) -> bool:
    return any(url.lower().split("?")[0].endswith(ext) for ext in VALID_EXTS)


def _from_media_tags(entry) -> Optional[str]:
    media = getattr(entry, "media_content", None)
    if media and isinstance(media, list):
        for m in media:
            if m.get("url"):
                return m["url"]
    thumb = getattr(entry, "media_thumbnail", None)
    if thumb and isinstance(thumb, list) and thumb[0].get("url"):
        return thumb[0]["url"]
    return None


def _from_enclosure(entry) -> Optional[str]:
    for enc in getattr(entry, "enclosures", []):
        href = enc.get("href", "")
        if enc.get("type", "").startswith("image") or _looks_like_image(href):
            return href
    return None


def _from_content_html(entry) -> Optional[str]:
    for source in [*getattr(entry, "content", []), {"value": getattr(entry, "summary", "")}]:
        soup = BeautifulSoup(source.get("value", ""), "lxml")
        img = soup.find("img")
        if img and img.get("src"):
            return img["src"]
    return None


async def _from_article_page(url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "RSSNewsBot/1.0"})
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "lxml")
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"]
        tw = soup.find("meta", attrs={"name": "twitter:image"})
        if tw and tw.get("content"):
            return tw["content"]
    except Exception:
        return None
    return None


async def extract_image(entry, article_url: str, fetch_article: bool = True) -> Optional[str]:
    img = _from_media_tags(entry) or _from_enclosure(entry) or _from_content_html(entry)
    if img:
        return img
    if fetch_article and article_url:
        return await _from_article_page(article_url)
    return None
