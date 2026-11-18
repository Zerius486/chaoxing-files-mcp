from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from chaoxing_files.client import ChaoxingError
from chaoxing_files.materials import parse_materials, to_open_args

BASE = "https://mooc2-ans.chaoxing.com/mooc2-ans/coursedata/stu-datalist?courseid=1&clazzid=2&cpi=3"


def listing(rows="", folder="0", page=1, total=1):
    return f'''<input type="hidden" id="courseid" value="1">
      <input type="hidden" id="classId" value="2"><input type="hidden" id="cpi" value="3">
      <input type="hidden" id="dataId" value="{folder}"><input type="hidden" id="enc" value="page-enc">
      <input type="hidden" id="totalPages" value="{total}">
      <input type="hidden" id="currentPageNo" value="{page}">{rows}'''


def folder_row(data_id="10", name="参考课件"):
    return f'''<ul class="dataBody_td" type="afolder" id="{data_id}" dataname="{name}" isdown="1">
      <li onclick="toOpen('{name}','afolder',{data_id},'','','',2,1,'2','folder-enc','','0','')">
      <img src="/images/folder.gif"></li></ul>'''


def file_row(data_id="20", name="电路课件.pptx", down="1"):
    return f'''<ul class="dataBody_td" type="pptx" id="{data_id}" dataname="{name}"
       objectid="object-{data_id}" isdown="{down}"><li class="dataBody_size_stu">2 MB</li>
       <li><a href="https://mooc1.chaoxing.com/coursedata/downloadData?dataId={data_id}&amp;classId=2&amp;courseId=1&amp;cpi=3&amp;ut=s">下载</a></li></ul>'''


def courses_response():
    return httpx.Response(
        200,
        json={
            "channelList": [
                {
                    "content": {
                        "id": 2,
                        "cpi": 3,
                        "course": {"data": [{"id": 1, "name": "电路"}]},
                    }
                }
            ]
        },
    )


def test_navigation_metadata_and_icons_excluded():
    result = parse_materials(listing(folder_row() + file_row()), BASE)
    assert result["recognized"]
    assert len(result["folders"]) == len(result["files"]) == 1
    folder = result["folders"][0]
    params = parse_qs(urlsplit(folder["url"]).query)
    assert params["dataId"] == ["10"]
    assert params["enc"] == ["folder-enc"]
    assert params["cpi"] == ["3"]
    assert result["files"][0]["filename"] == "电路课件.pptx"


def test_legacy_folder_and_file_navigation():
    html = """<input type="hidden" id="courseid" value="1">
      <input type="hidden" id="classId" value="2"><input type="hidden" id="cpi" value="3">
      <input type="hidden" id="dataId" value="10"><input type="hidden" id="enc" value="parent-enc">
      <tr type="afolder" id="11"><td onclick="toOpen('nested','afolder',11,'','','',2,1,'2','nested-enc','','')">nested</td></tr>
      <tr type="pdf" id="12" isdown="1" objectid="object"><td>
       <a title="Unit1.pdf" name="Unit1.pdf"></a></td></tr>
      <script>page.showPage(1,3, "course_change")</script>"""
    result = parse_materials(
        html,
        "https://mooc1.chaoxing.com/mooc-ans/coursedata?courseId=1&classId=2&dataId=10",
    )
    assert result["files"][0]["filename"] == "Unit1.pdf"
    assert "cpi=3" in result["files"][0]["url"]
    assert result["has_more"] and result["total_pages"] == 3
    query = parse_qs(urlsplit(result["next_page_url"]).query)
    assert query["dataId"] == ["10"] and query["enc"] == ["parent-enc"]
    assert "/mooc-ans/coursedata?" in result["folders"][0]["url"]


def test_literal_arguments_not_executed():
    assert (
        to_open_args("toOpen(window.evil(),'afolder',10,'','','',2,1,'2','enc')") == []
    )
    args = to_open_args(
        r"""toOpen('O\'Brien, lecture','afolder',10,'','','',2,1,'2','enc',this)"""
    )
    assert args[0] == "O'Brien, lecture" and args[9] == "enc"


def test_restricted_file_has_no_resource_id(make_client):
    client = make_client(
        lambda _: httpx.Response(200, text=listing(file_row(down="0")))
    )
    result = client.inspect_page(BASE)
    assert result["files"][0]["downloadable"] is False
    assert "resource_id" not in result["files"][0]
    assert client.resources == {}


def test_recursive_folders_pagination_and_download(make_client):
    seen = []

    def handler(request):
        assert request.method == "GET"
        if "backclazzdata" in request.url.path:
            return courses_response()
        if "downloadData" in request.url.path:
            return httpx.Response(200, content=b"pptx-file")
        folder = request.url.params.get("dataId", "0")
        page = int(request.url.params.get("pages", "1"))
        seen.append((folder, page))
        if folder == "0":
            return httpx.Response(200, text=listing(folder_row()))
        assert request.url.params["enc"] in ("folder-enc", "page-enc")
        assert request.url.params["cpi"] == "3"
        if page == 1:
            return httpx.Response(200, text=listing(file_row(), "10", 1, 2))
        return httpx.Response(
            200, text=listing(file_row("21", "第二讲.pptx"), "10", 2, 2)
        )

    client = make_client(handler)
    result = client.find_course_materials("1", "2", ".pptx")
    assert result["complete"] and result["matched_files"] == 2
    assert seen == [("0", 1), ("10", 1), ("10", 2)]
    assert result["files"][0]["folder_path"] == "参考课件"
    assert client.download(result["files"][0]["resource_id"])["bytes"] == 9


@pytest.mark.parametrize(
    "depth,pages,flag", [(0, 10, "depth_limit_reached"), (8, 1, "page_limit_reached")]
)
def test_traversal_limits_are_explicit(make_client, depth, pages, flag):
    client = make_client(
        lambda r: (
            courses_response()
            if "backclazzdata" in r.url.path
            else httpx.Response(200, text=listing(folder_row()))
        )
    )
    result = client.find_course_materials("1", max_depth=depth, max_pages=pages)
    assert not result["complete"] and result[flag]


def test_folder_failure_is_partial_not_empty_success(make_client):
    def handler(r):
        if "backclazzdata" in r.url.path:
            return courses_response()
        if r.url.params.get("dataId") == "10":
            return httpx.Response(403)
        return httpx.Response(200, text=listing(folder_row() + file_row()))

    result = make_client(handler).find_course_materials("1")
    assert not result["complete"]
    assert result["matched_files"] == 1 and result["errors"]


def test_repeated_page_cannot_loop(make_client):
    client = make_client(
        lambda r: (
            courses_response()
            if "backclazzdata" in r.url.path
            else httpx.Response(200, text=listing(file_row(), page=1, total=2))
        )
    )
    result = client.find_course_materials("1")
    assert not result["complete"] and result["errors"]
    assert result["pages_read"] == 2


def test_skeleton_not_misreported_as_empty():
    assert not parse_materials(
        listing('<div class="NoResult">正在加载，请稍后</div>'), BASE
    )["recognized"]
    assert not parse_materials('<img src="loading.gif">', BASE)["recognized"]
    assert parse_materials(listing(), BASE)["recognized"]


def test_newer_endpoint_falls_back_to_signed_legacy_menu(make_client):
    def handler(r):
        if "backclazzdata" in r.url.path:
            return courses_response()
        if "stu-datalist" in r.url.path:
            return httpx.Response(404)
        if "stucoursemiddle" in r.url.path:
            return httpx.Response(
                200,
                text='<a href="/mooc-ans/coursedata?courseId=1&amp;classId=2&amp;cpi=3&amp;enc=signed">资料</a>',
            )
        assert r.url.params["enc"] == "signed"
        return httpx.Response(200, text=listing(file_row()))

    result = make_client(handler).list_course_materials("1")
    assert result["files"][0]["resource_id"]


def test_folder_listing_auto_uses_root_folder_signature(make_client):
    def handler(r):
        if "backclazzdata" in r.url.path:
            return courses_response()
        if r.url.params.get("dataId") == "10":
            assert r.url.params["enc"] == "folder-enc"
            return httpx.Response(200, text=listing(file_row(), folder="10"))
        return httpx.Response(200, text=listing(folder_row()))

    result = make_client(handler).list_course_materials("1", folder_id="10")
    assert result["folder_id"] == "10" and len(result["files"]) == 1


def test_bad_input_makes_no_requests(make_client):
    client = make_client(lambda _: pytest.fail("unexpected request"))
    with pytest.raises(ChaoxingError):
        client.list_course_materials("1", page=0)
    with pytest.raises(ChaoxingError):
        client.find_course_materials("1", max_pages=0)
    with pytest.raises(ChaoxingError):
        client.list_course_materials("not-an-id")
