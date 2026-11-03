# CoachLoop-FS Next

面向花样滑冰教师与专项教练的中文 AI 教学对话 MVP。React + TypeScript + FastAPI，无数据库。独立于 CoachLoop-FS 旧项目。

## Mac 本地运行

需要 Python 3.11+（本次验证 3.12.14）、Node.js 22+（本次验证 24.22.1）和 npm。Mac 可用 Homebrew 安装：`brew install python@3.12 node@22`，并确保对应版本的 `python3`、`node`、`npm` 已加入 PATH；先用 `python3 --version`、`node --version` 检查。未在真实 Mac 设备上执行验收。

```bash
git clone https://github.com/charlielv429-bit/CoachLoop-FS-Next.git
cd CoachLoop-FS-Next
# PR 合并前，请先切换到 feat/mvp1-ai-chat-retrieval 分支
git switch feat/mvp1-ai-chat-retrieval
bash scripts/setup.sh
# 使用编辑器填写 backend/.env；不要将密钥提交到 Git
bash scripts/dev.sh
```

浏览器打开 http://localhost:5173 。Ctrl+C 停止两个服务。前端通过 Vite 转发 `/api` 到本机后端 8000 端口。端口需空闲；运行服务绑定本机，适合本地开发。

## 真实模型 API

`backend/.env.example` 提供配置说明：

- `LLM_API_KEY`：服务商密钥，仅后端读取。
- `LLM_BASE_URL`：可信的 OpenAI 兼容 HTTPS API 根地址，默认 `https://api.openai.com/v1`。
- `LLM_MODEL`：账户可用模型，默认 `gpt-4o-mini`。

服务需支持 Chat Completions、JSON object 输出和 `max_tokens`。修改 `.env` 后重启后端。未配置密钥时不会调用模型；已配置仅表示存在凭据，首次成功响应后页面才显示已连接。请求中的对话文本和已检索摘要会发送给所选服务商，请先确认服务商的数据政策与摘要使用权。页面无文件或视频上传功能。停止按钮取消浏览器等待，不能保证撤回模型服务商已接受的请求。

每条消息最多 6000 字符、上下文 24000 字符、最多 12 轮；单进程每客户端每分钟 12 次请求、最多 3 个并发模型请求；上游超时 45 秒、整体 55 秒。当前为本地单用户 MVP，无生产级身份认证及跨进程限流，请勿直接公开部署。

## 环境变量示例

安装脚本仅在 `backend/.env` 不存在时创建文件；不会覆盖你已有的配置。使用编辑器填写以下内容，密钥仅在你自己的 Mac 上保存，不要粘贴到聊天或提交仓库：

```dotenv
LLM_API_KEY=YOUR_LOCAL_API_KEY
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

不要使用 `VITE_` 前缀保存密钥，前端不需要模型凭据。`.env`、`.env.*` 默认忽略，只有空凭据示例文件允许提交。个人资料应放在忽略的 `personal-data/`、`student-data/` 或 `private-data/`；不要将学生资料写入源码、教材摘要或测试夹具。Git 忽略规则无法自动识别任意文件内的敏感内容。

## 故障排查

- `python3` 或 `node` 版本不符：确认 Homebrew 对应工具已在 PATH；已有 `.venv` 使用旧 Python 时，先备份本地配置，再仅删除 `.venv` 并重新运行安装脚本。
- 安装失败：确认可访问 PyPI 与 npm registry，保留 TLS 校验；使用 `bash scripts/setup.sh` 查看出错命令，勿关闭证书验证。
- 8000 / 5173 端口占用：用 `lsof -nP -iTCP:8000 -sTCP:LISTEN` 或对应 5173 查看占用者，停止你自己的旧开发进程再启动。Ctrl+C 后若端口仍被占用也按此检查，勿盲目结束其他应用。
- 页面无法连接后端：确认终端有 Uvicorn 与 Vite 启动输出，并检查 `curl http://127.0.0.1:8000/api/status`。页面应从 Vite 的 5173 端口打开。
- 模型未连接：确认文件位置为 `backend/.env`、密钥非空，并重启后端。已配置不等于认证或真实响应成功。
- 认证失败 / 429 / 超时：分别检查服务商权限与模型名称、额度与请求频率、网络和服务状态；兼容服务须支持 JSON object 输出。错误提示不会显示密钥或上游原始响应。
- 引用校验失败：重新发送问题；若持续失败，检查服务商是否支持指定输出格式，勿绕过引用校验。教材状态 pending 属于待专业审核，不是配置错误。

## 教材资料与真实性

`data/sources.json` 已录入用户提供的 13 条资料：B02 的 PDF 90–93 页／印刷76–79页、B03 的 PDF39页／印刷29页，以及 L01–L08 每课45分钟的课程设计。

教材保留 `verification_status: pending` 和 `scan_checked: true`：用户已核对原始扫描页，但仍待专业教师审核。此类摘要可检索，引用卡片始终显示待审核；不能当作原文或正式技术标准。课程标为 `confirmed`，不代表教材规定的官方等级动作组合。本项目未独立查看原始 PDF。

检索使用中文双字词与英文词重叠排序，适合小型资料集；仅检索已核验、已确认课程，或明确核对过扫描页的非空记录。空白、未核对资料不参与检索。每轮结合历史用户问题，返回最多4条。出处卡片由后端记录生成，书名和页码不由模型编写；未知引用 ID、无引用的事实及自行输出书名/页码/链接会被拒绝。这不能保证语义完全正确，教师仍需核对原始教材。没有检索结果时不显示教材事实。

补充资料时记录书名、作者、PDF与印刷页码、摘要、来源类型及核实状态；经专业审核后再设为 `verified` 并补充 `verified_by`、`verified_at`、`verification_note`。不要将模型生成的文字改标为教材事实。数据每次检索重新读取。

## 验证

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
(cd frontend && npm run build)
```

配置凭据并启动服务后，可执行 `.venv/bin/python scripts/smoke_real.py` 发起两轮真实请求，再人工核对上下文和教学内容。

实际结果见 `docs/verification.md`。测试中的教材与模型响应均为明确的人工测试夹具，不属于真实教材资料或真实模型验收。

## 结构与边界

- `backend/app/main.py`：模型 API、格式校验、错误和请求限制。
- `backend/app/knowledge.py`：最小检索模块。
- `frontend/src/`：对话、引用卡片、连接状态、停止与清空会话。
- `data/sources.json`：人工核验来源目录。

会话仅保存在当前网页内存，刷新即清除；后端不落盘对话。不进行正式技术评分，不替代现场指导或医疗意见。不支持视频分析、教案编辑器、数据库管理或完整 Agent 工作流。请勿输入真实学生个人信息及敏感数据；当前文字输入不包含自动脱敏系统。
