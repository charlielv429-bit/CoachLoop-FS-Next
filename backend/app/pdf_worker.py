"""Isolated, bounded PDF parser/renderer. Never invokes a shell or a cloud service."""

import argparse
import csv
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile


def limits():
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (100, 100))
        if sys.platform != "darwin":
            resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
        resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024**2, 32 * 1024**2))


def render(path, page, destination, scale=1.4):
    import pypdfium2 as pdfium

    with pdfium.PdfDocument(str(path)) as doc:
        item = doc[page - 1]
        try:
            width, height = item.get_size()
            if not all(math.isfinite(n) and 0 < n < 20000 for n in (width, height)):
                raise ValueError("Unsupported page dimensions")
            scale = min(scale, math.sqrt(8_000_000 / (width * height)))
            bitmap = item.render(scale=scale)
            try:
                raw = bitmap.to_pil()  # Pillow is explicitly pinned by this project.
                raw.convert("RGB").save(destination, format="PNG")
            finally:
                bitmap.close()
        finally:
            item.close()


def inspect(path):
    from pypdf import PdfReader

    reader = PdfReader(path, strict=True)
    if reader.is_encrypted:
        raise ValueError("不支持加密 PDF，请在本机使用有权解密的副本。")
    count = len(reader.pages)
    if not 1 <= count <= 1500:
        raise ValueError("每份 PDF 需为 1–1500 页。")
    catalog = reader.trailer["/Root"]
    names = catalog.get("/Names", {})
    if hasattr(names, "get_object"):
        names = names.get_object()
    if any(key in catalog for key in ("/OpenAction", "/AA", "/AcroForm")) or any(
        key in names for key in ("/JavaScript", "/EmbeddedFiles")
    ):
        raise ValueError("不支持主动脚本、表单或附件 PDF。")
    for page in reader.pages:
        if "/AA" in page:
            raise ValueError("不支持页面主动动作。")
        for annotation in page.get("/Annots", []):
            annotation = annotation.get_object()
            action = annotation.get("/A", {})
            if hasattr(action, "get_object"):
                action = action.get_object()
            if "/AA" in annotation or action.get("/S") in (
                "/JavaScript",
                "/Launch",
                "/SubmitForm",
                "/ImportData",
            ):
                raise ValueError("不支持主动动作 PDF。")
    return {"pages": count}


def batch(path, start, end, ocr, outdir):
    from pypdf import PdfReader

    reader = PdfReader(path, strict=True)
    bookmarks = []

    def walk(items):
        for item in items[:5000]:
            if isinstance(item, list):
                walk(item)
            else:
                try:
                    destination = reader.get_destination_page_number(item)
                    title = str(item.title).strip()[:180]
                    if destination is not None and title:
                        bookmarks.append((destination + 1, title))
                except Exception:
                    pass

    try:
        walk(reader.outline)
    except Exception:
        pass
    bookmarks.sort(key=lambda item: item[0])
    for number in range(start, end + 1):
        result = {
            "page": number,
            "text": "",
            "extraction": "failed",
            "quality": None,
            "ocr_attempted": False,
            "text_status": "needs_review",
            "error": "",
        }
        chapters = [title for page, title in bookmarks if page <= number]
        result["chapter"] = chapters[-1] if chapters else None
        try:
            page = reader.pages[number - 1]
            # Bound decompression before extract_text; the process also has memory/CPU limits.
            stream = page.get_contents()
            if stream is not None and len(stream.get_data()) > 12_000_000:
                raise ValueError("页面解压文本过大，请拆分后重试。")
            text = (page.extract_text() or "").replace("\x00", "").strip()
            visible = sum(c.isalnum() for c in text)
            if visible >= 15 and text.count("\ufffd") / max(1, len(text)) < 0.03:
                result.update(
                    text=text[:24000],
                    extraction="text",
                    text_status="extracted_unchecked"
                    if len(text) <= 24000
                    else "needs_review",
                    error=""
                    if len(text) <= 24000
                    else "此页正文超过24000字符，仅保留核对草稿，未进入索引。",
                )
            elif ocr:
                result["ocr_attempted"] = True
                result["error"] = "本页 OCR 中断，可重试。"
                (outdir / f"{number}.json").write_text(
                    json.dumps(result, ensure_ascii=False), encoding="utf-8"
                )
                with tempfile.TemporaryDirectory() as directory:
                    image = Path(directory) / "page.png"
                    render(path, number, image, scale=2.5)
                    command = [
                        "tesseract",
                        str(image),
                        "stdout",
                        "-l",
                        "chi_sim+eng",
                        "-c",
                        "tessedit_create_tsv=1",
                    ]
                    run = subprocess.run(
                        command, capture_output=True, text=True, timeout=25, check=True
                    )
                    rows = list(csv.DictReader(io.StringIO(run.stdout), delimiter="\t"))
                    words = [
                        (r.get("text") or "").strip()
                        for r in rows
                        if (r.get("text") or "").strip()
                    ]
                    conf = [
                        float(r["conf"])
                        for r in rows
                        if (r.get("text") or "").strip() and float(r["conf"]) >= 0
                    ]
                    quality = sum(conf) / len(conf) / 100 if conf else 0
                    text = " ".join(words)
                    result.update(
                        text=text[:24000],
                        extraction="ocr",
                        quality=round(quality, 3),
                        text_status="ocr_unchecked"
                        if quality >= 0.75 and 15 <= len(text) <= 24000
                        else "low_quality",
                        error=""
                        if len(text) <= 24000
                        else "OCR正文超过安全长度，草稿待核对，未进入索引。",
                    )
            else:
                result.update(
                    extraction="scan",
                    text_status="needs_ocr",
                    error="未发现足够可用正文；可启用本机中文 OCR 或人工核对。",
                )
        except Exception:
            result["error"] = "页面解析或 OCR 失败；原始页保留，可逐页重试或人工核对。"
        destination = outdir / f"{number}.json"
        destination.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["inspect", "batch", "render"])
    parser.add_argument("path")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=1)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--out", required=False)
    args = parser.parse_args()
    limits()
    if args.mode == "inspect":
        print(json.dumps(inspect(args.path)))
    elif args.mode == "render":
        render(args.path, args.start, args.out)
    else:
        batch(args.path, args.start, args.end, args.ocr, Path(args.out))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Do not echo document contents, host paths, or parser exception payloads.
        print("PDF处理失败：文件可能加密、损坏、过大或超出安全限制。", file=sys.stderr)
        sys.exit(1)
