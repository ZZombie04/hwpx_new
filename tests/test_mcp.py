# -*- coding: utf-8 -*-
"""MCP 서버 테스트: 외부 패키지 없이 직접 프로토콜(JSON-RPC)로 호출하고, 공식 SDK 클라이언트가 있으면 호환성도 확인."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, 'examples', 'sample_template.hwpx')


class Client:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, '-m', 'hwpx_new.mcp_server'], cwd=ROOT, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  env={**os.environ, 'PYTHONUTF8': '1'})
        self.n = 0

    def call(self, method, params=None):
        self.n += 1
        msg = {'jsonrpc': '2.0', 'id': self.n, 'method': method, 'params': params or {}}
        self.p.stdin.write((json.dumps(msg, ensure_ascii=False) + '\n').encode('utf-8'))
        self.p.stdin.flush()
        line = self.p.stdout.readline().decode('utf-8')
        return json.loads(line)

    def notify(self, method):
        self.p.stdin.write((json.dumps({'jsonrpc': '2.0', 'method': method}) + '\n').encode('utf-8'))
        self.p.stdin.flush()

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=10)


def test_protocol_roundtrip():
    c = Client()
    try:
        r = c.call('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}})
        assert r['result']['serverInfo']['name'] == 'hwpx_new' and 'tools' in r['result']['capabilities']
        c.notify('notifications/initialized')
        tools = {t['name']: t for t in c.call('tools/list')['result']['tools']}
        assert {'hwpx_build', 'hwpx_analyze', 'hwpx_start_here', 'hwpx_preview'} <= set(tools)
        assert tools['hwpx_build']['inputSchema']['required'] == ['template_path', 'content', 'output_dir']
        res = c.call('tools/call', {'name': 'hwpx_analyze', 'arguments': {'template_path': TPL}})['result']
        assert not res['isError'] and '서식 종류' in res['content'][0]['text'] and '```markdown' in res['content'][0]['text']
        out = tempfile.mkdtemp()
        md = os.path.join(ROOT, 'examples', 'sample_content.md')
        res = c.call('tools/call', {'name': 'hwpx_build', 'arguments': {
            'template_path': TPL, 'content': md, 'output_dir': out, 'name': 'mcp_test', 'engine': 'html'}})['result']
        assert not res['isError'], res
        assert os.path.exists(os.path.join(out, 'mcp_test.hwpx')) and os.path.exists(os.path.join(out, 'mcp_test.pdf'))
        img = c.call('tools/call', {'name': 'hwpx_preview', 'arguments': {'pdf_path': os.path.join(out, 'mcp_test.pdf')}})['result']
        assert img['content'][0]['type'] == 'image' and img['content'][0]['mimeType'] == 'image/png'
        bad = c.call('tools/call', {'name': 'hwpx_analyze', 'arguments': {'template_path': 'nope.hwpx'}})['result']
        assert bad['isError']
        assert 'error' in c.call('no/such/method')
    finally:
        c.close()


def test_sdk_client_compat():
    """공식 MCP SDK 클라이언트(있을 때만)로도 연결·호출이 되는지."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        return
    import asyncio

    async def go():
        params = StdioServerParameters(command=sys.executable, args=['-m', 'hwpx_new.mcp_server'], cwd=ROOT,
                                       env={**os.environ, 'PYTHONUTF8': '1'})
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = [t.name for t in (await s.list_tools()).tools]
                assert 'hwpx_build' in tools
                res = await s.call_tool('hwpx_analyze', {'template_path': TPL})
                assert '서식' in res.content[0].text
    asyncio.run(go())


if __name__ == '__main__':
    test_protocol_roundtrip()
    test_sdk_client_compat()
    print('MCP OK')
