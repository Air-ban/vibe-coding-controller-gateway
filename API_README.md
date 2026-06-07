# Opencode API Gateway

基于 FastAPI 的 Opencode API 网关，提供版本查询、模型管理、工作目录切换、对话等功能。

## 功能特性

- **版本查询**：查询当前 opencode 版本号
- **模型管理**：查询可用模型列表，切换模型
- **工作目录**：支持切换工作目录，在指定文件夹内工作
- **对话功能**：支持非流式和 SSE 流式对话
- **历史记录**：自动保存对话历史，支持上下文理解
- **会话管理**：多会话支持，会话持久化
- **局域网访问**：绑定 0.0.0.0，支持局域网内访问

## 快速开始

### 1. 安装依赖

```bash
pip install fastapi uvicorn requests
```

### 2. 启动服务

```bash
python opencode_api.py
```

服务将启动在 `http://0.0.0.0:8000`，支持局域网访问。

### 3. 访问文档

打开浏览器访问：`http://localhost:8000/docs`

## API 端点

### 系统信息

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/` | 服务信息 |
| GET | `/api/discover` | 局域网发现（供APP搜索） |
| GET | `/api/version` | 查询 opencode 版本 |

### 模型管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/models` | 查询可用模型列表 |
| GET | `/api/sessions/{id}/model` | 获取当前模型 |
| POST | `/api/sessions/{id}/model` | 切换模型 |

### 工作目录

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/workdir` | 获取工作目录 |
| POST | `/api/sessions/{id}/workdir` | 设置工作目录 |

### 会话管理

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/sessions` | 创建会话 |
| GET | `/api/sessions` | 列出所有会话 |
| GET | `/api/sessions/{id}` | 获取会话详情 |
| DELETE | `/api/sessions/{id}` | 删除会话 |

### 历史记录

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/history` | 获取历史记录 |
| DELETE | `/api/sessions/{id}/history` | 清空历史记录 |

### 对话

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/chat` | 非流式对话 |
| POST | `/api/chat/stream` | SSE 流式对话 |

## 使用示例

### 1. 局域网发现（APP搜索）

```bash
curl http://localhost:8000/api/discover
```

响应：
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

### 2. 查询版本

```bash
curl http://localhost:8000/api/version
```

响应：
```json
{
  "version": "1.16.2",
  "gateway_version": "1.0.0"
}
```

### 3. 查询模型列表

```bash
curl http://localhost:8000/api/models
```

响应：
```json
{
  "models": [
    {"id": "opencode/big-pickle", "name": "opencode/big-pickle"},
    {"id": "kimi-for-coding/k2p6", "name": "kimi-for-coding/k2p6"}
  ],
  "count": 15
}
```

### 4. 创建会话

```bash
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"work_dir": "C:\\Users\\xxx\\Desktop"}'
```

响应：
```json
{
  "session_id": "xxx",
  "work_dir": "C:\\Users\\xxx\\Desktop",
  "created_at": "2024-01-01T00:00:00"
}
```

### 5. 切换模型

```bash
curl -X POST http://localhost:8000/api/sessions/xxx/model \
  -H "Content-Type: application/json" \
  -d '{"model": "kimi-for-coding/k2p6"}'
```

### 6. 非流式对话

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你好",
    "session_id": "xxx"
  }'
```

响应：
```json
{
  "session_id": "xxx",
  "response": "你好！有什么我可以帮你的吗？",
  "model": "kimi-for-coding/k2p6",
  "message_count": 2
}
```

### 7. SSE 流式对话

```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "请介绍Python",
    "session_id": "xxx"
  }'
```

响应（SSE 事件流）：
```
data: {"type": "text", "content": "Python", "session_id": "xxx"}

data: {"type": "text", "content": " 是一种", "session_id": "xxx"}

data: {"type": "done", "content": "完整回复", "session_id": "xxx"}

data: [DONE]
```

### 8. 查询历史记录

```bash
curl http://localhost:8000/api/sessions/xxx/history
```

## 局域网访问

服务默认绑定 `0.0.0.0:8000`，局域网内的其他设备可以通过以下地址访问：

1. 获取本机 IP 地址：
```bash
ipconfig  # Windows
ifconfig  # Linux/Mac
```

2. 其他设备访问：
```
http://你的IP地址:8000
```

例如：`http://192.168.1.100:8000`

## 会话持久化

会话数据自动保存到 `sessions/` 目录下的 JSON 文件中，即使重启服务也不会丢失。

## 上下文管理

对话自动保留最近 10 条消息作为上下文，支持多轮对话和上下文理解。

## 测试

```bash
python test_api_simple.py
```

## 文件说明

- `opencode_api.py` - FastAPI 主应用
- `test_api_simple.py` - API 测试脚本
- `sessions/` - 会话数据存储目录

## 注意事项

1. 确保 opencode 已安装并在 PATH 中
2. Windows 系统下使用 PowerShell 执行命令
3. 服务启动后会自动创建 `sessions/` 目录
4. 默认端口为 8000，可通过修改代码更改
