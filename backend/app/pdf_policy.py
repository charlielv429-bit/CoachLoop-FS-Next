"""Fail-closed passive PDF policy. No scripts, URLs, names or text in diagnostics."""

from collections import Counter
import math
from pypdf.generic import ArrayObject, DictionaryObject, NullObject, NameObject

MESSAGES = {
    "PDF_STRUCTURE_REJECTED": "PDF结构无法被严格解析，保持拒绝。",
    "PDF_RESOURCE_LIMIT": "PDF处理触及资源限制，保持拒绝。",
    "PDF_PARSE_ERROR": "PDF处理异常，无法可靠判断，保持拒绝。",
    "PDF_DOCUMENT_JAVASCRIPT_BLOCKED": "文档包含JavaScript名称树，拒绝导入。",
    "PDF_JAVASCRIPT_ACTION_BLOCKED": "对象包含JavaScript动作，拒绝导入。",
    "PDF_EMBEDDED_FILES_BLOCKED": "对象包含附件或嵌入文件，拒绝导入。",
    "PDF_XFA_BLOCKED": "表单包含动态XFA内容，拒绝导入。",
    "PDF_LAUNCH_BLOCKED": "对象包含外部程序或文件启动动作，拒绝导入。",
    "PDF_SUBMIT_BLOCKED": "对象包含数据提交或导入动作，拒绝导入。",
    "PDF_EXTERNAL_URL_BLOCKED": "对象包含外部URL动作，拒绝导入。",
    "PDF_REMOTE_GOTO_BLOCKED": "对象包含远程文件跳转，拒绝导入。",
    "PDF_MEDIA_BLOCKED": "对象包含多媒体或外部交互内容，拒绝导入。",
    "PDF_UNKNOWN_ACTION_BLOCKED": "无法可靠判断此动作，保持拒绝。",
    "PDF_INVALID_DESTINATION": "无法验证目标为本文档内页面，保持拒绝。",
    "PDF_INVALID_OBJECT": "交互对象结构无效或不受支持，保持拒绝。",
    "PDF_OBJECT_LIMIT": "交互对象循环、过深或超出检查上限。",
    "PDF_ENCRYPTED": "文件已加密，请使用有权解密的本机副本。",
    "PDF_PAGE_LIMIT": "每份PDF需为1–1500页。",
}
SCOPES = frozenset(
    (
        "document",
        "document_javascript",
        "embedded_files",
        "acroform",
        "document_open_action",
        "document_additional_action",
        "page_additional_action",
        "annotation",
        "annotation_action",
        "annotation_additional_action",
        "form_field",
        "outline_action",
        "destination",
    )
)
ADVICE = (
    "保留原件；仅回传错误代码、对象类别和页码。不要关闭安全检查、执行脚本或打开附件。"
)
NOTE_CODES = frozenset(
    (
        "PDF_INTERNAL_DESTINATION_IGNORED",
        "PDF_INTERNAL_ACTION_IGNORED",
        "PDF_STATIC_FORM_ISOLATED",
        "PDF_ORDINARY_ANNOTATION_ALLOWED",
    )
)


class PDFPolicyError(ValueError):
    def __init__(self, code, object_type="document", pdf_page=None):
        self.code, self.object_type, self.pdf_page = code, object_type, pdf_page
        super().__init__(MESSAGES[code])

    def diagnostic(self):
        return {
            "code": self.code,
            "object_type": self.object_type,
            "pdf_page": self.pdf_page,
            "message": MESSAGES[self.code],
            "advice": ADVICE,
        }


def safe_failure(value):
    """Only accept fixed protocol fields from an untrusted parsing subprocess."""
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("code"), str)
        or not isinstance(value.get("object_type"), str)
        or value.get("code") not in MESSAGES
        or value.get("object_type") not in SCOPES
    ):
        return None
    page = value.get("pdf_page")
    if page is not None and (type(page) is not int or not 1 <= page <= 1500):
        return None
    return PDFPolicyError(value["code"], value["object_type"], page).diagnostic()


class Policy:
    def __init__(self, reader):
        self.reader = reader
        self.pages = list(reader.pages)
        self.page_ids = {
            (p.indirect_reference.idnum, p.indirect_reference.generation)
            for p in self.pages
            if p.indirect_reference
        }
        self.visiting = set()
        self.nodes = 0
        self.notes = Counter()

    def fail(self, code, scope, page=None):
        raise PDFPolicyError(code, scope, page)

    def resolve(self, value, scope, page=None):
        try:
            value = value.get_object() if hasattr(value, "get_object") else value
            return None if isinstance(value, NullObject) else value
        except Exception:
            self.fail("PDF_INVALID_OBJECT", scope, page)

    def dictionary(self, value, scope, page=None):
        value = self.resolve(value, scope, page)
        if not isinstance(value, DictionaryObject):
            self.fail("PDF_INVALID_OBJECT", scope, page)
        return value

    def note(self, code, scope):
        self.notes[(code, scope)] += 1

    def enter(self, value, scope, page, depth):
        self.nodes += 1
        identity = id(value)
        if depth > 24 or self.nodes > 20000 or identity in self.visiting:
            self.fail("PDF_OBJECT_LIMIT", scope, page)
        self.visiting.add(identity)
        return identity

    def destination(self, value, scope, page=None):
        value = self.resolve(value, scope, page)
        if isinstance(value, str):
            # Named destinations are resolved locally; their names are never logged.
            try:
                targets = self.reader.named_destinations
                target = targets.get(value) or targets.get(value.lstrip("/"))
                number = (
                    self.reader.get_destination_page_number(target) if target else None
                )
                if number is None or not 0 <= number < len(self.pages):
                    raise ValueError()
            except Exception:
                self.fail("PDF_INVALID_DESTINATION", scope, page)
        elif isinstance(value, ArrayObject) and len(value) >= 2:
            first = value[0]
            if type(first) is int or (
                isinstance(first, int) and not isinstance(first, bool)
            ):
                valid = 0 <= first < len(self.pages)
            else:
                ref = (
                    first
                    if hasattr(first, "idnum")
                    else getattr(first, "indirect_reference", None)
                )
                valid = ref is not None and (ref.idnum, ref.generation) in self.page_ids
            counts = {
                "/XYZ": 5,
                "/Fit": 2,
                "/FitH": 3,
                "/FitV": 3,
                "/FitR": 6,
                "/FitB": 2,
                "/FitBH": 3,
                "/FitBV": 3,
            }
            if not valid or counts.get(str(value[1])) != len(value):
                self.fail("PDF_INVALID_DESTINATION", scope, page)
            for operand in value[2:]:
                operand = self.resolve(operand, scope, page)
                if operand is not None:
                    try:
                        valid = not isinstance(
                            operand, (bool, str, dict, list)
                        ) and math.isfinite(float(operand))
                    except (ValueError, TypeError, OverflowError):
                        valid = False
                    if not valid:
                        self.fail("PDF_INVALID_DESTINATION", scope, page)
        else:
            self.fail("PDF_INVALID_DESTINATION", scope, page)
        self.note("PDF_INTERNAL_DESTINATION_IGNORED", scope)

    def action(self, value, scope, page=None, depth=0):
        value = self.resolve(value, scope, page)
        if value is None:
            return
        if isinstance(value, ArrayObject):
            identity = self.enter(value, scope, page, depth)
            try:
                for item in value:
                    self.action(item, scope, page, depth + 1)
            finally:
                self.visiting.remove(identity)
            return
        value = self.dictionary(value, scope, page)
        identity = self.enter(value, scope, page, depth)
        try:
            kind = value.get("/S")
            if not isinstance(kind, NameObject):
                self.fail("PDF_UNKNOWN_ACTION_BLOCKED", scope, page)
            denied = {
                "/JavaScript": "PDF_JAVASCRIPT_ACTION_BLOCKED",
                "/Launch": "PDF_LAUNCH_BLOCKED",
                "/SubmitForm": "PDF_SUBMIT_BLOCKED",
                "/ImportData": "PDF_SUBMIT_BLOCKED",
                "/URI": "PDF_EXTERNAL_URL_BLOCKED",
                "/GoToR": "PDF_REMOTE_GOTO_BLOCKED",
                "/GoToE": "PDF_REMOTE_GOTO_BLOCKED",
                "/Rendition": "PDF_MEDIA_BLOCKED",
                "/Movie": "PDF_MEDIA_BLOCKED",
                "/Sound": "PDF_MEDIA_BLOCKED",
            }
            if kind in denied:
                self.fail(denied[kind], scope, page)
            if kind == "/GoTo":
                self.destination(value.get("/D"), scope, page)
            elif kind == "/Named" and value.get("/N") in (
                "/NextPage",
                "/PrevPage",
                "/FirstPage",
                "/LastPage",
            ):
                self.note("PDF_INTERNAL_ACTION_IGNORED", scope)
            else:
                self.fail("PDF_UNKNOWN_ACTION_BLOCKED", scope, page)
            if "/Next" in value:
                self.action(value["/Next"], scope, page, depth + 1)
        finally:
            self.visiting.remove(identity)

    def additional(self, value, scope, page=None):
        if self.resolve(value, scope, page) is None:
            return
        value = self.dictionary(value, scope, page)
        for action in value.values():
            self.action(action, scope, page)

    def field(self, value, depth=0):
        field = self.dictionary(value, "form_field")
        identity = self.enter(field, "form_field", None, depth)
        try:
            if "/FT" in field and field["/FT"] not in ("/Btn", "/Tx", "/Ch", "/Sig"):
                self.fail("PDF_INVALID_OBJECT", "form_field")
            if "/AF" in field:
                self.fail("PDF_EMBEDDED_FILES_BLOCKED", "form_field")
            if "/A" in field:
                self.action(field["/A"], "form_field")
            if "/AA" in field:
                self.additional(field["/AA"], "form_field")
            if "/Kids" in field:
                kids = self.resolve(field["/Kids"], "form_field")
                if not isinstance(kids, ArrayObject):
                    self.fail("PDF_INVALID_OBJECT", "form_field")
                for item in kids:
                    self.field(item, depth + 1)
        finally:
            self.visiting.remove(identity)

    def outline(self, value, depth=0):
        siblings = set()
        while value is not None:
            value = self.resolve(value, "outline_action")
            if value is None:
                return
            item = self.dictionary(value, "outline_action")
            if id(item) in siblings:
                self.fail("PDF_OBJECT_LIMIT", "outline_action")
            siblings.add(id(item))
            identity = self.enter(item, "outline_action", None, depth)
            try:
                if "/A" in item:
                    self.action(item["/A"], "outline_action")
                if "/Dest" in item:
                    self.destination(item["/Dest"], "outline_action")
                if "/First" in item:
                    self.outline(item["/First"], depth + 1)
            finally:
                self.visiting.remove(identity)
            value = item.get("/Next")

    def widget_parents(self, item, page):
        seen = set()
        while "/Parent" in item:
            item = self.dictionary(item["/Parent"], "form_field", page)
            if id(item) in seen or len(seen) >= 24:
                self.fail("PDF_OBJECT_LIMIT", "form_field", page)
            seen.add(id(item))
            if "/AF" in item:
                self.fail("PDF_EMBEDDED_FILES_BLOCKED", "form_field", page)
            if "/A" in item:
                self.action(item["/A"], "form_field", page)
            if "/AA" in item:
                self.additional(item["/AA"], "form_field", page)

    def check(self):
        catalog = self.dictionary(self.reader.trailer["/Root"], "document")
        if "/AF" in catalog:
            self.fail("PDF_EMBEDDED_FILES_BLOCKED", "embedded_files")
        if "/Names" in catalog:
            names = self.dictionary(catalog["/Names"], "document")
            if "/JavaScript" in names:
                self.fail("PDF_DOCUMENT_JAVASCRIPT_BLOCKED", "document_javascript")
            if "/EmbeddedFiles" in names:
                self.fail("PDF_EMBEDDED_FILES_BLOCKED", "embedded_files")
        if "/OpenAction" in catalog:
            action = self.resolve(catalog["/OpenAction"], "document_open_action")
            if isinstance(action, (ArrayObject, str)):
                self.destination(action, "document_open_action")
            elif action is not None:
                self.action(action, "document_open_action")
        if "/AA" in catalog:
            self.additional(catalog["/AA"], "document_additional_action")
        if "/AcroForm" in catalog:
            form = self.dictionary(catalog["/AcroForm"], "acroform")
            if "/XFA" in form:
                self.fail("PDF_XFA_BLOCKED", "acroform")
            if "/A" in form:
                self.action(form["/A"], "acroform")
            if "/AA" in form:
                self.additional(form["/AA"], "acroform")
            for key in ("/Fields", "/CO"):
                if key in form:
                    fields = self.resolve(form[key], "acroform")
                    if not isinstance(fields, ArrayObject):
                        self.fail("PDF_INVALID_OBJECT", "acroform")
                    for field in fields:
                        self.field(field)
            self.note("PDF_STATIC_FORM_ISOLATED", "acroform")
        if "/Outlines" in catalog:
            self.outline(catalog["/Outlines"])
        ordinary = {
            "/Text",
            "/Link",
            "/FreeText",
            "/Line",
            "/Square",
            "/Circle",
            "/Polygon",
            "/PolyLine",
            "/Highlight",
            "/Underline",
            "/Squiggly",
            "/StrikeOut",
            "/Stamp",
            "/Caret",
            "/Ink",
            "/Popup",
            "/Widget",
            "/Redact",
            "/Watermark",
        }
        for number, page in enumerate(self.pages, 1):
            if "/AF" in page:
                self.fail("PDF_EMBEDDED_FILES_BLOCKED", "annotation", number)
            if "/AA" in page:
                self.additional(page["/AA"], "page_additional_action", number)
            if "/Annots" not in page:
                continue
            annotations = self.resolve(page["/Annots"], "annotation", number)
            if not isinstance(annotations, ArrayObject):
                self.fail("PDF_INVALID_OBJECT", "annotation", number)
            for reference in annotations:
                item = self.dictionary(reference, "annotation", number)
                self.nodes += 1
                if self.nodes > 20000:
                    self.fail("PDF_OBJECT_LIMIT", "annotation", number)
                subtype = item.get("/Subtype")
                if not isinstance(subtype, NameObject):
                    self.fail("PDF_INVALID_OBJECT", "annotation", number)
                if subtype == "/Widget":
                    self.widget_parents(item, number)
                if subtype == "/FileAttachment" or "/FS" in item or "/AF" in item:
                    self.fail("PDF_EMBEDDED_FILES_BLOCKED", "annotation", number)
                if subtype in ("/RichMedia", "/Movie", "/Screen", "/3D", "/Sound"):
                    self.fail("PDF_MEDIA_BLOCKED", "annotation", number)
                if subtype not in ordinary:
                    self.fail("PDF_INVALID_OBJECT", "annotation", number)
                if "/A" in item:
                    self.action(item["/A"], "annotation_action", number)
                if "/AA" in item:
                    self.additional(item["/AA"], "annotation_additional_action", number)
                if "/Dest" in item:
                    self.destination(item["/Dest"], "annotation_action", number)
                self.note("PDF_ORDINARY_ANNOTATION_ALLOWED", "annotation")
        return [
            {"code": code, "object_type": scope, "count": count}
            for (code, scope), count in sorted(self.notes.items())
        ]
