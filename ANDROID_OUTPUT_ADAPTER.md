# Android APP Output Adapter Guide

本文档说明 Android APP 如何适配网关新的对话输出。变更目标是让 APP 能展示模型文本、推理内容、工具调用过程、工具调用结果和错误信息。

## 适配范围

涉及两个接口：

- `POST /api/chat`
- `POST /api/chat/stream`

原有 `response` 字段继续保留，旧版只展示最终文本的客户端仍可工作。新版客户端应优先读取结构化字段。

## 非流式接口

请求不变：

```json
{
  "message": "帮我看一下项目结构",
  "session_id": "可选"
}
```

响应新增 `reasoning`、`events`、`tools`、`permissions`：

```json
{
  "session_id": "xxx",
  "response": "最终回复文本",
  "reasoning": "推理文本，可能为空",
  "events": [],
  "tools": [],
  "permissions": [],
  "error": null,
  "model": "provider/model",
  "message_count": 2
}
```

字段说明：

- `response`: 最终给用户展示的助手文本。
- `reasoning`: 推理内容，可能为空。建议默认折叠或不展示。
- `events`: 后端原始 JSON 事件数组，用于调试或高级展示。
- `tools`: 归一化后的工具事件数组，Android 端主要适配这个字段。
- `permissions`: Claude Code 权限/授权相关事件数组。
- `error`: 后端错误文本。权限类错误也可能保留在这里，便于顶部错误提示。

## Tool Event 结构

`tools` 数组中的每一项格式如下：

```json
{
  "event_type": "tool",
  "tool": "bash",
  "tool_call_id": "call_xxx",
  "status": "completed",
  "input": {
    "cmd": "pwd"
  },
  "output": "/project",
  "error": null,
  "requires_approval": false,
  "raw": {}
}
```

字段说明：

- `event_type`: 上游原始事件类型。
- `tool`: 工具名称，例如 `bash`、`read`、`edit`。
- `tool_call_id`: 工具调用 ID。可能为空，客户端要做空值兼容。
- `status`: 工具状态。可能为空。
- `input`: 工具输入参数。类型不固定，建议按 JSON 对象或 JSON 元素处理。
- `output`: 工具执行结果。类型不固定，可能是字符串、对象或数组。
- `error`: 工具错误信息。非空时应按失败状态展示。
- `requires_approval`: `true` 表示该工具事件关联 Claude Code 权限/授权问题。
- `raw`: 原始事件，便于排查兼容问题。

## Permission Event 结构

Claude Code 在非交互模式下遇到需要授权或权限被拒绝时，网关会返回 `permissions`，并且 SSE 会发送 `type=permission` 事件。

```json
{
  "event_type": "permission",
  "provider": "claude",
  "tool": "Bash",
  "tool_call_id": "toolu_bash",
  "status": "permission_denied",
  "reason": "Permission denied: Bash(git push) requires approval.",
  "raw": {}
}
```

字段说明：

- `tool`: 关联工具名，可能为 `unknown`。
- `tool_call_id`: 关联工具调用 ID，可能为空。
- `status`: 常见值包括 `permission_required`、`permission_denied`、`permission_granted`。
- `reason`: 具体原因，类型不固定，建议用 `JsonElement` 承接。
- `raw`: 原始事件或原始 stderr 文本。

注意：Android 端不能直接替 Claude Code 点交互授权。真正放行工具要通过服务端的 `permission_mode`、Claude Code settings、`--allowedTools` 等 Claude Code 配置完成；APP 侧负责展示“需要授权/已拒绝/已放行”的状态。

## 流式接口 SSE

`POST /api/chat/stream` 返回 `text/event-stream`。每条消息格式：

```text
data: {"type":"text","content":"你","session_id":"xxx"}

data: {"type":"tool","content":"Tool bash call","tool":"bash","input":{"cmd":"pwd"},"session_id":"xxx"}

data: {"type":"tool","content":"Tool bash result","tool":"bash","output":"/project","session_id":"xxx"}

data: {"type":"permission","content":"Permission permission_denied for Bash","tool":"Bash","status":"permission_denied","reason":"Permission denied: Bash(git push) requires approval.","session_id":"xxx"}

data: {"type":"done","content":"完整回复","tools":[],"permissions":[],"error":null,"session_id":"xxx"}

data: [DONE]
```

事件类型：

- `text`: 普通回答文本。按 `content` 追加到当前助手消息。
- `reasoning`: 推理文本。可收集后折叠展示。
- `tool`: 工具调用事件。展示工具名、参数、结果或错误。
- `permission`: Claude Code 权限/授权状态。展示为需要授权、被拒绝或已放行。
- `error`: 网关或 opencode 执行错误。展示错误状态。
- `done`: 本轮完成。`content` 是完整回复，`tools` 和 `permissions` 是本轮事件汇总。
- `[DONE]`: SSE 结束标记，不是 JSON。

## Android 解析建议

使用 OkHttp 读取 SSE 时，按行处理：

1. 只处理以 `data:` 开头的行。
2. 去掉 `data:` 前缀并 `trim()`。
3. 如果内容是 `[DONE]`，结束本轮流式读取。
4. 否则按 JSON 解析成 `StreamEvent`。
5. 遇到空行忽略。

Kotlin 数据结构建议使用 `JsonElement` 承接动态字段：

```kotlin
@Serializable
data class StreamEvent(
    val type: String,
    val content: String? = null,
    val session_id: String? = null,
    val tool: String? = null,
    val tool_call_id: String? = null,
    val status: String? = null,
    val input: JsonElement? = null,
    val output: JsonElement? = null,
    val error: JsonElement? = null,
    val event_type: String? = null,
    val raw: JsonElement? = null,
    val requires_approval: Boolean = false,
    val reason: JsonElement? = null,
    val tools: List<ToolEvent> = emptyList(),
    val permissions: List<PermissionEvent> = emptyList()
)

@Serializable
data class ToolEvent(
    val event_type: String? = null,
    val tool: String? = null,
    val tool_call_id: String? = null,
    val status: String? = null,
    val input: JsonElement? = null,
    val output: JsonElement? = null,
    val error: JsonElement? = null,
    val requires_approval: Boolean = false,
    val raw: JsonElement? = null
)

@Serializable
data class PermissionEvent(
    val event_type: String? = null,
    val provider: String? = null,
    val tool: String? = null,
    val tool_call_id: String? = null,
    val status: String? = null,
    val reason: JsonElement? = null,
    val raw: JsonElement? = null
)
```

`kotlinx.serialization` 配置建议：

```kotlin
val json = Json {
    ignoreUnknownKeys = true
    isLenient = true
}
```

## UI 展示建议

推荐把一轮助手消息拆成三块：

- 文本区：追加 `text.content`，最终以 `done.content` 校准。
- 推理区：收集 `reasoning.content`，默认折叠。
- 工具区：每个 `tool` 事件显示为工具卡片。
- 权限区：每个 `permission` 事件显示为权限状态条或工具卡片内状态。

工具卡片展示规则：

- 有 `input`：显示“调用工具：{tool}”，参数默认折叠。
- 有 `output`：显示“工具结果：{tool}”，结果默认折叠，支持复制。
- 有 `error`：显示失败状态，错误信息高亮。
- `requires_approval=true`：显示“需要授权/权限受限”，并引导用户去服务端调整权限配置。
- 有 `status`：可显示执行中、完成、失败等状态。

工具事件可能分多次到达。合并策略：

- 优先使用 `tool_call_id` 作为 key。
- `tool_call_id` 为空时，用到达顺序作为 key。
- 同一个 key 下后到字段覆盖前面字段，例如后续 `output` 更新同一张工具卡片。

## 兼容策略

Android 端应按以下优先级读取：

非流式：

1. 展示 `response`。
2. 如果 `tools` 非空，展示工具区。
3. 如果 `permissions` 非空，展示权限/授权状态。
4. 如需调试，再读取 `events`。

流式：

1. `text` 事件实时追加到消息气泡。
2. `tool` 事件实时更新工具卡片。
3. `permission` 事件实时更新权限状态。
4. `done` 到达后用 `done.content` 替换或校准最终文本。
5. `[DONE]` 到达后关闭 loading。

## 错误处理

遇到以下情况不要崩溃：

- `tool_call_id` 为空。
- `input`、`output`、`error` 类型不是字符串。
- `tools` 数组为空。
- `permissions` 数组为空。
- `reason` 类型不是字符串。
- SSE 中出现未知 `type`。
- `raw` 字段很大或结构变化。

未知事件建议记录日志并忽略，不影响当前消息展示。

## 最小验收点

Android APP 完成适配后，至少验证：

- 普通文本回复仍能显示。
- 流式 `text` 可以逐字或逐段追加。
- 工具调用参数能显示。
- 工具执行结果能显示。
- 工具错误能显示。
- Claude Code 权限拒绝或需要授权时能显示 `permission` 状态。
- `done` 后 loading 正确结束。
- 旧服务没有 `tools/events/reasoning/permissions` 字段时不会崩溃。
