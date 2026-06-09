# Openremote API Gateway 接口文档

## 概览

Openremote API Gateway 是一个基于 FastAPI 的本地 HTTP 网关，用来把本机 CLI 能力封装成 REST/SSE API。

当前支持两个后端：

- `opencode`：默认后端，兼容原有接口行为。
- `claude`：新增后端，调用 Claude Code CLI，并通过 Claude Code 自己的 `session_id` 连续携带上下文。

基础地址：

```text
http://localhost:8000
```

Swagger 文档：

```text
http://localhost:8000/docs
```

## 启动

安装依赖：

```powershell
python -m pip install fastapi uvicorn pydantic
```

启动服务：

```powershell
ocr --host 0.0.0.0 --port 8000
```

兼容旧入口：

```powershell
python opencode_api.py
```

## CLI 依赖

确认本机 CLI 可用：

```powershell
opencode --version
claude --version
```

可选环境变量：

```powershell
$env:OPENCODE_BIN = "C:\path\to\opencode.exe"
$env:CLAUDE_BIN = "C:\path\to\claude.exe"
$env:CLAUDE_PERMISSION_MODE = "bypassPermissions"
```

`CLAUDE_PERMISSION_MODE` 也可以在每次 `/api/chat` 请求中用 `permission_mode` 覆盖。

支持的 Claude Code permission mode：

```text
acceptEdits, auto, bypassPermissions, default, dontAsk, plan
```

## 通用字段

### provider

`provider` 用来选择后端：

```json
{
  "provider": "opencode"
}
```

或：

```json
{
  "provider": "claude"
}
```

不传时默认使用 `opencode`，保持旧客户端兼容。

### session_id 与 provider_session_id

- `session_id`：网关自己的会话 ID，用于所有 API 路由。
- `provider_session_id`：后端 CLI 的真实会话 ID。Claude Code 会返回该字段，网关会保存它，并在后续请求中用 `claude --resume <provider_session_id>` 续接上下文。

## 系统接口

### GET /

返回网关基础信息。

响应示例：

```json
{
  "name": "Openremote API Gateway",
  "version": "1.1.0",
  "providers": ["opencode", "claude"],
  "docs": "/docs"
}
```

### GET /api/discover

用于局域网发现。

响应示例：

```json
{
  "service": "openremote-api-gateway",
  "name": "Openremote API Gateway",
  "gateway_version": "1.1.0",
  "opencode_version": "1.16.2",
  "claude_version": "2.1.168 (Claude Code)",
  "providers": ["opencode", "claude"],
  "computer_name": "MyPC",
  "port": 8000,
  "docs_url": "/docs"
}
```

### GET /api/version

查询网关和 CLI 版本。

响应示例：

```json
{
  "version": "1.16.2",
  "opencode_version": "1.16.2",
  "claude_version": "2.1.168 (Claude Code)",
  "gateway_version": "1.1.0",
  "providers": ["opencode", "claude"]
}
```

## 模型接口

### GET /api/models

默认查询 opencode 模型：

```powershell
curl.exe "http://localhost:8000/api/models"
```

查询 Claude Code 可用别名：

```powershell
curl.exe "http://localhost:8000/api/models?provider=claude"
```

Claude 响应示例：

```json
{
  "provider": "claude",
  "models": [
    {"id": "sonnet", "name": "sonnet"},
    {"id": "opus", "name": "opus"}
  ],
  "count": 2
}
```

### GET /api/sessions/{session_id}/model

查询某个会话的当前模型。

### POST /api/sessions/{session_id}/model

设置会话模型。

请求示例：

```json
{
  "provider": "claude",
  "model": "sonnet"
}
```

opencode 模型会校验是否存在于 `opencode models`；Claude Code 允许 `sonnet`、`opus` 或完整模型名。

## 会话接口

### POST /api/sessions

创建会话。参数为 query 参数：

```powershell
curl.exe -X POST "http://localhost:8000/api/sessions?provider=claude&work_dir=D%3A%5Cproject%5Copencode"
```

响应示例：

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "work_dir": "D:\\project\\opencode",
  "provider": "claude",
  "created_at": "2026-06-09T01:30:00.000000"
}
```

### GET /api/sessions

列出所有会话。

### GET /api/sessions/{session_id}

获取会话详情。

响应包含：

```json
{
  "session_id": "xxx",
  "work_dir": "D:\\project\\opencode",
  "provider": "claude",
  "current_model": null,
  "provider_session_id": "5361bd4f-1d8b-470e-8ffe-29dac9cbc8fc",
  "message_count": 4,
  "created_at": "2026-06-09T01:30:00",
  "updated_at": "2026-06-09T01:31:00"
}
```

### DELETE /api/sessions/{session_id}

删除会话。

## 工作目录接口

### GET /api/sessions/{session_id}/workdir

查询工作目录。

### POST /api/sessions/{session_id}/workdir

设置工作目录。

请求示例：

```json
{
  "path": "D:\\project\\opencode"
}
```

切换工作目录会清空该会话的 `provider_session_id`，避免 Claude Code 在错误目录中续接旧会话。

## 历史接口

### GET /api/sessions/{session_id}/history

查询本地历史记录。

### DELETE /api/sessions/{session_id}/history

清空本地历史记录，并清空 `provider_session_id`。

## 非流式对话

### POST /api/chat

请求字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `message` | string | 是 | 用户消息 |
| `session_id` | string | 否 | 不传则创建新会话 |
| `provider` | string | 否 | `opencode` 或 `claude`，默认 `opencode` |
| `permission_mode` | string | 否 | 仅 Claude Code 使用 |
| `stream` | boolean | 否 | 兼容字段，非流式接口中不使用 |

Claude Code 请求示例：

```powershell
$body = @{
  provider = "claude"
  message = "Reply exactly: API_OK"
  permission_mode = "bypassPermissions"
} | ConvertTo-Json -Compress

Invoke-RestMethod `
  -Uri "http://localhost:8000/api/chat" `
  -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

响应示例：

```json
{
  "session_id": "44cc3892-a7f7-4945-afa7-237ff0b7cd0b",
  "provider": "claude",
  "provider_session_id": "4679ff49-8cfc-4b16-9138-c5bd09c2adf9",
  "response": "API_OK",
  "reasoning": "",
  "events": [
    {
      "type": "result",
      "result": "API_OK",
      "session_id": "4679ff49-8cfc-4b16-9138-c5bd09c2adf9"
    }
  ],
  "tools": [],
  "permissions": [],
  "error": null,
  "fallback": null,
  "model": null,
  "message_count": 2
}
```

### Claude Code 工具和授权事件

Claude Code provider 通过 `claude -p --output-format stream-json --verbose --include-hook-events` 调用。网关会解析 Claude Code 事件流，并归一化为以下字段：

- `events`: Claude Code 原始 JSON 事件数组。
- `tools`: 工具调用和工具结果。包括 `tool_use`、`tool_result`。
- `permissions`: 权限或授权相关事件。例如工具需要授权、权限被拒绝、hook/permission 事件。
- `error`: 后端错误文本。权限类错误也会保留在这里，便于顶部错误提示。

`tools[]` 示例：

```json
{
  "event_type": "tool_use",
  "provider": "claude",
  "tool": "Bash",
  "tool_call_id": "toolu_bash",
  "status": "requested",
  "input": {
    "command": "git status"
  },
  "output": null,
  "error": null,
  "requires_approval": false
}
```

工具结果示例：

```json
{
  "event_type": "tool_result",
  "provider": "claude",
  "tool": "Bash",
  "tool_call_id": "toolu_bash",
  "status": "completed",
  "input": null,
  "output": "On branch master",
  "error": null,
  "requires_approval": false
}
```

授权/权限事件示例：

```json
{
  "permissions": [
    {
      "event_type": "permission",
      "provider": "claude",
      "tool": "Bash",
      "tool_call_id": "toolu_bash",
      "status": "permission_denied",
      "reason": "Permission denied: Bash(git push) requires approval."
    }
  ],
  "tools": [
    {
      "event_type": "tool_result",
      "provider": "claude",
      "tool": "Bash",
      "tool_call_id": "toolu_bash",
      "status": "permission_denied",
      "error": "Permission denied: Bash(git push) requires approval.",
      "requires_approval": true
    }
  ]
}
```

说明：`/api/chat` 是非交互 HTTP 调用，Android 端不能直接替 Claude Code 点交互授权。真正放行工具需要通过 `permission_mode`、Claude Code settings、`--allowedTools` 等 Claude Code 侧配置完成。网关负责把“需要授权/被拒绝”的状态结构化返回给客户端展示。

连续上下文示例：

```powershell
$first = Invoke-RestMethod -Uri "http://localhost:8000/api/chat" -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body (@{
    provider = "claude"
    message = "Remember this token: CTX-926. Reply exactly OK."
    permission_mode = "bypassPermissions"
  } | ConvertTo-Json -Compress)

$second = Invoke-RestMethod -Uri "http://localhost:8000/api/chat" -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body (@{
    provider = "claude"
    session_id = $first.session_id
    message = "What is the token? Reply only the token."
    permission_mode = "bypassPermissions"
  } | ConvertTo-Json -Compress)

$second.response
```

预期返回：

```text
CTX-926
```

## SSE 流式对话

### POST /api/chat/stream

请求字段同 `/api/chat`。

Claude Code 请求示例：

```json
{
  "provider": "claude",
  "message": "Reply exactly SSE_PASS.",
  "permission_mode": "bypassPermissions"
}
```

响应头：

```text
Content-Type: text/event-stream
X-Session-ID: <gateway session id>
X-Provider: claude
```

事件示例：

```text
data: {"type":"text","content":"S","session_id":"xxx","provider":"claude"}

data: {"type":"tool","content":"Tool Bash call","session_id":"xxx","provider":"claude","tool":"Bash","tool_call_id":"toolu_bash","status":"requested","input":{"command":"git status"},"requires_approval":false}

data: {"type":"permission","content":"Permission permission_denied for Bash","session_id":"xxx","provider":"claude","tool":"Bash","tool_call_id":"toolu_bash","status":"permission_denied","reason":"Permission denied: Bash(git push) requires approval."}

data: {"type":"done","content":"SSE_PASS.","session_id":"xxx","provider":"claude","provider_session_id":"5361bd4f-1d8b-470e-8ffe-29dac9cbc8fc","tools":[],"permissions":[],"error":null,"fallback":null}

data: [DONE]
```

事件类型：

| 类型 | 说明 |
| --- | --- |
| `text` | 文本增量，客户端应拼接 |
| `tool` | 工具调用、工具结果或工具错误 |
| `permission` | Claude Code 权限/授权状态，例如需要授权或被拒绝 |
| `done` | 本轮完整结果 |
| `error` | 网关或后端错误 |
| `[DONE]` | SSE 结束标记 |

## 上下文策略

opencode：

- 网关把最近 10 条本地历史拼接进新 prompt。
- 本地历史最多保留 50 条消息。

Claude Code：

- 首轮调用 `claude -p --output-format stream-json --verbose --include-hook-events <message>`。
- Claude Code 返回 `session_id` 后，网关保存到 `provider_session_id`。
- 后续同一网关 `session_id` 的请求使用 `claude --resume <provider_session_id>`，上下文由 Claude Code 自己维护。
- 如果旧会话没有 `provider_session_id`，网关会临时把本地历史拼接进 prompt。

## 错误示例

opencode 余额不足时，网关会透传明确错误：

```json
{
  "detail": "opencode chat failed: Insufficient Balance"
}
```

Claude Code 未安装或不在 PATH 中时：

```json
{
  "detail": "Claude Code chat failed: ..."
}
```

## 验证记录

在 2026-06-09 使用临时端口 `127.0.0.1:8765` 验证：

- `GET /api/version` 返回 `opencode_version=1.16.2`、`claude_version=2.1.168 (Claude Code)`。
- `POST /api/chat` 使用 `provider=claude` 返回 `API_OK`。
- Claude 连续上下文测试通过：第二轮正确返回 `CTX-926`。
- `POST /api/chat/stream` 使用 `provider=claude` 返回 `SSE_PASS.`。
- opencode 当前 CLI 返回 `Insufficient Balance`，网关已正确透传为 HTTP 500 错误。
