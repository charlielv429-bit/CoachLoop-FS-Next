import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import KnowledgeLibrary, {
  api,
  Evidence,
  reviewLabel,
  textLabel,
} from "./KnowledgeLibrary";
type Source = {
  id: string;
  title: string;
  authors: string;
  pages: string | null;
  source_type: string;
  verification_status: string;
  note?: string;
  document_id?: string;
  pdf_page?: number;
  printed_page?: string | null;
  preview_url?: string;
  original_url?: string;
  content?: string;
  text_status?: string;
  ocr_quality?: number | null;
};
type Answer = {
  textbook_facts: string[];
  suggestions: string;
  limitations: string;
  citations: Source[];
  model: string;
};
type Entry = { role: "user" | "assistant"; content: string; answer?: Answer };
type Status = {
  configured: boolean;
  connection: string;
  model: string;
  verified_sources: number;
  retrievable_sources: number;
  sources: Source[];
};
const prompts = [
  "初学者如何建立正确的滑行姿态？",
  "如何向学生解释内刃与外刃？",
  "学生练习时容易失去平衡，如何引导？",
];
function App() {
  const [status, setStatus] = useState<Status | null>(null),
    [messages, setMessages] = useState<Entry[]>([]),
    [input, setInput] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [connected, setConnected] = useState(false),
    [showSources, setShowSources] = useState(false);
  const [preparing, setPreparing] = useState(false),
    [evidence, setEvidence] = useState<{
      text: string;
      results: Evidence[];
    } | null>(null),
    [selectedIds, setSelectedIds] = useState<string[]>([]);
  const abort = useRef<AbortController | null>(null),
    end = useRef<HTMLDivElement>(null),
    mounted = useRef(true);
  async function refresh() {
    try {
      const r = await fetch("/api/status");
      if (!r.ok) throw Error();
      setStatus(await r.json());
    } catch {
      setStatus(null);
      setError("暂时无法连接后端，请确认服务已启动。");
    }
  }
  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
      abort.current?.abort();
    };
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy, error]);
  async function send(text = input) {
    if (!text.trim() || busy || preparing) return;
    if (!status?.configured) {
      setError("尚未连接模型。请在后端配置 API Key，再点击刷新连接。");
      return;
    }
    setPreparing(true);
    setError("");
    try {
      const query = [
        ...messages.filter((m) => m.role === "user").map((m) => m.content),
        text,
      ].join("\n");
      const preview = await api<{
        results: Evidence[];
        has_documents: boolean;
      }>("/api/evidence", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      if (preview.has_documents) {
        setSelectedIds([]);
        setEvidence({ text, results: preview.results });
      } else void runSend(text);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPreparing(false);
    }
  }
  async function runSend(text = input, evidence_ids: string[] = []) {
    if (!text.trim() || busy) return;
    if (!status?.configured) {
      setError("尚未连接模型。请在后端配置 API Key，再点击刷新连接。");
      return;
    }
    if (messages.length >= 24) {
      setError("本次会话已达 12 轮上限，请清空后开始新对话。");
      return;
    }
    const next: Entry[] = [...messages, { role: "user", content: text.trim() }];
    setMessages(next);
    setInput("");
    setError("");
    setBusy(true);
    const controller = new AbortController();
    abort.current = controller;
    const timer = setTimeout(() => controller.abort("timeout"), 60000);
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: next.map(({ role, content }) => ({ role, content })),
          evidence_ids,
        }),
        signal: controller.signal,
      });
      const data = await r.json();
      if (!r.ok)
        throw Error(
          typeof data.detail === "string"
            ? data.detail
            : "请求内容过长或格式有误，请缩短后重试。",
        );
      if (abort.current !== controller) return;
      const a = data as Answer;
      setConnected(true);
      setMessages([
        ...next,
        {
          role: "assistant",
          content: [...a.textbook_facts, a.suggestions, a.limitations].join(
            "\n",
          ),
          answer: a,
        },
      ]);
    } catch (e) {
      if (!mounted.current || abort.current !== controller) return;
      setMessages(messages);
      setInput(text);
      if (controller.signal.aborted)
        setError(
          controller.signal.reason === "timeout"
            ? "请求超时，请稍后重试。"
            : "已停止等待。本次问题未加入会话；模型服务可能仍在完成请求。",
        );
      else setError(e instanceof Error ? e.message : "连接失败，请稍后重试。");
    } finally {
      clearTimeout(timer);
      if (abort.current === controller) {
        if (mounted.current) setBusy(false);
        abort.current = null;
      }
    }
  }
  function stop() {
    const controller = abort.current;
    if (!controller) return;
    abort.current = null;
    controller.abort();
    const last = messages[messages.length - 1];
    if (last?.role === "user") {
      setInput(last.content);
      setMessages(messages.slice(0, -1));
    }
    setBusy(false);
    setError("已停止等待。本次问题未加入会话；模型服务可能仍在完成请求。");
  }
  function clear() {
    if (busy || preparing) return;
    setShowSources(false);
    setEvidence(null);
    setMessages([]);
    setError("");
    setInput("");
  }
  return (
    <div className="app">
      <aside>
        <a className="brand" href="/" aria-label="CoachLoop 首页">
          <span className="logo">
            C<span>↗</span>
          </span>
          <div>
            CoachLoop<span className="brand-sub">FIGURE SKATING · NEXT</span>
          </div>
        </a>
        <button className="new-chat" onClick={clear} disabled={busy}>
          <span>＋</span> 开始新对话 <small>↗</small>
        </button>
        <div className="nav-label">工作空间</div>
        <button
          className={"nav " + (!showSources ? "active" : "")}
          onClick={() => setShowSources(false)}
        >
          <span>◌</span> AI 教学对话 <span className="tag">MVP 1.5</span>
        </button>
        <button className="nav" onClick={() => setShowSources(!showSources)}>
          <span>▤</span> 专项知识库 <small>本机</small>
        </button>
        <div className="sidebar-note">
          <span className="note-icon">✧</span>
          <strong>从经验，走向有据可循</strong>
          <p>将专项知识与教学思考，连接到每一次冰上练习。</p>
        </div>
        <div className="profile">
          <span className="avatar">教</span>
          <div>
            教师工作台<small>教学参考 · 专业陪伴</small>
          </div>
        </div>
      </aside>
      <main className={showSources ? "kb-main" : ""}>
        <header>
          <div>
            AI 教学对话 <span className="header-sub">/ 花样滑冰</span>
          </div>
          <div className="header-actions">
            <button
              className="mobile-action"
              onClick={clear}
              disabled={busy}
              aria-label="清空会话"
            >
              ＋
            </button>
            <button
              className="mobile-action"
              onClick={() => setShowSources(!showSources)}
              aria-label="查看资料库"
            >
              ▤
            </button>
            <div className={"status " + (connected ? "online" : "")}>
              <i />
              {connected
                ? "模型已连接"
                : status?.configured
                  ? "已配置 · 待验证"
                  : "模型未连接"}
              <button
                onClick={() => {
                  setConnected(false);
                  void refresh();
                }}
                aria-label="刷新连接"
              >
                ↻
              </button>
            </div>
          </div>
        </header>
        <div className="conversation">
          {showSources ? (
            <>
              <KnowledgeLibrary />
              <details className="library">
                <summary>
                  原有摘要与课程资料（{status?.sources.length ?? 13}条）
                </summary>
                {status?.sources.map((s) => (
                  <article className="source" key={s.id}>
                    <strong>
                      {s.authors}《{s.title}》
                    </strong>
                    <span>
                      {s.pages ?? "课程目录"} · {s.source_type} ·{" "}
                      {s.document_id && textLabel(s.text_status)} ·{" "}
                      {reviewLabel(s.verification_status)}
                    </span>
                    <p>{s.note}</p>
                  </article>
                ))}
              </details>
            </>
          ) : messages.length === 0 ? (
            <section className="welcome">
              <div className="welcome-mark">✧</div>
              <span className="eyebrow">YOUR PARTNER ON THE ICE</span>
              <h1>
                让每一次教学，
                <br />
                都有更清晰的思路。
              </h1>
              <p>
                你好，我是你的 AI 花样滑冰教学助手。
                <br />
                一起探讨专项知识、梳理动作要点，让教学更有依据。
              </p>
              <div className="prompt-label">
                从一个教学问题开始 <span>↙</span>
              </div>
              <div className="prompts">
                {prompts.map((p, i) => (
                  <button
                    key={p}
                    onClick={() => {
                      setShowSources(false);
                      void send(p);
                    }}
                  >
                    <span className="prompt-icon">{["◇", "⌁", "↗"][i]}</span>
                    <span>{p}</span>
                    <small>↗</small>
                  </button>
                ))}
              </div>
              <div className="evidence-note">
                <span>▤</span> 教材事实与 AI 建议分开展示，引用可追溯。
                <br />
                <small>
                  已收录 B02 / B03 摘要与 L01–L08 课程 · 教材待专业审核
                </small>
              </div>
            </section>
          ) : (
            <section className="thread">
              {messages.map((m, i) => (
                <article className={"message " + m.role} key={i}>
                  <span className="message-avatar">
                    {m.role === "user" ? "你" : "✧"}
                  </span>
                  <div className="message-body">
                    <div className="message-name">
                      {m.role === "user" ? "你" : "CoachLoop"}
                      {m.role === "assistant" && <small>AI 教学助手</small>}
                    </div>
                    {m.answer ? (
                      <>
                        <h3>资料依据</h3>
                        {m.answer.textbook_facts.length ? (
                          m.answer.textbook_facts.map((f, j) => (
                            <p key={j}>{f}</p>
                          ))
                        ) : (
                          <p className="muted">本轮未检索到相关资料支持。</p>
                        )}
                        <h3>AI 教学建议</h3>
                        <p>{m.answer.suggestions}</p>
                        {m.answer.citations.map((s) => (
                          <div className="citation" key={s.id}>
                            <strong>
                              ▤ {s.authors}《{s.title}》
                            </strong>
                            <span>
                              {s.pages ?? "无页码"} · {s.source_type} ·{" "}
                              {s.document_id && textLabel(s.text_status)} ·{" "}
                              {reviewLabel(s.verification_status)}
                            </span>
                            {s.document_id && (
                              <>
                                <p>{s.content}</p>
                                <a
                                  href={s.original_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  查看原 PDF 第{s.pdf_page}页 ↗
                                </a>
                                <a
                                  style={{ marginLeft: 14 }}
                                  href={s.preview_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  查看本机原页图像
                                </a>
                              </>
                            )}
                          </div>
                        ))}
                        <div className="limitations">
                          <strong>参考边界</strong>
                          <p>{m.answer.limitations}</p>
                        </div>
                      </>
                    ) : (
                      <p>{m.content}</p>
                    )}
                  </div>
                </article>
              ))}
              {busy && (
                <div className="thinking" role="status">
                  ✧ 正在检索资料并思考<span>···</span>
                </div>
              )}
            </section>
          )}
          <div ref={end} />
        </div>
        <footer>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setShowSources(false);
              void send();
            }}
          >
            <textarea
              aria-label="输入教学问题"
              placeholder="聊聊你的教学问题，例如：如何引导初学者找到外刃？"
              value={input}
              maxLength={6000}
              disabled={busy || preparing}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  setShowSources(false);
                  void send();
                }
              }}
            />
            <div className="composer-bottom">
              <span>
                ✧ 专项教学助手 <small>· 中文对话</small>
              </span>
              {busy ? (
                <button
                  key="stop"
                  type="button"
                  className="send stop"
                  onClick={(e) => {
                    e.preventDefault();
                    stop();
                  }}
                  aria-label="停止生成"
                >
                  ■
                </button>
              ) : (
                <button
                  key="send"
                  type="submit"
                  className="send"
                  disabled={!input.trim() || preparing}
                  aria-label="发送问题"
                >
                  ↑
                </button>
              )}
            </div>
          </form>
          <div className="disclaimer">
            {preparing ? "正在本机检索资料… " : ""}AI
            建议仅供教学参考，不用于正式技术评分。请勿输入学生个人信息、视频或敏感数据。
          </div>
        </footer>
        {evidence && (
          <div className="evidence-overlay">
            <section
              className="evidence-dialog"
              role="dialog"
              aria-modal="true"
              aria-label="确认本轮教材片段"
            >
              <h2>本轮允许发送哪些教材片段？</h2>
              <p>
                只向当前模型发送你选择的短片段，不发送
                PDF、原页图片或整个索引。最多4条。下列内容均在本机检索；文档许可关闭或
                OCR 未核对时不能发送。原有摘要与当前对话历史仍按原流程发送。
              </p>
              {evidence.results.length === 0 && (
                <p>
                  本地教材未找到相关可靠片段。本轮可继续一般教学讨论，并明确证据不足。
                </p>
              )}
              {evidence.results.map((item) => (
                <article className="evidence-card" key={item.id}>
                  <label>
                    <input
                      type="checkbox"
                      disabled={
                        !item.can_send ||
                        (!selectedIds.includes(item.id) &&
                          selectedIds.length >= 4)
                      }
                      checked={selectedIds.includes(item.id)}
                      onChange={(e) =>
                        setSelectedIds((old) =>
                          e.target.checked
                            ? [...old, item.id]
                            : old.filter((id) => id !== item.id),
                        )
                      }
                    />
                    <strong>
                      {item.authors}《{item.title}》
                    </strong>
                  </label>
                  <small>
                    {item.pages} · {textLabel(item.text_status)} ·{" "}
                    {reviewLabel(item.verification_status)}
                  </small>
                  <p>{item.content}</p>
                  {!item.can_send && (
                    <small>
                      未允许发送：请在专项知识库开启教材许可，并核对 OCR 正文。
                    </small>
                  )}
                  <a
                    href={item.original_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    对照原 PDF 页 ↗
                  </a>
                </article>
              ))}
              <div className="evidence-actions">
                <button
                  className="kb-primary"
                  onClick={() => {
                    const current = evidence;
                    setEvidence(null);
                    void runSend(current.text, selectedIds);
                  }}
                >
                  发送问题
                  {selectedIds.length
                    ? `与${selectedIds.length}条片段`
                    : "（不使用本地片段）"}
                </button>
                <button onClick={() => setEvidence(null)}>返回编辑</button>
                <button
                  onClick={() => {
                    setEvidence(null);
                    setShowSources(true);
                  }}
                >
                  管理教材许可 / 核对原页
                </button>
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
