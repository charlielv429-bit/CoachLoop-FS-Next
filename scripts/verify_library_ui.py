"""Real browser/local PDF pipeline, with explicitly MOCKED model responses only.
Requires a clean TEST backend on 8001 (no API key) and frontend proxy pointing to it.
Uses CC0/self-authored PDFs; never run against a real teacher's library.
"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:5173")
parser.add_argument("--backend", default="http://127.0.0.1:8001")
args = parser.parse_args()
shots = ROOT / "docs" / "mvp1-5"
shots.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as directory, sync_playwright() as p:
    subprocess.run(
        [
            str(ROOT / ".venv/bin/python"),
            str(ROOT / "scripts/generate_demo_pdfs.py"),
            directory,
        ],
        check=True,
    )
    browser = p.chromium.launch(
        executable_path="/usr/bin/chromium",
        headless=True,
        args=["--no-sandbox", "--no-proxy-server"],
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    page.set_default_timeout(20000)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    existing = page.request.get(args.backend + "/api/library/documents").json()[
        "documents"
    ]
    assert not existing, "Use a clean isolated TEST library, never a real library"
    page.goto(args.url, wait_until="domcontentloaded")
    page.get_by_role("button", name="专项知识库").click()
    page.locator("input[type=file]").set_input_files(
        str(Path(directory) / "self-authored-demo.pdf")
    )
    page.get_by_role("button", name="开始批量导入 / 重试失败文件").click()

    def wait_books(count):
        for _ in range(120):
            books = page.request.get(args.backend + "/api/library/documents").json()[
                "documents"
            ]
            if len(books) == count and all(
                b["status"] not in ("queued", "processing") for b in books
            ):
                return books
            page.wait_for_timeout(250)
        raise AssertionError("Index processing timeout")

    books = wait_books(1)
    book = books[0]
    assert (
        book["total_pages"] == book["processed_pages"] == book["searchable_pages"] == 3
    )
    samples = []
    for expected, word in enumerate(["平衡练习", "左前压步", "单足侧蹬冰"], 1):
        found = page.request.get(
            args.backend + "/api/library/search",
            params={"q": word, "doc_id": book["id"]},
        ).json()["results"]
        hit_page = next(h for h in found if word in h["content"])
        assert hit_page["pdf_page"] == expected
        assert page.request.get(args.backend + hit_page["preview_url"]).status == 200
        samples.append(
            {
                "phrase": word,
                "expected_pdf_page": expected,
                "actual_pdf_page": hit_page["pdf_page"],
            }
        )
    page.get_by_role("button", name="清空本批列表").click()
    page.get_by_role("textbox", name="搜索本地教材").fill("单足侧蹬冰")
    page.get_by_role("button", name="搜索", exact=True).click()
    page.get_by_role("button", name="核对 PDF 第3页").click()
    expect(page.get_by_role("dialog", name="教材原页与文本核对")).to_be_visible()
    image = page.get_by_alt_text("原PDF第3页（包含动作图片）")
    expect(image).to_be_visible()
    page.wait_for_function(
        "[...document.images].some(i=>i.alt.includes('原PDF第3页')&&i.complete&&i.naturalWidth>0)"
    )
    page.screenshot(path=str(shots / "original-page.png"), full_page=True)
    page.get_by_role("button", name="关闭原页预览").click()
    page.get_by_label("允许在每轮确认后，向当前云模型发送相关短片段").check()
    page.wait_for_function("true")
    # Duplicate import, surfaced as a readable message, not silently duplicated.
    page.locator("input[type=file]").set_input_files(
        str(Path(directory) / "self-authored-demo.pdf")
    )
    page.get_by_role("button", name="开始批量导入 / 重试失败文件").click()
    page.get_by_text("重复文件：已导入", exact=False).wait_for()
    page.get_by_role("button", name="清空本批列表").click()
    # Seven SYNTHETIC files, not the seven textbooks.
    page.locator("input[type=file]").set_input_files(
        [str(Path(directory) / f"synthetic-volume-{i + 1}.pdf") for i in range(7)]
    )
    page.get_by_role("button", name="开始批量导入 / 重试失败文件").click()
    books = wait_books(8)
    expect(page.get_by_text("预检通过 · 已登记教材 · 等待文本提取/OCR与索引")).to_have_count(7)
    page.get_by_role("button", name="清空本批列表").click()
    page.screenshot(path=str(shots / "library-imports.png"), full_page=True)
    scan = Path(directory) / "self-authored-scan.pdf"
    if (
        scan.exists()
        and page.request.get(args.backend + "/api/library/documents").json()["ocr"][
            "available"
        ]
    ):
        page.locator("input[type=file]").set_input_files(str(scan))
        page.get_by_label("对扫描页启用本机中文 OCR").check()
        page.get_by_role("button", name="开始批量导入 / 重试失败文件").click()
        books = wait_books(9)
        scan_book = next(b for b in books if b["title"] == "self-authored-scan")
        assert scan_book["ocr_pages"] == 1 and scan_book["failed_pages"] == 0
        page.get_by_role("button", name="清空本批列表").click()
    # Actual evidence comes from real local SQLite; only model output is mocked.
    hit = next(
        h
        for h in page.request.get(
            args.backend + "/api/library/search?q=单足侧蹬冰"
        ).json()["results"]
        if h["document_id"] == book["id"]
    )
    status = page.request.get(args.backend + "/api/status").json()
    page.route(
        "**/api/status",
        lambda route: route.fulfill(
            json={**status, "configured": True, "connection": "unverified"}
        ),
    )
    sent = []

    def model(route):
        body = route.request.post_data_json
        sent.append(body)
        assert body["evidence_ids"] == [hit["id"]]
        route.fulfill(
            json={
                "textbook_facts": [
                    "【模型模拟验收】自建授权测试资料包含单足侧蹬冰关键词。"
                ],
                "suggestions": "【模拟响应，非Gemini】可与现场教师讨论分解练习。",
                "limitations": "只用于本地流程验收。教材专业审核仍为待审核。",
                "citations": [hit],
                "model": "TEST ONLY",
            }
        )

    page.route("**/api/chat", model)
    page.get_by_role("button", name="AI 教学对话").click()
    page.get_by_role("button", name="刷新连接").click()
    page.locator(".status").filter(has_text="已配置").wait_for()
    page.get_by_role("textbox", name="输入教学问题").fill("单足侧蹬冰")
    page.get_by_role("button", name="发送问题").click()
    dialog = page.get_by_role("dialog", name="确认本轮教材片段")
    expect(dialog).to_be_visible()
    checkbox = (
        dialog.locator(".evidence-card")
        .filter(has_text=hit["content"])
        .get_by_role("checkbox")
    )
    expect(checkbox).to_be_enabled()
    expect(checkbox).not_to_be_checked()
    checkbox.check()
    page.screenshot(path=str(shots / "snippet-consent.png"), full_page=True)
    dialog.get_by_role("button", name="发送问题与1条片段").click()
    page.get_by_text(
        "【模型模拟验收】自建授权测试资料包含单足侧蹬冰关键词。"
    ).wait_for()
    citation = page.locator(".citation").filter(has_text="self-authored-demo")
    assert "#page=3" in citation.get_by_role(
        "link", name="打开原 PDF 第3页"
    ).get_attribute("href")
    with page.expect_popup() as popup:
        citation.get_by_role("link", name="打开原 PDF 第3页").click()
    popup.value.wait_for_load_state("domcontentloaded")
    assert "#page=3" in popup.value.url
    assert sent and not errors, errors
    page.screenshot(path=str(shots / "chat-mocked.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="查看资料库").click()
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.screenshot(path=str(shots / "mobile-library.png"), full_page=True)
    report = {
        "dataset": "Self-authored synthetic PDFs only; NOT the seven textbooks",
        "model": "MOCKED; no Gemini call",
        "documents": [
            {
                "title": b["title"],
                "pages": b["total_pages"],
                "searchable": b["searchable_pages"],
                "ocr_pages": b["ocr_pages"],
                "ocr_failed": b["ocr_failed_pages"],
                "ocr_low_quality": b["low_quality_pages"],
                "failed": b["failed_pages"],
                "missing": b["missing_pages"],
                "status": b["status"],
            }
            for b in books
        ],
        "citation_sample": {
            "checked": len(samples),
            "correct": sum(
                s["expected_pdf_page"] == s["actual_pdf_page"] for s in samples
            ),
            "samples": samples,
            "note": "All three demo page-specific phrases checked against generated original pages by API tests; browser opened matching page 3.",
        },
    }
    (shots / "synthetic-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    browser.close()
    print(
        "PASS: real PDF upload/extraction/FTS/preview; 7 synthetic files; offline OCR where installed; explicit snippet consent; mocked chat citation opens original page 3; mobile; no JS errors."
    )
