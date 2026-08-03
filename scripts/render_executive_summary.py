"""Render the evidence-backed executive Markdown brief as a one-page PDF."""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

ROOT = Path(__file__).parents[1]
DEFAULT_SOURCE = ROOT / "executive_summary.md"
DEFAULT_OUTPUT = ROOT / "executive_summary.pdf"
NAVY = colors.HexColor("#12314B")
GREEN = colors.HexColor("#159A8C")
SLATE = colors.HexColor("#425466")
PALE = colors.HexColor("#EAF5F3")


def _styles() -> dict[str, ParagraphStyle]:
    base = {
        "fontName": "Helvetica",
        "textColor": SLATE,
        "leading": 10.2,
        "fontSize": 8.1,
        "spaceAfter": 2.2,
    }

    def style(name: str, **overrides: object) -> ParagraphStyle:
        return ParagraphStyle(name, **{**base, **overrides})

    return {
        "title": style(
            "Title", fontName="Helvetica-Bold", fontSize=18,
            leading=20, textColor=NAVY, alignment=TA_CENTER, spaceAfter=4
        ),
        "h2": style(
            "Heading2", fontName="Helvetica-Bold", fontSize=10.2,
            leading=11.5, textColor=NAVY, spaceBefore=3.5, spaceAfter=2
        ),
        "body": style("Body"),
        "bullet": style(
            "Bullet", leftIndent=10, firstLineIndent=-6,
            bulletIndent=3, spaceAfter=1.7
        ),
        "source": style(
            "Source", fontSize=6.5, leading=7.6, spaceAfter=1
        ),
        "decision": style(
            "Decision", fontName="Helvetica-Bold", fontSize=8.8,
            leading=11, textColor=NAVY, backColor=PALE, borderColor=GREEN,
            borderWidth=0.6, borderPadding=5, spaceAfter=4
        ),
    }


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    return re.sub(
        r"`(.+?)`",
        r'<font name="Courier" size="6.8">\1</font>',
        escaped,
    )


def _paragraph(
    line: str,
    style_name: str,
    styles: dict[str, ParagraphStyle],
) -> Paragraph:
    if line.startswith("- "):
        return Paragraph(_inline(line[2:]), styles[style_name], bulletText="•")
    return Paragraph(_inline(line), styles[style_name])


def _unwrap(markdown: str) -> list[str]:
    """Join soft-wrapped continuation lines back into one logical line each."""
    lines: list[str] = []
    for raw_line in markdown.splitlines():
        stripped = raw_line.strip()
        starts_block = not stripped or stripped.startswith(("#", "- "))
        if starts_block or not lines:
            lines.append(stripped)
        else:
            lines[-1] = f"{lines[-1]} {stripped}"
    return lines


def _story(markdown: str) -> list[object]:
    styles = _styles()
    story: list[object] = []
    in_sources = False
    for line in _unwrap(markdown):
        if not line:
            story.append(Spacer(1, 1.2))
        elif line.startswith("# "):
            story.append(Paragraph(_inline(line[2:]), styles["title"]))
            story.append(HRFlowable(color=GREEN, thickness=1.2, spaceAfter=3))
        elif line.startswith("## "):
            in_sources = line == "## Source register"
            story.append(Paragraph(_inline(line[3:]), styles["h2"]))
        elif line.startswith("**Decision:**"):
            story.append(_paragraph(line, "decision", styles))
        elif line.startswith("- "):
            style = "source" if in_sources else "bullet"
            story.append(_paragraph(line, style, styles))
        else:
            style = "source" if in_sources else "body"
            story.append(_paragraph(line, style, styles))
    return story


def _footer(canvas: object, document: object) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D7E1E8"))
    canvas.line(18 * mm, 10 * mm, 192 * mm, 10 * mm)
    canvas.setFont("Helvetica", 6.5)
    canvas.setFillColor(SLATE)
    canvas.drawString(18 * mm, 6.5 * mm, "AfyaPlus leadership evidence brief")
    canvas.drawRightString(
        192 * mm,
        6.5 * mm,
        f"Page {document.page}",
    )
    canvas.restoreState()


def render(source: Path, output: Path) -> None:
    markdown = source.read_text(encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=11 * mm,
        bottomMargin=13 * mm,
        title="AfyaPlus Executive Evidence Brief",
        author="AfyaPlus",
    )
    document.build(_story(markdown), onFirstPage=_footer, onLaterPages=_footer)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    render(args.source.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
