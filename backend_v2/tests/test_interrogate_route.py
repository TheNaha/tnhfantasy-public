import io
from fastapi.testclient import TestClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from api.main import app


def test_interrogate_with_embedded_metadata():
    client = TestClient(app)

    # Create an in-memory PNG with embedded Automatic1111/Civitai parameters
    img = Image.new("RGB", (100, 100), color="blue")
    png_info = PngInfo()
    png_info.add_text(
        "parameters",
        "1girl, solo, dark blue hair, smiling, masterpiece, best quality\n"
        "Negative prompt: worst quality, low quality, bad anatomy\n"
        "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 12345, Size: 512x512",
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=png_info)
    buf.seek(0)

    response = client.post(
        "/api/generate/interrogate",
        files={"file": ("test.png", buf.getvalue(), "image/png")},
    )

    assert response.status_code == 200
    data = response.json()
    assert "1girl, solo, dark blue hair, smiling" in data["prompt"]
    assert "worst quality, low quality, bad anatomy" in data["negative_prompt"]
    assert "1girl" in data["tags"]
    assert data["source"] == "embedded_metadata"


def test_interrogate_fallback_heuristics():
    client = TestClient(app)

    # Create an image without metadata
    img = Image.new("RGB", (120, 80), color="green")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)

    response = client.post(
        "/api/generate/interrogate",
        files={"file": ("test.jpg", buf.getvalue(), "image/jpeg")},
    )

    assert response.status_code == 200
    data = response.json()
    assert "landscape" in data["prompt"]
    assert data["source"] == "heuristics"
