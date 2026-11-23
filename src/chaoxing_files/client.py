import hashlib
import http.cookiejar
import json
import os
import re
import tempfile
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from .config import Settings
from .materials import is_materials_url, parse_materials, update_query
from .parsing import object_url, parse_page


class ChaoxingError(ValueError):
    pass


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:180].rstrip(" .")
    if not name or name.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        name = "file_" + name
    return name


class ChaoxingClient:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.http = httpx.Client(
            transport=transport,
            timeout=30,
            follow_redirects=False,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        self.resources: dict[str, dict] = {}
        self._cookie_stamp = None

    def close(self):
        self.http.close()

    def validate_url(self, url: str):
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            raise ChaoxingError("只允许 HTTPS 超星资源地址（默认 443 端口）。")
        if not any(
            host == d or host.endswith("." + d) for d in self.settings.allowed_domains
        ):
            raise ChaoxingError(
                f"资源域名 {host!r} 不在允许列表中；可在本地配置 CHAOXING_EXTRA_DOMAINS。"
            )
        if re.search(r"(?:submit|delete|remove|signIn|signOut|logout)", p.path, re.I):
            raise ChaoxingError("文件服务不访问提交、删除、签到或退出接口。")

    def load_cookies(self):
        path = self.settings.cookie_file
        if not path.is_file():
            raise ChaoxingError(
                "缺少本地 Cookie 文件，请按 README 导出已登录的超星 Cookie。"
            )
        stamp = (path.stat().st_mtime_ns, path.stat().st_size)
        if stamp == self._cookie_stamp:
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            cookies = data.get("cookies", []) if isinstance(data, dict) else data
            if not isinstance(cookies, list) or not cookies:
                raise ValueError()
            jar = http.cookiejar.CookieJar()
            for c in cookies:
                domain = str(c["domain"]).lower()
                bare = domain.lstrip(".")
                if not any(
                    bare == d or bare.endswith("." + d)
                    for d in ("chaoxing.com", "chaoxing.com.cn")
                ):
                    continue
                expires = c.get("expirationDate", c.get("expires"))
                expires = int(expires) if expires and float(expires) > 0 else None
                if expires and expires <= time.time():
                    continue
                jar.set_cookie(
                    http.cookiejar.Cookie(
                        0,
                        str(c["name"]),
                        str(c["value"]),
                        None,
                        False,
                        domain,
                        domain.startswith("."),
                        domain.startswith("."),
                        str(c.get("path", "/")),
                        True,
                        True,
                        expires,
                        expires is None,
                        None,
                        None,
                        {},
                        False,
                    )
                )
            if not list(jar):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise ChaoxingError(
                "Cookie JSON 格式错误、已过期或不包含超星域名。"
            ) from None
        self.http.cookies = httpx.Cookies(jar)
        self.resources.clear()
        self._cookie_stamp = stamp

    @contextmanager
    def response(self, url: str, download: bool = False):
        self.load_cookies()
        for _ in range(8):
            self.validate_url(url)
            if any(
                s in url.lower()
                for s in (
                    "antispider",
                    "passport2.chaoxing.com/login",
                    "verifycode/studychapter",
                )
            ):
                raise ChaoxingError(
                    "登录已失效、无访问权限或需要人工验证码，请在浏览器完成后更新 Cookie。"
                )
            host = (urlsplit(url).hostname or "").lower()
            headers = (
                {"Referer": "https://mooc1.chaoxing.com/"}
                if download
                or any(
                    host == d or host.endswith("." + d)
                    for d in ("chaoxing.com", "chaoxing.com.cn")
                )
                else {}
            )
            with self.http.stream("GET", url, headers=headers) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ChaoxingError("重定向缺少目标地址。")
                    url = urljoin(url, location)
                    continue
                if response.status_code in (202, 401, 403) or any(
                    s in str(response.url).lower()
                    for s in (
                        "antispider",
                        "passport2.chaoxing.com/login",
                        "verifycode/studychapter",
                    )
                ):
                    raise ChaoxingError(
                        "登录已失效、无访问权限或需要人工验证码，请在浏览器完成后更新 Cookie。"
                    )
                response.raise_for_status()
                yield response
                return
        raise ChaoxingError("重定向次数过多。")

    def get_page(self, url: str) -> tuple[str, str]:
        with self.response(url) as r:
            data = bytearray()
            for chunk in r.iter_bytes():
                data.extend(chunk)
                if len(data) > 8 * 1024 * 1024:
                    raise ChaoxingError("页面超过 8 MiB；请使用下载工具获取文件。")
            text = data.decode(r.encoding or "utf-8", errors="replace")
            soup = BeautifulSoup(text, "html.parser")
            if (
                soup.select_one('input[type="password"]')
                or "antispiderShowVerify" in text
                or "verifycode/studychapter" in text.lower()
            ):
                raise ChaoxingError("需要重新登录或人工验证，请更新 Cookie。")
            return text, str(r.url)

    def list_courses(self) -> list[dict]:
        text, _ = self.get_page("https://mooc1-api.chaoxing.com/mycourse/backclazzdata")
        try:
            data = json.loads(text)
        except ValueError:
            raise ChaoxingError("课程接口未返回 JSON，请检查登录状态。") from None
        if not isinstance(data, dict) or not isinstance(data.get("channelList"), list):
            raise ChaoxingError("课程接口结构变化或登录失效，未获得 channelList。")
        courses = []
        for channel in data["channelList"]:
            if not isinstance(channel, dict):
                continue
            content = channel.get("content", {})
            if not isinstance(content, dict):
                continue
            block = content.get("course", {})
            if not isinstance(block, dict):
                continue
            course_data = block.get("data", [])
            if not isinstance(course_data, list):
                continue
            for c in course_data:
                if not isinstance(c, dict) or not c.get("id"):
                    continue
                params = {
                    "courseid": str(c["id"]),
                    "clazzid": str(content.get("id", "")),
                    "cpi": str(content.get("cpi", "")),
                    "vc": "1",
                }
                url = str(
                    httpx.URL(
                        "https://mooc1.chaoxing.com/visit/stucoursemiddle",
                        params=params,
                    )
                )
                courses.append({"name": c.get("name", ""), **params, "url": url})
        return courses

    def register(self, item: dict) -> dict:
        self.validate_url(item["url"])
        resource_id = hashlib.sha256(item["url"].encode()).hexdigest()[:24]
        self.resources[resource_id] = dict(item)
        return {"resource_id": resource_id, **item}

    @staticmethod
    def _studentstudy_cards_url(url: str) -> str | None:
        parts = urlsplit(url)
        if not re.search(r"/mycourse/studentstudy(?:/|$)", parts.path, re.I):
            return None
        query = {k.lower(): v[0] for k, v in parse_qs(parts.query).items()}
        course_id = query.get("courseid", "")
        class_id = query.get("clazzid") or query.get("classid", "")
        chapter_id = query.get("knowledgeid") or query.get("chapterid", "")
        if not (course_id and class_id and chapter_id):
            return None
        params = {
            "clazzid": class_id,
            "courseid": course_id,
            "knowledgeid": chapter_id,
            "num": query.get("num", "0"),
            "ut": "s",
        }
        for key in ("cpi", "openc"):
            if query.get(key):
                params[key] = query[key]
        base = urlunsplit((parts.scheme, parts.netloc, "/knowledge/cards", "", ""))
        return update_query(base, **params)

    def inspect_page(self, url: str) -> dict:
        fallback_note = ""
        try:
            text, final_url = self.get_page(url)
        except ChaoxingError as exc:
            cards_url = self._studentstudy_cards_url(url)
            if not cards_url:
                raise
            try:
                text, final_url = self.get_page(cards_url)
            except (ChaoxingError, httpx.HTTPStatusError):
                raise ChaoxingError(
                    "章节学习页及卡片接口均触发浏览器环境校验或无权限，请在浏览器打开该章节完成验证后更新 Cookie。"
                ) from exc
            fallback_note = "章节学习页触发校验，已自动回退直连 /knowledge/cards 解析；"
        if is_materials_url(final_url):
            materials = parse_materials(text, final_url)
            if materials.pop("recognized"):
                return self._register_materials(materials, final_url)
        parsed = parse_page(text, final_url)
        files, links = [], []
        skipped = 0
        for item in parsed["files"]:
            try:
                files.append(self.register(item))
            except ChaoxingError:
                skipped += 1
        for item in parsed["links"]:
            try:
                self.validate_url(item["url"])
                links.append(item)
            except ChaoxingError:
                skipped += 1
        return {
            "url": final_url,
            "title": parsed["title"],
            "files": files,
            "links": links,
            "skipped_links": skipped,
            "note": (
                f"{fallback_note}仅解析当前页面。可继续 inspect_page 浏览 links 中的目录、分页和 iframe；不执行 JavaScript。"
            ),
        }

    def _register_materials(self, parsed: dict, url: str) -> dict:
        files = []
        for item in parsed["files"]:
            if item["downloadable"]:
                try:
                    item = self.register(item)
                except ChaoxingError as e:
                    item = {**item, "downloadable": False, "url": ""}
                    parsed["warnings"].append(str(e))
            files.append(item)
        links = list(parsed["links"])
        links.extend({"name": f["name"], "url": f["url"]} for f in parsed["folders"])
        if parsed["next_page_url"]:
            links.append({"name": "下一页", "url": parsed["next_page_url"]})
        safe_links = []
        for link in links:
            try:
                self.validate_url(link["url"])
                safe_links.append(link)
            except ChaoxingError:
                pass
        return {
            **parsed,
            "files": files,
            "links": safe_links,
            "url": url,
            "note": "课程资料列表，已解析文件夹导航和分页。folders 可继续浏览，files 的 resource_id 可下载；不执行页面脚本。",
        }

    def _material_page(self, url: str) -> dict:
        text, final_url = self.get_page(url)
        parsed = parse_materials(text, final_url)
        if not parsed.pop("recognized"):
            raise ChaoxingError(
                "未识别资料列表（可能仍在加载、无权限或平台结构变化），不能视为空目录。"
            )
        return self._register_materials(parsed, final_url)

    def _material_root(self, course_id: str, class_id: str) -> dict:
        if not course_id.isdecimal() or (class_id and not class_id.isdecimal()):
            raise ChaoxingError("course_id 和 class_id 必须为课程列表返回的数字 ID。")
        courses = [
            c
            for c in self.list_courses()
            if c["courseid"] == course_id and (not class_id or c["clazzid"] == class_id)
        ]
        if len(courses) != 1:
            raise ChaoxingError(
                "课程未找到或存在多个教学班，请先 list_courses 并指定正确的 class_id。"
            )
        course = courses[0]
        url = update_query(
            "https://mooc2-ans.chaoxing.com/mooc2-ans/coursedata/stu-datalist",
            courseid=course_id,
            clazzid=course["clazzid"],
            cpi=course["cpi"],
            ut="s",
            pages=1,
        )
        try:
            page = self._material_page(url)
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in (404, 405, 500, 502, 503):
                raise
            page = None
        except ChaoxingError as e:
            if not str(e).startswith("未识别资料列表"):
                raise
            page = None
        if page is None:
            # Resolve legacy signed menu entry from the actual course home page.
            home = self.inspect_page(course["url"])
            entry = next(
                (
                    link["url"]
                    for link in home["links"]
                    if is_materials_url(link["url"])
                ),
                "",
            )
            if not entry:
                raise ChaoxingError("课程主页未发现资料入口。")
            page = self._material_page(entry)
        return {
            **page,
            "course_id": course_id,
            "class_id": course["clazzid"],
            "course_name": course["name"],
        }

    def list_course_materials(
        self,
        course_id: str,
        class_id: str = "",
        folder_id: str = "0",
        folder_enc: str = "",
        page: int = 1,
    ) -> dict:
        if not folder_id.isdecimal() or not 1 <= page <= 10000:
            raise ChaoxingError("folder_id 必须是数字，page 必须在 1～10000 之间。")
        root = self._material_root(course_id, class_id)
        if folder_id == "0" and page == 1:
            return root
        if folder_id != "0" and not folder_enc:
            folder = next(
                (f for f in root["folders"] if f["folder_id"] == folder_id), None
            )
            if folder:
                folder_enc = folder["folder_enc"]
            else:
                raise ChaoxingError(
                    "子文件夹请提供父目录返回的 folder_id 和 folder_enc，或直接 inspect_page(folder.url)。"
                )
        url = update_query(
            root["url"],
            dataId=folder_id,
            pages=page,
            **({"enc": folder_enc} if folder_enc else {}),
        )
        result = self._material_page(url)
        return {
            **result,
            **{k: root[k] for k in ("course_id", "class_id", "course_name")},
        }

    def find_course_materials(
        self,
        course_id: str,
        class_id: str = "",
        keyword: str = "",
        max_depth: int = 8,
        max_pages: int = 100,
    ) -> dict:
        if not 0 <= max_depth <= 20 or not 1 <= max_pages <= 500:
            raise ChaoxingError("max_depth 必须为 0～20，max_pages 必须为 1～500。")
        root = self._material_root(course_id, class_id)
        queue = deque([(root["url"], "", 0, root)])
        seen_pages, seen_folders, seen_files = set(), {"0"}, set()
        files, folders, errors, warnings = [], [], [], []
        pages_read, depth_limited = 0, False
        while queue and pages_read < max_pages:
            url, path, depth, cached = queue.popleft()
            pages_read += 1
            try:
                result = cached if cached is not None else self._material_page(url)
            except (ChaoxingError, httpx.RequestError, httpx.HTTPStatusError) as e:
                message = (
                    str(e)
                    if isinstance(e, ChaoxingError)
                    else (
                        f"HTTP {e.response.status_code}"
                        if isinstance(e, httpx.HTTPStatusError)
                        else "网络请求失败"
                    )
                )
                errors.append({"folder_path": path, "error": message})
                continue
            key = (result["folder_id"], result["page"])
            if key in seen_pages:
                errors.append(
                    {
                        "folder_path": path,
                        "error": "接口重复返回已读取页面，已停止重复遍历。",
                    }
                )
                continue
            seen_pages.add(key)
            warnings.extend(result["warnings"])
            for item in result["files"]:
                file_key = item["data_id"]
                if file_key not in seen_files:
                    seen_files.add(file_key)
                    if keyword.casefold() in (path + "/" + item["filename"]).casefold():
                        files.append({**item, "folder_path": path})
            for folder in result["folders"]:
                if folder["folder_id"] in seen_folders:
                    continue
                seen_folders.add(folder["folder_id"])
                child_path = path + "/" + folder["name"] if path else folder["name"]
                folders.append({**folder, "folder_path": child_path})
                if depth < max_depth:
                    queue.append((folder["url"], child_path, depth + 1, None))
                else:
                    depth_limited = True
            if result["has_more"]:
                queue.append((result["next_page_url"], path, depth, None))
        return {
            "course_id": course_id,
            "class_id": root["class_id"],
            "course_name": root["course_name"],
            "files": files,
            "folders": folders,
            "keyword": keyword,
            "pages_read": pages_read,
            "matched_files": len(files),
            "complete": not (errors or queue or depth_limited),
            "page_limit_reached": bool(queue),
            "depth_limit_reached": depth_limited,
            "errors": errors,
            "warnings": warnings,
        }

    def resolve_object(self, object_id: str, filename: str) -> dict:
        if not re.fullmatch(r"[\w-]{1,128}", object_id):
            raise ChaoxingError("object_id 格式无效。")
        self.load_cookies()
        return self.register(
            {
                "url": object_url(object_id),
                "object_id": object_id,
                "filename": filename or object_id,
            }
        )

    def download(self, resource_id: str, filename: str = "") -> dict:
        self.load_cookies()
        item = self.resources.get(resource_id)
        if not item:
            raise ChaoxingError(
                "资源 ID 已失效，请重新 inspect_page 或 resolve_object。"
            )
        url = item["url"]
        # Preview wrappers are resolved for every extension, not only Word/PDF.
        for _ in range(4):
            with self.response(url, download=True) as r:
                media_type = r.headers.get("content-type", "").lower()
                if "text/html" in media_type:
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > 2 * 1024 * 1024:
                            raise ChaoxingError("预览页过大，未保存为文件。")
                    soup = BeautifulSoup(
                        buf.decode(r.encoding or "utf-8", "replace"), "html.parser"
                    )
                    link = soup.select_one(
                        "a.btnDown[href], a[download][href], a#download[href]"
                    )
                    if not link:
                        raise ChaoxingError(
                            "返回登录/预览 HTML，未找到原文件下载链接；未保存伪文件。"
                        )
                    url = urljoin(str(r.url), str(link["href"]))
                    continue
                target_dir = self.settings.download_dir.resolve()
                target_dir.mkdir(parents=True, exist_ok=True)
                name = safe_filename(filename or item["filename"] or resource_id)
                target = target_dir / name
                if target.exists() or target.is_symlink():
                    raise ChaoxingError(
                        "目标文件已存在，请指定其他 filename；不会覆盖。"
                    )
                size, digest = 0, hashlib.sha256()
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=target_dir, prefix=".partial-", delete=False
                    ) as f:
                        temp_path = Path(f.name)
                        for chunk in r.iter_bytes():
                            size += len(chunk)
                            if size > self.settings.max_bytes:
                                raise ChaoxingError(
                                    "文件超过 CHAOXING_MAX_FILE_MB 限制。"
                                )
                            # Detect mislabeled login/preview pages before writing them.
                            if f.tell() == 0 and chunk.lstrip().lower().startswith(
                                (b"<!doctype html", b"<html")
                            ):
                                raise ChaoxingError(
                                    "服务器返回 HTML 而非文件，下载已停止。"
                                )
                            digest.update(chunk)
                            f.write(chunk)
                    if size == 0:
                        raise ChaoxingError("服务器返回空文件。")
                    # Windows rename is atomic and refuses existing destinations.
                    # POSIX rename replaces destinations, so use an exclusive hard link there.
                    if os.name == "nt":
                        os.rename(temp_path, target)
                    else:
                        os.link(temp_path, target)
                finally:
                    if temp_path:
                        temp_path.unlink(missing_ok=True)
                return {
                    "path": str(target),
                    "bytes": size,
                    "sha256": digest.hexdigest(),
                    "resource_id": resource_id,
                }
        raise ChaoxingError("预览下载链接循环。")
