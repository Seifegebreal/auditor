import math
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel


PATH_RE = re.compile(
    r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.(?:py|md|json|toml|pdf|txt|yml|yaml)"
)


class Chunk(BaseModel):
    index: int
    section: str
    text: str


def ingest_pdf(path: str, max_chars: int = 1200) -> List[Chunk]:
    if max_chars < 1:
        raise ValueError("max_chars must be a positive integer")
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF report not found: {pdf_path}")
    try:
        from docling.document_converter import DocumentConverter

        document_text = (
            DocumentConverter()
            .convert(str(pdf_path))
            .document.export_to_markdown()
        )
    except Exception as docling_error:
        try:
            import fitz

            with fitz.open(pdf_path) as document:
                document_text = "\n".join(
                    page.get_text("text") for page in document
                )
        except Exception as pymupdf_error:
            raise RuntimeError(
                "PDF extraction failed with both Docling and PyMuPDF: "
                f"Docling: {docling_error}; PyMuPDF: {pymupdf_error}"
            ) from pymupdf_error

    chunks: List[Chunk] = []
    section = "Preamble"
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer.strip():
            chunks.append(
                Chunk(index=len(chunks), section=section, text=buffer.strip())
            )
        buffer = ""

    for line in document_text.splitlines():
        if line.lstrip().startswith("#"):
            flush()
            section = line.lstrip("# ").strip() or "Untitled section"
            continue
        buffer += line + " "
        if len(buffer) >= max_chars:
            flush()
    flush()
    return chunks


def query_chunks(chunks: List[Chunk], query: str, k: int = 3) -> List[Chunk]:
    if k < 0:
        raise ValueError("k must not be negative")
    terms = [term for term in re.split(r"[^a-z0-9]+", query.lower()) if term]

    def score(chunk: Chunk) -> float:
        words = Counter(re.split(r"[^a-z0-9]+", chunk.text.lower()))
        return sum(math.log1p(words[term]) for term in terms)

    ranked = sorted(chunks, key=score, reverse=True)[:k]
    return [chunk for chunk in ranked if score(chunk) > 0]


def term_context(chunks: List[Chunk], term: str) -> Dict[str, object]:
    if not term.strip():
        raise ValueError("term must not be empty")
    hits = [
        chunk
        for chunk in chunks
        if re.search(rf"\b{re.escape(term)}\b", chunk.text, re.IGNORECASE)
    ]
    summary_only = bool(hits) and all(
        re.search(r"summary|introduction|abstract", chunk.section, re.IGNORECASE)
        for chunk in hits
    )
    return {
        "term": term,
        "hits": len(hits),
        "sections": sorted({chunk.section for chunk in hits}),
        "only_in_summary": summary_only,
        "snippets": [chunk.text[:300] for chunk in hits[:2]],
    }


def extract_images_from_pdf(path: str, out_dir: str) -> List[str]:
    import fitz

    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF report not found: {pdf_path}")
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    saved: List[str] = []

    with fitz.open(pdf_path) as document:
        for page_number, page in enumerate(document, start=1):
            images = page.get_images(full=True)
            if images:
                for image_number, image in enumerate(images, start=1):
                    pixmap = fitz.Pixmap(document, image[0])
                    if pixmap.n - pixmap.alpha >= 4:
                        pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
                    target = destination / f"p{page_number}_{image_number}.png"
                    pixmap.save(target)
                    saved.append(str(target))
            elif page.get_drawings():
                target = destination / f"p{page_number}_vector.png"
                page.get_pixmap(dpi=110, alpha=False).save(target)
                saved.append(str(target))
    return saved
