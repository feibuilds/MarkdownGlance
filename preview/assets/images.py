import struct
from dataclasses import dataclass
from typing import BinaryIO

# minihtml decodes PNG, JPEG and GIF and nothing else, so a file in any other
# format has to be told apart from a truncated one or from a 404 page served
# where an image was expected: "not a format the preview can draw" is a fact
# about the document its author can act on, "Unavailable" reads as a missing
# file. A binary signature sits in the first bytes; an SVG's root element can
# be behind a BOM, an XML declaration, comments and a DOCTYPE, so the sniff is
# wide enough for all four.
SNIFF_BYTES = 2048

UTF8_BOM = b"\xef\xbb\xbf"


class InvalidImage(ValueError):
    pass


class UnsupportedImage(InvalidImage):
    """An image in a format minihtml cannot decode.

    A subclass, so that a caller that only asks whether it has a drawable
    image is unchanged; the two that report a status to the reader catch this
    one first and say which of the two failures it was.
    """


class SvgImage(UnsupportedImage):
    """An SVG, which the local renderer can turn into a PNG (ADR 0019).

    Told apart from the rest of the family because it is the one format with
    a way through: a caller that has a renderer draws it, one that has none
    reports it like any other format minihtml cannot decode.
    """


@dataclass(frozen=True)
class ImageInfo:
    mime_type: str
    width: int
    height: int


def _is_unsupported_binary(head: bytes) -> bool:
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return True
    # BMP, then TIFF little- and big-endian.
    if head.startswith((b"BM", b"II*\x00", b"MM\x00*")):
        return True
    # ICO and CUR, which carry no magic beyond a reserved word and a type.
    if head.startswith((b"\x00\x00\x01\x00", b"\x00\x00\x02\x00")):
        return True
    # AVIF and HEIC, and the rest of the ISO base media family with them.
    return head[4:8] == b"ftyp"


def _is_svg(head: bytes) -> bool:
    """Whether the prefix reaches an `svg` root element, prologue and all.

    Walking the prologue rather than searching for the string is what keeps an
    HTML page with an inline icon in it -- an error page served where an image
    was expected -- from being reported as an SVG: its root element is `html`,
    and it is a broken link, not a format the reader can convert.
    """
    text = head.decode("latin-1")
    if head.startswith(UTF8_BOM):
        text = text[len(UTF8_BOM) :]
    at = 0
    while at < len(text):
        if text[at].isspace():
            at += 1
        elif text.startswith("<svg", at):
            return at + 4 == len(text) or text[at + 4] in " \t\r\n/>"
        elif text.startswith("<!--", at):
            at = text.find("-->", at)
            if at < 0:
                return False
            at += 3
        elif text.startswith("<?", at):
            at = text.find("?>", at)
            if at < 0:
                return False
            at += 2
        elif text.startswith("<!", at):
            # A DOCTYPE, which ends after its internal subset when it has one
            # rather than at the first `>` the subset happens to contain.
            close = text.find(">", at)
            subset = text.find("[", at)
            if 0 <= subset < close:
                close = text.find("]>", at)
                if close >= 0:
                    close += 1
            if close < 0:
                return False
            at = close + 1
        else:
            return False
    return False


def detect(stream: BinaryIO) -> ImageInfo:
    stream.seek(0)
    head = stream.read(SNIFF_BYTES)
    if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
        width, height = struct.unpack(">II", head[16:24])
        return ImageInfo("image/png", width, height)
    if head.startswith((b"GIF87a", b"GIF89a")) and len(head) >= 10:
        width, height = struct.unpack("<HH", head[6:10])
        return ImageInfo("image/gif", width, height)
    if head.startswith(b"\xff\xd8"):
        stream.seek(2)
        while True:
            marker_start = stream.read(1)
            if not marker_start:
                break
            if marker_start != b"\xff":
                continue
            marker = stream.read(1)
            while marker == b"\xff":
                marker = stream.read(1)
            if not marker:
                break
            marker_value = marker[0]
            if marker_value in (0xD8, 0xD9):
                continue
            size_data = stream.read(2)
            if len(size_data) != 2:
                break
            size = struct.unpack(">H", size_data)[0]
            if 0xC0 <= marker_value <= 0xCF and marker_value not in (0xC4, 0xC8, 0xCC):
                payload = stream.read(5)
                if len(payload) != 5:
                    break
                height, width = struct.unpack(">HH", payload[1:5])
                return ImageInfo("image/jpeg", width, height)
            stream.seek(max(size - 2, 0), 1)
    if _is_svg(head):
        raise SvgImage("an SVG, which minihtml cannot decode")
    if _is_unsupported_binary(head):
        raise UnsupportedImage("not a format minihtml can decode")
    raise InvalidImage("unsupported or malformed image")
