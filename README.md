# 学习通文件 MCP

独立的 Python stdio MCP 服务，用于查找和下载本人账号有权访问的超星学习通文件。只提供课程枚举、页面浏览、资源发现和下载，不包含大模型 API、答题、生成作业、提交、签到或刷课。

## 能力与边界

| 工具 | 功能 |
| --- | --- |
| `health_check` | 检查本地配置，不访问网络 |
| `list_courses` | 获取当前账号课程和主页链接 |
| `list_course_materials` | 列出课程「资料」栏目中的文件、文件夹和分页，支持新旧版列表 |
| `find_course_materials` | 递归展开资料文件夹与分页，按文件名/目录路径搜索 |
| `inspect_page` | 提取当前页面附件、图片、音视频，以及目录、分页和 iframe 链接 |
| `resolve_object` | 用已知 objectId 和原文件名注册文件 |
| `download_file` | 下载单个资源，返回本地路径、大小、SHA256 |
| `download_files` | 最多 50 个资源的顺序下载，逐项报告结果 |

支持发现 HTML 中的文件链接、`objectid` / `data-objectid`、iframe JSON `data`、媒体 `src`，以及超星预览页的 `btnDown` 原文件链接。下载类型不限于 Word/PDF，实际以服务器是否提供可访问的原文件为准。

课程「资料」已适配新版 `/mooc2-ans/coursedata/stu-datalist` 和旧版 `/mooc-ans/coursedata`。直接请求前端用于异步加载的只读列表接口，并从行属性和 `toOpen(...)` 的字面参数提取文件夹导航，不需要执行 JavaScript 或安装浏览器。支持逐层浏览、分页、递归扫描，保留原文件名并排除文件夹图标等界面图片。下载使用课程的 `downloadData` 接口，保留 courseId/classId/cpi/dataId；平台标记不可下载的文件不会提供下载资源 ID。

这不是完整学习通 API，也不保证列出平台所有文件。云盘、章节、通知或作业中的文件，仍以页面提供的链接/属性为主。其他未适配的动态接口、脚本拼接的作业链接、嵌入脚本的章节任务数据、DRM 视频、直播及未开放下载的资源尚未适配。没有自动爬取全部课程或专门的云盘目录 API。遇到验证码请在浏览器人工处理；不会自动识别或绕过验证。

## 安装

需要 Python 3.11+，先克隆仓库：

```powershell
git clone https://github.com/Zerius486/chaoxing-files-mcp.git
cd chaoxing-files-mcp
```

在项目目录执行：

```powershell
uv sync --extra dev
```

uv 配置默认使用清华 PyPI 镜像；依赖版本记录在 `uv.lock`。如需官方源，可修改 `pyproject.toml` 的 `tool.uv.index` 后重新锁定。

不用 uv 时也可：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 登录

服务只读取本地 Cookie，不接收或存储密码。先在浏览器登录学习通并打开一门课程，再通过你信任的 Cookie 导出方式保存 JSON 到 `.chaoxing/cookies.json`。支持浏览器 Cookie 导出的数组格式，以及 Playwright storage state 的 `{"cookies": [...]}` 格式；不读取其中的 localStorage。

格式示例（示例值不能用于登录，实际需要完整会话 Cookie，不能只填 `_uid`）：

```json
[
  {"name": "_uid", "value": "YOUR_UID", "domain": ".chaoxing.com", "path": "/", "secure": true},
  {"name": "EXAMPLE_SESSION_COOKIE", "value": "YOUR_VALUE", "domain": ".chaoxing.com", "path": "/", "secure": true}
]
```

必须保留真实 domain/path，文件需包含超星域名 Cookie。支持 `expirationDate` 和 `expires`。Cookie 文件变化后下一次调用会自动重载并清空旧资源 ID。`list_courses` 成功才代表服务端确认本次课程访问可用，`health_check` 不验证登录。

Cookie 等同登录凭证，保存在本机即可，不要发到聊天或提交仓库。默认忽略 `.chaoxing/`、`cookies*.json` 和下载目录。

## 启动与接入

```powershell
.\.venv\Scripts\python.exe -m chaoxing_files.server
```

该进程通过 stdin/stdout 交换 MCP 消息，终端没有普通交互提示属于正常情况。客户端使用 [mcp-config.example.json](mcp-config.example.json)，请把示例中的 `C:/path/to/chaoxing-files-mcp` 改成项目的实际绝对路径。macOS/Linux 请将 Python 路径改成 `.venv/bin/python`。配置格式因客户端而异，此文件使用常见 `mcpServers` 格式。

环境变量：

| 变量 | 默认值 |
| --- | --- |
| `CHAOXING_COOKIE_FILE` | 项目目录 `/.chaoxing/cookies.json` |
| `CHAOXING_DOWNLOAD_DIR` | 项目目录 `/downloads` |
| `CHAOXING_MAX_FILE_MB` | 512，必须大于 0 |
| `CHAOXING_EXTRA_DOMAINS` | 空，逗号分隔附加 CDN 域名 |

`.env.example` 仅作参考，**不会自动加载 `.env`**；在客户端 env 或进程环境中设置。

## 使用示例

让 MCP 客户端执行：

1. `list_courses()` 找到课程主页 URL。
2. `inspect_page(url)` 查看课程菜单、资料目录和 iframe 链接。
3. 继续对返回的 `links` 调用 `inspect_page`，直至发现目标文件。分页需逐页访问。
4. 把 `files` 中的 `resource_id` 传给 `download_file` / `download_files`。

获取课程菜单中的 **「资料」** 时，优先使用专用工具：

```python
# course_id/class_id 分别来自 list_courses 返回的 courseid/clazzid
list_course_materials(course_id="YOUR_COURSE_ID", class_id="YOUR_CLASS_ID")
# 遍历全部资料目录、分页，查找“参考课件”目录中的文件
find_course_materials(course_id="YOUR_COURSE_ID", class_id="YOUR_CLASS_ID", keyword="参考课件")
```

`list_course_materials` 返回 `folders`、`files`、`page`、`total_pages`、`has_more` 和 `next_page_url`。进入文件夹时传入父目录返回的 `folder_id`、`folder_enc`；也可直接对 `folder.url` 调用 `inspect_page`。下一页使用相同文件夹参数并递增 `page`，或直接浏览 `next_page_url`。

`find_course_materials` 的 `keyword` 留空时返回扫描到的所有文件；也可以用 `.pdf`、`.ppt`、课件名或目录名过滤。默认最多扫描 100 页、深入 8 层，可设置 `max_pages`（1～500）和 `max_depth`（0～20）。`complete=false` 表示触及限制或出现访问错误；请同时查看 `page_limit_reached`、`depth_limit_reached`、`errors` 和 `warnings`，不能把未扫描完的结果当作空目录。分页和循环目录会去重，不会无限遍历。文件返回 `folder_path`，但下载仍写入配置目录，不自动创建相同目录树。

升级后需重启客户端中的 MCP 服务以刷新工具清单，当前共有 8 个工具。多个客户端可以连接到同一份本地安装；更新代码后分别重启各客户端的服务即可。

也可直接提供已登录浏览器中的课程/资料/作业详情 URL；已知 objectId 时使用 `resolve_object(object_id, filename)`。资源 ID 仅在当前服务进程有效，重启或更换 Cookie 后需重新发现。

默认校验 TLS；仅允许 HTTPS 超星域名、实际附件重定向确认使用的 `d0.cldisk.com`，及显式配置的附加域名，每次重定向重新检查。域名拒绝错误会显示主机名，`health_check` 会列出当前允许域名。Cookie 仅从超星域名导入并按域名发送；不会把超星 Cookie 作为全局请求头转发给 CDN。只发送 GET 请求，屏蔽明显的提交/删除/签到 URL。读取页面仍可能被平台记作访问记录。

下载只写入配置目录，清理 Windows 非法文件名、不覆盖已有文件，流式计算哈希并限制大小，失败清理临时文件。HTML 预览/登录响应不会当作原文件保存，因此不支持直接保存 HTML 文件。Windows 使用拒绝覆盖的原子重命名；其他平台使用同目录硬链接发布文件。页面返回 URL 可能含短期授权参数，也应视作私有信息。

## 验证

```powershell
uv run pytest
uv run ruff check .
```

自动化测试使用模拟超星响应，覆盖两版资料页、文件夹导航、分页、递归限制、循环去重、受限下载和 MCP stdio。另已使用真实账号验证多层资料目录、文件列表、课程课件与附件下载。账号凭证、真实课程页面和下载文件不随仓库分发。这些验证不保证所有学校、课程或后续版本页面均兼容。

## 开源许可证

本项目采用 [MIT License](LICENSE)。仅下载本人账号有权访问的资料；开源许可证不授予第三方课程资料的复制或再分发权。

## 参考与实现来源

参考 [Aemiser/chaoxing_mcp](https://github.com/Aemiser/chaoxing_mcp) 中的课程列表接口、作业附件 objectId 形式及超星预览下载流程。原仓库未声明开源许可证，本项目没有复制其实现代码，独立实现文件服务，也没有引入其 AI 作业工作流、pickle 会话或关闭 TLS 验证的设置。

MCP 基于 [官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)，HTTP 基于 [HTTPX](https://www.python-httpx.org/)。超星接口为非官方接口，平台变更后可能需要调整。
