"""Self-authored objects only. No copyrighted textbook, script or network execution."""

from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)
from fastapi.testclient import TestClient
from app import main, library_store
from app.pdf_worker import inspect, render
from app.pdf_policy import PDFPolicyError, safe_failure
from pdf_factory import make_pdf
from test_library import import_pdf, wait_finished

SECRET = "PRIVATE_BODY_FIELD_LINK_SCRIPT_DO_NOT_PRINT"
ROOT = Path(__file__).resolve().parents[2]


def dictionary(**values):
    return DictionaryObject({NameObject("/" + k): v for k, v in values.items()})


def sample(kind):
    writer = PdfWriter()
    writer.append_pages_from_reader(PdfReader(BytesIO(make_pdf())))
    destination = ArrayObject([writer.pages[1].indirect_reference, NameObject("/Fit")])
    goto = dictionary(S=NameObject("/GoTo"), D=destination)
    script = dictionary(S=NameObject("/JavaScript"), JS=TextStringObject(SECRET))

    def annotation(**extra):
        item = dictionary(
            Type=NameObject("/Annot"),
            Subtype=NameObject("/Text"),
            Rect=ArrayObject([NumberObject(n) for n in (10, 10, 30, 30)]),
            Contents=TextStringObject(SECRET),
        )
        for k, v in extra.items():
            item[NameObject("/" + k)] = v
        writer.pages[0][NameObject("/Annots")] = ArrayObject([writer._add_object(item)])
        return item

    if kind == "open_destination":
        writer._root_object[NameObject("/OpenAction")] = destination
    elif kind == "open_goto":
        writer._root_object[NameObject("/OpenAction")] = goto
    elif kind == "named_destination":
        writer.add_named_destination(SECRET, 1)
        writer._root_object[NameObject("/OpenAction")] = TextStringObject(SECRET)
    elif kind == "ordinary_annotation":
        annotation()
    elif kind == "internal_link":
        annotation(Subtype=NameObject("/Link"), Dest=destination)
    elif kind == "static_form":
        field = dictionary(
            FT=NameObject("/Tx"), T=TextStringObject(SECRET), V=TextStringObject(SECRET)
        )
        field_ref = writer._add_object(field)
        writer._root_object[NameObject("/AcroForm")] = dictionary(
            Fields=ArrayObject([field_ref])
        )
        annotation(Subtype=NameObject("/Widget"), Parent=field_ref)
    elif kind == "form_unknown":
        field = dictionary(FT=NameObject("/UnknownField"), T=TextStringObject(SECRET))
        writer._root_object[NameObject("/AcroForm")] = dictionary(
            Fields=ArrayObject([writer._add_object(field)])
        )
    elif kind == "xfa":
        writer._root_object[NameObject("/AcroForm")] = dictionary(
            XFA=TextStringObject(SECRET)
        )
    elif kind == "form_js":
        field = dictionary(
            FT=NameObject("/Tx"), T=TextStringObject(SECRET), AA=dictionary(K=script)
        )
        writer._root_object[NameObject("/AcroForm")] = dictionary(
            Fields=ArrayObject([writer._add_object(field)])
        )
    elif kind == "widget_parent_js":
        annotation(
            Subtype=NameObject("/Widget"),
            Parent=writer._add_object(dictionary(AA=dictionary(K=script))),
        )
    elif kind == "document_js":
        writer.add_js(SECRET)
    elif kind == "open_js":
        writer._root_object[NameObject("/OpenAction")] = script
    elif kind == "annotation_js":
        annotation(A=script)
    elif kind == "annotation_aa":
        annotation(AA=dictionary(E=script))
    elif kind == "page_aa":
        writer.pages[0][NameObject("/AA")] = dictionary(O=script)
    elif kind == "document_aa":
        writer._root_object[NameObject("/AA")] = dictionary(WC=script)
    elif kind == "next_js":
        goto[NameObject("/Next")] = ArrayObject([script])
        writer._root_object[NameObject("/OpenAction")] = goto
    elif kind == "cycle":
        reference = writer._add_object(goto)
        goto[NameObject("/Next")] = reference
        writer._root_object[NameObject("/OpenAction")] = reference
    elif kind == "bad_destination":
        writer._root_object[NameObject("/OpenAction")] = ArrayObject(
            [NumberObject(99), NameObject("/Fit")]
        )
    elif kind == "unresolved_destination":
        writer._root_object[NameObject("/OpenAction")] = TextStringObject(SECRET)
    elif kind == "outline_js":
        writer.add_outline_item(SECRET, 0)
        writer._root_object["/Outlines"]["/First"][NameObject("/A")] = script
    elif kind == "many_bookmarks":
        for _ in range(40):
            writer.add_outline_item(SECRET, 0)
    elif kind in ("url", "launch", "submit", "import", "remote", "unknown", "print"):
        action = {
            "url": "/URI",
            "launch": "/Launch",
            "submit": "/SubmitForm",
            "import": "/ImportData",
            "remote": "/GoToR",
            "unknown": "/UNKNOWN",
            "print": "/Named",
        }[kind]
        writer._root_object[NameObject("/OpenAction")] = dictionary(
            S=NameObject(action),
            URI=TextStringObject("https://example.invalid/"+SECRET),
            F=TextStringObject(SECRET),
            N=NameObject("/Print"),
        )
    elif kind == "annotation_url":
        annotation(
            Subtype=NameObject("/Link"),
            A=dictionary(S=NameObject("/URI"), URI=TextStringObject("https://example.invalid/"+SECRET)),
        )
    elif kind == "embedded":
        writer.add_attachment(SECRET, b"test-only attachment")
    elif kind == "file_annotation":
        annotation(
            Subtype=NameObject("/FileAttachment"),
            FS=dictionary(F=TextStringObject(SECRET)),
        )
    elif kind == "media":
        annotation(Subtype=NameObject("/RichMedia"))
    elif kind == "encrypted":
        writer.encrypt(SECRET)
    elif kind != "plain":
        raise ValueError(kind)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize(
    "kind",
    [
        "plain",
        "open_destination",
        "open_goto",
        "named_destination",
        "ordinary_annotation",
        "internal_link",
        "static_form",
        "many_bookmarks",
    ],
)
def test_passive_objects_can_be_imported_and_original_preserved(tmp_path, kind):
    data = sample(kind)
    path = tmp_path / "self-authored.pdf"
    path.write_bytes(data)
    result = inspect(path)
    assert result["pages"] == 3 and result["policy"] == "passive-raster-preview-v1"
    assert SECRET not in json.dumps(result)
    with TestClient(main.app, base_url="http://127.0.0.1") as client:
        response = import_pdf(client, data)
        assert response.status_code == 201, response.text
        doc_id = response.json()["id"]
        book = wait_finished(client, doc_id)
        assert book["searchable_pages"] == 3 and book["failed_pages"] == 0
        assert library_store.pdf_path(doc_id).read_bytes() == data
        assert (
            client.get(f"/api/library/documents/{doc_id}/pages/2/image").status_code
            == 200
        )
        viewer = client.get(f"/api/library/documents/{doc_id}/original")
        assert viewer.headers["content-type"].startswith("text/html")
        assert "object-src 'none'" in viewer.headers["content-security-policy"]
        assert SECRET not in viewer.text
        assert "<embed" not in viewer.text and "<iframe" not in viewer.text
        assert data not in viewer.content


CASES = [
    ("form_unknown", "PDF_INVALID_OBJECT", "form_field", None),
    ("document_js", "PDF_DOCUMENT_JAVASCRIPT_BLOCKED", "document_javascript", None),
    ("open_js", "PDF_JAVASCRIPT_ACTION_BLOCKED", "document_open_action", None),
    ("annotation_js", "PDF_JAVASCRIPT_ACTION_BLOCKED", "annotation_action", 1),
    (
        "annotation_aa",
        "PDF_JAVASCRIPT_ACTION_BLOCKED",
        "annotation_additional_action",
        1,
    ),
    ("page_aa", "PDF_JAVASCRIPT_ACTION_BLOCKED", "page_additional_action", 1),
    (
        "document_aa",
        "PDF_JAVASCRIPT_ACTION_BLOCKED",
        "document_additional_action",
        None,
    ),
    ("next_js", "PDF_JAVASCRIPT_ACTION_BLOCKED", "document_open_action", None),
    ("form_js", "PDF_JAVASCRIPT_ACTION_BLOCKED", "form_field", None),
    ("widget_parent_js", "PDF_JAVASCRIPT_ACTION_BLOCKED", "form_field", 1),
    ("outline_js", "PDF_JAVASCRIPT_ACTION_BLOCKED", "outline_action", None),
    ("xfa", "PDF_XFA_BLOCKED", "acroform", None),
    ("url", "PDF_EXTERNAL_URL_BLOCKED", "document_open_action", None),
    ("annotation_url", "PDF_EXTERNAL_URL_BLOCKED", "annotation_action", 1),
    ("launch", "PDF_LAUNCH_BLOCKED", "document_open_action", None),
    ("submit", "PDF_SUBMIT_BLOCKED", "document_open_action", None),
    ("import", "PDF_SUBMIT_BLOCKED", "document_open_action", None),
    ("remote", "PDF_REMOTE_GOTO_BLOCKED", "document_open_action", None),
    ("unknown", "PDF_UNKNOWN_ACTION_BLOCKED", "document_open_action", None),
    ("print", "PDF_UNKNOWN_ACTION_BLOCKED", "document_open_action", None),
    ("embedded", "PDF_EMBEDDED_FILES_BLOCKED", "embedded_files", None),
    ("file_annotation", "PDF_EMBEDDED_FILES_BLOCKED", "annotation", 1),
    ("media", "PDF_MEDIA_BLOCKED", "annotation", 1),
    ("cycle", "PDF_OBJECT_LIMIT", "document_open_action", None),
    ("bad_destination", "PDF_INVALID_DESTINATION", "document_open_action", None),
    ("unresolved_destination", "PDF_INVALID_DESTINATION", "document_open_action", None),
    ("encrypted", "PDF_ENCRYPTED", "document", None),
]


@pytest.mark.parametrize("kind,code,scope,page", CASES)
def test_dangerous_and_unverifiable_objects_are_rejected(
    tmp_path, kind, code, scope, page
):
    data = sample(kind)
    path = tmp_path / "self-authored.pdf"
    path.write_bytes(data)
    with pytest.raises(PDFPolicyError) as caught:
        inspect(path)
    expected = caught.value.diagnostic()
    assert (
        expected["code"] == code
        and expected["object_type"] == scope
        and expected["pdf_page"] == page
    )
    assert SECRET not in json.dumps(expected)
    with TestClient(main.app, base_url="http://127.0.0.1") as client:
        result = import_pdf(client, data)
        assert result.status_code == 422, result.text
        detail = result.json()["detail"]
        assert (
            detail["code"] == code
            and detail["object_type"] == scope
            and detail["pdf_page"] == page
        )
        assert detail["worker_exit_code"] == 1
        assert SECRET not in result.text
        assert library_store.documents() == []


def test_scanned_image_is_passive_and_render_does_not_init_forms(tmp_path, monkeypatch):
    import pypdfium2
    from PIL import Image

    image = Image.new("RGB", (600, 800), "white")
    data = BytesIO()
    image.save(data, format="PDF")
    path = tmp_path / "scan.pdf"
    path.write_bytes(data.getvalue())
    assert inspect(path)["pages"] == 1

    def forbidden(*args, **kwargs):
        raise AssertionError("Forms must not be initialized")

    monkeypatch.setattr(pypdfium2.PdfDocument, "init_forms", forbidden)
    render(path, 1, tmp_path / "scan.png")
    assert (tmp_path / "scan.png").is_file()
    with TestClient(main.app, base_url="http://127.0.0.1") as client:
        response = import_pdf(client, data.getvalue())
        assert response.status_code == 201
        book = wait_finished(client, response.json()["id"])
        assert book["processed_pages"] == 1 and book["needs_ocr_pages"] == 1
        assert book["searchable_pages"] == 0  # Do not pretend a blank scan has text.


def test_corrupt_pdf_has_fixed_error_and_no_body_leak():
    with TestClient(main.app, base_url="http://127.0.0.1") as client:
        result = import_pdf(client, b"%PDF-1.7\n" + SECRET.encode() + b"\n%%EOF")
        assert result.status_code == 422
        assert result.json()["detail"]["code"] == "PDF_STRUCTURE_REJECTED"
        assert SECRET not in result.text


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("open_destination", "PDF_PRECHECK_OK"),
        ("open_js", "PDF_JAVASCRIPT_ACTION_BLOCKED"),
        ("xfa", "PDF_XFA_BLOCKED"),
        ("embedded", "PDF_EMBEDDED_FILES_BLOCKED"),
    ],
)
def test_readonly_mac_diagnostic_protocol(tmp_path, kind, expected):
    path = tmp_path / "self-authored.pdf"
    data = sample(kind)
    path.write_bytes(data)
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts/diagnose_pdf_import.py"), str(path)],
        capture_output=True,
        text=True,
        timeout=35,
    )
    assert (
        expected in run.stdout
        and "对象类别=" in run.stdout
        and "耗时=" in run.stdout
        and "进程退出码=" in run.stdout
    )
    assert SECRET not in run.stdout + run.stderr
    assert run.returncode == (0 if expected == "PDF_PRECHECK_OK" else 1)
    assert path.read_bytes() == data


def test_untrusted_worker_error_fields_are_not_echoed():
    assert (
        safe_failure({"code": "PRIVATE", "object_type": "document", "message": SECRET})
        is None
    )
    assert safe_failure({"code": [], "object_type": {}}) is None
    value = safe_failure(
        {
            "code": "PDF_XFA_BLOCKED",
            "object_type": "acroform",
            "message": SECRET,
            "advice": SECRET,
        }
    )
    assert SECRET not in json.dumps(value)
