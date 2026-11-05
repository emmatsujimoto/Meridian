"""The minimal PDF writer."""

import re

import pytest

from meridian.pdf import Document, Page, escape_text, text_width, wrap_text


def _objects(data: bytes) -> dict[int, bytes]:
    return {
        int(match.group(1)): match.group(2)
        for match in re.finditer(rb"(\d+) 0 obj\n(.*?)\nendobj", data, re.S)
    }


def _xref_offsets(data: bytes) -> list[int]:
    start = int(re.search(rb"startxref\n(\d+)", data).group(1))
    table = data[start:].split(b"trailer")[0].splitlines()[3:]
    return [int(line[:10]) for line in table]


def test_escape_text():
    assert escape_text("a(b)c\\d") == "a\\(b\\)c\\\\d"


def test_escape_text_replaces_non_latin():
    assert escape_text("CO₂ café") == "CO? café"


def test_text_width_scales():
    assert text_width("abcd", 10) == pytest.approx(2 * text_width("ab", 10))
    assert text_width("ab", 20) == pytest.approx(2 * text_width("ab", 10))


def test_page_text_operation():
    page = Page(100, 100)
    page.text(10, 20, "Hello (world)", size=12, style="bold")
    assert page.operations == ["BT /F2 12 Tf 10.00 20.00 Td (Hello \\(world\\)) Tj ET"]


def test_page_text_alignment():
    page = Page(100, 100)
    page.text(50, 10, "abcd", size=10, align="right")
    page.text(50, 10, "abcd", size=10, align="centre")
    right_x = float(page.operations[0].split()[4])
    centre_x = float(page.operations[1].split()[4])
    assert right_x == pytest.approx(50 - text_width("abcd", 10))
    assert centre_x == pytest.approx(50 - text_width("abcd", 10) / 2)


def test_page_text_rejects_bad_options():
    page = Page(100, 100)
    with pytest.raises(ValueError, match="style"):
        page.text(0, 0, "x", style="italic")
    with pytest.raises(ValueError, match="align"):
        page.text(0, 0, "x", align="middle")


def test_page_line_and_rect():
    page = Page(100, 100)
    page.line(0, 0, 10, 10, width=2, rgb=(1, 0, 0))
    page.rect(1, 2, 3, 4, rgb=(0, 0.5, 1))
    assert page.operations == [
        "q 2 w 1.000 0.000 0.000 RG 0.00 0.00 m 10.00 10.00 l S Q",
        "q 0.000 0.500 1.000 rg 1.00 2.00 3.00 4.00 re f Q",
    ]


@pytest.mark.parametrize("rgb", [(1, 0), (2, 0, 0), (-0.1, 0, 0)])
def test_bad_colours(rgb):
    with pytest.raises(ValueError, match="Colours"):
        Page(10, 10).rect(0, 0, 1, 1, rgb=rgb)


def test_negative_rectangle():
    with pytest.raises(ValueError, match="must not be negative"):
        Page(10, 10).rect(0, 0, -1, 1)


def test_document_needs_pages():
    with pytest.raises(ValueError, match="at least one page"):
        Document().to_bytes()


def test_page_size_positive():
    with pytest.raises(ValueError, match="positive"):
        Document().add_page(0, 100)


def test_document_structure():
    document = Document("Test (report)")
    first = document.add_page(595, 842)
    first.text(50, 800, "First page")
    second = document.add_page(842, 595)
    second.rect(10, 10, 20, 20)
    data = document.to_bytes()
    assert data.startswith(b"%PDF-1.4\n")
    assert data.rstrip().endswith(b"%%EOF")
    objects = _objects(data)
    assert b"/Type /Catalog" in objects[1]
    assert b"/Count 2" in objects[2]
    assert b"/BaseFont /Helvetica " in objects[3]
    assert b"/BaseFont /Helvetica-Bold " in objects[4]
    boxes = re.findall(rb"/MediaBox \[0 0 (\d+) (\d+)\]", data)
    assert boxes == [(b"595", b"842"), (b"842", b"595")]
    assert b"/Title (Test \\(report\\))" in data


def test_xref_offsets_point_at_objects():
    document = Document()
    document.add_page(200, 200).text(10, 10, "x")
    data = document.to_bytes()
    for number, offset in enumerate(_xref_offsets(data), start=1):
        assert data[offset:].startswith(f"{number} 0 obj".encode())


def test_stream_lengths_match():
    document = Document()
    page = document.add_page(200, 200)
    for index in range(20):
        page.text(10, 10 + index * 8, f"Line {index}")
    data = document.to_bytes()
    for match in re.finditer(rb"<< /Length (\d+) >>\nstream\n", data):
        length = int(match.group(1))
        end = match.end() + length
        assert data[end : end + len(b"\nendstream")] == b"\nendstream"


def test_wrap_text_fits_width():
    text = "Orders charged when placed, including orders arriving after the horizon."
    lines = wrap_text(text, 10, 150)
    assert " ".join(lines) == text
    assert all(text_width(line, 10) <= 150 for line in lines)
    assert len(lines) > 1


def test_wrap_text_long_word():
    assert wrap_text("a " + "x" * 80 + " b", 10, 50) == ["a", "x" * 80, "b"]


def test_wrap_text_empty():
    assert wrap_text("   ", 10, 100) == []


def test_paragraph_draws_wrapped_lines():
    page = Page(200, 200)
    bottom = page.paragraph(10, 100, "one two three four five six seven eight", 60, size=10)
    assert len(page.operations) == len(wrap_text("one two three four five six seven eight", 10, 60))
    assert bottom == pytest.approx(100 - 13.5 * len(page.operations))


def test_document_author_and_subject():
    document = Document("T", author="A (team)", subject="S")
    document.add_page(10, 10)
    data = document.to_bytes()
    assert b"/Author (A \\(team\\))" in data
    assert b"/Subject (S)" in data


def test_many_pages_have_consistent_xref():
    document = Document("Many")
    for number in range(30):
        page = document.add_page(595, 842)
        page.text(50, 800, f"Page {number + 1}", size=14, style="bold")
        page.rect(50, 700, 100 + number, 10, rgb=(0.2, 0.4, 0.6))
    data = document.to_bytes()
    offsets = _xref_offsets(data)
    assert len(offsets) == len(_objects(data))
    for number, offset in enumerate(offsets, start=1):
        assert data[offset:].startswith(f"{number} 0 obj".encode())
