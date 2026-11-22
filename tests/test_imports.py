"""DOCX and MOBI book extraction tests."""

import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app import main


def make_docx() -> bytes:
    from docx import Document

    document = Document()
    document.add_heading("The First Chapter", level=1)
    document.add_paragraph("The first chapter has readable body text.")
    document.add_heading("A smaller section", level=2)
    document.add_paragraph("The section continues the story.")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def make_epub() -> bytes:
    container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>'''
    content = b'''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>A Converted Chapter</h1><p>This is enough readable text for the MOBI conversion test.</p>
</body></html>'''
    package = b'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Test</dc:title></metadata>
  <manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="chapter"/></spine>
</package>'''
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", package)
        archive.writestr("OEBPS/chapter.xhtml", content)
    return output.getvalue()


def make_epub_with_navigation() -> bytes:
    container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>'''
    navigation = b'''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<p>Table of Contents</p>
<p><a href="chapter.xhtml">A Better Chapter</a></p>
<p><a href="chapter.xhtml#part-1">Part 1</a></p>
<p><a href="chapter.xhtml#part-2">Part 2</a></p>
<p><a href="chapter.xhtml#part-3">Part 3</a></p>
</body></html>'''
    chapter = b'''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Unknown</title></head><body>
<h2>1</h2><p>A Better Chapter</p><p>This is the actual chapter body and it should be retained for narration.</p>
</body></html>'''
    package = b'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Test</dc:title></metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="navigation" href="navigation.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx"><itemref idref="navigation"/><itemref idref="chapter"/></spine>
</package>'''
    toc = b'''<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap><navPoint id="chapter"><navLabel><text>A Better Chapter</text></navLabel><content src="chapter.xhtml"/></navPoint></navMap>
</ncx>'''
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", package)
        archive.writestr("OEBPS/toc.ncx", toc)
        archive.writestr("OEBPS/navigation.xhtml", navigation)
        archive.writestr("OEBPS/chapter.xhtml", chapter)
    return output.getvalue()


def test_extracts_docx_headings_and_body_text():
    chapters = main.extract(make_docx(), ".docx")

    assert [chapter["title"] for chapter in chapters] == ["The First Chapter", "A smaller section"]
    assert "readable body text" in chapters[0]["text"]
    assert "continues the story" in chapters[1]["text"]


def test_mobi_requires_calibre_when_converter_is_missing(monkeypatch):
    monkeypatch.setattr(main.shutil, "which", lambda _: None)

    with pytest.raises(HTTPException) as error:
        main.extract(b"not a real mobi", ".mobi")

    assert error.value.status_code == 503
    assert "Calibre" in str(error.value.detail)


def test_mobi_conversion_reuses_epub_extraction(monkeypatch):
    epub_data = make_epub()
    monkeypatch.setattr(main.shutil, "which", lambda _: "ebook-convert")

    def fake_run(args, **kwargs):
        Path(args[-1]).write_bytes(epub_data)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    chapters = main.extract(b"mobi bytes", ".mobi")

    assert chapters[0]["title"] == "A Converted Chapter"
    assert "enough readable text" in chapters[0]["text"]


def test_epub_uses_navigation_titles_and_omits_navigation_pages():
    chapters = main.extract(make_epub_with_navigation(), ".epub")

    assert [chapter["title"] for chapter in chapters] == ["A Better Chapter"]
    assert all("Table of Contents" not in chapter["text"] for chapter in chapters)
    assert "actual chapter body" in chapters[0]["text"]
