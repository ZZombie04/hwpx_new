# -*- coding: utf-8 -*-
"""MCP 서버 스모크 테스트: 도구 목록과 analyze/build 호출이 되는지 확인."""
import asyncio
import os
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def main():
    params = StdioServerParameters(command=sys.executable, args=['-m', 'hwpx_new.mcp_server'], cwd=ROOT,
                                   env={**os.environ, 'PYTHONUTF8': '1'})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            print('tools:', tools)
            assert 'hwpx_build' in tools and 'hwpx_analyze' in tools
            tpl = os.path.join(ROOT, 'examples', 'sample_template.hwpx')
            res = await s.call_tool('hwpx_analyze', {'template_path': tpl})
            text = res.content[0].text
            assert '소제목' in text and '표' in text
            out = tempfile.mkdtemp()
            md = os.path.join(ROOT, 'examples', 'sample_content.md')
            res = await s.call_tool('hwpx_build', {'template_path': tpl, 'content': md, 'output_dir': out,
                                                   'name': 'mcp_test', 'engine': 'html'})
            print(res.content[0].text)
            assert os.path.exists(os.path.join(out, 'mcp_test.hwpx'))
            assert os.path.exists(os.path.join(out, 'mcp_test.pdf'))
            img = await s.call_tool('hwpx_preview', {'pdf_path': os.path.join(out, 'mcp_test.pdf'), 'page': 1})
            assert img.content[0].type == 'image'
    print('MCP OK')


if __name__ == '__main__':
    asyncio.run(main())
