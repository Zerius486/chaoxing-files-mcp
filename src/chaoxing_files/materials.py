"""Parse the two Chaoxing course-material listing formats without running JS."""

import re
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


def update_query(url: str, **updates) -> str:
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
    query.update({k: str(v) for k, v in updates.items()})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def to_open_args(source: str) -> list[str]:
    """Read only literal arguments of toOpen; never evaluate expressions/code."""
    match = re.search(r"\btoOpen\s*\(", source)
    if not match:
        return []
    token = re.compile(
        r"""\s*(?:'((?:\\.|[^'\\])*)'|"((?:\\.|[^"\\])*)"|(-?\d+))\s*([,)])"""
    )
    pos, args = match.end(), []
    # Only the first ten arguments are required; later arguments can be DOM expressions.
    for _ in range(10):
        value = token.match(source, pos)
        if not value:
            return []
        raw = next(x for x in value.groups()[:3] if x is not None)
        args.append(re.sub(r"\\(['\"\\])", r"\1", raw))
        pos = value.end()
        if value.group(4) == ")":
            break
    return args


def is_materials_url(url: str) -> bool:
    return bool(re.search(r"/coursedata(?:/|$)", urlsplit(url).path))


def parse_materials(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    hidden = {}
    for tag in soup.select('input[type="hidden"]'):
        for key in (tag.get("id"), tag.get("name")):
            if key:
                hidden[str(key).lower()] = str(tag.get("value", ""))
    query = {k.lower(): v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    context = {**query, **hidden}
    course_id = context.get("courseid", "")
    class_id = context.get("clazzid") or context.get("classid", "")
    cpi = context.get("cpi", "")
    rows = soup.select("tr[type][id], ul.dataBody_td[type][id]")
    marker = soup.select_one("#dataId")
    loading = any("正在加载" in n.get_text() for n in soup.select(".NoResult"))
    recognized = (
        bool(rows or (marker and (soup.select_one("#totalPage, #totalPages, #pages"))))
        and not loading
    )
    files, folders, links, warnings = [], [], [], []
    new = "/mooc2-ans/" in urlsplit(url).path
    folder_base = urlunsplit(
        (
            *urlsplit(url)[:2],
            "/mooc2-ans/coursedata/stu-datalist" if new else "/mooc-ans/coursedata",
            "",
            "",
        )
    )
    folder_params = {
        "courseid" if new else "courseId": course_id,
        "clazzid" if new else "classId": class_id,
        "cpi": cpi,
        "ut": "s",
        "type": "1",
    }
    for key in ("openc", "t", "microtopicid"):
        if context.get(key):
            folder_params["microTopicId" if key == "microtopicid" else key] = context[
                key
            ]

    for row in rows:
        data_id = str(row.get("id", ""))
        if not data_id.isdecimal():
            warnings.append("发现没有有效 dataId 的资料项，未自动处理。")
            continue
        args = []
        for node in row.select("[onclick]"):
            args = to_open_args(str(node.get("onclick", "")))
            if len(args) >= 10:
                break
        title = row.select_one("a.rename_title[title], a[name][title]")
        name = str(
            row.get("dataname")
            or (title.get("title") if title else "")
            or (unquote(args[0]) if args else "")
            or data_id
        )
        kind = str(row.get("type", ""))
        enc = args[9] if len(args) >= 10 else ""
        if kind == "afolder":
            if not enc:
                warnings.append(f"文件夹 {name} 缺少导航签名，访问可能失败。")
            folder_url = update_query(
                folder_base,
                **folder_params,
                dataId=data_id,
                dataName=name,
                enc=enc,
                pages=1,
            )
            folders.append(
                {
                    "name": name,
                    "folder_id": data_id,
                    "folder_enc": enc,
                    "url": folder_url,
                }
            )
            continue
        object_id = str(row.get("objectid") or (args[4] if len(args) >= 5 else ""))
        if kind in ("url", "book", "zt_chapter", "swift_course", "periodical"):
            target = row.get("url") or (args[5] if len(args) > 5 else "")
            if target:
                links.append({"name": name, "url": urljoin(url, str(target))})
            continue
        downloadable = str(row.get("isdown", "0")) == "1"
        download_link = row.select_one('a[href*="/coursedata/downloadData?"]')
        download_url = urljoin(url, str(download_link["href"])) if download_link else ""
        if not download_url and downloadable and course_id and class_id and cpi:
            download_url = update_query(
                "https://mooc1.chaoxing.com/coursedata/downloadData",
                courseId=course_id,
                classId=class_id,
                cpi=cpi,
                dataId=data_id,
                ut="s",
            )
        downloadable = downloadable and bool(download_url)
        size = row.select_one(".dataBody_size_stu")
        cells = row.find_all("td", recursive=False)
        size_text = (
            size.get_text(strip=True)
            if size
            else (cells[3].get_text(strip=True) if len(cells) > 3 else "")
        )
        files.append(
            {
                "filename": name,
                "data_id": data_id,
                "object_id": object_id,
                "file_type": kind,
                "size": size_text,
                "downloadable": downloadable,
                "url": download_url if downloadable else "",
            }
        )

    page_match = re.search(r"page\.showPage\(\s*(\d+)\s*,\s*(\d+)", html)
    page = int(
        context.get("currentpageno")
        or query.get("pages")
        or (page_match[1] if page_match else 1)
    )
    total_pages = int(
        context.get("totalpages")
        or context.get("totalpage")
        or (page_match[2] if page_match else page)
    )
    # Preserve folder ID and its enc/cpi on every page, including legacy pagination.
    page_url = update_query(
        folder_base,
        **folder_params,
        dataId=context.get("dataid", "0"),
        enc=context.get("enc", ""),
        dataName=context.get("dataname", ""),
        pages=page + 1,
    )
    return {
        "recognized": recognized,
        "files": files,
        "folders": folders,
        "links": links,
        "folder_id": context.get("dataid", "0"),
        "page": page,
        "total_pages": max(total_pages, 1),
        "has_more": page < total_pages,
        "next_page_url": page_url if page < total_pages else "",
        "warnings": warnings,
    }
