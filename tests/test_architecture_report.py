import pymupdf

from scripts.render_architecture_report import build_report


def test_architecture_report_renderer_preserves_markdown_and_is_idempotent(tmp_path):
    pdf_path = tmp_path / "report.pdf"
    source_path = tmp_path / "architecture.md"
    source_path.write_text(
        "# Architecture guide\n\nAn implementation-grounded overview.\n\n"
        "## Executive briefing\n\nThe full report explains the design.\n\n"
        "<!-- pagebreak -->\n"
        "# System map\n\n"
        "```mermaid\nflowchart TD\n  A --> B\n```\n\n"
        "### Fan-In / Fan-Out\n\nParallel evidence reaches an aggregator.\n",
        encoding="utf-8",
    )

    build_report(pdf_path, source_path)
    first_build = pymupdf.open(pdf_path)
    assert len(first_build) == 2
    assert "Architecture guide" in first_build[0].get_text()
    assert "1 / 2" in first_build[0].get_text()
    assert "Fan-In / Fan-Out" in first_build[1].get_text()
    assert "2 / 2" in first_build[1].get_text()
    first_build.close()

    build_report(pdf_path, source_path)
    second_build = pymupdf.open(pdf_path)
    assert len(second_build) == 2
    assert "1 / 2" in second_build[0].get_text()
    assert "2 / 2" in second_build[1].get_text()
    second_build.close()
