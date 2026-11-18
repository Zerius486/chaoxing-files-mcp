# 学习通文件 MCP

让支持 MCP 的 AI 客户端查找并下载你在超星学习通中有权访问的课程文件。

适用于这样的需求：

> 找到我的《大学物理》课程，进入课程菜单的「资料」，展开所有文件夹，列出 PDF 和 PPT，再下载我选中的课件。

本项目提供课程枚举、资料目录浏览、递归搜索、页面附件发现和文件下载。使用本地 Cookie 登录，通过 **stdio** 与客户端通信，不需要大模型 API Key，也不需要单独启动 HTTP 服务。

## 目录

- [1. 安装项目](#1-安装项目)
- [2. 准备登录 Cookie](#2-准备登录-cookie)
- [3. 接入 MCP 客户端](#3-接入-mcp-客户端)
- [4. 首次连接检查](#4-首次连接检查)
- [5. 完整流程：查找并下载课程资料](#5-完整流程查找并下载课程资料)
- [6. 获取其他页面中的附件](#6-获取其他页面中的附件)
- [7. 下载位置与文件处理](#7-下载位置与文件处理)
- [8. 配置项与工具速查](#8-配置项与工具速查)
- [9. 常见问题](#9-常见问题)
- [10. 更新、测试与项目结构](#10-更新测试与项目结构)
- [支持范围与实现来源](#支持范围与实现来源)
- [许可证](#许可证)

## 1. 安装项目

### 环境要求

| 项目 | 要求 |
| --- | --- |
| Python | 3.11 或更高版本 |
| Git | 用于克隆和更新仓库 |
| 包管理器 | uv 或 pip，任选一种 |
| 学习通账号 | 能在浏览器中正常打开目标课程 |
| MCP 客户端 | 支持启动本地 stdio 服务，例如 Codex、Antigravity 或 DeepSeek Harness |

客户端、项目代码和 Cookie 文件需要位于同一台运行环境中。云端客户端无法直接执行你电脑里的 Python 或读取本地路径。

### 克隆仓库

```sh
git clone https://github.com/Zerius486/chaoxing-files-mcp.git
cd chaoxing-files-mcp
```

后续安装命令都在项目根目录执行。

### 方法 A：使用 uv

```sh
uv sync --locked
```

命令会创建项目内的 `.venv` 并安装服务依赖。需要运行开发检查时，改用 `uv sync --locked --extra dev`。

仓库默认使用清华 PyPI 镜像。需要换回官方 PyPI 时，修改 `pyproject.toml` 中的 `tool.uv.index`，重新执行 `uv lock`、`uv sync`。

### 方法 B：使用 pip

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

macOS / Linux：

```sh
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
```

这里使用可编辑安装，更新源码后，客户端重启服务即可加载新代码。

## 2. 准备登录 Cookie

服务不接收账号密码，使用你在浏览器中完成登录后导出的 Cookie 访问该账号可以查看的课程。

### 2.1 在浏览器中完成登录

1. 打开学习通网页版，使用自己的账号登录。
2. 进入一门课程，打开课程菜单中的「资料」，确认浏览器能看到文件或文件夹。
3. 如果出现验证码、学校统一认证或其他验证，先在浏览器中完成。

### 2.2 导出 Cookie 为 JSON

使用你信任的 Cookie 导出工具，导出与当前超星会话相关的 Cookie。通常需要包含 `.chaoxing.com` 及实际课程主机下的记录，保留每条记录原有的 `name`、`value`、`domain`、`path` 和有效期。

没有导出工具时，也可以在浏览器开发者工具中，打开 **Application / 应用程序 → Storage / 存储 → Cookies**，查看相关超星域名下的记录，按下面的 JSON 数组格式逐条填写。不同浏览器的菜单名称可能略有不同。

不要只复制 `_uid`，它不能替代完整登录会话。也不要只依赖 `document.cookie`，它无法读取 HttpOnly Cookie，容易遗漏必要凭证。

服务接受两种格式。

**Cookie 数组：**

```json
[
  {
    "name": "_uid",
    "value": "YOUR_UID",
    "domain": ".chaoxing.com",
    "path": "/",
    "secure": true
  },
  {
    "name": "EXAMPLE_SESSION_COOKIE",
    "value": "YOUR_SESSION_VALUE",
    "domain": ".chaoxing.com",
    "path": "/",
    "secure": true
  }
]
```

**Playwright storage state 对象：**

```json
{
  "cookies": [
    {
      "name": "EXAMPLE_SESSION_COOKIE",
      "value": "YOUR_SESSION_VALUE",
      "domain": ".chaoxing.com",
      "path": "/",
      "secure": true
    }
  ],
  "origins": []
}
```

以上仅展示格式，Cookie 名称和值都是占位示例，不能用于登录。请使用自己的完整导出记录，不要为了匹配示例而修改原始域名或 Cookie 名称。服务支持 `expirationDate` 和 `expires`，只读取 Cookie，不读取 localStorage。

### 2.3 保存到本地

在项目根目录创建 `.chaoxing` 文件夹。

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force .chaoxing
```

macOS / Linux：

```sh
mkdir -p .chaoxing
```

将 JSON 文件保存为 UTF-8 编码的：

```text
chaoxing-files-mcp/
└── .chaoxing/
    └── cookies.json
```

Cookie 等同登录凭证，只保存在本机。不要发到 AI 聊天、Issue 或公开仓库。`.chaoxing/` 已加入 `.gitignore`；如果改用其他文件位置，也要自行排除该文件。

## 3. 接入 MCP 客户端

选择自己使用的客户端，完成对应配置即可。**不需要提前在终端运行服务**：客户端会启动 Python 子进程，并通过 stdin/stdout 与它通信。

下面的静态配置使用 `C:/path/to/chaoxing-files-mcp` 作为项目路径占位符。请替换为实际的**绝对路径**，不要直接照抄该路径。

| 路径 | Windows | macOS / Linux |
| --- | --- | --- |
| Python 可执行文件 | `<项目目录>/.venv/Scripts/python.exe` | `<项目目录>/.venv/bin/python` |
| Cookie 文件 | `<项目目录>/.chaoxing/cookies.json` | 相同 |
| 下载目录 | `<项目目录>/downloads` | 相同 |

### 3.1 Codex

安装好 Codex CLI 后，在**项目根目录**执行下面的 PowerShell 命令。它会使用当前目录生成绝对路径：

```powershell
$ProjectDir = (Get-Location).Path
codex mcp add chaoxing-files --env "CHAOXING_COOKIE_FILE=$ProjectDir/.chaoxing/cookies.json" --env "CHAOXING_DOWNLOAD_DIR=$ProjectDir/downloads" -- "$ProjectDir/.venv/Scripts/python.exe" -m chaoxing_files.server
codex mcp list
```

macOS / Linux：

```sh
codex mcp add chaoxing-files \
  --env "CHAOXING_COOKIE_FILE=$PWD/.chaoxing/cookies.json" \
  --env "CHAOXING_DOWNLOAD_DIR=$PWD/downloads" \
  -- "$PWD/.venv/bin/python" -m chaoxing_files.server
codex mcp list
```

也可以手动配置 `~/.codex/config.toml`。与 CLI 添加方式任选一种，避免重复注册：

```toml
[mcp_servers.chaoxing-files]
command = "C:/path/to/chaoxing-files-mcp/.venv/Scripts/python.exe"
args = ["-m", "chaoxing_files.server"]
tool_timeout_sec = 600

[mcp_servers.chaoxing-files.env]
CHAOXING_COOKIE_FILE = "C:/path/to/chaoxing-files-mcp/.chaoxing/cookies.json"
CHAOXING_DOWNLOAD_DIR = "C:/path/to/chaoxing-files-mcp/downloads"
```

保存后重新打开 Codex 或重新启动对应 MCP 服务，再进行[首次连接检查](#4-首次连接检查)。配置命令与格式见 [Codex 官方 MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。

### 3.2 Antigravity

在全局配置文件 `~/.gemini/config/mcp_config.json` 中添加 `chaoxing-files`。Windows 对应路径为 `%USERPROFILE%\.gemini\config\mcp_config.json`。

```json
{
  "mcpServers": {
    "chaoxing-files": {
      "command": "C:/path/to/chaoxing-files-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "chaoxing_files.server"],
      "env": {
        "CHAOXING_COOKIE_FILE": "C:/path/to/chaoxing-files-mcp/.chaoxing/cookies.json",
        "CHAOXING_DOWNLOAD_DIR": "C:/path/to/chaoxing-files-mcp/downloads"
      },
      "timeoutSeconds": 600
    }
  }
}
```

已有其他服务时，只把 `chaoxing-files` 这一项合并到现有 `mcpServers` 中，不要覆盖整个配置文件。空白配置文件可以直接填入完整示例；JSON 不允许尾随逗号。

保存后在 **Customizations → Installed → MCP Servers** 中查看、重启服务，也可以重新启动 Antigravity。不同版本入口可能有变化，实际配置位置可通过应用中的 MCP 管理界面确认。参见 [Antigravity 官方 MCP 文档](https://antigravity.google/docs/mcp)。

### 3.3 dsh / DeepSeek Harness

对于使用 Cordis profile 配置的 DeepSeek Harness，可向当前 profile 的 `cordis.patch.yml` 追加下面的条目。桌面版常见位置为 `~/.dsh/profiles/desktop/cordis.patch.yml`；CLI profile 应使用自身目录，例如 `~/.dsh/profiles/<profile>/cordis.patch.yml`。

```yaml
- insert:
    - id: mcp-chaoxing-files
      name: "@deepseek-ai/dsh-mcp-client"
      config:
        serverName: chaoxing-files
        transport: stdio
        command: C:/path/to/chaoxing-files-mcp/.venv/Scripts/python.exe
        args: ["-m", "chaoxing_files.server"]
        env:
          CHAOXING_COOKIE_FILE: C:/path/to/chaoxing-files-mcp/.chaoxing/cookies.json
          CHAOXING_DOWNLOAD_DIR: C:/path/to/chaoxing-files-mcp/downloads
        toolCallTimeoutMs: 600000
```

保留原有 YAML 条目，确保同一作用域内没有其他名为 `chaoxing-files` 的服务。配置为 `[]` 的空文件应替换为以上数组条目，不要把条目写在 `[]` 后面。

保存后重启对应 profile 或桌面应用。版本采用设置界面管理 MCP 时，也可以按界面要求填写相同的 stdio command、args 和 env；不要再重复添加 YAML 条目。连接参数见 [DeepSeek Harness 官方 MCP 客户端文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)。

### 3.4 其他支持 stdio 的客户端

使用 [mcp-config.example.json](mcp-config.example.json) 作为模板，按客户端要求填写：

- 服务名称：`chaoxing-files`。
- 传输方式：`stdio`。
- command：项目虚拟环境中的 Python **可执行文件路径**。
- args：`["-m", "chaoxing_files.server"]`。
- env：Cookie 和下载目录的绝对路径。

部分客户端使用不同的 JSON 外层结构，请以自己的文档为准。该服务当前没有 HTTP/SSE 地址，不能填入只接受远程 URL 的配置入口。

## 4. 首次连接检查

在客户端中发送：

> 使用 chaoxing-files，先调用 health_check 检查配置，再调用 list_courses 验证登录，告诉我是否能访问课程。

按下面的顺序判断：

| 检查结果 | 说明 |
| --- | --- |
| 客户端发现本项目当前的 8 个工具 | 服务已启动、工具清单已加载；按需加载的客户端可能需要先展开或加载该服务 |
| `health_check.cookie_file_exists` 为 `true` | 文件路径存在，尚不代表 JSON 格式或登录有效 |
| `list_courses` 返回 `ok: true` 和课程列表 | 本次课程列表访问成功，可以继续查询资料 |

`health_check` 不访问网络，也不验证 Cookie 内容或登录状态。部分客户端会延迟展示工具，应以实际调用成功为准。出错时查看返回的 `error`，处理方法见[常见问题](#9-常见问题)。

## 5. 完整流程：查找并下载课程资料

### 5.1 最简单的用法：直接描述任务

把下面的话发给已连接服务的客户端，将课程名换成自己的：

> 使用 chaoxing-files 找到《大学物理》课程，递归浏览课程菜单中的「资料」，列出所有 PDF、PPT、PPTX，显示文件所在目录。先不要下载；如果有分页、扫描限制或错误，请说明。

选好文件后继续说：

> 下载刚才列出的第 1、3、5 个文件，使用默认下载目录，并返回每个文件的本地路径。

也可以直接指定：

> 进入《电路》课程的「资料」，递归找到「参考课件」文件夹，把其中可下载的 PDF 课件下载到已配置的下载目录。如果有同名文件，请询问我如何重命名。

以下是客户端实际调用工具的过程。**JSON 代码块是 MCP 工具的参数，不是要在 Python 或 PowerShell 中直接执行的脚本。**示例 ID 均为虚构数据，必须替换为上一步返回的值。

### 5.2 找到课程和教学班

调用 `list_courses`，参数为：

```json
{}
```

返回的课程字段示意如下，已省略部分字段：

```json
{
  "ok": true,
  "data": [
    {
      "name": "示例课程",
      "courseid": "100001",
      "clazzid": "100002",
      "cpi": "100003"
    }
  ]
}
```

后续参数对应关系：

| `list_courses` 返回字段 | 资料工具使用的参数 |
| --- | --- |
| `courseid` | `course_id` |
| `clazzid` | `class_id` |
| `cpi` | 服务自动使用，无需自己填写 |

同名课程可能属于不同学期或教学班，应确认目标后再查询。存在多个教学班时，请明确提供 `class_id`。

### 5.3 递归获取整门课程的资料

调用 `find_course_materials`：

```json
{
  "course_id": "100001",
  "class_id": "100002",
  "keyword": "",
  "max_depth": 8,
  "max_pages": 100
}
```

工具会请求资料列表，逐层展开文件夹和分页，只列出资料，不下载文件。它直接请求已适配的只读接口，无需浏览器执行 JavaScript。

重点查看返回的 `data`：

| 字段 | 如何使用 |
| --- | --- |
| `files` | 文件列表，包含 `filename`、`folder_path`、`downloadable` 等信息 |
| `files[].resource_id` | 可下载文件的临时资源标识，交给下载工具使用 |
| `folders` | 扫描过程中发现的文件夹 |
| `matched_files` | 与关键词匹配的文件数，不一定等于可下载数量 |
| `pages_read` | 本次尝试读取的列表页数 |
| `complete` | 是否在遍历限制内、未发生访问错误地完成扫描 |
| `errors` / `warnings` | 失败目录、重复页面或其他需要注意的情况 |

`keyword` 是对**文件名和文件夹路径**的不区分大小写的子串匹配，不搜索文件正文，也不支持通配符或正则表达式：

| `keyword` 示例 | 作用 |
| --- | --- |
| `""` | 返回本次扫描到的全部文件 |
| `"参考课件"` | 匹配该目录下的文件，或名称含有该词的文件 |
| `".pdf"` | 匹配 PDF 文件名 |
| `".ppt"` | 匹配 PPT 和 PPTX 文件名 |
| `"Unit1"` | 匹配文件名或路径中的 Unit1 |

默认最多扫描 100 页、深入 8 层。`max_pages` 可设为 1～500，`max_depth` 可设为 0～20；深度 0 仅扫描根目录及其分页。`complete: false` 时检查 `page_limit_reached`、`depth_limit_reached` 和 `errors`，根据情况调整限制或单独浏览失败目录。也要查看 `warnings`；扫描完成不代表每项资源都可下载。

### 5.4 只查看某个文件夹

不想递归扫描时，先调用 `list_course_materials` 查看根目录：

```json
{
  "course_id": "100001",
  "class_id": "100002"
}
```

从返回的 `data.folders` 中找到目标文件夹，复制它的 `folder_id` 和 `folder_enc`。进入该文件夹：

```json
{
  "course_id": "100001",
  "class_id": "100002",
  "folder_id": "200001",
  "folder_enc": "COPY_FROM_PARENT_FOLDER_RESULT",
  "page": 1
}
```

更简单的方式是把该文件夹返回的完整 `url` 交给 `inspect_page`。不要自行猜测或拼接签名参数。

查看更深一层目录时，继续使用当前结果中子文件夹的 ID 和签名。若 `has_more: true`，保留当前文件夹参数，将 `page` 增加 1；也可直接浏览 `next_page_url`。`list_course_materials` 每次只读取一页，自动翻页和下钻应使用 `find_course_materials`。

### 5.5 下载指定文件

只选择 `downloadable: true` 且带有 `resource_id` 的文件。

调用 `download_file`：

```json
{
  "resource_id": "COPY_FROM_FILE_RESULT"
}
```

需要重命名时添加 `filename`，建议保留真实扩展名：

```json
{
  "resource_id": "COPY_FROM_FILE_RESULT",
  "filename": "电路课件-Unit1.pdf"
}
```

调用 `download_files` 可一次顺序下载最多 50 个资源：

```json
{
  "resource_ids": [
    "COPY_FIRST_RESOURCE_ID",
    "COPY_SECOND_RESOURCE_ID"
  ]
}
```

单文件下载成功后返回本地绝对路径 `path`、实际字节数 `bytes`、`sha256` 和资源 ID。批量下载返回 `results`，每个文件分别标记 `ok`；一个文件失败不会阻止其余文件继续下载。超过 50 个文件请拆成多批。

`resource_id` 只在发现文件的**同一个 MCP 服务进程**中有效。重启服务、更换 Cookie，或换到另一个客户端后，应重新列出或搜索文件，再使用新结果中的 ID。

## 6. 获取其他页面中的附件

课程「资料」优先使用上一节的专用工具。对于课程主页、通知、作业详情或其他超星页面中的附件，可以调用 `inspect_page`：

```json
{
  "url": "COPY_THE_COMPLETE_CHAOXING_PAGE_URL"
}
```

它会返回发现的 `files` 和可继续浏览的 `links`。普通页面会提取附件 objectId、文件链接、图片、媒体地址和 iframe 链接；已适配的资料页还会返回文件夹与分页信息。它不会执行任意页面脚本，也不会自动遍历整门课程。

如果已从页面获得一个真实的超星 objectId，可以调用 `resolve_object`：

```json
{
  "object_id": "COPY_THE_OBJECT_ID",
  "filename": "原文件名.pdf"
}
```

该工具仅把已知 objectId 注册为临时资源，不证明文件存在、可下载或已授权；实际下载仍受服务器权限限制。不要把课程 `data_id`、文件夹 `folder_id` 当作 objectId。资料列表已经给出 `resource_id` 时，直接使用该 ID 下载即可。

## 7. 下载位置与文件处理

默认下载目录为项目根目录的 `downloads/`，目录会在下载时创建。更改位置请修改客户端 env 中的 `CHAOXING_DOWNLOAD_DIR`，再重启服务。

```json
{
  "CHAOXING_DOWNLOAD_DIR": "D:/Course/示例课程"
}
```

这里展示的是 env 中的一项，不是完整客户端配置。下载工具不接受任意目标目录参数；`filename` 仅用于命名文件，路径分隔符等非法字符会被清理。

文件列表中的 `folder_path` 便于区分来源，但下载时**不会自动重建课程文件夹树**。多个目录存在同名文件时，请逐个调用 `download_file` 并指定不同的 `filename`。服务不会覆盖已有文件，也不支持断点续传。

下载后，PDF/PPT 正文提取、扫描件 OCR、总结或复习讲义生成，由你的 AI 客户端或其他本地工具完成。本项目没有读取文件正文或 OCR 工具，下载返回的是文件路径和校验信息。

## 8. 配置项与工具速查

### 环境变量

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CHAOXING_COOKIE_FILE` | `<项目目录>/.chaoxing/cookies.json` | 登录 Cookie JSON 的路径 |
| `CHAOXING_DOWNLOAD_DIR` | `<项目目录>/downloads` | 所有下载文件的保存目录 |
| `CHAOXING_MAX_FILE_MB` | `512` | 单文件上限，正整数，按 1024 × 1024 字节计算 |
| `CHAOXING_EXTRA_DOMAINS` | 空 | 逗号分隔的附加文件主机或域名 |

`.env.example` 只是配置参考，服务**不会自动加载 `.env`**。请把变量写入 MCP 客户端的 env，或在启动进程的环境中设置。为避免工作目录不同导致路径错误，建议全部使用绝对路径。

默认允许 `chaoxing.com`、`chaoxing.com.cn` 及其子域名，以及已验证的 `d0.cldisk.com`。所有请求和重定向均校验 HTTPS、主机与端口。`health_check.allowed_domains` 可以查看运行中的允许列表。

只有实际出现另一个已确认的文件主机时，才增加对应值，例如：

```json
{
  "CHAOXING_EXTRA_DOMAINS": "confirmed-file-host.example.com"
}
```

以上主机名是格式示例，不是真实超星主机。填写值时不带 `https://`、路径或通配符；多个值用英文逗号分隔。每个域名也允许其子域名，所以应尽量填写具体主机，避免放开无关域名。

Cookie 仅从超星域名记录导入并按域发送，不会作为全局请求头发送给其他 CDN。除 Cookie 文件支持自动重载外，更改这些环境变量后都需要重启服务。

### 工具速查

| 工具 | 主要参数 | 用途 |
| --- | --- | --- |
| `health_check` | 无 | 检查文件路径是否存在、下载目录、大小上限与允许域名 |
| `list_courses` | 无 | 获取课程、教学班和主页链接，验证本次课程访问 |
| `list_course_materials` | `course_id`、`class_id?`、`folder_id?`、`folder_enc?`、`page?` | 查看课程「资料」中的某一页 |
| `find_course_materials` | `course_id`、`class_id?`、`keyword?`、`max_depth?`、`max_pages?` | 递归搜索资料目录与分页 |
| `inspect_page` | `url` | 检查页面中的附件、链接或资料列表 |
| `resolve_object` | `object_id`、`filename?` | 注册已知 objectId |
| `download_file` | `resource_id`、`filename?` | 下载单个文件，可重命名 |
| `download_files` | `resource_ids` | 顺序下载最多 50 个文件，逐项返回结果 |

`?` 表示可选参数。多数工具返回 `{"ok": true, "data": ...}` 或 `{"ok": false, "error": ...}`；`health_check` 直接返回配置检查结果，`download_files` 返回顶层 `ok` 和逐项 `results`。不要只依据客户端显示的“工具调用完成”判断操作成功，还要检查结果中的 `ok`。

## 9. 常见问题

### 工具没有出现，或只有旧版工具

检查 command 是否指向项目 `.venv` 中的 Python、args 是否为 `-m chaoxing_files.server`，以及是否完成项目安装。随后重启对应 MCP 服务，必要时重新打开客户端或新建聊天。

当前服务提供 8 个工具，包括 `list_course_materials` 和 `find_course_materials`。支持按需加载的客户端可能不会一次展示全部工具，应在服务管理界面或实际调用中确认。

### `ModuleNotFoundError: No module named 'chaoxing_files'`

通常是用了其他 Python，或没有执行可编辑安装。返回项目目录重新执行 `uv sync --locked`，或使用该虚拟环境的 Python 执行 `-m pip install -e .`，再核对客户端 command。

### 手动启动服务后没有输出

stdio 服务等待 MCP 协议消息，没有聊天式终端提示属于正常情况。可以按 Ctrl+C 结束手动启动的进程，让客户端自行启动服务。

如需手动检查能否启动，Windows 使用：

```powershell
.\.venv\Scripts\python.exe -m chaoxing_files.server
```

macOS / Linux 使用 `./.venv/bin/python -m chaoxing_files.server`。启动成功不等于 Cookie 有效，仍需调用 `list_courses`。

### 缺少 Cookie 文件，或 Cookie JSON 格式错误

检查文件是否保存到配置指定的位置、是否为有效 JSON、是否包含实际超星域名记录，以及 Cookie 是否已过期。导出的 `cookies.txt`、复制的 `Cookie: ...` 请求头或只含一个字符串的文件，都不是本服务接受的格式。

### `health_check` 正常，但登录失败、HTTP 401/403 或需要验证码

`health_check` 仅检查本地配置。请在浏览器重新登录并打开目标课程，完成所需验证，重新导出完整 Cookie 覆盖原 JSON。

下一次调用会检测 Cookie 文件变化并重载，无需仅为更换 Cookie 而重启服务；原有资源 ID 会清空，需重新查询文件。403 也可能表示账号没有目标文件权限，不能仅凭该状态码认定 Cookie 失效。

### 资料页只返回 folder.gif、loading.gif 或看不到课件

先使用 `list_course_materials` 或 `find_course_materials`，不要仅依赖通用页面附件提取。课件可能位于文件夹中，也可能以 PDF 形式上传，直接搜索 `.ppt` 不一定能找到它们。

专用工具提示“未识别资料列表”时，可能是接口结构变化或没有访问权限，不能据此认定目录为空。提交问题时提供去除凭证后的错误、客户端和页面版本即可，不要上传完整 Cookie 或带授权参数的 URL。

### `complete: false`，结果是否还能用？

已返回的文件仍可按 `downloadable` 和 `resource_id` 判断是否可下载，但列表可能不完整。检查 `errors` 和两项限制标志：遇到页数/深度限制可适当提高参数，访问错误则单独检查对应目录。

### 文件显示 `downloadable: false`

当前解析结果没有可用的下载入口，或平台标记不允许下载。这类文件不提供资源 ID；增加域名配置不能解除平台权限限制。

### 资源 ID 已失效

重新列出或搜索文件，再下载。不同客户端启动的是不同服务进程，不能把一个客户端获得的 `resource_id` 直接交给另一个客户端。

### 资源域名不在允许列表中

错误会显示具体主机。确认它是目标文件实际使用的合法下载主机后，将其加入 `CHAOXING_EXTRA_DOMAINS` 并重启服务。

`s3.ananas.chaoxing.com`、`d0.ananas.chaoxing.com`、`cs-ans.chaoxing.com` 已包含在默认的 `chaoxing.com` 子域规则中，无需重复添加。默认也已允许 `d0.cldisk.com`；运行中仍拒绝它时，先检查是否加载了旧代码。

### 文件超过大小上限、调用超时或批量下载失败

大文件可提高 `CHAOXING_MAX_FILE_MB` 并重启服务。客户端工具超时与文件大小上限是不同设置；长任务可增加客户端工具超时，或拆成更小批次、单个文件下载。HTTP 请求本身也有超时，单纯增大客户端等待时间不能解决持续的网络故障。

批量下载逐项检查 `results`。成功文件会保留，不要对全部文件盲目重试，否则可能触发同名文件错误。

### 同名文件已存在

服务不会覆盖。对该文件使用 `download_file` 并传入新的 `filename`，或者由你自行管理已有文件。`download_files` 不提供逐项重命名参数。

### 返回 HTML 预览页，或找不到原文件链接

登录页和 HTML 预览不会被当作文件保存。没有可解析的原文件下载链接时，工具会返回错误。本项目也因此不支持直接把 HTML 网页作为原文件下载。

### 想让 AI 读取 PDF/PPT 的内容

先完成下载，再让客户端读取返回的本地路径；扫描件需要客户端额外使用 OCR。MCP 当前负责找文件和下载，不返回文档正文。

## 10. 更新、测试与项目结构

### 更新

在项目目录执行：

```sh
git pull --ff-only
uv sync --locked
```

使用 pip 时，更新源码后执行虚拟环境中的 `python -m pip install -e .`。保留原有 Cookie 与下载目录，分别重启使用这份安装的客户端 MCP 服务。`git pull` 因本地修改而停止时，请先处理自己的改动，不要直接覆盖配置或源码。

### 开发检查

```sh
uv sync --locked --extra dev
uv run pytest
uv run ruff check .
```

测试使用模拟响应，覆盖新旧资料列表、文件夹导航、分页、递归限制、重复页面、下载权限、Cookie 隔离、失败清理和 MCP stdio。已另行实测多层课程资料目录与实际课件下载，但不保证所有学校、课程或后续版本均兼容。

### 项目结构

```text
chaoxing-files-mcp/
├── src/chaoxing_files/
│   ├── server.py                 # MCP 工具与 stdio 入口
│   ├── client.py                 # 会话、课程请求、递归浏览和下载
│   ├── materials.py              # 新旧版课程资料解析与导航
│   ├── parsing.py                # 通用页面附件提取
│   └── config.py                 # 环境变量配置
├── tests/                        # 模拟接口与协议测试
├── .env.example                  # 环境变量参考，不自动加载
├── mcp-config.example.json       # 通用客户端配置模板
├── pyproject.toml
├── uv.lock
├── LICENSE
├── .chaoxing/cookies.json        # 你自行保存，不提交仓库
└── downloads/                    # 本地下载文件，不提交仓库
```

## 支持范围与实现来源

本项目只查询和下载账号有权访问的文件，不包含答题、作业提交、签到、刷课、文档生成或验证码识别。读取页面和下载文件仍可能被平台记录为访问行为。

课程「资料」已适配新版 `/mooc2-ans/coursedata/stu-datalist` 与旧版 `/mooc-ans/coursedata`。其他页面通过可解析的链接和附件属性发现文件；专门的云盘目录、未适配的动态页面、嵌入脚本的章节任务数据、DRM 视频和直播尚未覆盖。该服务使用非官方接口，平台变化后可能需要调整。

参考 [Aemiser/chaoxing_mcp](https://github.com/Aemiser/chaoxing_mcp) 的课程列表接口、附件 objectId 形式与超星预览下载流程，独立实现文件服务，没有复制其实现代码。协议基于 [MCP 官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)，HTTP 请求基于 [HTTPX](https://www.python-httpx.org/)。

## 许可证

采用 [MIT License](LICENSE)。项目许可证适用于本项目代码，不授予第三方课程文件的复制或再分发权；请遵守学校、平台及资料权利人的使用要求。
