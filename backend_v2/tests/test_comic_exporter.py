import os
import zipfile
from core.entities import StoryChapter
from services.comic_exporter import (
    _assemble_and_write_outputs,
    _write_html_reader,
    split_chapter_into_panels,
)


def test_write_html_reader_handles_empty_page_paths(tmp_path):
    out_dir = str(tmp_path)
    manifest = {"title": "Test Comic", "chapter_number": 1}
    html_path = _write_html_reader(out_dir, [], manifest)

    assert os.path.exists(html_path)
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "<span id=\"pageTotal\">0</span>" in content
    assert "<div id=\"reader\">" in content


def test_write_html_reader_with_pages(tmp_path):
    out_dir = str(tmp_path)
    page1 = os.path.join(out_dir, "page_001.png")
    with open(page1, "w") as f:
        f.write("mock")

    manifest = {"title": "Test Chapter", "chapter_number": 1}
    html_path = _write_html_reader(out_dir, [page1], manifest)

    assert os.path.exists(html_path)
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "page_001.png" in content
    assert "<span id=\"pageTotal\">1</span>" in content


def test_assemble_and_write_outputs(tmp_path):
    out_dir = str(tmp_path)
    chapter = StoryChapter(
        id="ch_1",
        story_id="st_1",
        title="Chapter One",
        chapter_number=1,
        content="Panel one text.\n\nPanel two text.",
    )
    panels = split_chapter_into_panels(chapter, {})
    assert len(panels) >= 1

    page_paths, manifest, cbz_path, html_path = _assemble_and_write_outputs(
        panels=panels,
        output_dir=out_dir,
        chapter=chapter,
        story_id="st_1",
        user_id="user_1",
    )

    assert len(page_paths) == len(panels)
    assert os.path.exists(cbz_path)
    assert os.path.exists(html_path)
    assert os.path.exists(os.path.join(out_dir, "comic.yaml"))

    # Verify CBZ archive contents
    with zipfile.ZipFile(cbz_path, "r") as zf:
        namelist = zf.namelist()
        assert "comic.yaml" in namelist
        assert len(namelist) >= 2  # At least comic.yaml and one page
