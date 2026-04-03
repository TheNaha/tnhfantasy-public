import pytest

from infrastructure.providers.ndjson import iter_ndjson_payloads


async def _iter_chunks(chunks):
    for chunk in chunks:
        yield chunk


async def _collect_payloads(chunks):
    return [
        payload async for payload in iter_ndjson_payloads(
            _iter_chunks(chunks),
            source='test-provider',
        )
    ]


@pytest.mark.asyncio
async def test_iter_ndjson_payloads_handles_chunk_boundaries():
    payloads = await _collect_payloads([
        b'{"status":"progress","value":1}\n{"status":"execut',
        b'ing","node":"4"}\n',
    ])

    assert payloads == [
        {"status": "progress", "value": 1},
        {"status": "executing", "node": "4"},
    ]


@pytest.mark.asyncio
async def test_iter_ndjson_payloads_skips_malformed_lines():
    payloads = await _collect_payloads([
        b'not-json\n{"status":"queued"}\n',
    ])

    assert payloads == [{"status": "queued"}]


@pytest.mark.asyncio
async def test_iter_ndjson_payloads_reads_trailing_line_without_newline():
    payloads = await _collect_payloads([
        b'{"status":"success","images":[{"filename":"x.png"}]}'
    ])

    assert payloads == [{"status": "success", "images": [{"filename": "x.png"}]}]
