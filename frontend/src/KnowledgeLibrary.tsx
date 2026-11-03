import { useEffect, useRef, useState } from "react";
import "./library.css";
export type Evidence = {
  id: string;
  title: string;
  authors: string;
  pages: string | null;
  source_type: string;
  verification_status: string;
  content: string;
  document_id?: string;
  pdf_page?: number;
  printed_page?: string | null;
  preview_url?: string;
  original_url?: string;
  text_status?: string;
  ocr_quality?: number | null;
  can_send?: boolean;
};
type Book = {
  id: string;
  title: string;
  author: string;
  edition: string;
  provenance: string;
  total_pages: number;
  processed_pages: number;
  searchable_pages: number;
  missing_pages: number;
  ocr_pages: number;
  ocr_failed_pages: number;
  failed_pages: number;
  review_pages: number;
  low_quality_pages: number;
  needs_ocr_pages: number;
  unchecked_ocr_pages: number;
  status: string;
  cloud_allowed: boolean;
  error: string;
  ocr: boolean;
};
type ImportItem = {
  file: File;
  title: string;
  author: string;
  edition: string;
  provenance: string;
  ocr: boolean;
  status: string;
  progress: number;
  phase: "selected" | "uploading" | "prechecking" | "queued" | "failed";
};
type Page = {
  pdf_page: number;
  printed_page?: string | null;
  chapter?: string | null;
  text?: string;
  extraction?: string;
  quality?: number | null;
  text_status: string;
  review_status?: string;
  error?: string;
};
const catalog = [
  ["花样滑冰", "王树本", ""],
  ["花样滑冰技法与指导", "李乡状等", ""],
  ["怎样练习花样滑冰", "沈祖修、杨家声", ""],
  ["花样滑冰", "韦迪主编", ""],
  ["少年儿童业余训练教材·花样滑冰", "", ""],
  ["ISU Technical Panel Handbook Single Skating", "ISU", "2025–2026"],
  ["花样滑冰竞赛规则（1987）", "", "1987"],
];
export const reviewLabel = (s: string) =>
  s === "verified"
    ? "已人工专业审核"
    : s === "confirmed"
      ? "已确认课程设计"
      : "待专业审核";
export const textLabel = (s?: string) =>
  ({
    checked: "文本已人工核对",
    extracted_unchecked: "文本自动提取 · 未核对",
    ocr_unchecked: "OCR成功 · 文本待核对",
    low_quality: "OCR低质量 · 待核对",
    needs_ocr: "扫描页 · 需要OCR",
    needs_review: "处理失败或待核对",
    not_processed: "尚未处理",
  })[s ?? ""] ??
  s ??
  "";
export function importError(data: {
  detail?: unknown;
  stage?: string;
  code?: string;
  advice?: string;
}): string {
  const detail = data.detail;
  const payload =
    detail && typeof detail === "object"
      ? (detail as {
          message?: string;
          stage?: string;
          code?: string;
          advice?: string;
          worker_exit_code?: number;
          object_type?: string;
          pdf_page?: number;
        })
      : data;
  const message =
    typeof detail === "string"
      ? detail
      : "message" in payload && typeof payload.message === "string"
        ? payload.message
        : "导入请求失败。";
  const stage = { origin_check: "页面来源校验", pdf_precheck: "PDF预检" }[
    payload.stage ?? ""
  ];
  return [
    message,
    stage && `阶段：${stage}`,
    payload.code && `错误代码：${payload.code}`,
    "worker_exit_code" in payload &&
      payload.worker_exit_code != null &&
      `进程退出码：${payload.worker_exit_code}`,
    "object_type" in payload &&
      payload.object_type &&
      `对象类别：${payload.object_type}`,
    "pdf_page" in payload && payload.pdf_page && `PDF页码：${payload.pdf_page}`,
    payload.advice,
  ]
    .filter(Boolean)
    .join(" · ");
}
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const r = await fetch(path, options);
  let data;
  try {
    data = await r.json();
  } catch {
    throw Error("服务响应异常，请确认后端已启动。");
  }
  if (!r.ok) throw Error(importError(data));
  return data as T;
}
const json = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
export default function KnowledgeLibrary() {
  const [books, setBooks] = useState<Book[]>([]),
    [items, setItems] = useState<ImportItem[]>([]),
    [uploading, setUploading] = useState(false),
    [ocr, setOcr] = useState({ available: false, message: "" }),
    [error, setError] = useState(""),
    [query, setQuery] = useState(""),
    [results, setResults] = useState<Evidence[]>([]),
    [searched, setSearched] = useState(false),
    [preview, setPreview] = useState<{ id: string; page: number } | null>(null),
    [page, setPage] = useState<Page | null>(null),
    [text, setText] = useState(""),
    [printed, setPrinted] = useState(""),
    [chapter, setChapter] = useState(""),
    [checked, setChecked] = useState(false),
    [professional, setProfessional] = useState(false),
    [pageNumber, setPageNumber] = useState("1"),
    [pageError, setPageError] = useState(""),
    [notice, setNotice] = useState(""),
    [working, setWorking] = useState(false);
  const picker = useRef<HTMLInputElement>(null),
    alive = useRef(true),
    request = useRef<XMLHttpRequest | null>(null);
  async function refresh() {
    try {
      const data = await api<{
        documents: Book[];
        ocr: { available: boolean; message: string };
      }>("/api/library/documents");
      if (alive.current) {
        setBooks(data.documents);
        setOcr(data.ocr);
      }
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    }
  }
  useEffect(() => {
    alive.current = true;
    void refresh();
    const timer = setInterval(() => void refresh(), 2000);
    return () => {
      alive.current = false;
      clearInterval(timer);
      request.current?.abort();
    };
  }, []);
  useEffect(() => {
    if (!preview) return;
    let active = true;
    setPage(null);
    setPageError("");
    setNotice("");
    setPageNumber(String(preview.page));
    api<Page>(`/api/library/documents/${preview.id}/pages/${preview.page}`)
      .then((p) => {
        if (!active) return;
        setPage(p);
        setText(p.text ?? "");
        setPrinted(p.printed_page ?? "");
        setChapter(p.chapter ?? "");
        setChecked(p.text_status === "checked");
        setProfessional(p.review_status === "verified");
      })
      .catch((e) => {
        if (active) setPageError(e.message);
      });
    return () => {
      active = false;
    };
  }, [preview]);
  function choose(files: FileList | File[] | null) {
    if (!files || uploading) return;
    const list = Array.from(files);
    if (list.length + items.length > 7) {
      setError("每批最多选择7份PDF；完成本批后可继续导入。");
      return;
    }
    if (
      list.some(
        (f) =>
          !f.name.toLowerCase().endsWith(".pdf") ||
          f.size > 100 * 1024 * 1024 ||
          f.size === 0,
      )
    ) {
      setError("请选择非空 PDF，单份不超过100MB。");
      return;
    }
    setError("");
    setItems((old) => [
      ...old,
      ...list.map((file) => ({
        file,
        title: file.name.replace(/\.pdf$/i, ""),
        author: "",
        edition: "",
        provenance: "用户本机授权资料",
        ocr: false,
        status: "待导入",
        progress: 0,
        phase: "selected" as const,
      })),
    ]);
  }
  function update(index: number, patch: Partial<ImportItem>) {
    setItems((old) =>
      old.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    );
  }
  async function uploadAll() {
    setUploading(true);
    setError("");
    for (let i = 0; i < items.length; i++) {
      if (!alive.current) break;
      const item = items[i];
      if (item.phase === "queued") continue;
      if (!item.title.trim()) {
        update(i, { status: "请填写教材名" });
        continue;
      }
      try {
        await new Promise<void>((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          request.current = xhr;
          const params = new URLSearchParams({
            title: item.title,
            author: item.author,
            edition: item.edition,
            provenance: item.provenance,
            ocr: String(item.ocr),
          });
          xhr.open("POST", "/api/library/documents?" + params);
          xhr.setRequestHeader("Content-Type", "application/pdf");
          xhr.upload.onprogress = (e) => {
            if (alive.current && e.lengthComputable)
              update(i, {
                progress: Math.round((e.loaded / e.total) * 100),
                status: "正在传输到本机（尚未预检或索引）",
                phase: "uploading",
              });
          };
          xhr.upload.onload = () => {
            if (alive.current)
              update(i, {
                progress: 100,
                phase: "prechecking",
                status: "文件传输完成 · 正在等待PDF预检（尚未登记教材）",
              });
          };
          xhr.timeout = 180000;
          xhr.ontimeout = () =>
            reject(
              Error(
                "请求等待超时 [UPLOAD_REQUEST_TIMEOUT]。请先刷新教材列表，若未登记，再用只读诊断定位预检阶段。",
              ),
            );
          xhr.onload = () => {
            let data;
            try {
              data = JSON.parse(xhr.responseText);
            } catch {
              reject(
                Error(
                  "本机代理未返回有效后端响应 [PROXY_RESPONSE_INVALID]。请确认8001后端已启动，Vite的BACKEND_PORT指向同一端口。",
                ),
              );
              return;
            }
            if (xhr.status >= 200 && xhr.status < 300) resolve();
            else reject(Error(importError(data)));
          };
          xhr.onerror = () => reject(Error("本机连接失败，文件未完成接收。"));
          xhr.onabort = () =>
            reject(Error("已取消上传；已接收的文档会继续在本机索引。"));
          xhr.send(item.file);
        });
        if (!alive.current) break;
        update(i, {
          status: "预检通过 · 已登记教材 · 等待文本提取/OCR与索引",
          progress: 100,
          phase: "queued",
        });
        await refresh();
      } catch (e) {
        if (alive.current)
          update(i, { status: (e as Error).message, phase: "failed" });
      }
    }
    if (alive.current) setUploading(false);
    request.current = null;
  }
  async function action(fn: () => Promise<unknown>) {
    if (working) return;
    setWorking(true);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
      await refresh();
    } finally {
      setWorking(false);
    }
  }
  async function search() {
    setError("");
    try {
      const data = await api<{ results: Evidence[] }>(
        "/api/library/search?q=" + encodeURIComponent(query),
      );
      setResults(data.results);
      setSearched(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const selected = books.find((b) => b.id === preview?.id);
  async function save() {
    if (!preview) return;
    await action(async () => {
      await api(
        `/api/library/documents/${preview.id}/pages/${preview.page}`,
        json("PUT", {
          text,
          printed_page: printed || null,
          chapter: chapter || null,
          checked,
          professional_reviewed: professional,
        }),
      );
      setNotice("已保存核对记录并更新本地索引。");
      setResults([]);
      setSearched(false);
    });
  }
  return (
    <section className="kb">
      <div className="kb-heading">
        <div>
          <span className="eyebrow">LOCAL KNOWLEDGE LIBRARY</span>
          <h1>专项知识库</h1>
        </div>
        <span className="local-badge">◎ 仅保存在本机</span>
      </div>
      <p className="kb-intro">
        导入教材，回查原页。默认不向模型发送本地资料；开启教材许可后，每次提问仍需确认具体短片段。
      </p>
      {error && (
        <div role="alert" className="error">
          {error}
        </div>
      )}
      <div
        className="dropzone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          choose(e.dataTransfer.files);
        }}
      >
        <strong>▤ 选择或拖入 PDF 教材</strong>
        <p>每批最多7份 · 每份100MB / 1500页 · 保留原始文件页序</p>
        <button
          className="kb-primary"
          disabled={uploading}
          onClick={() => picker.current?.click()}
        >
          选择本机 PDF
        </button>
        <input
          ref={picker}
          hidden
          type="file"
          multiple
          accept=".pdf,application/pdf"
          onChange={(e) => {
            choose(e.target.files);
            e.target.value = "";
          }}
        />
        <small>
          仅导入你有权使用的教材。扫描页可选择离线
          OCR，识别成功不会自动通过专业审核。
        </small>
      </div>
      {items.length > 0 && (
        <div className="import-list">
          <h2>本批导入信息</h2>
          {items.map((item, i) => (
            <article key={i} className="import-item">
              <div className="file-name">
                {item.file.name}
                <small>{(item.file.size / 1024 / 1024).toFixed(1)} MB</small>
              </div>
              <label>
                教材选择
                <select
                  aria-label={`教材选择 ${i + 1}`}
                  disabled={uploading}
                  defaultValue=""
                  onChange={(e) => {
                    const entry = catalog[Number(e.target.value)];
                    if (entry)
                      update(i, {
                        title: entry[0],
                        author: entry[1],
                        edition: entry[2],
                      });
                  }}
                >
                  <option value="">自定义 / 按文件名</option>
                  {catalog.map((b, j) => (
                    <option value={j} key={j}>
                      {b[1]}《{b[0]}》 {b[2]}
                    </option>
                  ))}
                </select>
              </label>
              <div className="metadata-fields">
                <label>
                  教材名
                  <input
                    disabled={uploading}
                    maxLength={160}
                    value={item.title}
                    onChange={(e) => update(i, { title: e.target.value })}
                  />
                </label>
                <label>
                  作者
                  <input
                    disabled={uploading}
                    maxLength={120}
                    value={item.author}
                    onChange={(e) => update(i, { author: e.target.value })}
                  />
                </label>
                <label>
                  版本
                  <input
                    disabled={uploading}
                    maxLength={120}
                    value={item.edition}
                    onChange={(e) => update(i, { edition: e.target.value })}
                  />
                </label>
                <label>
                  来源 / 授权说明
                  <input
                    disabled={uploading}
                    maxLength={300}
                    value={item.provenance}
                    onChange={(e) => update(i, { provenance: e.target.value })}
                  />
                </label>
              </div>
              <label className="check">
                <input
                  type="checkbox"
                  disabled={!ocr.available || uploading}
                  checked={item.ocr}
                  onChange={(e) => update(i, { ocr: e.target.checked })}
                />
                对扫描页启用本机中文 OCR
              </label>
              <small>
                文件传输 {item.progress}% · {item.status}
              </small>
            </article>
          ))}
          <p className="ocr-note">{ocr.message}</p>
          <div className="kb-actions">
            <button
              className="kb-primary"
              disabled={uploading}
              onClick={() => void uploadAll()}
            >
              开始批量导入 / 重试失败文件
            </button>
            <button disabled={uploading} onClick={() => setItems([])}>
              清空本批列表
            </button>
            {uploading && (
              <button onClick={() => request.current?.abort()}>
                取消当前上传
              </button>
            )}
          </div>
        </div>
      )}
      <h2>
        已导入教材 <small>{books.length} 本</small>
      </h2>
      {books.length === 0 && (
        <p className="kb-empty">
          尚未导入 PDF。原有13条摘要与课程资料仍可在 AI 对话中使用。
        </p>
      )}
      <div className="books">
        {books.map((book) => (
          <article className="book" key={book.id}>
            <div className="book-title">
              <strong>{book.title}</strong>
              <span>
                {book.status === "complete"
                  ? "索引已完成"
                  : book.status === "processing"
                    ? "正在分页处理"
                    : book.status === "queued"
                      ? "排队 / 恢复中"
                      : book.status === "unindexed"
                        ? "索引已清除 · 原件保留"
                        : book.status === "error"
                          ? "处理中断"
                          : "分页处理完成 · 有待核对页"}
              </span>
            </div>
            <p>
              {book.author || "作者未填"} · {book.edition || "版本未填"}
            </p>
            <progress max={book.total_pages} value={book.processed_pages} />
            <div className="book-stats">
              <span>原始 {book.total_pages} 页</span>
              <span>已处理 {book.processed_pages} 页</span>
              <span>可检索 {book.searchable_pages} 页</span>
              <span>缺处理记录 {book.missing_pages} 页</span>
              <span>失败 {book.failed_pages || 0} 页</span>
              <span>OCR失败 {book.ocr_failed_pages || 0} 页</span>
              <span>OCR低质量 {book.low_quality_pages || 0} 页</span>
              <span>扫描待OCR {book.needs_ocr_pages || 0} 页</span>
              <span>OCR待核对 {book.unchecked_ocr_pages || 0} 页</span>
            </div>
            {book.error && <p className="error">{book.error}</p>}
            <label className="check">
              <input
                type="checkbox"
                checked={Boolean(book.cloud_allowed)}
                disabled={working}
                onChange={(e) => {
                  const allowed = e.target.checked;
                  setBooks((old) =>
                    old.map((b) =>
                      b.id === book.id ? { ...b, cloud_allowed: allowed } : b,
                    ),
                  );
                  void action(() =>
                    api(
                      `/api/library/documents/${book.id}/permission`,
                      json("PATCH", { cloud_allowed: allowed }),
                    ),
                  );
                }}
              />
              允许在每轮确认后，向当前云模型发送相关短片段
            </label>
            <small>
              关闭不会撤回已发送内容；需要时请清空旧会话。OCR文本必须先人工核对才可发送。
            </small>
            <div className="kb-actions">
              <button onClick={() => setPreview({ id: book.id, page: 1 })}>
                查看原页与核对
              </button>
              <button
                disabled={
                  working || ["processing", "queued"].includes(book.status)
                }
                onClick={() =>
                  void action(() =>
                    api(
                      `/api/library/documents/${book.id}/retry`,
                      json("POST", { ocr: ocr.available, all_pages: false }),
                    ),
                  )
                }
              >
                继续 / 重试失败与扫描页
              </button>
              <button
                disabled={
                  working || ["processing", "queued"].includes(book.status)
                }
                onClick={() => {
                  if (
                    confirm(
                      "重新提取机器处理页？已人工核对的文本、印刷页码和审核记录会保留。",
                    )
                  )
                    void action(() =>
                      api(
                        `/api/library/documents/${book.id}/retry`,
                        json("POST", { ocr: ocr.available, all_pages: true }),
                      ),
                    );
                }}
              >
                重建机器索引
              </button>
              <button
                disabled={
                  working || ["processing", "queued"].includes(book.status)
                }
                onClick={() => {
                  if (
                    confirm(
                      "清除正文、页码核对记录及索引，保留原PDF？云端许可将关闭；之后可点击继续处理重新建立索引。",
                    )
                  )
                    void action(async () => {
                      await api(`/api/library/documents/${book.id}/index`, {
                        method: "DELETE",
                      });
                      setResults([]);
                      setSearched(false);
                      setPreview(null);
                    });
                }}
              >
                清除索引，保留PDF
              </button>
              <button
                className="danger"
                disabled={
                  working || ["processing", "queued"].includes(book.status)
                }
                onClick={() => {
                  if (
                    confirm("删除这本教材的本机 PDF 与索引？此操作不能撤销。")
                  )
                    void action(async () => {
                      await api(`/api/library/documents/${book.id}`, {
                        method: "DELETE",
                      });
                      setResults([]);
                      setPreview(null);
                    });
                }}
              >
                删除本地教材
              </button>
            </div>
          </article>
        ))}
      </div>
      <h2>检索本地教材</h2>
      <form
        className="kb-search"
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
      >
        <input
          aria-label="搜索本地教材"
          maxLength={1000}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="输入动作、规则或教学关键词"
        />
        <button disabled={!query.trim()}>搜索</button>
      </form>
      <p className="kb-hint">
        全文关键词检索 · 不按模型补全文本 · 低质量或失败页需核对后才进入索引
      </p>
      {searched && results.length === 0 && (
        <p>未找到相关片段。可尝试动作关键词，或检查扫描页的 OCR / 核对状态。</p>
      )}
      {results.map((r) => (
        <article className="search-result" key={r.id}>
          <strong>
            {r.authors}《{r.title}》
          </strong>
          <small>
            {r.pages} · {textLabel(r.text_status)} ·{" "}
            {reviewLabel(r.verification_status)}
          </small>
          <p>{r.content}</p>
          <button
            onClick={() =>
              setPreview({ id: r.document_id!, page: r.pdf_page! })
            }
          >
            核对 PDF 第{r.pdf_page}页 ↗
          </button>
        </article>
      ))}
      {preview && selected && (
        <div
          className="preview-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="教材原页与文本核对"
        >
          <div className="preview-panel">
            <div className="preview-heading">
              <strong>{selected.title}</strong>
              <button
                onClick={() => setPreview(null)}
                aria-label="关闭原页预览"
              >
                关闭 ×
              </button>
            </div>
            <div className="page-navigation">
              <button
                disabled={preview.page <= 1}
                onClick={() =>
                  setPreview({ ...preview, page: preview.page - 1 })
                }
              >
                上一页
              </button>
              <label>
                PDF页码{" "}
                <input
                  aria-label="原PDF页码"
                  type="number"
                  min={1}
                  max={selected.total_pages}
                  value={pageNumber}
                  onChange={(e) => setPageNumber(e.target.value)}
                />
              </label>
              <button
                onClick={() => {
                  const number = Number(pageNumber);
                  if (
                    Number.isInteger(number) &&
                    number >= 1 &&
                    number <= selected.total_pages
                  )
                    setPreview({ ...preview, page: number });
                  else setPageError("页码超出原始 PDF 范围。");
                }}
              >
                跳转
              </button>
              <span>/ {selected.total_pages}</span>
              <button
                disabled={preview.page >= selected.total_pages}
                onClick={() =>
                  setPreview({ ...preview, page: preview.page + 1 })
                }
              >
                下一页
              </button>
              <a
                target="_blank"
                rel="noopener noreferrer"
                href={`/api/library/documents/${preview.id}/original#page=${preview.page}`}
              >
                原PDF安全预览 ↗
              </a>
            </div>
            {pageError && (
              <div className="error" role="alert">
                {pageError}
              </div>
            )}
            <div className="page-columns">
              <div className="page-image">
                <img
                  key={`${preview.id}:${preview.page}`}
                  src={`/api/library/documents/${preview.id}/pages/${preview.page}/image`}
                  alt={`原PDF第${preview.page}页（包含动作图片）`}
                  onError={() =>
                    setPageError("原页图像暂不可用，可尝试打开原 PDF。")
                  }
                />
              </div>
              <div className="page-editor">
                {!page ? (
                  <p>正在读取本机文本…</p>
                ) : (
                  <>
                    <p>
                      {textLabel(page.text_status)} ·{" "}
                      {reviewLabel(page.review_status ?? "pending")}
                    </p>
                    {page.quality != null && (
                      <p>
                        OCR引擎平均置信度 {(page.quality * 100).toFixed(0)}
                        %（不是准确率或专业评分）
                      </p>
                    )}
                    {page.error && <p className="error">{page.error}</p>}
                    <label>
                      本页提取正文（仅保存在本机）
                      <textarea
                        aria-label="本页正文"
                        maxLength={24000}
                        value={text}
                        onChange={(e) => {
                          setText(e.target.value);
                          setChecked(false);
                          setProfessional(false);
                        }}
                      />
                    </label>
                    <label>
                      印刷页码（对照原页后填写）
                      <input
                        value={printed}
                        maxLength={40}
                        placeholder="未核对，保持为空"
                        onChange={(e) => setPrinted(e.target.value)}
                      />
                    </label>
                    <label>
                      章节（仅在原页明确标注时填写）
                      <input
                        value={chapter}
                        maxLength={180}
                        onChange={(e) => setChapter(e.target.value)}
                      />
                    </label>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          setChecked(e.target.checked);
                          if (!e.target.checked) setProfessional(false);
                        }}
                      />
                      我已对照原 PDF 核对本页正文与页码
                    </label>
                    <label className="check">
                      <input
                        type="checkbox"
                        disabled={!checked}
                        checked={professional}
                        onChange={(e) => setProfessional(e.target.checked)}
                      />
                      我已完成本页专项专业审核（独立于 OCR / 文本核对）
                    </label>
                    <button
                      className="kb-primary"
                      disabled={
                        working ||
                        ["processing", "queued"].includes(selected.status) ||
                        page.text_status === "not_processed"
                      }
                      onClick={() => void save()}
                    >
                      保存核对并更新索引
                    </button>
                    {notice && <p role="status">{notice}</p>}
                    <small>
                      保存前必须有权处理此内容；“专业审核”是用户声明，不是系统认证。
                    </small>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
