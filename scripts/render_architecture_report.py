import argparse
import os
import re
import tempfile
from pathlib import Path
from typing import List, Tuple

import pymupdf


_PAGE_BREAK = "<!-- pagebreak -->"
_CODE_SPAN = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.*?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")

Section = Tuple[str, str]
PageContent = Tuple[str, str, List[Section], bool]


def _plain_text(markdown: str) -> str:
    text = _LINK.sub(r"\1", markdown)
    text = _CODE_SPAN.sub(r"\1", text)
    text = _BOLD.sub(r"\1", text)
    text = _ITALIC.sub(r"\1", text)
    return (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("—", " - ")
        .replace("–", "-")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("…", "...")
    )


def _parse_markdown(markdown: str) -> List[PageContent]:
    pages: List[PageContent] = []
    for source_page in markdown.split(_PAGE_BREAK):
        title = ""
        lead: List[str] = []
        sections: List[Section] = []
        section_title = ""
        section_paragraphs: List[str] = []
        paragraph: List[str] = []
        in_code = False
        is_mermaid = False
        skip_mermaid = False

        def flush_paragraph() -> None:
            if not paragraph:
                return
            text = " ".join(part.strip() for part in paragraph).strip()
            if text:
                if section_title:
                    section_paragraphs.append(text)
                else:
                    lead.append(text)
            paragraph.clear()

        def flush_section() -> None:
            nonlocal section_paragraphs
            flush_paragraph()
            if section_title:
                sections.append((section_title, "\n\n".join(section_paragraphs)))
            section_paragraphs = []

        for raw_line in source_page.splitlines():
            line = raw_line.strip()
            if line.startswith("```"):
                flush_paragraph()
                if not in_code:
                    in_code = True
                    skip_mermaid = line[3:].strip().lower() == "mermaid"
                    is_mermaid = is_mermaid or skip_mermaid
                else:
                    in_code = False
                    skip_mermaid = False
                continue
            if in_code:
                if not skip_mermaid and line:
                    paragraph.append(line)
                continue
            if line.startswith("# "):
                flush_section()
                title = _plain_text(line[2:].strip())
            elif re.match(r"^#{2,6}\s+", line):
                flush_section()
                section_title = _plain_text(re.sub(r"^#{2,6}\s+", "", line))
            elif not line:
                flush_paragraph()
            elif line.startswith("> "):
                paragraph.append(line[2:].strip())
            elif line.startswith(("- ", "* ")):
                paragraph.append("- " + line[2:].strip())
            elif line.startswith("|"):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if cells and all(set(cell) <= {"-", ":"} for cell in cells):
                    continue
                paragraph.append(" — ".join(cells))
            else:
                paragraph.append(line)

        flush_section()
        if title:
            pages.append((title, "\n\n".join(lead), sections, is_mermaid))
    if not pages:
        raise ValueError("Markdown must contain at least one # page heading")
    if any(not title or not (lead or sections) for title, lead, sections, _ in pages):
        raise ValueError("Each page needs a title and at least one content block")
    return pages


def _draw_arrow(
    page: pymupdf.Page,
    start: Tuple[float, float],
    end: Tuple[float, float],
    color: Tuple[float, float, float] = (0.34, 0.45, 0.57),
    dashed: bool = False,
) -> None:
    page.draw_line(start, end, color=color, width=1.1, dashes="[3 2]" if dashed else None)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if abs(dx) > abs(dy):
        direction = 1 if dx > 0 else -1
        points = [
            end,
            (end[0] - 5 * direction, end[1] - 3),
            (end[0] - 5 * direction, end[1] + 3),
        ]
    else:
        direction = 1 if dy > 0 else -1
        points = [
            end,
            (end[0] - 3, end[1] - 5 * direction),
            (end[0] + 3, end[1] - 5 * direction),
        ]
    page.draw_polyline(points + [points[0]], color=color, fill=color, width=0.5)


def _center_x(rect: pymupdf.Rect) -> float:
    return (rect.x0 + rect.x1) / 2


def _center_y(rect: pymupdf.Rect) -> float:
    return (rect.y0 + rect.y1) / 2


def _draw_node(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    title: str,
    detail: str = "",
    fill: Tuple[float, float, float] = (0.95, 0.97, 0.99),
    stroke: Tuple[float, float, float] = (0.72, 0.79, 0.86),
    text: Tuple[float, float, float] = (0.10, 0.19, 0.31),
) -> None:
    page.draw_rect(rect, color=stroke, fill=fill, width=0.9, radius=0.02)
    title_size = 8.5
    title_width = pymupdf.get_text_length(title, fontname="hebo", fontsize=title_size)
    title_x = (rect.x0 + rect.x1 - title_width) / 2
    if detail:
        page.insert_text(
            (title_x, rect.y0 + 17),
            title,
            fontname="hebo",
            fontsize=title_size,
            color=text,
        )
        page.insert_textbox(
            pymupdf.Rect(rect.x0 + 5, rect.y0 + 20, rect.x1 - 5, rect.y1 - 3),
            detail,
            fontname="helv",
            fontsize=7,
            align=1,
            color=(0.32, 0.41, 0.51),
        )
    else:
        page.insert_text(
            (title_x, rect.y0 + 16),
            title,
            fontname="hebo",
            fontsize=title_size,
            color=text,
        )


def _draw_system_map(page: pymupdf.Page) -> None:
    muted = (0.38, 0.47, 0.56)
    center_x = 297.5
    node_width = 148
    positions = [24, (595 - node_width) / 2, 595 - 24 - node_width]
    box_height = 44

    start = pymupdf.Rect(center_x - 37, 145, center_x + 37, 169)
    context = pymupdf.Rect(center_x - 83, 184, center_x + 83, 226)
    detectives = [
        pymupdf.Rect(x, 265, x + node_width, 265 + box_height) for x in positions
    ]
    aggregator = pymupdf.Rect(center_x - 91, 346, center_x + 91, 390)
    dispatch = pymupdf.Rect(center_x - 91, 424, center_x + 91, 464)
    judges = [
        pymupdf.Rect(x, 501, x + node_width, 501 + box_height) for x in positions
    ]
    chief = pymupdf.Rect(center_x - 91, 580, center_x + 91, 624)
    end = pymupdf.Rect(center_x - 37, 649, center_x + 37, 673)
    error = pymupdf.Rect(428, 348, 571, 392)

    _draw_arrow(page, (center_x, start.y1), (center_x, context.y0), muted)
    _draw_arrow(page, (center_x, context.y1), (center_x, 249), muted)
    page.draw_line((_center_x(detectives[0]), 249), (_center_x(detectives[2]), 249), color=muted, width=1.1)
    for detective in detectives:
        _draw_arrow(page, (_center_x(detective), 249), (_center_x(detective), detective.y0), muted)
    page.draw_line((_center_x(detectives[0]), 326), (_center_x(detectives[2]), 326), color=muted, width=1.1)
    _draw_arrow(page, (_center_x(detectives[0]), detectives[0].y1), (_center_x(detectives[0]), 326), muted)
    _draw_arrow(page, (_center_x(detectives[2]), detectives[2].y1), (_center_x(detectives[2]), 326), muted)
    _draw_arrow(page, (center_x, 326), (center_x, aggregator.y0), muted)
    _draw_arrow(page, (center_x, aggregator.y1), (center_x, dispatch.y0), muted)
    _draw_arrow(page, (aggregator.x1, _center_y(aggregator)), (error.x0, _center_y(error)), muted, True)
    _draw_arrow(page, (center_x, dispatch.y1), (center_x, 485), muted)
    page.draw_line((_center_x(judges[0]), 485), (_center_x(judges[2]), 485), color=muted, width=1.1)
    for judge in judges:
        _draw_arrow(page, (_center_x(judge), 485), (_center_x(judge), judge.y0), muted)
    page.draw_line((_center_x(judges[0]), 562), (_center_x(judges[2]), 562), color=muted, width=1.1)
    _draw_arrow(page, (_center_x(judges[0]), judges[0].y1), (_center_x(judges[0]), 562), muted)
    _draw_arrow(page, (_center_x(judges[2]), judges[2].y1), (_center_x(judges[2]), 562), muted)
    _draw_arrow(page, (center_x, 562), (center_x, chief.y0), muted)
    _draw_arrow(page, (center_x, chief.y1), (center_x, end.y0), muted)

    _draw_node(page, start, "START", fill=(0.93, 0.96, 0.99))
    _draw_node(page, context, "ContextBuilder", "Load and validate rubric")
    detective_titles = [
        ("RepoInvestigator", "AST + Git evidence"),
        ("DocAnalyst", "Report text + paths"),
        ("VisionInspector", "Optional PDF images"),
    ]
    for rect, (title, detail) in zip(detectives, detective_titles):
        _draw_node(page, rect, title, detail, fill=(0.91, 0.96, 0.99))
    _draw_node(page, aggregator, "EvidenceAggregator", "Cross-reference and reconcile")
    _draw_node(page, dispatch, "JudicialDispatch", "Start independent opinions")
    judge_titles = [
        ("Prosecutor", "Adversarial"),
        ("Defense", "Effort-aware"),
        ("TechLead", "Pragmatic"),
    ]
    judge_fills = [
        (0.99, 0.94, 0.92),
        (0.94, 0.96, 0.99),
        (0.92, 0.97, 0.94),
    ]
    for rect, (title, detail), fill in zip(judges, judge_titles, judge_fills):
        _draw_node(page, rect, title, detail, fill=fill)
    _draw_node(page, chief, "ChiefJustice", "Grounding, rules, score, dissent", fill=(0.98, 0.95, 0.86))
    _draw_node(page, end, "END", fill=(0.93, 0.96, 0.99))
    _draw_node(page, error, "ErrorReport", "Manifest unavailable", fill=(0.99, 0.93, 0.92))
    page.insert_text(
        (center_x + 96, 335),
        "conditional route",
        fontname="helv",
        fontsize=6.5,
        color=(0.42, 0.49, 0.57),
    )


def _draw_header(page: pymupdf.Page, title: str, page_index: int) -> None:
    navy = (0.08, 0.16, 0.29)
    page.draw_rect(pymupdf.Rect(0, 0, 595, 127), color=None, fill=navy)
    page.insert_text(
        (38, 35),
        f"ARCHITECTURE FIELD GUIDE  /  {page_index:02d}",
        fontname="hebo",
        fontsize=8,
        color=(0.62, 0.79, 0.91),
    )
    page.insert_textbox(
        pymupdf.Rect(38, 50, 555, 111),
        title,
        fontname="hebo",
        fontsize=22,
        lineheight=1.12,
        color=(1, 1, 1),
    )


def _draw_footer(page: pymupdf.Page, page_number: int, total: int) -> None:
    border = (0.84, 0.88, 0.92)
    muted = (0.38, 0.45, 0.53)
    page.draw_line((38, 807), (557, 807), color=border, width=0.7)
    page.insert_text(
        (40, 825),
        "AUTOMATON AUDITOR  |  EVIDENCE BEFORE OPINION",
        fontname="hebo",
        fontsize=7,
        color=muted,
    )
    label = f"{page_number} / {total}"
    page.insert_text(
        (555 - pymupdf.get_text_length(label, fontname="helv", fontsize=7.5), 825),
        label,
        fontname="helv",
        fontsize=7.5,
        color=muted,
    )


def _draw_card(
    page: pymupdf.Page,
    heading: str,
    body: str,
    y: float,
    height: float,
    font_size: float = 9.2,
) -> None:
    navy = (0.08, 0.16, 0.29)
    ink = (0.13, 0.19, 0.26)
    border = (0.83, 0.87, 0.91)
    fill = (0.97, 0.98, 0.99)
    accent = (0.13, 0.43, 0.62)
    card = pymupdf.Rect(38, y, 557, y + height)
    page.draw_rect(card, color=border, fill=fill, width=0.8, radius=0.02)
    page.draw_rect(
        pymupdf.Rect(card.x0, card.y0, card.x0 + 4, card.y1),
        color=None,
        fill=accent,
    )
    page.insert_textbox(
        pymupdf.Rect(card.x0 + 17, card.y0 + 13, card.x1 - 15, card.y0 + 34),
        heading,
        fontname="hebo",
        fontsize=11,
        color=navy,
    )
    content_rect = pymupdf.Rect(
        card.x0 + 17, card.y0 + 42, card.x1 - 15, card.y1 - 12
    )
    current_size = font_size
    remaining = -1
    while current_size >= 7.6 and remaining < 0:
        remaining = page.insert_textbox(
            content_rect,
            _plain_text(body),
            fontname="helv",
            fontsize=current_size,
            lineheight=1.28,
            color=ink,
        )
        if remaining < 0:
            current_size = round(current_size - 0.2, 1)
    if remaining < 0:
        raise ValueError(f"Content does not fit in the PDF section: {heading}")


def _draw_cover(
    document: pymupdf.Document,
    title: str,
    lead: str,
    sections: List[Section],
    total: int,
) -> None:
    page = document.new_page(width=595, height=842)
    navy = (0.08, 0.16, 0.29)
    accent = (0.20, 0.69, 0.70)
    page.draw_rect(page.rect, color=None, fill=(0.985, 0.99, 0.995))
    page.draw_rect(pymupdf.Rect(0, 0, 595, 380), color=None, fill=navy)
    page.draw_rect(pymupdf.Rect(38, 49, 69, 53), color=None, fill=accent)
    page.insert_text(
        (38, 40),
        "WEEK TWO  /  TECHNICAL CHALLENGE",
        fontname="hebo",
        fontsize=8,
        color=(0.69, 0.81, 0.92),
    )
    page.insert_textbox(
        pymupdf.Rect(38, 99, 500, 198),
        title,
        fontname="hebo",
        fontsize=37,
        lineheight=1.0,
        color=(1, 1, 1),
    )
    page.insert_textbox(
        pymupdf.Rect(40, 215, 535, 296),
        lead,
        fontname="helv",
        fontsize=14,
        lineheight=1.25,
        color=(0.83, 0.89, 0.95),
    )
    page.draw_circle((493, 91), 36, color=(0.25, 0.49, 0.62), width=1.4)
    page.draw_circle((493, 91), 23, color=accent, width=1.2)
    page.draw_circle((493, 91), 9, color=(0.98, 0.67, 0.35), fill=(0.98, 0.67, 0.35))

    cards = [
        ("PARALLEL", "Independent branches gather evidence without serial bottlenecks."),
        ("GROUNDED", "Citations and rules constrain persuasive but unsupported opinions."),
        ("HUMAN-LED", "People decide what to change; the auditor never rewrites itself."),
    ]
    card_y = 420
    card_width = 163
    for index, (label, detail) in enumerate(cards):
        x = 38 + index * (card_width + 13)
        card = pymupdf.Rect(x, card_y, x + card_width, card_y + 119)
        page.draw_rect(card, color=(0.84, 0.88, 0.92), fill=(1, 1, 1), width=0.8, radius=0.025)
        page.insert_text(
            (x + 13, card_y + 25),
            label,
            fontname="hebo",
            fontsize=8,
            color=(0.13, 0.43, 0.62),
        )
        page.insert_textbox(
            pymupdf.Rect(x + 13, card_y + 38, x + card_width - 12, card_y + 108),
            detail,
            fontname="helv",
            fontsize=8.5,
            lineheight=1.25,
            color=(0.16, 0.22, 0.29),
        )

    page.insert_text(
        (40, 625),
        "Evidence before opinion.",
        fontname="hebo",
        fontsize=18,
        color=(0.08, 0.16, 0.29),
    )
    page.insert_textbox(
        pymupdf.Rect(40, 640, 545, 696),
        "A practical guide to what the system does, how it reaches a score, and where human judgment remains essential.",
        fontname="helv",
        fontsize=10,
        lineheight=1.3,
        color=(0.34, 0.41, 0.49),
    )
    _draw_footer(page, 1, total)


def _draw_content_page(
    document: pymupdf.Document,
    title: str,
    lead: str,
    sections: List[Section],
    has_diagram: bool,
    page_number: int,
    total: int,
) -> None:
    page = document.new_page(width=595, height=842)
    page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
    _draw_header(page, title, page_number - 1)
    if has_diagram:
        _draw_system_map(page)
        if sections:
            heading, body = sections[0]
            _draw_card(page, heading, body, 691, 99, font_size=8.2)
        _draw_footer(page, page_number, total)
        return

    top = 151
    bottom = 788
    gap = 13
    available = bottom - top - gap * (len(sections) - 1)
    weights = [
        max(1.0, len(body) / 420 + body.count("\n\n") * 0.4)
        for _, body in sections
    ]
    total_weight = sum(weights)
    y = top
    for (heading, body), weight in zip(sections, weights):
        height = available * weight / total_weight
        _draw_card(page, heading, body, y, height)
        y += height + gap
    _draw_footer(page, page_number, total)


def build_report(pdf_path: Path, source_path: Path) -> None:
    if not source_path.is_file():
        raise FileNotFoundError(f"Architecture Markdown not found: {source_path}")
    pages = _parse_markdown(source_path.read_text(encoding="utf-8"))
    title, lead, sections, _ = pages[0]
    document = pymupdf.open()
    document.set_metadata(
        {
            "title": title + " - Architecture Field Guide",
            "author": "Automaton Auditor",
            "subject": "Evidence-grounded architecture and audit workflow",
            "keywords": "LangGraph, architecture, evidence, technical challenge",
        }
    )
    _draw_cover(document, title, lead, sections, len(pages))
    for page_number, (page_title, page_lead, page_sections, has_diagram) in enumerate(
        pages[1:], start=2
    ):
        _draw_content_page(
            document,
            page_title,
            page_lead,
            page_sections,
            has_diagram,
            page_number,
            len(pages),
        )

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            prefix="architecture_report_",
            dir=pdf_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        document.save(temporary_path, garbage=4, deflate=True)
    finally:
        document.close()
    try:
        os.replace(temporary_path, pdf_path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Render the complete architecture Markdown as a polished PDF."
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=repository / "reports" / "final_report.pdf",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=repository / "reports" / "architecture_report.md",
    )
    arguments = parser.parse_args()
    build_report(arguments.pdf.resolve(), arguments.markdown.resolve())
    print(arguments.pdf.resolve())


if __name__ == "__main__":
    main()
