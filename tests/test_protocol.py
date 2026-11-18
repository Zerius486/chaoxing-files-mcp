import os
import sys

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_tools_and_health():
    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "chaoxing_files.server"],
            env=dict(os.environ),
        )
        with anyio.fail_after(30):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    assert {t.name for t in result.tools} == {
                        "health_check",
                        "list_courses",
                        "inspect_page",
                        "resolve_object",
                        "download_file",
                        "download_files",
                        "list_course_materials",
                        "find_course_materials",
                    }
                    health = await session.call_tool("health_check", {})
                    assert not health.isError
                    assert "chaoxing-files" in health.content[0].text
                    batch = await session.call_tool(
                        "download_files", {"resource_ids": ["x"] * 51}
                    )
                    assert "50" in batch.content[0].text

    anyio.run(run)
