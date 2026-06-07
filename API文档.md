# Opencode API Gateway 接口文档

## 概述

Opencode API Gateway 是基于 FastAPI 构建的 RESTful API 网关，为 opencode CLI 提供 HTTP 接口封装，支持版本查询、模型管理、工作目录切换、智能对话（含SSE流式输出）、会话管理和历史记录等功能。

**基础URL**: `http://localhost:8000`  
**文档地址**: `http://localhost:8000/docs` (Swagger UI)  
**局域网访问**: `http://<本机IP>:8000`

---

## 通用规范

### 请求格式

- Content-Type: `application/json`
- 编码: UTF-8
- 所有 POST 请求体使用 JSON 格式

### 响应格式

```json
{
  "字段名": "值"
}
```

### HTTP 状态码

| 状态码 | 含义 |
|--------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在（会话不存在） |
| 500 | 服务器内部错误 |
| 504 | 请求超时 |

### 错误响应

```json
{
  "detail": "错误描述信息"
}
```

---

## 接口列表

### 1. 系统信息

#### 1.1 获取服务信息

```
GET /
```

**响应示例**:

```json
{
  "name": "Opencode API Gateway",
  "version": "1.0.0",
  "docs": "/docs"
}
```

#### 1.2 局域网发现

```
GET /api/discover
```

**说明**: 供手机APP在局域网内搜索此服务时使用。

**响应**:

| 字段 | 类型 | 说明 |
|------|------|------|
| service | string | 服务标识: `opencode-api-gateway` |
| name | string | 服务名称 |
| gateway_version | string | API 网关版本号 |
| opencode_version | string | opencode 版本号 |
| computer_name | string | 计算机名 |
| port | integer | 服务端口 |
| docs_url | string | 文档地址 |

**响应示例**:

```json
{
  "service": "opencode-api-gateway",
  "name": "Opencode API Gateway",
  "gateway_version": "1.0.0",
  "opencode_version": "1.16.2",
  "computer_name": "MyPC",
  "port": 8000,
  "docs_url": "/docs"
}
```

#### 1.3 查询 opencode 版本

```
GET /api/version
```

**响应**:

| 字段 | 类型 | 说明 |
|------|------|------|
| version | string | opencode 版本号 |
| gateway_version | string | API 网关版本号 |

**响应示例**:

```json
{
  "version": "1.16.2",
  "gateway_version": "1.0.0"
}
```

---

### 2. 模型管理

#### 2.1 查询可用模型列表

```
GET /api/models
```

**响应**:

| 字段 | 类型 | 说明 |
|------|------|------|
| models | array | 模型列表 |
| models[].id | string | 模型ID，格式: provider/model |
| models[].name | string | 模型名称 |
| count | integer | 模型总数 |

**响应示例**:

```json
{
  "models": [
    {
      "id": "opencode/big-pickle",
      "name": "opencode/big-pickle"
    },
    {
      "id": "deepseek/deepseek-chat",
      "name": "deepseek/deepseek-chat"
    },
    {
      "id": "kimi-for-coding/k2p6",
      "name": "kimi-for-coding/k2p6"
    }
  ],
  "count": 15
}
```

#### 2.2 获取当前会话模型

```
GET /api/sessions/{session_id}/model
```

**路径参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话ID |

**响应**:

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | string | 会话ID |
| current_model | string \| null | 当前使用的模型 |
| work_dir | string | 工作目录 |

**响应示例**:

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "current_model": "kimi-for-coding/k2p6",
  "work_dir": "C:\\Users\\xxx\\Desktop"
}
```

#### 2.3 切换模型

```
POST /api/sessions/{session_id}/model
```

**路径参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话ID |

**请求体**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| model | string | 是 | 模型ID，格式: provider/model |

**请求示例**:

```json
{
  "model": "kimi-for-coding/k2p6"
}
```

**响应**:

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | string | 会话ID |
| model | string | 切换后的模型 |
| message | string | 操作结果提示 |

**响应示例**:

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "model": "kimi-for-coding/k2p6",
  "message": "模型切换成功"
}
```

**错误响应**:

```json
{
  "detail": "模型 'invalid/model' 不可用。可用模型: opencode/big-pickle, deepseek/deepseek-chat, ..."
}
```

---

### 3. 工作目录管理

#### 3.1 获取工作目录

```
GET /api/sessions/{session_id}/workdir
```

**路径参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话ID |

**响应**:

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | string | 会话ID |
| work_dir | string | 当前工作目录绝对路径 |

**响应示例**:

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "work_dir": "C:\\Users\\xxx\\Desktop"
}
```

#### 3.2 设置工作目录

```
POST /api/sessions/{session_id}/workdir
```

**路径参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话ID |

**请求体**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| path | string | 是 | 工作目录路径（绝对或相对路径） |

**请求示例**:

```json
{
  "path": "C:\\Users\\xxx\\Desktop"
}
```

**响应**:

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | string | 会话ID |
| work_dir | string | 设置后的工作目录绝对路径 |
| message | string | 操作结果提示 |

**响应示例**:

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "work_dir": "C:\\Users\\xxx\\Desktop",
  "message": "工作目录设置成功"
}
```

**错误响应**:

```json
{
  "detail": "目录不存在: C:\\nonexistent"
}
```

---

### 4. 会话管理

#### 4.1 创建会话

```
POST /api/sessions
```

**查询参数** (可选):

| 参数 | 类型 | 说明 |
|------|------|------|
| work_dir | string | 初始工作目录，不传则使用当前目录 |

**响应**:

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | string | 新创建的会话ID (UUID) |
| work_dir | string | 工作目录 |
| created_at | string | 创建时间 (ISO 8601) |

**响应示例**:

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "work_dir": "C:\\Users\\xxx\\Documents",
  "created_at": "2026-06-08T10:30:00.000000"
}
```

#### 4.2 列出所有会话

```
GET /api/sessions
```

**响应**:

| 字段 | 类型 | 说明 |
|------|------|------|
| sessions | array | 会话列表 |
| sessions[].session_id | string | 会话ID |
| sessions[].work_dir | string | 工作目录 |
| sessions[].current_model | string \| null | 当前模型 |
| sessions[].message_count | integer | 消息数量 |
| sessions[].created_at | string | 创建时间 |
| sessions[].updated_at | string | 最后更新时间 |
| count | integer | 会话总数 |

**响应示例**:

```json
{
  "sessions": [
    {
      "session_id": "550e8400-e29b-41d4-a716-446655440000",
      "work_dir": "C:\\Users\\xxx\\Desktop",
      "current_model": "kimi-for-coding/k2p6",
      "message_count": 10,
      "created_at": "2026-06-08T10:00:00",
      "updated_at": "2026-06-08T10:30:00"
    }
  ],
  "count": 1
}
```

#### 4.3 获取会话详情

```
GET /api/sessions/{session_id}
```

**路径参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话ID |

**响应**:

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | string | 会话ID |
| work_dir | string | 工作目录 |
| current_model | string \| null | 当前模型 |
| message_count | integer | 消息数量 |
| created_at | string | 创建时间 |
| updated_at | string | 最后更新时间 |

**响应示例**:

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "work_dir": "C:\\Users\\xxx\\Desktop",
  "current_model": "kimi-for-coding/k2p6",
  "message_count": 10,
  "created_at": "2026-06-08T10:00:00",
  "updated_at": "2026-06-08T10:30:00"
}
```

#### 4.4 删除会话

```
DELETE /api/sessions/{session_id}
```

**路径参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话ID |

**响应示例**:

```json
{
  "message": "会话已删除"
}
```

---

### 5. 历史记录

#### 5.1 获取历史记录

```
GET /api/sessions/{session_id}/history
```

**路径参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话ID |

**响应**:

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | string | 会话ID |
| history | array | 消息列表 |
| history[].role | string | 角色: user / assistant |
| history[].content | string | 消息内容 |
| history[].timestamp | string | 时间戳 (ISO 8601) |
| history[].work_dir | string | 工作目录 |
| count | integer | 消息总数 |

**响应示例**:

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "history": [
    {
      "role": "user",
      "content": "你好",
      "timestamp": "2026-06-08T10:00:00",
      "work_dir": "C:\\Users\\xxx\\Desktop"
    },
    {
      "role": "assistant",
      "content": "你好！有什么我可以帮你的吗？",
      "timestamp": "2026-06-08T10:00:05",
      "work_dir": "C:\\Users\\xxx\\Desktop"
    }
  ],
  "count": 2
}
```

#### 5.2 清空历史记录

```
DELETE /api/sessions/{session_id}/history
```

**路径参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话ID |

**响应示例**:

```json
{
  "message": "历史记录已清空"
}
```

---

### 6. 对话功能

#### 6.1 非流式对话

```
POST /api/chat
```

**请求体**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| message | string | 是 | 用户消息 |
| session_id | string | 否 | 会话ID，不传则创建新会话 |
| stream | boolean | 否 | 是否流式输出，默认 false |

**请求示例**:

```json
{
  "message": "你好",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**响应**:

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | string | 会话ID |
| response | string | 助手回复 |
| model | string \| null | 使用的模型 |
| message_count | integer | 当前会话消息总数 |

**响应示例**:

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "response": "你好！有什么我可以帮你的吗？",
  "model": "kimi-for-coding/k2p6",
  "message_count": 2
}
```

#### 6.2 SSE 流式对话

```
POST /api/chat/stream
```

**请求体**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| message | string | 是 | 用户消息 |
| session_id | string | 否 | 会话ID，不传则创建新会话 |

**请求示例**:

```json
{
  "message": "请介绍Python",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**响应**: SSE (Server-Sent Events) 流

**Content-Type**: `text/event-stream`

**事件格式**:

```
data: {"type": "事件类型", "content": "内容", "session_id": "xxx"}

data: [DONE]
```

**事件类型**:

| 类型 | 说明 | 示例 |
|------|------|------|
| text | 文本内容 | `{"type": "text", "content": "Python", "session_id": "xxx"}` |
| reasoning | 思考过程 | `{"type": "reasoning", "content": "...", "session_id": "xxx"}` |
| tool | 工具调用 | `{"type": "tool", "content": "使用工具: bash", "tool": "bash", "session_id": "xxx"}` |
| done | 完成标记 | `{"type": "done", "content": "完整回复", "session_id": "xxx"}` |
| error | 错误信息 | `{"type": "error", "content": "错误描述", "session_id": "xxx"}` |

**SSE 响应示例**:

```
data: {"type": "text", "content": "Python", "session_id": "550e8400-e29b-41d4-a716-446655440000"}

data: {"type": "text", "content": " 是一种", "session_id": "550e8400-e29b-41d4-a716-446655440000"}

data: {"type": "text", "content": "高级编程语言", "session_id": "550e8400-e29b-41d4-a716-446655440000"}

data: {"type": "done", "content": "Python 是一种高级编程语言...", "session_id": "550e8400-e29b-41d4-a716-446655440000"}

data: [DONE]
```

**响应头**:

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Session-ID: 550e8400-e29b-41d4-a716-446655440000
```

---

## 使用示例

### 完整对话流程

```bash
# 1. 查询版本
 curl http://localhost:8000/api/version

# 2. 查询模型
 curl http://localhost:8000/api/models

# 3. 创建会话（指定工作目录）
curl -X POST "http://localhost:8000/api/sessions" \
  -H "Content-Type: application/json" \
  -d '{"work_dir": "C:\\Users\\xxx\\Desktop"}'

# 返回: {"session_id": "550e8400-...", ...}

# 4. 切换模型
curl -X POST "http://localhost:8000/api/sessions/550e8400-.../model" \
  -H "Content-Type: application/json" \
  -d '{"model": "kimi-for-coding/k2p6"}'

# 5. 进行对话
curl -X POST "http://localhost:8000/api/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "列出当前目录文件",
    "session_id": "550e8400-..."
  }'

# 6. 查看历史
curl "http://localhost:8000/api/sessions/550e8400-.../history"

# 7. SSE 流式对话
curl -X POST "http://localhost:8000/api/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "分析这些文件的用途",
    "session_id": "550e8400-..."
  }'
```

### Python 客户端示例

```python
import requests
import json

BASE_URL = "http://localhost:8000"

class OpencodeClient:
    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url
        self.session_id = None
    
    def create_session(self, work_dir=None):
        """创建会话"""
        params = {}
        if work_dir:
            params['work_dir'] = work_dir
        
        r = requests.post(f"{self.base_url}/api/sessions", params=params)
        data = r.json()
        self.session_id = data['session_id']
        return data
    
    def set_model(self, model):
        """切换模型"""
        r = requests.post(
            f"{self.base_url}/api/sessions/{self.session_id}/model",
            json={"model": model}
        )
        return r.json()
    
    def set_workdir(self, path):
        """设置工作目录"""
        r = requests.post(
            f"{self.base_url}/api/sessions/{self.session_id}/workdir",
            json={"path": path}
        )
        return r.json()
    
    def chat(self, message):
        """非流式对话"""
        r = requests.post(
            f"{self.base_url}/api/chat",
            json={"message": message, "session_id": self.session_id}
        )
        return r.json()
    
    def chat_stream(self, message):
        """流式对话"""
        r = requests.post(
            f"{self.base_url}/api/chat/stream",
            json={"message": message, "session_id": self.session_id},
            stream=True
        )
        
        for line in r.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]
                    if data_str == '[DONE]':
                        break
                    yield json.loads(data_str)
    
    def get_history(self):
        """获取历史记录"""
        r = requests.get(
            f"{self.base_url}/api/sessions/{self.session_id}/history"
        )
        return r.json()


# 使用示例
client = OpencodeClient()

# 创建会话
client.create_session(work_dir="C:\\Users\\xxx\\Desktop")

# 切换模型
client.set_model("kimi-for-coding/k2p6")

# 对话
response = client.chat("你好")
print(response['response'])

# 流式对话
for event in client.chat_stream("请介绍Python"):
    if event['type'] == 'text':
        print(event['content'], end='', flush=True)
    elif event['type'] == 'done':
        print("\n完成!")
```

### JavaScript 客户端示例

```javascript
class OpencodeClient {
  constructor(baseUrl = 'http://localhost:8000') {
    this.baseUrl = baseUrl;
    this.sessionId = null;
  }
  
  async createSession(workDir) {
    const params = workDir ? `?work_dir=${encodeURIComponent(workDir)}` : '';
    const res = await fetch(`${this.baseUrl}/api/sessions${params}`, {
      method: 'POST'
    });
    const data = await res.json();
    this.sessionId = data.session_id;
    return data;
  }
  
  async chat(message) {
    const res = await fetch(`${this.baseUrl}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, session_id: this.sessionId })
    });
    return res.json();
  }
  
  async *chatStream(message) {
    const res = await fetch(`${this.baseUrl}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, session_id: this.sessionId })
    });
    
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';
      
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') return;
          yield JSON.parse(data);
        }
      }
    }
  }
}

// 使用示例
const client = new OpencodeClient();

async function main() {
  await client.createSession('C:\\Users\\xxx\\Desktop');
  
  // 流式对话
  for await (const event of client.chatStream('请介绍Python')) {
    if (event.type === 'text') {
      process.stdout.write(event.content);
    }
  }
}

main();
```

---

## 上下文管理

API 自动管理对话上下文：

1. **上下文保留**：自动保留最近 10 条消息作为上下文
2. **上下文构建**：发送消息时自动将历史记录拼接为上下文
3. **历史限制**：单个会话最多保留 50 条消息，超出后自动清理旧消息
4. **持久化**：会话数据自动保存到 `sessions/` 目录

**上下文格式**:

```
以下是之前的对话历史：

用户: 你好
助手: 你好！有什么我可以帮你的吗？
用户: 我叫张三
助手: 你好张三！

用户的新问题: 我叫什么名字

请根据以上对话历史回答用户的新问题。
```

---

## 注意事项

1. **opencode 依赖**: 确保 opencode CLI 已安装并在系统 PATH 中
2. **PowerShell**: Windows 系统下使用 PowerShell 执行命令
3. **编码**: 所有文本使用 UTF-8 编码
4. **超时**: 单次对话请求超时时间为 120 秒
5. **目录权限**: 设置工作目录时确保有读写权限
6. **模型可用性**: 切换模型时会自动验证模型是否在可用列表中

---

## 错误码速查

| HTTP 状态码 | 场景 | 解决方案 |
|------------|------|----------|
| 200 | 成功 | - |
| 400 | 参数错误（目录不存在、模型不可用） | 检查参数合法性 |
| 404 | 会话不存在 | 创建新会话或检查 session_id |
| 500 | 服务器错误（opencode 执行失败） | 检查 opencode 安装和配置 |
| 504 | 请求超时 | 简化问题或检查网络 |

---

## 更新日志

### v1.0.0 (2026-06-08)

- 初始版本发布
- 支持版本查询、模型管理
- 支持工作目录切换
- 支持非流式和 SSE 流式对话
- 支持会话管理和历史记录
- 支持局域网访问
