# Opencode API Gateway

这是一个基于 FastAPI 的 opencode 网关，将本机 `opencode` CLI 封装成局域网可访问的 HTTP API。项目安装后的命令行入口是 `ocr`，Python 包名是 `openremote`。

## 功能

- 查询 opencode 版本和可用模型。
- 创建、查询、删除会话。
- 为每个会话设置模型和工作目录。
- 提供非流式对话接口 `POST /api/chat`。
- 提供 SSE 流式对话接口 `POST /api/chat/stream`。
- 返回模型文本、推理内容、原始事件和工具调用过程。
- 会话历史持久化到 `sessions/` 目录。

## 安装

在仓库根目录执行：

```powershell
python -m pip install --force-reinstall --no-deps -e .
```

如需安装依赖：

```powershell
python -m pip install fastapi uvicorn pydantic
```

确保本机已经安装 `opencode`，并且能执行：

```powershell
opencode --version
```

Windows 后台服务环境可能拿不到完整 `PATH`。网关会优先使用 `OPENCODE_BIN`，然后回退到 npm 安装路径：

```powershell
$env:OPENCODE_BIN = "C:\Users\xiaox\AppData\Roaming\npm\node_modules\opencode-ai\bin\opencode.exe"
```

## 启动

```powershell
ocr --host 0.0.0.0 --port 8000
```

启动后访问：

- API 文档：`http://127.0.0.1:8000/docs`
- 局域网发现：`http://127.0.0.1:8000/api/discover`
- 版本检查：`http://127.0.0.1:8000/api/version`

局域网设备使用本机 IP 访问，例如：

```text
http://192.168.1.100:8000
```

## 常用接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | 服务信息 |
| `GET` | `/api/discover` | 局域网发现 |
| `GET` | `/api/version` | opencode 和网关版本 |
| `GET` | `/api/models` | 可用模型列表 |
| `POST` | `/api/sessions` | 创建会话 |
| `GET` | `/api/sessions` | 会话列表 |
| `GET` | `/api/sessions/{id}` | 会话详情 |
| `DELETE` | `/api/sessions/{id}` | 删除会话 |
| `GET` | `/api/sessions/{id}/model` | 获取当前模型 |
| `POST` | `/api/sessions/{id}/model` | 设置当前模型 |
| `GET` | `/api/sessions/{id}/workdir` | 获取工作目录 |
| `POST` | `/api/sessions/{id}/workdir` | 设置工作目录 |
| `GET` | `/api/sessions/{id}/history` | 获取历史 |
| `DELETE` | `/api/sessions/{id}/history` | 清空历史 |
| `POST` | `/api/chat` | 非流式对话 |
| `POST` | `/api/chat/stream` | SSE 流式对话 |

## 非流式对话

请求：

```json
{
  "message": "只回复 pong",
  "session_id": "可选"
}
```

响应：

```json
{
  "session_id": "xxx",
  "response": "pong",
  "reasoning": "",
  "events": [],
  "tools": [],
  "fallback": null,
  "model": null,
  "message_count": 2
}
```

字段说明：

- `response`: 助手最终文本。
- `reasoning`: 推理文本，可能为空。
- `events`: opencode 原始 JSON 事件，用于调试。
- `tools`: 归一化后的工具调用事件。
- `fallback`: 当 JSON 格式没有可展示文本时，网关会回退到 `--format default`，此字段为 `"default"`。

## 流式对话

`POST /api/chat/stream` 返回 `text/event-stream`：

```text
data: {"type":"text","content":"p","session_id":"xxx"}

data: {"type":"tool","content":"Tool read result","tool":"read","output":"...","session_id":"xxx"}

data: {"type":"done","content":"pong","tools":[],"session_id":"xxx"}

data: [DONE]
```

事件类型：

- `text`: 普通回答文本，客户端应追加到当前消息。
- `reasoning`: 推理文本，建议默认折叠。
- `tool`: 工具调用过程或结果。
- `error`: 网关或 opencode 错误。
- `done`: 本轮完成，`content` 是完整回复，`tools` 是本轮工具事件汇总。
- `[DONE]`: SSE 结束标记。

## Android 适配

Android 客户端应兼容动态 JSON 字段：

- `input`、`output`、`error` 可能是字符串、对象、数组或 `null`。
- `tool_call_id` 可能为空。
- 未知 `type` 应记录日志并忽略。
- 流式输出以 `done.content` 校准最终文本。

详细适配文档见 [ANDROID_OUTPUT_ADAPTER.md](ANDROID_OUTPUT_ADAPTER.md)。

## 验证

语法检查：

```powershell
python -m py_compile src\openremote\api.py opencode_api.py
```

版本检查：

```powershell
curl.exe http://127.0.0.1:8000/api/version
```

非流式检查：

```powershell
$body = @{ message = '只回复 pong' } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/chat' -Method Post -ContentType 'application/json; charset=utf-8' -Body $body
```

## 文件说明

- `src/openremote/api.py`: 安装入口实际加载的 FastAPI 应用。
- `src/openremote/cli.py`: `ocr` 命令入口。
- `opencode_api.py`: 兼容保留的单文件启动入口。
- `ANDROID_OUTPUT_ADAPTER.md`: Android 输出适配说明。
- `API_README.md`: 旧版 API 使用说明。
- `sessions/`: 会话持久化目录。

## 排障

`ocr.exe` 被占用导致 pip 重装失败：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
Stop-Process -Id <PID> -Force
python -m pip install --force-reinstall --no-deps -e .
```

`opencode` 找不到：

- 确认 `opencode --version` 能在终端运行。
- 设置 `OPENCODE_BIN` 指向实际 `opencode.exe`。
- 重启 `ocr` 服务。

网关无回复或空回复：

- 优先检查 `/api/version` 是否正常。
- 检查 `/api/chat` 是否返回 `events` 或 `tools`。
- 如果 JSON 输出没有文本，网关会自动回退到 default 输出。
