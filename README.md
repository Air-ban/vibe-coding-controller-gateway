# Openremote API Gateway

FastAPI 网关，用 HTTP API 封装本机 CLI。默认兼容原来的 `opencode` 调用，现在也支持 `Claude Code`。

支持的 provider：

- `opencode`：默认后端，不传 `provider` 时使用它。
- `claude`：调用 Claude Code CLI，并保存 Claude Code 返回的真实 `session_id`，后续请求自动用 `--resume` 携带上下文。

## 安装

```powershell
python -m pip install --force-reinstall --no-deps -e .
python -m pip install fastapi uvicorn pydantic
```

确认 CLI 可用：

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

## 启动

```powershell
ocr --host 0.0.0.0 --port 8000
```

兼容旧入口：

```powershell
python opencode_api.py
```

启动后访问：

- Swagger: `http://127.0.0.1:8000/docs`
- 版本: `http://127.0.0.1:8000/api/version`
- 局域网发现: `http://127.0.0.1:8000/api/discover`

## 常用接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/version` | 查询网关、opencode、Claude Code 版本 |
| `GET` | `/api/models?provider=opencode` | 查询 opencode 模型 |
| `GET` | `/api/models?provider=claude` | 查询 Claude Code 常用别名 |
| `POST` | `/api/sessions?provider=claude` | 创建会话 |
| `GET` | `/api/sessions` | 会话列表 |
| `GET` | `/api/sessions/{id}` | 会话详情 |
| `POST` | `/api/chat` | 非流式对话 |
| `POST` | `/api/chat/stream` | SSE 流式对话 |

## Claude Code 非流式调用

```powershell
$body = @{
  provider = "claude"
  message = "Reply exactly: API_OK"
  permission_mode = "bypassPermissions"
} | ConvertTo-Json -Compress

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/chat" `
  -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

响应会包含：

```json
{
  "session_id": "gateway-session-id",
  "provider": "claude",
  "provider_session_id": "claude-code-session-id",
  "response": "API_OK",
  "events": [],
  "tools": [],
  "permissions": [],
  "error": null,
  "message_count": 2
}
```

## Claude Code 工具和授权事件

Claude Code 现在通过 `--output-format stream-json --verbose --include-hook-events` 调用。网关会解析 Claude Code 的事件流：

- `tool_use` 会返回为 `tools[]` 中 `status=requested` 的工具调用。
- `tool_result` 会返回为 `tools[]` 中 `status=completed` 或 `status=error` 的工具结果。
- 权限/授权相关内容会返回为 `permissions[]`，并在关联工具事件里设置 `requires_approval=true`。
- 非交互模式下如果 Claude Code 因权限问题退出，网关也会尽量把 stderr 归一化成 `permissions[]` 和 `error`。

权限事件示例：

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

注意：Android 端不能直接替 Claude Code 点交互授权。真正放行工具要通过 `permission_mode`、Claude Code settings、`--allowedTools` 等 Claude Code 侧配置完成；网关负责把“需要授权/被拒绝”的状态返回给客户端展示。

## Claude Code 连续上下文

```powershell
$first = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/chat" -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body (@{
    provider = "claude"
    message = "Remember this token: CTX-926. Reply exactly OK."
    permission_mode = "bypassPermissions"
  } | ConvertTo-Json -Compress)

$second = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/chat" -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body (@{
    provider = "claude"
    session_id = $first.session_id
    message = "What is the token? Reply only the token."
    permission_mode = "bypassPermissions"
  } | ConvertTo-Json -Compress)

$second.response
```

`provider_session_id` 是 Claude Code 的真实会话 ID，网关会自动保存并用于后续 `claude --resume`。

## SSE 流式调用

```json
{
  "provider": "claude",
  "message": "Reply exactly SSE_PASS.",
  "permission_mode": "bypassPermissions"
}
```

事件示例：

```text
data: {"type":"text","content":"S","session_id":"xxx","provider":"claude"}

data: {"type":"tool","content":"Tool Bash call","tool":"Bash","status":"requested","input":{"command":"git status"},"session_id":"xxx","provider":"claude"}

data: {"type":"permission","content":"Permission permission_denied for Bash","tool":"Bash","status":"permission_denied","reason":"Permission denied: Bash(git push) requires approval.","session_id":"xxx","provider":"claude"}

data: {"type":"done","content":"SSE_PASS.","session_id":"xxx","provider":"claude","provider_session_id":"...","tools":[],"permissions":[],"error":null,"fallback":null}

data: [DONE]
```

## 文件说明

- `src/openremote/api.py`: FastAPI 主实现。
- `src/openremote/cli.py`: `ocr` 命令入口。
- `opencode_api.py`: 兼容旧启动方式的包装入口。
- `API文档.md`: 完整接口文档。
- `ANDROID_OUTPUT_ADAPTER.md`: Android 输出适配说明。

## 验证

```powershell
python -m py_compile src\openremote\api.py opencode_api.py
```

本次验证结果记录见 `API文档.md` 的“验证记录”章节。
