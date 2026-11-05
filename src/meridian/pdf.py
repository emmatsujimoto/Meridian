"""A minimal PDF writer for text, lines and filled rectangles.

Meridian's reports only need simple vector pages, so this module writes PDF 1.4 directly
instead of adding a dependency. It uses the standard Helvetica fonts, which every PDF
reader provides, so nothing is embedded. Coordinates are in points from the bottom-left
corner of the page.
"""

from dataclasses import dataclass, field

FONTS = {"regular": "Helvetica", "bold": "Helvetica-Bold"}
_FONT_KEYS = {"regular": "F1", "bold": "F2"}

# Average Helvetica glyph width as a share of the font size, used to estimate text width.
_AVERAGE_WIDTH = 0.52


def escape_text(text: str) -> str:
    """Text for a PDF string literal: Latin-1 only, with special characters escaped."""
    latin = text.encode("latin-1", errors="replace").decode("latin-1")
    return latin.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_width(text: str, size: float) -> float:
    """Approximate width in points of ``text`` at ``size``, for right-aligning numbers."""
    return len(text) * size * _AVERAGE_WIDTH


def _colour(rgb: tuple[float, float, float]) -> str:
    """An RGB colour with components from 0 to 1 as PDF operands."""
    if len(rgb) != 3 or any(not 0 <= c <= 1 for c in rgb):
        raise ValueError("Colours need three components from 0 to 1")
    return " ".join(f"{c:.3f}" for c in rgb)


@dataclass
class Page:
    """One page's drawing operations, in the order they are added."""

    width: float
    height: float
    operations: list[str] = field(default_factory=list)

    def text(
        self,
        x: float,
        y: float,
        value: str,
        size: float = 10,
        style: str = "regular",
        align: str = "left",
    ) -> None:
        """Draw one line of text; ``align`` is left, right or centre around ``x``."""
        if style not in _FONT_KEYS:
            raise ValueError(f"style must be one of {', '.join(_FONT_KEYS)}")
        if align == "right":
            x -= text_width(value, size)
        elif align == "centre":
            x -= text_width(value, size) / 2
        elif align != "left":
            raise ValueError("align must be left, right or centre")
        self.operations.append(
            f"BT /{_FONT_KEYS[style]} {size:g} Tf {x:.2f} {y:.2f} Td ({escape_text(value)}) Tj ET"
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        width: float = 0.5,
        rgb: tuple[float, float, float] = (0, 0, 0),
    ) -> None:
        """Draw a straight line."""
        self.operations.append(
            f"q {width:g} w {_colour(rgb)} RG {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S Q"
        )

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        rgb: tuple[float, float, float] = (0, 0, 0),
    ) -> None:
        """Draw a filled rectangle with its lower-left corner at (x, y)."""
        if w < 0 or h < 0:
            raise ValueError("Rectangle width and height must not be negative")
        self.operations.append(f"q {_colour(rgb)} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f Q")

    def paragraph(
        self, x: float, y: float, text: str, width: float, size: float = 10, leading: float = 1.35
    ) -> float:
        """Draw wrapped text starting at ``y``; return the y position below the last line."""
        for line in wrap_text(text, size, width):
            self.text(x, y, line, size=size)
            y -= size * leading
        return y

    def content(self) -> bytes:
        """The page's content stream."""
        return "\n".join(self.operations).encode("latin-1")


class Document:
    """A PDF document built page by page and serialised with ``to_bytes``."""

    def __init__(self, title: str = "", author: str = "", subject: str = "") -> None:
        self.title = title
        self.author = author
        self.subject = subject
        self.pages: list[Page] = []

    def add_page(self, width: float, height: float) -> Page:
        """Append a blank page of the given size in points and return it."""
        if width <= 0 or height <= 0:
            raise ValueError("Page size must be positive")
        page = Page(width, height)
        self.pages.append(page)
        return page

    def to_bytes(self) -> bytes:
        """The complete PDF file."""
        if not self.pages:
            raise ValueError("A PDF needs at least one page")
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        catalog = add(b"")
        pages = add(b"")
        fonts = {
            key: add(
                f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} "
                f"/Encoding /WinAnsiEncoding >>".encode()
            )
            for key, name in FONTS.items()
        }
        resources = (
            f"<< /Font << /{_FONT_KEYS['regular']} {fonts['regular']} 0 R "
            f"/{_FONT_KEYS['bold']} {fonts['bold']} 0 R >> >>"
        )
        page_ids = []
        for page in self.pages:
            stream = page.content()
            content = add(
                f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
            )
            page_ids.append(
                add(
                    f"<< /Type /Page /Parent {pages} 0 R "
                    f"/MediaBox [0 0 {page.width:g} {page.height:g}] "
                    f"/Resources {resources} /Contents {content} 0 R >>".encode()
                )
            )
        objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages} 0 R >>".encode()
        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        objects[pages - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
        info = add(
            f"<< /Title ({escape_text(self.title)}) /Author ({escape_text(self.author)}) "
            f"/Subject ({escape_text(self.subject)}) /Producer (Meridian) >>".encode()
        )

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
        for offset in offsets:
            out += f"{offset:010d} 00000 n \n".encode()
        out += (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
        return bytes(out)


def wrap_text(text: str, size: float, width: float) -> list[str]:
    """Split ``text`` into lines that fit ``width`` points at ``size``, breaking at spaces.

    A single word longer than the width is kept on its own line rather than cut.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if current and text_width(candidate, size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines
