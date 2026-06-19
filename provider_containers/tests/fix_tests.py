import re
import os

filepath = "/home/thenaha/containers/stacks/comfyui/provider_containers/tests/test_workflow_executor.py"
with open(filepath, "r") as f:
    content = f.read()

header = """
class _FakeAsyncClient:
    def __init__(self, fake_urlopen):
        self.fake_urlopen = fake_urlopen
    async def __aenter__(self): return self
    async def __aexit__(self, exc_type, exc, tb): pass
    async def post(self, url, json=None, timeout=None, **kwargs):
        import urllib.request, urllib.error
        req = urllib.request.Request(url, data=b"fake")
        try:
            res = self.fake_urlopen(req, timeout)
            res.json = lambda: __import__('json').loads(res.read())
            res.raise_for_status = lambda: None
            return res
        except urllib.error.HTTPError as e:
            import httpx
            class MockResponse:
                text = e.fp.read().decode('utf-8') if hasattr(e.fp, 'read') else str(e)
            error = httpx.HTTPStatusError("error", request=httpx.Request("POST", url), response=MockResponse())
            raise error

    async def get(self, url, params=None, timeout=None, **kwargs):
        if params:
            import urllib.parse
            url += "?" + urllib.parse.urlencode(params)
        res = self.fake_urlopen(url, timeout)
        res.json = lambda: __import__('json').loads(res.read())
        res.content = res.read()
        res.raise_for_status = lambda: None
        return res
"""

if "_FakeAsyncClient" not in content:
    content = content.replace("class _BytesResponse:", header + "\nclass _BytesResponse:")

content = re.sub(
    r'monkeypatch\.setattr\("provider_core\.workflow_executor\.urllib\.request\.urlopen", fake_urlopen\)',
    r'monkeypatch.setattr("provider_core.workflow_executor.httpx.AsyncClient", lambda: _FakeAsyncClient(fake_urlopen))',
    content
)

with open(filepath, "w") as f:
    f.write(content)
