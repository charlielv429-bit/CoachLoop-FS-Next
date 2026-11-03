# MVP 1 实际验证记录

验证日期：2026-11-03（北京时间）。环境：Linux、Python 3.12.14、Node.js 24.22.1、Chromium。Mac 命令已提供，但没有在真实 Mac 设备上执行。

## 结果

| 验收 | 状态 | 证据与限制 |
|---|---|---|
| A 真实模型回答中文 | 未执行（按用户最新要求暂缓） | 未配置真实 API Key；不宣称真实 AI 成功 |
| B 连续追问与上下文 | 模拟测试通过 | 后端验证完整消息传递；浏览器第二轮提交3条历史消息。真实模型上下文理解待本地验证 |
| C 教材书名与页码 | 检索和展示通过 | 真实用户提供的数据检索到 B02-93 与 B03-39；PDF和印刷页码正确。浏览器引用卡片测试使用固定模拟响应 |
| D 不编造出处 | 已测规则通过 | 未知来源ID、无引用事实、模型自行输出书名/页码被拒绝；这不是对任意模型输出的语义真实性保证 |
| E 未配置 API Key | 通过 | 实际后端返回503；页面明确未连接并显示配置提示，不生成假回答 |
| F 页面与启动 | 当前云环境通过 | 一键安装重复执行成功；启动双服务、Vite代理和真实浏览器正常；Mac设备实测未执行 |

运行 `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q`：**16 passed**，一个来自 Starlette/AnyIO 的弃用警告，无测试跳过。

运行 `cd frontend && npm run build`：TypeScript检查与生产构建成功。

运行 `python scripts/verify_ui.py`：桌面与手机、缺失密钥、资料目录、模拟多轮与引用卡片、清空及停止全部通过，无页面 JavaScript 异常。此脚本使用独立安装的 Playwright 和 Linux `/usr/bin/chromium`，不属于运行应用的依赖；其他机器需调整 executable_path。停止测试曾暴露按钮复用引发的再次提交，已修复并回归通过。

`bash scripts/setup.sh` 重复执行成功。`bash scripts/dev.sh` 已在本环境启动；本机 `/api/status` 返回 configured=false、13条可检索资料。脚本不会覆盖已有 backend/.env。

## 截图

- [桌面首页](home-desktop.png)
- [手机首页](home-mobile.png)
- [未配置密钥提示](missing-api-key.png)
- [资料目录与待审核状态](sources.png)
- [模拟聊天与引用卡片](chat-mocked.png) —— 回答中明确标注模拟，不是真实模型回答。
- [停止后的恢复状态](stopped.png)

## 资料边界

5条教材页摘要由用户提供并声明已核对扫描页，本项目没有独立查看原始PDF。保留 pending；8条课程设计为 confirmed，不构成官方等级动作组合。检索不扩写扫描页细节，不将摘要当作教材逐字原文。后端对 pending 引用强制补充待专业教师审核提示。

## 在 Mac 完成真实验收

1. 按 README 安装，在 backend/.env 安全填写服务商凭据，重启双服务。
2. 执行 `.venv/bin/python scripts/smoke_real.py`，发起两轮非个人问题的真实请求。
3. 人工核对中文回答与上文承接；对照 sources.json 和原始PDF检查引用及摘要忠实性。
4. 再询问资料未覆盖的问题，确认回答说明证据不足，没有杜撰书名页码。

当前未完成真实模型验收，未进行正式技术评分质量评价，也未进行公开生产部署。
