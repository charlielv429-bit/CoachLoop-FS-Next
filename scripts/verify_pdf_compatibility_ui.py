"""Self-authored UI verification only; requires a CLEAN isolated backend on 8004
and Vite on 5176 proxying to it. Never run against a teacher's existing library.
"""

from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
shots = ROOT / "docs/pdf-import-compatibility"
shots.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as directory, sync_playwright() as p:
    code = """import sys
from pathlib import Path
sys.path[:0]=['backend','backend/tests']
from test_pdf_policy import sample
for kind in ['open_destination','open_js']:
 Path(sys.argv[1],kind+'.pdf').write_bytes(sample(kind))
"""
    subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-c", code, directory], cwd=ROOT, check=True
    )
    browser = p.chromium.launch(
        executable_path="/usr/bin/chromium",
        headless=True,
        args=["--no-sandbox", "--no-proxy-server"],
    )
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    requests = []
    context.on("request", lambda request: requests.append(request.url))
    page = context.new_page()
    page.set_default_timeout(20000)
    assert (
        page.request.get("http://127.0.0.1:8004/api/library/documents").json()[
            "documents"
        ]
        == []
    ), "Requires CLEAN isolated test library"
    page.goto("http://127.0.0.1:5176", wait_until="domcontentloaded")
    page.get_by_role("button", name="专项知识库").click()
    page.locator("input[type=file]").set_input_files(
        str(Path(directory) / "open_destination.pdf")
    )
    page.get_by_role("button", name="开始批量导入 / 重试失败文件").click()
    expect(page.locator(".book")).to_have_count(1)
    expect(page.locator(".book").get_by_text("可检索 3 页")).to_be_visible()
    page.get_by_role("button", name="查看原页与核对").click()
    page.get_by_role("spinbutton", name="原PDF页码").fill("2")
    page.get_by_role("button", name="跳转", exact=True).click()
    expect(page.get_by_alt_text("原PDF第2页（包含动作图片）")).to_be_visible()
    with page.expect_popup() as pop:
        page.get_by_role("link", name="原PDF安全预览").click()
    preview = pop.value
    preview.wait_for_load_state("domcontentloaded")
    expect(preview.locator('#status')).to_have_text('PDF 第2页；印刷页码需另行核对。')
    assert preview.url.endswith("#page=2")
    assert preview.locator("embed,object,iframe").count() == 0
    assert "PDF 第2页" in preview.locator("#status").inner_text()
    preview.get_by_role("button", name="下一页").click()
    expect(preview.locator("#page")).to_have_value("3")
    expect(preview.locator('#status')).to_have_text('PDF 第3页；印刷页码需另行核对。')
    response = page.request.get(preview.url.split("#")[0])
    assert response.headers["content-type"].startswith("text/html")
    assert "object-src 'none'" in response.headers["content-security-policy"]
    preview.screenshot(path=str(shots / "passive-preview.png"), full_page=True)
    preview.close()
    page.get_by_role("button", name="关闭原页预览").click()
    page.locator("input[type=file]").set_input_files(
        str(Path(directory) / "open_js.pdf")
    )
    page.get_by_role("button", name="开始批量导入 / 重试失败文件").click()
    expect(
        page.get_by_text("错误代码：PDF_JAVASCRIPT_ACTION_BLOCKED", exact=False)
    ).to_be_visible()
    expect(
        page.get_by_text("对象类别：document_open_action", exact=False)
    ).to_be_visible()
    assert page.locator(".book").count() == 1
    assert "PRIVATE_BODY_FIELD_LINK_SCRIPT_DO_NOT_PRINT" not in page.inner_text("body")
    page.screenshot(path=str(shots / "blocked-javascript.png"), full_page=True)
    assert all(
        urlparse(url).hostname in ("127.0.0.1", "localhost")
        for url in requests
        if urlparse(url).scheme in ("http", "https")
    ), requests
    browser.close()
    print(
        "PASS: actual browser import of self-authored internal OpenAction, 3 indexed pages; raster viewer page2→3 under CSP; JS upload refused with fixed scope/code; no external HTTP requests. NOT a Wang textbook test."
    )
