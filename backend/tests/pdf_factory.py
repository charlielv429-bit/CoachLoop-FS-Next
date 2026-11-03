"""Self-authored, public-domain test PDF generator. Contains no textbook excerpts."""

from io import BytesIO
from pypdf import PdfWriter
from pypdf.generic import (
    DictionaryObject,
    NameObject,
    ArrayObject,
    NumberObject,
    DecodedStreamObject,
    TextStringObject,
)


def make_pdf(texts=None, encrypted=False):
    texts = texts or [
        "自建授权测试资料：平衡练习应由现场教师指导。",
        "自建授权测试资料：左前压步示例仅用于页码定位测试。",
        "自建授权测试资料：此页介绍单足侧蹬冰关键词。",
    ]
    writer = PdfWriter()
    cmap = DecodedStreamObject()
    mapping = "\n".join(
        f"<{ord(c):04X}> <{ord(c):04X}>" for c in sorted(set("".join(texts)))
    )
    cmap.set_data(
        (
            """/CIDInit /ProcSet findresource begin 12 dict begin begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /DemoUnicode def /CMapType 2 def
1 begincodespacerange <0000> <FFFF> endcodespacerange
"""
            + str(len(set("".join(texts))))
            + " beginbfchar\n"
            + mapping
            + "\nendbfchar\nendcmap CMapName currentdict /CMap defineresource pop end end"
        ).encode()
    )
    descendant = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/CIDFontType0"),
            NameObject("/BaseFont"): NameObject("/STSong-Light"),
            NameObject("/CIDSystemInfo"): DictionaryObject(
                {
                    NameObject("/Registry"): TextStringObject("Adobe"),
                    NameObject("/Ordering"): TextStringObject("GB1"),
                    NameObject("/Supplement"): NumberObject(0),
                }
            ),
        }
    )
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/BaseFont"): NameObject("/STSong-Light"),
            NameObject("/Encoding"): NameObject("/UniGB-UCS2-H"),
            NameObject("/DescendantFonts"): ArrayObject(
                [writer._add_object(descendant)]
            ),
            NameObject("/ToUnicode"): writer._add_object(cmap),
        }
    )
    font_ref = writer._add_object(font)
    for i, text in enumerate(texts):
        page = writer.add_blank_page(width=595, height=842)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        stream = DecodedStreamObject()
        # Short lines make previews legible; PDF page index is independent of printed labels.
        lines = [
            f"自建测试 PDF 第{i + 1}页（非教材）",
            *[text[n : n + 24] for n in range(0, len(text), 24)],
        ]
        data = (
            "BT /F1 16 Tf 40 790 Td\n"
            + "\n0 -28 Td\n".join(
                "<" + line.encode("utf-16-be").hex() + "> Tj" for line in lines
            )
            + "\nET"
        )
        stream.set_data(data.encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("test-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def make_scan():
    from PIL import Image, ImageDraw, ImageFont
    from pathlib import Path

    font_path = next(
        (
            p
            for p in [
                Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
                Path("/System/Library/Fonts/PingFang.ttc"),
            ]
            if p.exists()
        ),
        None,
    )
    if not font_path:
        raise FileNotFoundError("CJK font required for optional scan fixture")
    image = Image.new("RGB", (1800, 2400), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 60)
    for index, line in enumerate(
        [
            "自建授权扫描测试资料",
            "平衡练习需要现场教师指导",
            "本页仅用于离线中文识别测试",
            "TEST SCAN PAGE ONE",
        ]
    ):
        draw.text((110, 200 + index * 140), line, font=font, fill="black")
    output = BytesIO()
    image.save(output, format="PDF", resolution=180)
    return output.getvalue()
