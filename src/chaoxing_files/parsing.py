import json
import re
from pathlib import PurePosixPath
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

FILE_EXTENSIONS = set(
    "pdf doc docx ppt pptx xls xlsx csv txt md zip rar 7z tar gz jpg jpeg png gif webp svg mp3 wav m4a mp4 webm mov epub exe apk py java c cpp ipynb".split()
)


def object_url(object_id: str) -> str:
    return (
        "https://mooc1.chaoxing.com/mooc-ans/ueditorupload/read?objectId=" + object_id
    )


def parse_page(html: str, base_url: str) -> dict:
    """Extract links and files without executing remote JavaScript."""
    soup = BeautifulSoup(html, "html.parser")
    files: dict[str, dict] = {}
    links: dict[str, dict] = {}

    def add_file(url: str, name: str = "", object_id: str = ""):
        url = urljoin(base_url, url)
        if urlsplit(url).scheme not in ("http", "https"):
            return
        key = object_id or url
        item = {
            "filename": name
            or unquote(PurePosixPath(urlsplit(url).path).name)
            or object_id,
            "url": url,
            "object_id": object_id,
        }
        if key not in files or (name and not files[key]["filename"]):
            files[key] = item

    for tag in soup.find_all(True):
        name = str(
            tag.get("filename")
            or tag.get("data-name")
            or tag.get("download")
            or tag.get("title")
            or tag.get_text(" ", strip=True)[:160]
            or tag.get("alt")
            or ""
        )
        oid = (
            tag.get("objectid") or tag.get("data-objectid") or tag.get("data-object-id")
        )
        if oid and re.fullmatch(r"[\w-]{1,128}", str(oid)):
            add_file(object_url(str(oid)), name, str(oid))
        raw_data = tag.get("data")
        if raw_data and str(raw_data).lstrip().startswith("{"):
            try:
                data = json.loads(str(raw_data))
                oid = data.get("objectid") or data.get("objectId")
                if oid and re.fullmatch(r"[\w-]{1,128}", str(oid)):
                    add_file(object_url(str(oid)), data.get("name", name), str(oid))
            except (ValueError, AttributeError):
                pass
        for attr in ("href", "src", "data", "data-url"):
            raw = str(tag.get(attr) or "").strip()
            if not raw or raw.startswith(
                ("javascript:", "data:", "#", "blob:", "{", "[")
            ):
                continue
            url = urljoin(base_url, raw)
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https"):
                continue
            query = {k.lower(): v for k, v in parse_qs(parsed.query).items()}
            oid = query.get("objectid", [""])[0]
            ext = PurePosixPath(parsed.path).suffix.lower().lstrip(".")
            if (
                oid
                or ext in FILE_EXTENSIONS
                or tag.name in ("video", "audio", "source", "img")
                or tag.has_attr("download")
            ):
                add_file(url, name, oid)
            elif tag.name in ("a", "iframe", "frame") and attr in (
                "href",
                "src",
                "data",
                "data-url",
            ):
                links[url] = {"name": name or "页面", "url": url}

    return {
        "title": soup.title.get_text(strip=True) if soup.title else "",
        "files": list(files.values()),
        "links": list(links.values()),
    }
