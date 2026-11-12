import sys
import types

from src.tools.doc_tools import Chunk, ingest_pdf


def test_ingest_pdf_falls_back_to_pymupdf_when_docling_fails(
    tmp_path, monkeypatch
):
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"placeholder")

    class BrokenConverter:
        def __init__(self):
            raise RuntimeError("docling unavailable")

    docling_package = types.ModuleType("docling")
    docling_package.__path__ = []
    converter_module = types.ModuleType("docling.document_converter")
    converter_module.DocumentConverter = BrokenConverter
    monkeypatch.setitem(sys.modules, "docling", docling_package)
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter_module)

    class Page:
        def get_text(self, mode):
            return "Architecture\nState Synchronization uses reducers."

    class Document:
        def __enter__(self):
            return [Page()]

        def __exit__(self, *args):
            return False

    monkeypatch.setitem(sys.modules, "fitz", types.SimpleNamespace(open=lambda path: Document()))
    chunks = ingest_pdf(str(pdf_path))
    assert chunks == [
        Chunk(index=0, section="Preamble", text="Architecture State Synchronization uses reducers.")
    ]
