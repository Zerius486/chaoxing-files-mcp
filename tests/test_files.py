import hashlib
import json
from pathlib import Path

import httpx
import pytest

from chaoxing_files.client import ChaoxingError, safe_filename
from chaoxing_files.parsing import parse_page


def test_page_forms():
    result = parse_page(
        """<title>资料</title>
      <iframe objectid="abc123" filename="实验.docx"></iframe>
      <iframe data='{"objectid":"def456","name":"讲义.pdf"}'></iframe>
      <a href="javascript:;" data="/folder?p=2">目录</a>
      <a href="/files/book.zip">压缩包</a><video src="//media.chaoxing.com/lecture.mp4"></video>
      <iframe src="/chapter"></iframe>""",
        "https://mooc1.chaoxing.com/course",
    )
    assert result["title"] == "资料"
    assert {f["object_id"] for f in result["files"]} >= {"abc123", "def456"}
    assert len(result["files"]) == 4
    assert {x["url"] for x in result["links"]} == {
        "https://mooc1.chaoxing.com/folder?p=2",
        "https://mooc1.chaoxing.com/chapter",
    }


def test_courses(make_client):
    def handler(request):
        assert request.method == "GET"
        assert "session=secret" in request.headers["cookie"]
        return httpx.Response(
            200,
            json={
                "channelList": [
                    {
                        "content": {
                            "id": 88,
                            "cpi": 99,
                            "course": {"data": [{"id": 123, "name": "课程"}]},
                        }
                    }
                ]
            },
        )

    courses = make_client(handler).list_courses()
    assert courses[0]["name"] == "课程"
    assert "clazzid=88" in courses[0]["url"]


@pytest.mark.parametrize(
    "url",
    [
        "http://mooc1.chaoxing.com/x",
        "https://chaoxing.com.evil.test/x",
        "https://127.0.0.1/",
        "https://u:p@mooc1.chaoxing.com/x",
        "https://mooc1.chaoxing.com:444/x",
        "https://mooc1.chaoxing.com/work/submit",
    ],
)
def test_reject_urls(make_client, url):
    with pytest.raises(ChaoxingError):
        make_client(lambda _: pytest.fail("must not request")).validate_url(url)


def test_redirect_checked(make_client):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://evil.test/file.pdf"})

    client = make_client(handler)
    with pytest.raises(ChaoxingError):
        client.get_page("https://mooc1.chaoxing.com/x")
    assert len(requests) == 1


def test_preview_download_and_no_overwrite(make_client):
    def handler(request):
        if "ueditorupload" in request.url.path:
            return httpx.Response(
                200,
                text='<a href="/real.pdf" class="btnDown">下载</a>',
                headers={"content-type": "text/html"},
            )
        return httpx.Response(
            200, content=b"%PDF-file", headers={"content-type": "application/pdf"}
        )

    client = make_client(handler)
    rid = client.resolve_object("abcdef", "课件.pdf")["resource_id"]
    result = client.download(rid)
    assert Path(result["path"]).read_bytes() == b"%PDF-file"
    assert result["sha256"] == hashlib.sha256(b"%PDF-file").hexdigest()
    with pytest.raises(ChaoxingError, match="已存在"):
        client.download(rid)


@pytest.mark.parametrize(
    "body,ctype,limit",
    [
        (b'<html><input type="password"></html>', "text/html", 1000),
        (b"<html>login</html>", "application/octet-stream", 1000),
        (b"123456", "application/octet-stream", 3),
        (b"", "application/octet-stream", 1000),
    ],
)
def test_failed_download_cleaned(make_client, body, ctype, limit):
    client = make_client(
        lambda _: httpx.Response(200, content=body, headers={"content-type": ctype}),
        limit,
    )
    rid = client.resolve_object("abc", "x.pdf")["resource_id"]
    with pytest.raises(ChaoxingError):
        client.download(rid)
    assert not list(client.settings.download_dir.glob("*"))


def test_cookie_is_not_leaked_to_extra_cdn(make_client):
    def handler(request):
        assert "cookie" not in request.headers
        return httpx.Response(200, content=b"file")

    client = make_client(handler)
    client.settings.allowed_domains += ("cdn.example.org",)
    client.load_cookies()
    rid = client.register(
        {"url": "https://cdn.example.org/a.pdf", "filename": "a.pdf"}
    )["resource_id"]
    assert client.download(rid)["bytes"] == 4


def test_cookie_reload_invalidates_resource(make_client):
    client = make_client(lambda _: httpx.Response(200, content=b"file"))
    rid = client.resolve_object("abc", "a.pdf")["resource_id"]
    client.settings.cookie_file.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "session",
                        "value": "new-secret",
                        "domain": ".chaoxing.com",
                    }
                ]
            }
        )
    )
    with pytest.raises(ChaoxingError, match="ID 已失效"):
        client.download(rid)


def test_login_and_invalid_courses_reported(make_client):
    client = make_client(lambda _: httpx.Response(200, json={"result": False}))
    with pytest.raises(ChaoxingError, match="channelList"):
        client.list_courses()
    client = make_client(lambda _: httpx.Response(200, text='<input type="password">'))
    with pytest.raises(ChaoxingError, match="登录"):
        client.list_courses()


def test_safe_names():
    assert "/" not in safe_filename("../../foo.pdf")
    assert "\\" not in safe_filename("..\\foo.pdf")
    assert safe_filename("CON.txt").startswith("file_")


def test_verified_chaoxing_storage_domain(make_client):
    def handler(request):
        if request.url.host == "mooc1.chaoxing.com":
            return httpx.Response(
                302, headers={"location": "https://d0.cldisk.com/a.pdf"}
            )
        assert request.url.host == "d0.cldisk.com"
        assert "cookie" not in request.headers
        return httpx.Response(
            200, content=b"%PDF-storage", headers={"content-type": "application/pdf"}
        )

    client = make_client(handler)
    rid = client.resolve_object("storage-id", "storage.pdf")["resource_id"]
    assert client.download(rid)["bytes"] == len(b"%PDF-storage")
    with pytest.raises(ChaoxingError, match="unapproved.cldisk.com"):
        client.validate_url("https://unapproved.cldisk.com/file.pdf")


def test_verifycode_studychapter_rejected_on_regular_page(make_client):
    client = make_client(
        lambda _: httpx.Response(
            302, headers={"location": "https://mooc1.chaoxing.com/verifyCode/studychapter"}
        )
    )
    with pytest.raises(ChaoxingError, match="验证码"):
        client.inspect_page("https://mooc1.chaoxing.com/visit/courses")


def test_studentstudy_falls_back_to_knowledge_cards(make_client):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith("/mycourse/studentstudy"):
            assert "Mozilla/5.0 (" in request.headers["user-agent"]
            assert request.headers["referer"] == "https://mooc1.chaoxing.com/"
            return httpx.Response(
                302,
                headers={
                    "location": "https://mooc1.chaoxing.com/verifyCode/studychapter"
                },
            )
        if request.url.path == "/knowledge/cards":
            params = dict(request.url.params)
            assert params["courseid"] == "265717871"
            assert params["clazzid"] == "151043639"
            assert params["knowledgeid"] == "1205310213"
            assert params["num"] == "0"
            assert params["ut"] == "s"
            return httpx.Response(
                200,
                text='<title>章节卡片</title><iframe data=\'{"objectid":"chap123","name":"第一章课件.pdf"}\'></iframe>',
            )
        return httpx.Response(404)

    result = make_client(handler).inspect_page(
        "https://mooc1.chaoxing.com/mooc-ans/mycourse/studentstudy?chapterId=1205310213&courseId=265717871&clazzid=151043639&enc=abc"
    )
    assert seen == ["/mooc-ans/mycourse/studentstudy", "/knowledge/cards"]
    assert len(result["files"]) == 1
    assert result["files"][0]["object_id"] == "chap123"
    assert result["files"][0]["filename"] == "第一章课件.pdf"
    assert "/knowledge/cards" in result["note"]


def test_studentstudy_both_blocked_raises_clear_error(make_client):
    def handler(request):
        return httpx.Response(
            200,
            text="<html><script>location.href='/verifyCode/studychapter'</script></html>",
        )

    with pytest.raises(ChaoxingError, match="浏览器环境校验"):
        make_client(handler).inspect_page(
            "https://mooc1.chaoxing.com/mycourse/studentstudy?chapterId=1&courseId=2&clazzid=3"
        )
