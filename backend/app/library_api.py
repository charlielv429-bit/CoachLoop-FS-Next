import asyncio
import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from . import library_store as store
from .pdf_policy import safe_failure, MESSAGES, NOTE_CODES, SCOPES
from .pdf_viewer import passive_viewer

router = APIRouter(prefix="/api/library")
MAX_BYTES = 100 * 1024 * 1024
WORKER = Path(__file__).with_name("pdf_worker.py")
process_lock = threading.Lock()
preview_slots = threading.BoundedSemaphore(2)
upload_slots = asyncio.Semaphore(2)


def run_worker(args, timeout=100):
    # Do not inherit model credentials, proxy authentication or other private env values.
    child_env = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TESSDATA_PREFIX", "SYSTEMROOT")
        if key in os.environ
    }
    command = [sys.executable, str(WORKER), *map(str, args)]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=child_env,
        start_new_session=(os.name == "posix"),
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.communicate()
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def ocr_status():
    if not shutil.which("tesseract"):
        return {
            "available": False,
            "message": "本机未安装离线 OCR 引擎；文本型 PDF 仍可直接导入。",
        }
    try:
        result = subprocess.run(
            ["tesseract", "--list-langs"], capture_output=True, text=True, timeout=5
        )
        available = result.returncode == 0 and {"chi_sim", "eng"} <= set(
            result.stdout.split()
        )
        return {
            "available": available,
            "message": "本机中文＋英文 OCR 可用"
            if available
            else "本机缺少中文或英文 OCR 语言包；可先导入，安装后重新处理扫描页。",
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "message": "本机 OCR 引擎检查失败。"}


class Jobs:
    def __init__(self):
        self.pending = queue.Queue()
        self.scheduled = set()
        self.guard = threading.Lock()
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop.clear()
        self.thread = threading.Thread(
            target=self.work, daemon=True, name="local-pdf-indexer"
        )
        self.thread.start()
        for item in store.documents():
            if item["status"] == "queued":
                self.add(item["id"])

    def add(self, doc_id):
        with self.guard:
            if doc_id not in self.scheduled:
                self.scheduled.add(doc_id)
                self.pending.put(doc_id)

    def work(self):
        while not self.stop.is_set():
            try:
                doc_id = self.pending.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                self.process(doc_id)
            except Exception:
                with store.db() as con:
                    con.execute(
                        "UPDATE documents SET status='error',error='索引处理中断；可点击继续处理，已完成页保留。' WHERE id=?",
                        (doc_id,),
                    )
            finally:
                with self.guard:
                    self.scheduled.discard(doc_id)
                self.pending.task_done()

    def process(self, doc_id):
        document = store.document(doc_id)
        if not document:
            return
        with store.db() as con:
            con.execute(
                "UPDATE documents SET status='processing',error='' WHERE id=?",
                (doc_id,),
            )
            completed = {
                r[0]
                for r in con.execute(
                    "SELECT pdf_page FROM pages WHERE doc_id=?", (doc_id,)
                )
            }
        remaining = [
            p for p in range(1, document["total_pages"] + 1) if p not in completed
        ]
        # Jobs are serialized; each bounded batch commits individual pages.
        for start in range(0, len(remaining), 5):
            if self.stop.is_set():
                with store.db() as con:
                    con.execute(
                        "UPDATE documents SET status='queued' WHERE id=?", (doc_id,)
                    )
                return
            group = remaining[start : start + 5]
            # Resumed gaps may be noncontiguous: process contiguous spans only.
            spans = []
            for number in group:
                if spans and spans[-1][-1] + 1 == number:
                    spans[-1].append(number)
                else:
                    spans.append([number])
            for span in spans:
                with tempfile.TemporaryDirectory(dir=store.root()) as directory:
                    args = [
                        "batch",
                        store.pdf_path(doc_id),
                        "--start",
                        span[0],
                        "--end",
                        span[-1],
                        "--out",
                        directory,
                    ]
                    if document["ocr"]:
                        args.append("--ocr")
                    try:
                        run_worker(args, timeout=150)
                    except (subprocess.TimeoutExpired, OSError):
                        pass
                    for number in span:
                        checkpoint = Path(directory) / f"{number}.json"
                        try:
                            result = json.loads(checkpoint.read_text())
                        except (OSError, ValueError):
                            result = {
                                "page": number,
                                "text": "",
                                "extraction": "failed",
                                "quality": None,
                                "text_status": "needs_review",
                                "error": "此页超出解析限制或进程失败，可重新处理。",
                            }
                        store.write_page(doc_id, result)
        with store.db() as con:
            review = con.execute(
                "SELECT COUNT(*) FROM pages WHERE doc_id=? AND text_status NOT IN ('checked','extracted_unchecked')",
                (doc_id,),
            ).fetchone()[0]
            con.execute(
                "UPDATE documents SET status=? WHERE id=?",
                ("needs_review" if review else "complete", doc_id),
            )


jobs = Jobs()


def get_document(doc_id):
    try:
        item = store.document(doc_id)
    except ValueError:
        item = None
    if not item:
        raise HTTPException(404, "教材不存在。")
    return item


def require_idle(item):
    if item["status"] in ("processing", "queued"):
        raise HTTPException(409, "教材正在处理，请等待当前批次完成后操作。")


@router.get("/documents")
def list_documents():
    return {
        "documents": store.documents(),
        "ocr": ocr_status(),
        "max_bytes": MAX_BYTES,
        "max_pages": 1500,
    }


@router.post("/documents", status_code=201)
async def upload(
    request: Request,
    title: str = Query(min_length=1, max_length=160),
    author: str = Query(default="", max_length=120),
    edition: str = Query(default="", max_length=120),
    provenance: str = Query(default="用户本机授权资料", max_length=300),
    ocr: bool = False,
):
    if not title.strip():
        raise HTTPException(422, "教材名称不能为空。")
    if request.headers.get("content-type", "").split(";")[0] != "application/pdf":
        raise HTTPException(415, "仅支持 PDF 文件。")
    if ocr and not ocr_status()["available"]:
        raise HTTPException(422, ocr_status()["message"])
    if len(store.documents()) >= 30:
        raise HTTPException(409, "当前本地库最多30份文档，请先删除不需要的教材。")
    path = store.root() / f"{uuid.uuid4().hex}.part"
    hasher = hashlib.sha256()
    size = 0
    async with upload_slots:
        try:
            with path.open("xb") as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(413, "单份 PDF 最大100MB，请拆分后导入。")
                    output.write(chunk)
                    hasher.update(chunk)
            with path.open("rb") as file:
                if not file.read(1024).lstrip().startswith(b"%PDF-"):
                    raise HTTPException(422, "文件内容不是有效 PDF。")
            digest = hasher.hexdigest()
            with store.db() as con:
                existing = con.execute(
                    "SELECT id,title FROM documents WHERE sha256=?", (digest,)
                ).fetchone()
            if existing:
                raise HTTPException(409, f"重复文件：已导入“{existing['title']}”。")

            def precheck_error(
                code, advice, exit_code=None, object_type=None, pdf_page=None
            ):
                return HTTPException(
                    422,
                    {
                        "message": MESSAGES.get(code, "PDF预检未通过，尚未登记教材。"),
                        "object_type": object_type,
                        "pdf_page": pdf_page,
                        "stage": "pdf_precheck",
                        "code": code,
                        "advice": advice,
                        "worker_exit_code": exit_code,
                    },
                )

            try:
                result = await asyncio.to_thread(run_worker, ["inspect", path], 25)
            except subprocess.TimeoutExpired:
                raise precheck_error(
                    "PDF_PRECHECK_TIMEOUT",
                    "预检达到25秒时限，尚未进入OCR。请保留原件，运行只读诊断并回传代码；不要关闭解析限制。",
                ) from None
            except OSError:
                raise precheck_error(
                    "PDF_WORKER_START_FAILED",
                    "本机PDF预检进程未能启动。请确认使用项目虚拟环境安装依赖后重启后端。",
                ) from None
            if result.returncode:
                try:
                    failure = (
                        safe_failure(json.loads(result.stdout).get("error"))
                        if len(result.stdout) <= 16384
                        else None
                    )
                except (ValueError, AttributeError, TypeError):
                    failure = None
                if failure:
                    raise precheck_error(
                        failure["code"],
                        failure["advice"],
                        result.returncode,
                        failure["object_type"],
                        failure["pdf_page"],
                    )
                code = (
                    "PDF_WORKER_TERMINATED"
                    if result.returncode < 0
                    else "PDF_PRECHECK_REJECTED"
                )
                raise precheck_error(
                    code,
                    "原始解析错误可能包含私有内容，页面不会直接显示。请使用只读诊断脚本定位具体规则；不要重新上传整个文件到模型。",
                    result.returncode,
                )
            try:
                inspection = json.loads(result.stdout)
                pages = inspection["pages"]
                if type(pages) is not int or not 1 <= pages <= 1500:
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise precheck_error(
                    "PDF_WORKER_RESPONSE_INVALID",
                    "预检进程没有返回有效页数。请重启后端并运行只读诊断；原件与已有知识库不受影响。",
                ) from None
            doc_id = uuid.uuid4().hex
            # Serialize final duplicate check + file registration.
            with process_lock:
                with store.db() as con:
                    if con.execute(
                        "SELECT 1 FROM documents WHERE sha256=?", (digest,)
                    ).fetchone():
                        raise HTTPException(409, "相同 PDF 正在导入，请刷新列表。")
                    if (
                        con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                        >= 30
                    ):
                        raise HTTPException(409, "本地库最多30份文档。")
                    if (
                        con.execute(
                            "SELECT COALESCE(SUM(total_pages),0) FROM documents"
                        ).fetchone()[0]
                        + pages
                        > 10000
                    ):
                        raise HTTPException(
                            409, "本地库最多10000页，请先删除不需要的教材。"
                        )
                    path.replace(store.pdf_path(doc_id))
                    con.execute(
                        "INSERT INTO documents (id,sha256,title,author,edition,provenance,total_pages,ocr) VALUES (?,?,?,?,?,?,?,?)",
                        (
                            doc_id,
                            digest,
                            title.strip(),
                            author,
                            edition,
                            provenance,
                            pages,
                            int(ocr),
                        ),
                    )
            jobs.add(doc_id)
            objects = inspection.get("objects", [])
            objects = objects if isinstance(objects, list) else []
            notes = [
                n
                for n in objects
                if isinstance(n, dict)
                and isinstance(n.get("code"), str)
                and isinstance(n.get("object_type"), str)
                and n.get("code") in NOTE_CODES
                and n.get("object_type") in SCOPES
                and type(n.get("count")) is int
                and 0 < n["count"] <= 20000
            ][:64]
            return {
                "id": doc_id,
                "total_pages": pages,
                "status": "queued",
                "policy_objects": notes,
            }
        finally:
            path.unlink(missing_ok=True)


class Permission(BaseModel):
    cloud_allowed: bool


@router.patch("/documents/{doc_id}/permission")
def permission(doc_id: str, body: Permission):
    get_document(doc_id)
    with store.db() as con:
        con.execute(
            "UPDATE documents SET cloud_allowed=? WHERE id=?",
            (int(body.cloud_allowed), doc_id),
        )
    return {"cloud_allowed": body.cloud_allowed}


class Retry(BaseModel):
    ocr: bool = False
    all_pages: bool = False


@router.post("/documents/{doc_id}/retry")
def retry(doc_id: str, body: Retry):
    item = get_document(doc_id)
    require_idle(item)
    if body.ocr and not ocr_status()["available"]:
        raise HTTPException(422, ocr_status()["message"])
    with process_lock, store.db() as con:
        # Human-checked pages survive retries. Explicit all_pages rebuilds only machine pages.
        rows = con.execute(
            "SELECT pdf_page FROM pages WHERE doc_id=? AND text_status!='checked'"
            + (
                ""
                if body.all_pages
                else " AND text_status NOT IN ('extracted_unchecked')"
            ),
            (doc_id,),
        ).fetchall()
        for row in rows:
            ids = con.execute(
                "SELECT id FROM chunks WHERE doc_id=? AND pdf_page=?", (doc_id, row[0])
            ).fetchall()
            for chunk in ids:
                con.execute("DELETE FROM chunks_fts WHERE id=?", (chunk[0],))
            con.execute(
                "DELETE FROM chunks WHERE doc_id=? AND pdf_page=?", (doc_id, row[0])
            )
            con.execute(
                "DELETE FROM pages WHERE doc_id=? AND pdf_page=?", (doc_id, row[0])
            )
        con.execute(
            "UPDATE documents SET status='queued',ocr=?,error='' WHERE id=?",
            (int(body.ocr), doc_id),
        )
    jobs.add(doc_id)
    return {"status": "queued"}


@router.delete("/documents/{doc_id}/index")
def clear_index(doc_id: str):
    item = get_document(doc_id)
    require_idle(item)
    with process_lock, store.db() as con:
        rows = con.execute("SELECT id FROM chunks WHERE doc_id=?", (doc_id,)).fetchall()
        for row in rows:
            con.execute("DELETE FROM chunks_fts WHERE id=?", (row["id"],))
        con.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        con.execute("DELETE FROM pages WHERE doc_id=?", (doc_id,))
        con.execute(
            "UPDATE documents SET status='unindexed',cloud_allowed=0,error='' WHERE id=?",
            (doc_id,),
        )
    with store.db() as con:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {"index_deleted": True, "original_preserved": True}


@router.delete("/documents/{doc_id}")
def delete(doc_id: str):
    item = get_document(doc_id)
    require_idle(item)
    with process_lock:
        store.remove(doc_id)
    return {"deleted": True}


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=1000), doc_id: str | None = None):
    return {"results": store.search(q, limit=24, doc_id=doc_id)}


@router.get("/documents/{doc_id}/pages")
def page_list(
    doc_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    get_document(doc_id)
    with store.db() as con:
        rows = con.execute(
            "SELECT pdf_page,printed_page,chapter,extraction,quality,text_status,review_status,error FROM pages WHERE doc_id=? ORDER BY pdf_page LIMIT ? OFFSET ?",
            (doc_id, limit, offset),
        ).fetchall()
    return {"pages": [dict(row) for row in rows]}


@router.get("/documents/{doc_id}/pages/{page}")
def page_text(doc_id: str, page: int):
    item = get_document(doc_id)
    if not 1 <= page <= item["total_pages"]:
        raise HTTPException(404, "原始页不存在。")
    return store.page_record(doc_id, page) or {
        "pdf_page": page,
        "text": "",
        "text_status": "not_processed",
    }


class PageEdit(BaseModel):
    text: str = Field(max_length=24000)
    printed_page: str | None = Field(default=None, max_length=40)
    chapter: str | None = Field(default=None, max_length=180)
    checked: bool
    professional_reviewed: bool = False


@router.put("/documents/{doc_id}/pages/{page}")
def edit_page(doc_id: str, page: int, body: PageEdit):
    item = get_document(doc_id)
    require_idle(item)
    old = store.page_record(doc_id, page)
    if not old:
        raise HTTPException(404, "此页尚未处理。")
    if not body.checked and (
        body.printed_page or body.chapter or body.professional_reviewed
    ):
        raise HTTPException(
            422, "填写印刷页码、章节或专业审核前，请先确认已对照原页核对文本。"
        )
    if body.professional_reviewed and not body.text.strip():
        raise HTTPException(422, "空白正文不能设为专业审核通过。")
    result = {
        "page": page,
        "text": body.text.strip(),
        "extraction": old["extraction"],
        "quality": old["quality"],
        "ocr_attempted": old.get("ocr_attempted", False),
        "text_status": "checked" if body.checked else "needs_review",
        "error": "",
    }
    store.write_page(
        doc_id,
        result,
        body.printed_page or None,
        body.chapter or None,
        "verified" if body.professional_reviewed else "pending",
    )
    with store.db() as con:
        remaining = con.execute(
            "SELECT COUNT(*) FROM pages WHERE doc_id=? AND text_status NOT IN ('checked','extracted_unchecked')",
            (doc_id,),
        ).fetchone()[0]
        con.execute(
            "UPDATE documents SET status=? WHERE id=?",
            ("needs_review" if remaining else "complete", doc_id),
        )
    return {"saved": True}


@router.get("/documents/{doc_id}/pages/{page}/image")
def page_image(doc_id: str, page: int):
    item = get_document(doc_id)
    if not 1 <= page <= item["total_pages"]:
        raise HTTPException(404, "原始页不存在。")
    destination = store.root() / f"{uuid.uuid4().hex}.png"
    if not preview_slots.acquire(blocking=False):
        raise HTTPException(429, "原页预览繁忙，请稍后重试。")
    try:
        run = run_worker(
            ["render", store.pdf_path(doc_id), "--start", page, "--out", destination],
            25,
        )
        if run.returncode:
            raise ValueError()
    except (ValueError, OSError, subprocess.TimeoutExpired):
        destination.unlink(missing_ok=True)
        raise HTTPException(422, "此页预览失败；可尝试打开原 PDF。") from None
    finally:
        preview_slots.release()
    return FileResponse(
        destination,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(destination.unlink, missing_ok=True),
    )


@router.get("/documents/{doc_id}/original")
def original(doc_id: str):
    item = get_document(doc_id)
    if not store.pdf_path(doc_id).is_file():
        raise HTTPException(404, "本机PDF原件不存在。")
    # No PDF bytes, scripts, form widgets, attachments or URLs reach the browser.
    # Existing #page=N citations continue to point to their original page number.
    return passive_viewer(doc_id, item["title"], item["total_pages"])
