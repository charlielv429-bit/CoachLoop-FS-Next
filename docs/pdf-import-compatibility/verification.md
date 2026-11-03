# PDF兼容性与被动预览修复

基线：`974a415`（fix/pdf-import-reliability）。开发分支：`fix/pdf-import-compatibility`。
验证日期：2026-11-03（北京时间）。云端Linux、Python3.12、Chromium。没有王树本教材原件，也没有Mac远程执行权限。

## 真实已知与未知

用户Mac报告61,998,383 bytes，预检0.20秒，退出1，`PDF_ACTIVE_CONTENT_BLOCKED` / `ValueError`，OCR尚未参与。旧代码按键存在与否拦截，因此可能是OpenAction、AcroForm、附加动作、JS名称树或附件，不能据此确认具体对象。本次不宣称真实王树本PDF已导入或预检已通过。

## 规则审查与改变

旧版会把仅定位到某页的OpenAction数组、只含静态字段的AcroForm、只含内部跳转的附加动作一律拒绝；同时没有充分覆盖Next动作链、表单子字段和书签动作。新策略检查语义、引用与动作链，未知/畸形/循环/过深对象仍拒绝。

| 对象 | 新行为 | 固定代码/对象类别示例 |
|---|---|---|
| 本文档真实页面的OpenAction数组或GoTo | 验证目标属于当前文档、目标格式及数值；不执行定位，允许被动导入 | PDF_INTERNAL_DESTINATION_IGNORED / document_open_action |
| 已解析的文档内命名目标、内部链接 | 本地解析目标页；不执行跳转 | PDF_INTERNAL_DESTINATION_IGNORED |
| Text/Highlight/Link等普通注释 | 无危险动作时允许；原件保留，渲染不绘制注释/表单层 | PDF_ORDINARY_ANNOTATION_ALLOWED / annotation |
| 静态AcroForm | 递归检查字段/子字段/附加动作；不初始化表单引擎、不执行计算 | PDF_STATIC_FORM_ISOLATED / acroform |
| 文档JS名称树 | 拒绝 | PDF_DOCUMENT_JAVASCRIPT_BLOCKED / document_javascript |
| OpenAction、注释、字段或书签中的JS，包括Next后续链 | 拒绝 | PDF_JAVASCRIPT_ACTION_BLOCKED + 具体作用域/必要PDF页码 |
| 动态XFA | 拒绝 | PDF_XFA_BLOCKED / acroform |
| EmbeddedFiles、关联附件或文件注释 | 拒绝；不打开附件 | PDF_EMBEDDED_FILES_BLOCKED |
| URI、Launch、SubmitForm、ImportData、GoToR/GoToE | 拒绝，不访问外部地址、不启动或提交 | PDF_EXTERNAL_URL_BLOCKED / PDF_LAUNCH_BLOCKED / PDF_SUBMIT_BLOCKED / PDF_REMOTE_GOTO_BLOCKED |
| 多媒体、未知动作、无效目标、循环/超限对象 | 拒绝 | PDF_MEDIA_BLOCKED / PDF_UNKNOWN_ACTION_BLOCKED / PDF_INVALID_DESTINATION / PDF_OBJECT_LIMIT |
| 加密/损坏文件 | 拒绝，保留严格结构解析 | PDF_ENCRYPTED / PDF_STRUCTURE_REJECTED |

只读诊断输出固定代码、对象类别、必要页码、耗时、退出码与建议；安全对象按固定类别计数。不会输出字段名/值、目标名称、脚本、URL、附件名称或正文。API只接受子进程的白名单诊断字段，不回显stdout/stderr或异常原文。

## 安全原页边界

原件字节不改，库和13条既有资料不迁移、不重建，`.env`和Gemini配置未修改。现有`/original#page=N`入口改为可信HTML安全查看器，展示本机PDFium渲染的第N页PNG，不再给浏览器交付交互式PDF。禁用表单初始化/绘制和注释层绘制；不调用文档打开动作或动作处理API。页面正文、图像仍按原PDF页序渲染；表单/注释外观层不是此安全预览的内容，原件保留供用户自行管理。

查看器使用逐响应nonce CSP，无unsafe-eval、无外部资源、禁止object/embed；不嵌入PDF、脚本或附件。原件不暴露为HTTP原始PDF下载。保留原来100MB/1500页、严格解析、25秒预检时限、CPU/文件尺寸/渲染尺寸限制及Linux内存限制；资源限制不是完整OS沙箱或对任意恶意文件的安全证明。

## 实际验证

```bash
TESSDATA_PREFIX=/tmp/coachloop-ocr-models PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
(cd frontend && npm run build)
```

- 全部后端：**93 passed，0 skipped**，3条依赖弃用警告（Starlette/AnyIO、测试PDF中pypdf的JS生成接口）。包含已有真实离线中文OCR回归与新的42个对象/协议/导入测试。
- 前端：TypeScript与Vite生产构建通过。
- 自建数据测试覆盖普通扫描、正常正文、内部OpenAction数组/字典/命名目标、普通注释、静态表单、40个书签，以及JS/URL/启动/提交/导入/远程跳转/附件/XFA/未知字段/未知动作/循环/加密/损坏。安全文件实际导入并索引；危险文件422、类别和页码符合预期且不泄露标记文本。
- 每个成功导入样本检查本机原件字节未改变。扫描空白页明确为待OCR，不能假装已有正文。
- 浏览器测试：`scripts/verify_pdf_compatibility_ui.py`，要求空白隔离测试后端8004与Vite5176。自建内部定位PDF导入后3页可检索；安全查看器按#page=2打开并翻到第3页；JS样本被拒绝，网页展示代码及对象类别，无外部HTTP请求。使用DOM状态断言，无需放宽CSP。

上述全部是自建授权PDF；未使用、上传或提交真实教材。没有运行真实Gemini，不涉及此项修复的模型质量验收。

## Mac真实王树本PDF复验

先保存已有源码改动，不用reset或覆盖`.env`。在项目根目录获取并切换分支：

```bash
git fetch origin
git switch fix/pdf-import-compatibility
```

可直接复制以下一条命令，使用Mac文件选择器选择本机原件，不必改写路径，也不上传文件：

```bash
coachloop_pdf_path="$(osascript -e 'POSIX path of (choose file with prompt "选择王树本《花样滑冰》PDF" of type {"com.adobe.pdf"})')" && .venv/bin/python scripts/diagnose_pdf_import.py "$coachloop_pdf_path" --backend http://127.0.0.1:8001 --origin http://127.0.0.1:5175
```

- 若`PDF_PRECHECK_OK`：记录被动对象分类，重启本机后端（`BACKEND_PORT=8001 bash scripts/dev.sh`），按终端实际Vite地址打开网页。用此文件导入，记录真实页数、可检索/失败/低质量页数、OCR与索引状态，抽查开头/中间/末尾的原页定位及检索。预检成功不等于OCR、索引或专业审核完成。
- 若返回具体拒绝代码：回传代码、对象类别、页码、耗时和退出码即可；不需要提供原件、正文、URL、附件或密钥。不要手动删除安全检查或执行PDF内程序。
- 如果仍是`PDF_STRUCTURE_REJECTED`或资源错误：该问题不属于已验证的普通交互误拦，不自动放宽严格解析或资源界限。

在用户Mac回传新结果并完成实际导入前，真实教材兼容性及全流程状态仍为**待复验**。
