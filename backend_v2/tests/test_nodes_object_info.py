"""`GET /api/nodes/object_info` — the per-provider node graph.

Two costs were measured on one endpoint: 2,388 kB / 2.7 s per call against a
provider whose ComfyUI has to spin up to introspect itself, and a payload four
times the size of what the node palette and editor read. These tests pin the
cache (including its single flight, because `/advanced` requests this twice on
first paint) and pin the exact field list of the digest, because a digest cannot
be verified against production data from a test that has no production data.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.routes import nodes as nodes_routes
from core.exceptions import ProviderTimeoutError

# A miniature node graph with every shape `ComfyNode.jsx` has to survive: a bare
# type, a type plus options, a combo (options array plus options), and a spec
# that is a bare dict.
SAMPLE_GRAPH = {
    "KSampler": {
        "input": {
            "required": {
                "model": ["MODEL", {"tooltip": "noise"}],
                "seed": ["INT", {"default": 0, "min": 0, "max": 10, "step": 1}],
                "sampler_name": [["euler", "heun"], {"tooltip": "algorithm"}],
                "denoise": {"default": 1.0, "min": 0.0, "max": 1.0},
                "bare": ["STRING"],
            }
        },
        "output": ["LATENT"],
        "output_name": ["LATENT"],
        "output_is_list": [False],
        "name": "KSampler",
        "display_name": "KSampler",
        "description": "The main sampler.",
        "category": "sampling",
        "python_module": "nodes",
        "input_order": {"required": ["model", "seed"]},
        "search_aliases": ["sampler"],
        "output_node": False,
        "price_badge": [{"type": "currency"}],
        "experimental": False,
    },
    "EmptyNode": {
        "input": {"required": {}},
        "output": [],
        "output_name": [],
        "display_name": "Empty",
        "description": "",
        "category": "utils",
    },
}


@pytest.fixture(name="cleared_cache", autouse=True)
def _cleared_cache():
    """The cache is module-global, so it has to start empty for every test."""
    nodes_routes._object_info_cache.clear()
    yield
    nodes_routes._object_info_cache.clear()


@pytest.fixture(name="upstream")
def _upstream():
    """A stubbed provider + worker response, and a counter of upstream fetches."""
    fetches: list[int] = []

    def client_factory():
        async def get(url, timeout=None):
            fetches.append(1)

            class Response:
                def raise_for_status(self_inner):
                    return None

                def json(self_inner):
                    return SAMPLE_GRAPH

            return Response()

        return SimpleNamespace(get=get)

    provider = SimpleNamespace(id="p1", type="remote_comfy", container_config={})
    service = SimpleNamespace(get_provider=AsyncMock(return_value=provider))
    runtime = SimpleNamespace(worker_url="http://worker.invalid")
    with (
        patch.object(nodes_routes, "get_provider_service", return_value=service),
        patch.object(
            nodes_routes,
            "resolve_provider_runtime_async",
            AsyncMock(return_value=runtime),
        ),
        patch.object(nodes_routes, "get_http_client", client_factory),
    ):
        yield fetches


def object_info(client, **params):
    query = {k: v for k, v in params.items() if v is not None}
    response = client.get("/api/nodes/object_info", params=query)
    assert response.status_code == 200, response.text
    return response.json()


class TestObjectInfoCache:
    def test_the_second_request_does_not_touch_the_provider(self, client, upstream):
        first = object_info(client, provider_id="p1")
        assert upstream, "the first request never reached the provider"
        second = object_info(client, provider_id="p1")
        assert len(upstream) == 1, f"{len(upstream)} upstream fetches for two requests"
        assert second == first

    def test_ten_requests_cost_one_fetch(self, client, upstream):
        for _ in range(10):
            object_info(client, provider_id="p1")
        assert len(upstream) == 1, len(upstream)

    def test_a_different_provider_is_a_different_key(self, client, upstream):
        object_info(client, provider_id="p1")
        object_info(client, provider_id="p2")
        assert len(upstream) == 2, len(upstream)

    def test_a_failure_is_not_cached(self, client):
        provider = SimpleNamespace(id="p1", type="remote_comfy", container_config={})

        async def get(url, timeout=None):
            raise TimeoutError("upstream hung")

        with (
            patch.object(
                nodes_routes,
                "get_provider_service",
                return_value=SimpleNamespace(get_provider=AsyncMock(return_value=provider)),
            ),
            patch.object(
                nodes_routes,
                "resolve_provider_runtime_async",
                AsyncMock(return_value=SimpleNamespace(worker_url="http://worker.invalid")),
            ),
            patch.object(
                nodes_routes, "get_http_client", lambda: SimpleNamespace(get=get)
            ),
        ):
            for _ in range(2):
                response = client.get(
                    "/api/nodes/object_info", params={"provider_id": "p1"}
                )
                assert response.status_code in (502, 504), response.status_code
            assert "p1" not in nodes_routes._object_info_cache, "a failure was cached"

    @pytest.mark.asyncio
    async def test_a_provider_timeout_is_still_a_timeout_error(self, client):
        import httpx

        provider = SimpleNamespace(id="p1", type="remote_comfy", container_config={})

        async def get(url, timeout=None):
            raise httpx.TimeoutException("too slow")

        with (
            patch.object(
                nodes_routes,
                "get_provider_service",
                return_value=SimpleNamespace(get_provider=AsyncMock(return_value=provider)),
            ),
            patch.object(
                nodes_routes,
                "resolve_provider_runtime_async",
                AsyncMock(return_value=SimpleNamespace(worker_url="http://worker.invalid")),
            ),
            patch.object(
                nodes_routes, "get_http_client", lambda: SimpleNamespace(get=get)
            ),
        ):
            with pytest.raises(ProviderTimeoutError):
                await nodes_routes.get_object_info(provider_id="p1")

    def test_invalidation_drops_the_entry(self, client, upstream):
        object_info(client, provider_id="p1")
        nodes_routes.invalidate_object_info_cache("p1")
        assert "p1" not in nodes_routes._object_info_cache
        object_info(client, provider_id="p1")
        assert len(upstream) == 2, len(upstream)

    @pytest.mark.asyncio
    async def test_concurrent_duplicates_cause_one_fetch(self):
        """`/advanced` fetches this twice on first paint. Two concurrent cold
        requests must not become two upstream ComfyUI spin-ups."""
        import asyncio

        started = 0

        def client_factory():
            async def get(url, timeout=None):
                nonlocal started
                started += 1
                await asyncio.sleep(0.05)
                return SimpleNamespace(
                    raise_for_status=lambda: None, json=lambda: SAMPLE_GRAPH
                )

            return SimpleNamespace(get=get)

        provider = SimpleNamespace(id="p1", type="remote_comfy", container_config={})
        with (
            patch.object(
                nodes_routes,
                "get_provider_service",
                return_value=SimpleNamespace(get_provider=AsyncMock(return_value=provider)),
            ),
            patch.object(
                nodes_routes,
                "resolve_provider_runtime_async",
                AsyncMock(return_value=SimpleNamespace(worker_url="http://worker.invalid")),
            ),
            patch.object(nodes_routes, "get_http_client", client_factory),
        ):
            results = await asyncio.gather(
                nodes_routes.get_object_info(provider_id="p1"),
                nodes_routes.get_object_info(provider_id="p1"),
            )

        assert started == 1, f"{started} upstream fetches for two concurrent requests"
        assert results[0] == results[1]
        # And the lock map must not keep the entry alive afterwards.
        assert "p1" not in nodes_routes._object_info_inflight


class TestNodeSchemaDigest:
    def test_every_dropped_node_field_is_named_and_absent(self):
        digest = nodes_routes.node_schema_digest(SAMPLE_GRAPH)
        dropped = {
            "input_order",
            "is_input_list",
            "output_is_list",
            "output_tooltips",
            "output_matchtypes",
            "search_aliases",
            "essentials_category",
            "has_intermediate_output",
            "price_badge",
            "api_node",
            "dev_only",
            "experimental",
            "deprecated",
            "python_module",
            "name",
        }
        for field in dropped:
            assert field not in digest["KSampler"], f"{field} survived the digest"
            assert field not in nodes_routes._OBJECT_INFO_NODE_FIELDS

    def test_the_fields_the_frontend_binds_survive(self):
        """`NodeRegistry.js` reads `category`, `getNodeDef` + `ComfyNode.jsx`
        read `display_name`, `NodeSidebar.jsx:79` reads `description`, and
        `getInputs`/`getOutputs` read `input.required`, `input.optional`,
        `output` and `output_name`."""
        digest = nodes_routes.node_schema_digest(SAMPLE_GRAPH)
        node = digest["KSampler"]
        assert node["display_name"] == "KSampler"
        assert node["description"] == "The main sampler."
        assert node["category"] == "sampling"
        assert node["output"] == ["LATENT"]
        assert node["output_name"] == ["LATENT"]
        assert set(node["input"]) == {"required"}

    def test_the_spec_shape_is_preserved_so_the_control_type_does_not_change(self):
        """`ComfyNode.jsx` branches on `inputDef[0]`: an array there means a
        dropdown, a known primitive means a number/text/checkbox input. Flattening
        a spec would silently turn every dropdown into something else."""
        digest = nodes_routes.node_schema_digest(SAMPLE_GRAPH)
        required = digest["KSampler"]["input"]["required"]

        assert required["model"] == ["MODEL"]
        assert required["bare"] == ["STRING"]
        assert required["seed"] == ["INT", {"default": 0}]
        assert required["sampler_name"] == [["euler", "heun"]]
        assert required["denoise"] == {"default": 1.0}

    def test_optional_is_kept_and_absent_sections_are_not_invented(self):
        graph = {
            "N": {
                "input": {"required": {"a": ["INT", {"default": 1}]}},
                "output": [],
                "output_name": [],
                "display_name": "N",
                "description": "",
                "category": "c",
            }
        }
        digest = nodes_routes.node_schema_digest(graph)
        assert "optional" not in digest["N"]["input"]
        assert digest["N"]["input"]["required"]["a"] == ["INT", {"default": 1}]

    def test_an_error_envelope_is_passed_through_not_flattened(self):
        """`useObjectInfo.js` treats `status: "error"` as a failure rather than a
        graph. A digest that dropped it would turn a diagnosable 200 into an
        empty palette."""
        envelope = {
            "status": "error",
            "success": False,
            "message": "Failed to query ComfyUI",
        }
        assert nodes_routes.node_schema_digest(envelope) == envelope

    def test_an_empty_payload_is_passed_through(self):
        assert nodes_routes.node_schema_digest({}) == {}