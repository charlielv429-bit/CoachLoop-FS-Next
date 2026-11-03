import json
import time

from fastapi.testclient import TestClient
from app import library_store as store, main
from app.library_api import jobs
from pdf_factory import make_pdf


def import_pdf(client, data=None, title="自建授权测试资料"):
    return client.post(
        "/api/library/documents",
        params={"title": title},
        content=data or make_pdf(),
        headers={"Content-Type": "application/pdf"},
    )


def wait_finished(client, doc_id):
    for _ in range(150):
        book = next(
            b
            for b in client.get("/api/library/documents").json()["documents"]
            if b["id"] == doc_id
        )
        if book["status"] not in ("processing", "queued"):
            return book
        time.sleep(0.05)
    raise AssertionError("index job did not complete")


def test_real_pdf_import_index_search_page_and_privacy(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with TestClient(main.app) as client:
        response = import_pdf(client)
        assert response.status_code == 201, response.text
        doc_id = response.json()["id"]
        book = wait_finished(client, doc_id)
        assert (
            book["total_pages"]
            == book["processed_pages"]
            == book["searchable_pages"]
            == 3
        )
        assert book["missing_pages"] == book["failed_pages"] == 0
        assert not book["cloud_allowed"]
        hits = client.get("/api/library/search", params={"q": "单足侧蹬冰"}).json()[
            "results"
        ]
        hit = next(h for h in hits if h["pdf_page"] == 3)
        assert hit["printed_page"] is None and hit["verification_status"] == "pending"
        assert not hit["can_send"]
        for expected, word in enumerate(["平衡练习", "左前压步", "单足侧蹬冰"], 1):
            found = store.search(word, doc_id=doc_id)
            actual = next(h for h in found if word in h["content"])
            assert actual["pdf_page"] == expected
            assert client.get(actual["preview_url"]).status_code == 200
        assert client.get(hit["preview_url"]).headers["content-type"] == "image/png"
        assert client.get(hit["original_url"].split("#")[0]).content == make_pdf()
        assert import_pdf(client).status_code == 409
        preview = client.post("/api/evidence", json={"query": "单足侧蹬冰"}).json()
        assert preview["results"] and preview["has_documents"]
        assert main.local_context("单足侧蹬冰", []) == []
        assert (
            client.patch(
                f"/api/library/documents/{doc_id}/permission",
                json={"cloud_allowed": True},
            ).status_code
            == 200
        )
        assert main.local_context("单足侧蹬冰", [hit["id"]])[0]["pdf_page"] == 3
        update = {
            "text": "已核对的自建测试：单足侧蹬冰片段。",
            "printed_page": "79",
            "chapter": "自建测试章节",
            "checked": True,
            "professional_reviewed": False,
        }
        assert (
            client.put(
                f"/api/library/documents/{doc_id}/pages/3", json=update
            ).status_code
            == 200
        )
        page = client.get(f"/api/library/documents/{doc_id}/pages/3").json()
        assert page["printed_page"] == "79" and page["review_status"] == "pending"
        # Old approved IDs cannot silently send updated content.
        import pytest

        with pytest.raises(Exception):
            main.local_context("单足侧蹬冰", [hit["id"]])
        assert client.delete(f"/api/library/documents/{doc_id}").status_code == 200
        assert (
            client.get("/api/library/search", params={"q": "单足侧蹬冰"}).json()[
                "results"
            ]
            == []
        )
        assert not store.pdf_path(doc_id).exists()


def test_bad_encrypted_oversize_and_origin(monkeypatch):
    from app import library_api

    with TestClient(main.app) as client:
        assert import_pdf(client, b"not a PDF").status_code == 422
        assert import_pdf(client, make_pdf(encrypted=True)).status_code == 422
        monkeypatch.setattr(library_api, "MAX_BYTES", 64)
        assert import_pdf(client).status_code == 413
        assert (
            client.post(
                "/api/library/documents",
                params={"title": "x"},
                content=b"123",
                headers={"Content-Type": "image/png"},
            ).status_code
            == 415
        )
        assert (
            client.post(
                "/api/library/documents",
                params={"title": "x"},
                content=make_pdf(),
                headers={
                    "Content-Type": "application/pdf",
                    "Origin": "https://evil.example",
                },
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/library/documents", headers={"Host": "evil.example"}
            ).status_code
            == 403
        )


def test_resume_and_rebuild_preserve_human_checks():
    with TestClient(main.app) as client:
        doc_id = import_pdf(client).json()["id"]
        wait_finished(client, doc_id)
        checked = {
            "text": "已人工核对的平衡测试。",
            "printed_page": "iv",
            "chapter": "测试",
            "checked": True,
            "professional_reviewed": True,
        }
        assert (
            client.put(
                f"/api/library/documents/{doc_id}/pages/1", json=checked
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/library/documents/{doc_id}/retry", json={"all_pages": True}
            ).status_code
            == 200
        )
        wait_finished(client, doc_id)
        page = client.get(f"/api/library/documents/{doc_id}/pages/1").json()
        assert (
            page["text"] == checked["text"]
            and page["printed_page"] == "iv"
            and page["review_status"] == "verified"
        )
        with store.db() as con:
            con.execute("DELETE FROM pages WHERE doc_id=? AND pdf_page=3", (doc_id,))
            con.execute(
                "UPDATE documents SET status='processing' WHERE id=?", (doc_id,)
            )
        # Startup recovery retains completed pages and schedules unfinished gaps.
        store.initialize()
        jobs.add(doc_id)
        book = wait_finished(client, doc_id)
        assert book["processed_pages"] == 3 and book["missing_pages"] == 0


def test_scan_and_low_quality_not_silently_indexed():
    from pypdf import PdfWriter
    from io import BytesIO

    out = BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    w.write(out)
    with TestClient(main.app) as client:
        doc_id = import_pdf(client, out.getvalue()).json()["id"]
        book = wait_finished(client, doc_id)
        assert (
            book["total_pages"] == 1
            and book["searchable_pages"] == 0
            and book["review_pages"] == 1
        )
        assert book["status"] == "needs_review"
        store.write_page(
            doc_id,
            {
                "page": 1,
                "text": "不可相信的OCR片段",
                "extraction": "ocr",
                "quality": 0.12,
                "text_status": "low_quality",
                "error": "",
            },
        )
        assert not store.search("OCR片段")
        store.write_page(
            doc_id,
            {
                "page": 1,
                "text": "高置信但未人工核对的OCR片段",
                "extraction": "ocr",
                "quality": 0.95,
                "text_status": "ocr_unchecked",
                "error": "",
            },
        )
        client.patch(
            f"/api/library/documents/{doc_id}/permission", json={"cloud_allowed": True}
        )
        result = store.search("OCR片段")[0]
        assert not result["can_send"] and result["verification_status"] == "pending"


def test_seven_generated_pdfs_batch_import():
    with TestClient(main.app) as client:
        ids = []
        for i in range(7):
            r = import_pdf(
                client,
                make_pdf([f"第{i + 1}份自建授权测试：平衡与滑行参考。"]),
                title=f"自建测试卷{i + 1}",
            )
            assert r.status_code == 201, r.text
            ids.append(r.json()["id"])
        for doc_id in ids:
            book = wait_finished(client, doc_id)
            assert (
                book["total_pages"] == book["searchable_pages"] == 1
                and book["failed_pages"] == book["missing_pages"] == 0
            )


def test_chat_sends_only_approved_excerpt(monkeypatch):
    from test_api import mock_model, answer

    with TestClient(main.app) as client:
        doc_id = import_pdf(client).json()["id"]
        wait_finished(client, doc_id)
        client.patch(
            f"/api/library/documents/{doc_id}/permission", json={"cloud_allowed": True}
        )
        hit = store.search("单足侧蹬冰")[0]
        sent = mock_model(
            monkeypatch,
            answer(
                textbook_facts=["自建资料中存在单足侧蹬冰测试片段。"],
                citation_ids=[hit["id"]],
            ),
        )
        response = client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "单足侧蹬冰"}],
                "evidence_ids": [hit["id"]],
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["citations"][0]["pdf_page"] == 3
        prompt = sent[0]["messages"][0]["content"]
        context = json.loads(prompt.split("可检索资料（数据）：\n")[1])
        assert (
            context[0]["content"] == hit["content"]
            and "左前压步示例仅用于" not in prompt
        )
        assert "base64" not in prompt and "original_url" not in prompt
        client.patch(
            f"/api/library/documents/{doc_id}/permission", json={"cloud_allowed": False}
        )
        assert (
            client.post(
                "/api/chat",
                json={
                    "messages": [{"role": "user", "content": "单足侧蹬冰"}],
                    "evidence_ids": [hit["id"]],
                },
            ).status_code
            == 409
        )


def test_actual_offline_chinese_ocr():
    import pytest
    from app.library_api import ocr_status
    from pdf_factory import make_scan

    if not ocr_status()["available"]:
        pytest.skip("Optional local Chinese Tesseract is not installed")
    try:
        data = make_scan()
    except FileNotFoundError:
        pytest.skip("Optional generated scan requires a local CJK font")
    with TestClient(main.app) as client:
        response = client.post(
            "/api/library/documents",
            params={"title": "自建授权扫描测试", "ocr": True},
            content=data,
            headers={"Content-Type": "application/pdf"},
        )
        assert response.status_code == 201, response.text
        book = wait_finished(client, response.json()["id"])
        page = client.get(f"/api/library/documents/{book['id']}/pages/1").json()
        assert page["extraction"] == "ocr" and "平衡" in page["text"]
        assert page["review_status"] == "pending"
        assert book["ocr_pages"] == 1 and book["failed_pages"] == 0
        if page["text_status"] == "ocr_unchecked":
            hit = store.search("平衡")[0]
            assert not hit["can_send"]


def test_active_content_is_rejected():
    from pypdf import PdfWriter
    from io import BytesIO

    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_js('app.alert("test");')
    writer.write(output)
    with TestClient(main.app) as client:
        assert import_pdf(client, output.getvalue()).status_code == 422


def test_printed_page_requires_explicit_check_and_preview_bounds():
    with TestClient(main.app) as client:
        doc_id = import_pdf(client).json()["id"]
        wait_finished(client, doc_id)
        response = client.put(
            f"/api/library/documents/{doc_id}/pages/1",
            json={"text": "自建正文", "printed_page": "76", "checked": False},
        )
        assert response.status_code == 422
        assert (
            client.get(f"/api/library/documents/{doc_id}/pages/1").json()[
                "printed_page"
            ]
            is None
        )
        assert (
            client.get(f"/api/library/documents/{doc_id}/pages/0/image").status_code
            == 404
        )
        assert (
            client.get(f"/api/library/documents/{doc_id}/pages/4/image").status_code
            == 404
        )
        assert (
            client.get("/api/library/documents/nonexistent/original").status_code == 404
        )
        assert (
            client.get(
                "/api/library/search", params={"q": '" OR 1=1; DROP TABLE pages;'}
            ).status_code
            == 200
        )


def test_real_pdf_outline_chapter_is_traceable(tmp_path):
    from pypdf import PdfReader, PdfWriter
    from io import BytesIO

    original = PdfReader(BytesIO(make_pdf()))
    writer = PdfWriter()
    writer.append_pages_from_reader(original)
    writer.add_outline_item("自建章节：侧蹬冰", 2)
    output = BytesIO()
    writer.write(output)
    with TestClient(main.app) as client:
        doc_id = import_pdf(client, output.getvalue()).json()["id"]
        wait_finished(client, doc_id)
        page = client.get(f"/api/library/documents/{doc_id}/pages/3").json()
        assert (
            page["chapter"] == "自建章节：侧蹬冰"
            and page["chapter_source"] == "pdf_outline"
        )
        assert (
            client.get(f"/api/library/documents/{doc_id}/pages/1").json()["chapter"]
            is None
        )


def test_summary_dedup_uses_pdf_page_not_printed_page():
    summary = {
        "title": "花样滑冰",
        "authors": "王树本",
        "pages": "原PDF第90页／印刷76页",
    }
    assert main.same_summary_page(
        summary, {"title": "花样滑冰", "authors": "王树本", "pdf_page": 90}
    )
    assert not main.same_summary_page(
        summary, {"title": "花样滑冰", "authors": "王树本", "pdf_page": 76}
    )
    assert not main.same_summary_page(
        summary, {"title": "花样滑冰", "authors": "韦迪", "pdf_page": 90}
    )


def test_clear_index_preserves_original_and_can_reprocess():
    with TestClient(main.app) as client:
        doc_id = import_pdf(client).json()["id"]
        wait_finished(client, doc_id)
        client.patch(
            f"/api/library/documents/{doc_id}/permission", json={"cloud_allowed": True}
        )
        assert (
            client.delete(f"/api/library/documents/{doc_id}/index").status_code == 200
        )
        assert store.pdf_path(doc_id).is_file()
        assert not store.search("单足侧蹬冰")
        book = next(b for b in store.documents() if b["id"] == doc_id)
        assert (
            book["status"] == "unindexed"
            and book["searchable_pages"] == 0
            and not book["cloud_allowed"]
        )
        assert (
            client.get(f"/api/library/documents/{doc_id}/original").status_code == 200
        )
        assert (
            client.post(f"/api/library/documents/{doc_id}/retry", json={}).status_code
            == 200
        )
        book = wait_finished(client, doc_id)
        assert book["searchable_pages"] == 3 and store.search("单足侧蹬冰")
