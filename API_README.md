# Openremote API Gateway Quick API

默认 provider 是 `opencode`。要调用 Claude Code，在请求体或会话创建时传：

```json
{
  "provider": "claude"
}
```

## 版本

```powershell
curl.exe http://127.0.0.1:8000/api/version
```

返回包含：

```json
{
  "opencode_version": "1.16.2",
  "claude_version": "2.1.168 (Claude Code)",
  "gateway_version": "1.1.0",
  "providers": ["opencode", "claude"]
}
```

## 创建会话

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/sessions?provider=claude"
```

## Claude Code 对话

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

响应重点字段：

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

`tools` 会包含 Claude Code 的 `tool_use` / `tool_result`。如果工具因为权限或授权问题无法执行，`permissions` 会包含对应状态，关联的工具事件会带 `requires_approval=true`。

```json
{
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
  ],
  "permissions": [
    {
      "event_type": "permission",
      "provider": "claude",
      "tool": "Bash",
      "tool_call_id": "toolu_bash",
      "status": "permission_denied",
      "reason": "Permission denied: Bash(git push) requires approval."
    }
  ]
}
```

说明：Android 端不能直接替 Claude Code 点交互授权。真正放行工具要通过 `permission_mode`、Claude Code settings、`--allowedTools` 等 Claude Code 侧配置完成；网关只负责把“需要授权/被拒绝”的状态返回给客户端展示。

后续请求只需要传网关的 `session_id`：

```json
{
  "provider": "claude",
  "session_id": "gateway-session-id",
  "message": "Continue the conversation."
}
```

网关会使用保存的 `provider_session_id` 调用 `claude --resume`。

## SSE

```powershell
$body = @{
  provider = "claude"
  message = "Reply exactly SSE_PASS."
  permission_mode = "bypassPermissions"
} | ConvertTo-Json -Compress

Invoke-WebRequest `
  -Uri "http://127.0.0.1:8000/api/chat/stream" `
  -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

事件：

```text
data: {"type":"text","content":"S","session_id":"xxx","provider":"claude"}
data: {"type":"tool","content":"Tool Bash call","tool":"Bash","status":"requested","input":{"command":"git status"},"session_id":"xxx","provider":"claude"}
data: {"type":"permission","content":"Permission permission_denied for Bash","tool":"Bash","status":"permission_denied","reason":"Permission denied: Bash(git push) requires approval.","session_id":"xxx","provider":"claude"}
data: {"type":"done","content":"SSE_PASS.","session_id":"xxx","provider":"claude","provider_session_id":"...","tools":[],"permissions":[],"error":null}
data: [DONE]
```

完整文档见 `API文档.md`。
