import pytest
from unittest.mock import MagicMock
from api.routes.files import list_files_endpoint


@pytest.mark.asyncio
async def test_list_files_unpacks_multiple_versions_for_embeddings():
    # Mock model service
    mock_service = MagicMock()
    mock_service.list_models_page.return_value = (
        [
            {
                "id": "model_1",
                "civitai_model_id": 1302719,
                "name": "Lazy Embeddings Pack",
                "type": "TextualInversion",
                "directory": "embeddings",
                "versions": [
                    {
                        "id": "v1",
                        "name": "lazypos",
                        "is_enabled": True,
                        "file": {
                            "filename": "_lazy_embeddings_for_all_illus_lazypos_1833157.safetensors",
                            "size_kb": 250,
                        },
                    },
                    {
                        "id": "v2",
                        "name": "lazyneg",
                        "is_enabled": True,
                        "file": {
                            "filename": "_lazy_embeddings_for_all_illus_lazyneg_1833160.safetensors",
                            "size_kb": 250,
                        },
                    },
                    {
                        "id": "v3",
                        "name": "lazyhand",
                        "is_enabled": True,
                        "file": {
                            "filename": "_lazy_embeddings_for_all_illus_lazyhand_1833165.safetensors",
                            "size_kb": 250,
                        },
                    },
                ],
            }
        ],
        1,
    )

    response = await list_files_endpoint(
        directory="models/embeddings",
        tags=None,
        search=None,
        model_service=mock_service,
    )

    files = response["files"]
    assert len(files) == 3

    names = [f["name"] for f in files]
    assert "_lazy_embeddings_for_all_illus_lazypos_1833157.safetensors" in names
    assert "_lazy_embeddings_for_all_illus_lazyneg_1833160.safetensors" in names
    assert "_lazy_embeddings_for_all_illus_lazyhand_1833165.safetensors" in names

    display_names = [f["display_name"] for f in files]
    assert "lazypos" in display_names
    assert "lazyneg" in display_names
    assert "lazyhand" in display_names
