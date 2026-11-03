"""Read-only local reproduction probe. Never imports a PDF into the library.
Run with the project's virtualenv; prints only fixed diagnostic codes, not PDF text.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def classify(error):
    message = str(error).lower()
    if "加密" in message or "encrypt" in message or "password" in message:
        return "PDF_ENCRYPTED", "使用你有权解密的本机副本；不要移除安全校验。"
    if "1500" in message:
        return "PDF_PAGE_LIMIT", "在本机保留原件并拆分为不超过1500页的副本。"
    if any(word in message for word in ("主动", "脚本", "表单", "附件")):
        return (
            "PDF_ACTIVE_CONTENT_BLOCKED",
            "文件触发主动动作、表单或附件规则；需检查具体对象后再判断，不能关闭所有检查。",
        )
    if any(
        word in message
        for word in ("xref", "trailer", "startxref", "eof", "pdf header")
    ):
        return (
            "PDF_STRUCTURE_REJECTED",
            "旧PDF的交叉引用或文件结构不被当前严格解析器接受；保留原件和本次诊断，待兼容性修复。",
        )
    if isinstance(error, MemoryError):
        return "PDF_MEMORY_LIMIT", "进程达到资源限制；保留原件，尝试较小的本机副本。"
    return (
        "PDF_PARSER_EXCEPTION",
        "解析失败，需结合异常类型在受控进程中复现；不要上传全文或关闭检查。",
    )


def child(pdf):
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from app.pdf_worker import inspect, limits

        limits()
        data = inspect(str(pdf))  # Exactly the current production precheck.
        print(json.dumps({"code": "PDF_PRECHECK_OK", "pages": data["pages"]}))
        return 0
    except Exception as error:
        code, advice = classify(error)
        print(
            json.dumps(
                {
                    "code": code,
                    "exception_type": type(error).__name__,
                    "advice": advice,
                },
                ensure_ascii=False,
            )
        )
        return 1


def probe_origin(backend, origin):
    url = urllib.parse.urlparse(backend)
    if (
        url.scheme != "http"
        or url.hostname not in ("localhost", "127.0.0.1", "::1")
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("后端地址必须为不含凭据的本机 HTTP 地址。")
    origin_url = urllib.parse.urlparse(origin)
    if not origin_url.hostname or origin_url.username or origin_url.password:
        raise ValueError("请仅提供不含凭据的浏览器页面地址。")
    # An Origin contains no URL query/path; never echo arbitrary query parameters.
    normalized = f"{origin_url.scheme}://{origin_url.netloc}"
    request = urllib.request.Request(
        backend.rstrip("/") + "/api/library/documents", headers={"Origin": normalized}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=8) as response:
            # Do not read or print the library catalog.
            return f"ORIGIN_ALLOWED (HTTP {response.status})"
    except urllib.error.HTTPError as error:
        error.close()
        return f"ORIGIN_REJECTED (HTTP {error.code})"
    except (urllib.error.URLError, TimeoutError):
        return "BACKEND_UNREACHABLE：确认8001后端已启动，且前端代理指向同一端口。"


def main():
    parser = argparse.ArgumentParser(
        description="只读PDF预检诊断：不写知识库，不发送模型，不输出正文或密钥。"
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--backend", default="http://127.0.0.1:8001")
    parser.add_argument(
        "--origin", help="出现错误时浏览器地址栏的地址，例如 http://localhost:5175"
    )
    parser.add_argument("--_child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._child:
        return child(args.pdf)
    if not args.pdf.is_file():
        parser.error("找不到本机PDF文件。")
    size = args.pdf.stat().st_size
    print("模式：只读；原件、.env、Gemini配置和已有知识库均不修改。", flush=True)
    print(f"阶段=file_validation 文件大小={size} bytes", flush=True)
    if size > 100 * 1024 * 1024:
        print("代码=PDF_SIZE_LIMIT；当前每份上限100MB。请保留原件，拆分副本。")
        return 1
    with args.pdf.open("rb") as file:
        if not file.read(1024).lstrip().startswith(b"%PDF-"):
            print("代码=PDF_MAGIC_INVALID；当前文件头校验不通过，需检查原始文件格式。")
            return 1
    if args.origin:
        try:
            print(
                "阶段=origin_check 代码=" + probe_origin(args.backend, args.origin),
                flush=True,
            )
        except ValueError as error:
            parser.error(str(error))
    print("阶段=pdf_precheck；使用现有严格解析和25秒时限…", flush=True)
    started = time.monotonic()
    env = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TESSDATA_PREFIX", "SYSTEMROOT")
        if key in os.environ
    }
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            str(args.pdf.resolve()),
            "--_child",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=(os.name == "posix"),
    )
    try:
        output, _ = process.communicate(timeout=25)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.communicate()
        print(
            "代码=PDF_PRECHECK_TIMEOUT；25秒预检时限达到，尚未进入OCR或索引。保留原件，待预检兼容性/耗时分析。"
        )
        return 1
    print(
        f"阶段=pdf_precheck 耗时={time.monotonic() - started:.2f}s 进程退出码={process.returncode}"
    )
    try:
        result = json.loads(output.decode().strip().splitlines()[-1])
    except (ValueError, IndexError, UnicodeError):
        print(
            "代码=PDF_PROCESS_TERMINATED；进程未返回诊断结果，可能被资源限制或系统终止。原始错误输出未展示，以保护文档内容。"
        )
        return 1
    print("代码=" + result["code"])
    if "pages" in result:
        print(f"预检页数={result['pages']}；这不等于已导入、OCR完成或已建立索引。")
    if "exception_type" in result:
        print("异常类型=" + result["exception_type"])
    if "advice" in result:
        print("建议=" + result["advice"])
    engine = shutil.which("tesseract")
    if engine:
        try:
            langs = subprocess.run(
                [engine, "--list-langs"], capture_output=True, text=True, timeout=5
            )
            print(
                "OCR语言包检查="
                + (
                    "chi_sim+eng可用"
                    if {"chi_sim", "eng"} <= set(langs.stdout.split())
                    else "需检查chi_sim/eng语言包"
                )
            )
        except (OSError, subprocess.TimeoutExpired):
            print("OCR语言包检查=引擎检查失败")
    else:
        print("OCR语言包检查=当前终端PATH未找到tesseract")
    print("本脚本未运行OCR、未上传文件、未读写知识库；请仅回传以上诊断代码。")
    return process.returncode


if __name__ == "__main__":
    sys.exit(main())
