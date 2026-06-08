"""
Opencode API Gateway
基于 FastAPI 的 API 网关，提供版本查询、模型管理、工作目录切换、对话等功能
"""

import subprocess
import json
import os
import re
import asyncio
import uuid
import socket
import shutil
from datetime import datetime
from typing import Optional, List, Dict, Any, AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# ============== Pydantic Models ==============

class WorkDirRequest(BaseModel):
    path: str = Field(..., description="工作目录路径")

class ChatRequest(BaseModel):
    message: str = Field(..., description="用户消息")
    stream: bool = Field(default=False, description="是否使用流式输出")
    session_id: Optional[str] = Field(default=None, description="会话ID，不传则创建新会话")

class ModelRequest(BaseModel):
    model: str = Field(..., description="模型ID，格式: provider/model")

class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: str
    work_dir: Optional[str] = None

class SessionInfo(BaseModel):
    session_id: str
    work_dir: str
    current_model: Optional[str] = None
    message_count: int
    created_at: str
    updated_at: str


# ============== Utility Functions ==============

def strip_ansi(text: str) -> str:
    """去除 ANSI 转义序列"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def run_opencode_command(args: List[str], work_dir: Optional[str] = None) -> tuple:
    """
    执行 opencode 命令

    Returns:
        (stdout, stderr, returncode)
    """
    cmd = ['powershell', '-Command']

    ps_command = '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; '

    if work_dir:
        ps_command += f'Set-Location -LiteralPath "{work_dir}"; '

    ps_command += 'opencode ' + ' '.join(args)

    cmd.append(ps_command)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=False,
            timeout=120
        )

        stdout = result.stdout.decode('utf-8', errors='replace')
        stderr = result.stderr.decode('utf-8', errors='replace')

        return stdout, stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "命令执行超时", -1
    except Exception as e:
        return "", str(e), -1


def _get_data_dir() -> str:
    """获取数据存储目录"""
    data_dir = os.path.join(os.path.expanduser("~"), ".openremote")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


# ============== Session Manager ==============

class SessionManager:
    """会话管理器"""

    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.history_dir = os.path.join(_get_data_dir(), 'sessions')
        os.makedirs(self.history_dir, exist_ok=True)

    def create_session(self, work_dir: Optional[str] = None) -> str:
        """创建新会话"""
        session_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        session = {
            'session_id': session_id,
            'work_dir': work_dir or os.getcwd(),
            'current_model': None,
            'history': [],
            'created_at': now,
            'updated_at': now
        }

        self.sessions[session_id] = session
        self._save_session(session_id)

        return session_id

    def get_session(self, session_id: str) -> Optional[Dict]:
        """获取会话"""
        if session_id in self.sessions:
            return self.sessions[session_id]

        # 尝试从文件加载
        session_file = os.path.join(self.history_dir, f"{session_id}.json")
        if os.path.exists(session_file):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session = json.load(f)
                self.sessions[session_id] = session
                return session
            except:
                return None

        return None

    def update_session(self, session_id: str, updates: Dict) -> bool:
        """更新会话"""
        session = self.get_session(session_id)
        if not session:
            return False

        session.update(updates)
        session['updated_at'] = datetime.now().isoformat()
        self._save_session(session_id)
        return True

    def add_message(self, session_id: str, role: str, content: str) -> bool:
        """添加消息到历史记录"""
        session = self.get_session(session_id)
        if not session:
            return False

        message = {
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'work_dir': session.get('work_dir')
        }

        session['history'].append(message)
        session['updated_at'] = datetime.now().isoformat()

        # 限制历史记录长度（保留最近 50 条）
        if len(session['history']) > 50:
            session['history'] = session['history'][-50:]

        self._save_session(session_id)
        return True

    def clear_history(self, session_id: str) -> bool:
        """清空历史记录"""
        session = self.get_session(session_id)
        if not session:
            return False

        session['history'] = []
        session['updated_at'] = datetime.now().isoformat()
        self._save_session(session_id)
        return True

    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]

        session_file = os.path.join(self.history_dir, f"{session_id}.json")
        if os.path.exists(session_file):
            os.remove(session_file)
            return True
        return False

    def list_sessions(self) -> List[Dict]:
        """列出所有会话"""
        sessions = []
        for filename in os.listdir(self.history_dir):
            if filename.endswith('.json'):
                session_id = filename[:-5]
                session = self.get_session(session_id)
                if session:
                    sessions.append({
                        'session_id': session['session_id'],
                        'work_dir': session['work_dir'],
                        'current_model': session.get('current_model'),
                        'message_count': len(session['history']),
                        'created_at': session['created_at'],
                        'updated_at': session['updated_at']
                    })
        return sessions

    def _save_session(self, session_id: str):
        """保存会话到文件"""
        session = self.sessions.get(session_id)
        if session:
            session_file = os.path.join(self.history_dir, f"{session_id}.json")
            try:
                with open(session_file, 'w', encoding='utf-8') as f:
                    json.dump(session, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"保存会话失败: {e}")


# ============== Global Instances ==============

session_manager = SessionManager()

# 缓存 opencode 版本
_opencode_version_cache: Optional[str] = None


def get_opencode_version() -> str:
    """获取 opencode 版本（带缓存）"""
    global _opencode_version_cache
    if _opencode_version_cache is None:
        stdout, stderr, returncode = run_opencode_command(['--version'])
        if returncode == 0:
            _opencode_version_cache = stdout.strip()
        else:
            _opencode_version_cache = "unknown"
    return _opencode_version_cache


def get_computer_name() -> str:
    """获取计算机名"""
    return socket.gethostname()


# ============== FastAPI App ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时加载所有会话
    print("Opencode API Gateway 启动中...")
    print(f"会话目录: {session_manager.history_dir}")
    yield
    # 关闭时保存所有会话
    print("Opencode API Gateway 关闭中...")


app = FastAPI(
    title="Opencode API Gateway",
    description="基于 FastAPI 的 Opencode API 网关，提供版本查询、模型管理、对话等功能",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== API Endpoints ==============

@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "Opencode API Gateway",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/api/discover")
async def discover():
    """
    局域网发现接口
    供手机APP在局域网内搜索此服务时使用
    """
    return {
        "service": "opencode-api-gateway",
        "name": "Opencode API Gateway",
        "gateway_version": "1.0.0",
        "opencode_version": get_opencode_version(),
        "computer_name": get_computer_name(),
        "port": 8000,
        "docs_url": "/docs"
    }


# ----- 版本查询 -----

@app.get("/api/version")
async def get_version():
    """
    查询当前 opencode 版本号

    Returns:
        {
            "version": "1.16.2",
            "gateway_version": "1.0.0"
        }
    """
    version = get_opencode_version()
    if version == "unknown":
        raise HTTPException(status_code=500, detail="获取版本失败")

    return {
        "version": version,
        "gateway_version": "1.0.0"
    }


# ----- 模型管理 -----

@app.get("/api/models")
async def list_models():
    """
    查询当前 opencode 可用的模型列表

    Returns:
        {
            "models": [
                {"id": "provider/model", "name": "provider/model"},
                ...
            ]
        }
    """
    stdout, stderr, returncode = run_opencode_command(['models'])

    if returncode != 0:
        raise HTTPException(status_code=500, detail=f"获取模型列表失败: {stderr}")

    models = []
    for line in stdout.strip().split('\n'):
        line = line.strip()
        if line and not line.startswith('>'):
            models.append({
                "id": line,
                "name": line
            })

    return {
        "models": models,
        "count": len(models)
    }


@app.get("/api/sessions/{session_id}/model")
async def get_current_model(session_id: str):
    """
    获取当前会话使用的模型

    Args:
        session_id: 会话ID
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    return {
        "session_id": session_id,
        "current_model": session.get('current_model'),
        "work_dir": session['work_dir']
    }


@app.post("/api/sessions/{session_id}/model")
async def set_model(session_id: str, request: ModelRequest):
    """
    切换当前会话使用的模型

    Args:
        session_id: 会话ID
        request: {"model": "provider/model"}

    Returns:
        {
            "session_id": "xxx",
            "model": "provider/model",
            "message": "模型切换成功"
        }
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 验证模型是否可用
    stdout, stderr, returncode = run_opencode_command(['models'])
    if returncode != 0:
        raise HTTPException(status_code=500, detail=f"获取模型列表失败: {stderr}")

    available_models = [line.strip() for line in stdout.strip().split('\n') if line.strip() and not line.strip().startswith('>')]

    if request.model not in available_models:
        raise HTTPException(
            status_code=400,
            detail=f"模型 '{request.model}' 不可用。可用模型: {', '.join(available_models)}"
        )

    session_manager.update_session(session_id, {'current_model': request.model})

    return {
        "session_id": session_id,
        "model": request.model,
        "message": "模型切换成功"
    }


# ----- 工作目录 -----

@app.get("/api/sessions/{session_id}/workdir")
async def get_workdir(session_id: str):
    """
    获取当前会话的工作目录

    Args:
        session_id: 会话ID
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    return {
        "session_id": session_id,
        "work_dir": session['work_dir']
    }


@app.post("/api/sessions/{session_id}/workdir")
async def set_workdir(session_id: str, request: WorkDirRequest):
    """
    设置工作目录

    Args:
        session_id: 会话ID
        request: {"path": "C:\\Users\\xxx\\Desktop"}

    Returns:
        {
            "session_id": "xxx",
            "work_dir": "C:\\Users\\xxx\\Desktop",
            "message": "工作目录设置成功"
        }
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 验证目录是否存在
    if not os.path.exists(request.path):
        raise HTTPException(status_code=400, detail=f"目录不存在: {request.path}")

    if not os.path.isdir(request.path):
        raise HTTPException(status_code=400, detail=f"路径不是目录: {request.path}")

    abs_path = os.path.abspath(request.path)
    session_manager.update_session(session_id, {'work_dir': abs_path})

    return {
        "session_id": session_id,
        "work_dir": abs_path,
        "message": "工作目录设置成功"
    }


# ----- 会话管理 -----

@app.post("/api/sessions")
async def create_session(work_dir: Optional[str] = None):
    """
    创建新会话

    Args:
        work_dir: 可选，工作目录路径

    Returns:
        {
            "session_id": "xxx",
            "work_dir": "xxx",
            "created_at": "2024-01-01T00:00:00"
        }
    """
    if work_dir and not os.path.exists(work_dir):
        raise HTTPException(status_code=400, detail=f"目录不存在: {work_dir}")

    session_id = session_manager.create_session(work_dir)
    session = session_manager.get_session(session_id)

    return {
        "session_id": session_id,
        "work_dir": session['work_dir'],
        "created_at": session['created_at']
    }


@app.get("/api/sessions")
async def list_sessions():
    """
    列出所有会话

    Returns:
        {
            "sessions": [
                {
                    "session_id": "xxx",
                    "work_dir": "xxx",
                    "current_model": "xxx",
                    "message_count": 10
                }
            ]
        }
    """
    sessions = session_manager.list_sessions()
    return {
        "sessions": sessions,
        "count": len(sessions)
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """
    获取会话详情

    Args:
        session_id: 会话ID
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    return {
        "session_id": session['session_id'],
        "work_dir": session['work_dir'],
        "current_model": session.get('current_model'),
        "message_count": len(session['history']),
        "created_at": session['created_at'],
        "updated_at": session['updated_at']
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    删除会话

    Args:
        session_id: 会话ID
    """
    if not session_manager.delete_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")

    return {"message": "会话已删除"}


# ----- 历史记录 -----

@app.get("/api/sessions/{session_id}/history")
async def get_history(session_id: str):
    """
    获取会话历史记录

    Args:
        session_id: 会话ID
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    return {
        "session_id": session_id,
        "history": session['history'],
        "count": len(session['history'])
    }


@app.delete("/api/sessions/{session_id}/history")
async def clear_history(session_id: str):
    """
    清空会话历史记录

    Args:
        session_id: 会话ID
    """
    if not session_manager.clear_history(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")

    return {"message": "历史记录已清空"}


# ----- 对话功能 -----

def build_context(history: List[Dict], user_message: str, max_history: int = 10) -> str:
    """构建带上下文的完整消息"""
    if not history:
        return user_message

    # 只保留最近的消息
    recent_history = history[-max_history:]

    context = "以下是之前的对话历史：\n\n"
    for msg in recent_history:
        role = msg['role']
        content = msg['content']
        if role == 'user':
            context += f"用户: {content}\n"
        elif role == 'assistant':
            context += f"助手: {content}\n"

    context += f"\n用户的新问题: {user_message}\n"
    context += "\n请根据以上对话历史回答用户的新问题。"

    return context


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_dicts(item)


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _get_event_part(event: Dict[str, Any]) -> Dict[str, Any]:
    containers = [
        event,
        _as_dict(event.get("data")),
        _as_dict(event.get("properties")),
        _as_dict(event.get("message")),
    ]
    for container in containers:
        part = container.get("part")
        if isinstance(part, dict):
            return part
        for key in ("parts", "content"):
            items = container.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        return item
        delta = container.get("delta")
        if isinstance(delta, dict):
            part = delta.get("part")
            if isinstance(part, dict):
                return part
            if str(delta.get("type", "")).lower() in ("text", "reasoning"):
                return delta
    return {}


def _extract_event_text(event: Dict[str, Any], part: Dict[str, Any]) -> tuple[Optional[str], str]:
    raw_type = str(event.get("type", "")).lower().replace(".", "_").replace("-", "_")
    part_type = str(part.get("type", "")).lower().replace(".", "_").replace("-", "_")
    text_type = part_type if part_type in ("text", "reasoning") else raw_type

    if text_type not in ("text", "reasoning"):
        if "reasoning" in raw_type or "reasoning" in part_type:
            text_type = "reasoning"
        elif "text" in raw_type or "content" in raw_type or "message" in raw_type:
            text_type = "text"
        elif any(
            isinstance(candidate.get(key), str)
            for candidate in (part, event, _as_dict(event.get("data")), _as_dict(event.get("message")))
            for key in ("delta", "text", "content")
        ):
            text_type = "text"
        else:
            for candidate in _iter_dicts(event):
                candidate_type = str(candidate.get("type", "")).lower()
                if candidate_type in ("text", "reasoning"):
                    text_type = candidate_type
                    break

    if text_type not in ("text", "reasoning"):
        return None, ""

    text = _first_value(
        part.get("delta"),
        event.get("delta"),
        part.get("text"),
        event.get("text"),
        part.get("content"),
        event.get("content"),
        part.get("response"),
        event.get("response"),
        part.get("output"),
        event.get("output"),
        part.get("result"),
        event.get("result"),
    )
    if isinstance(text, str):
        return text_type, text

    chunks: List[str] = []
    for candidate in _iter_dicts(event):
        candidate_type = str(candidate.get("type", "")).lower()
        if candidate_type not in ("text", "reasoning") and not any(key in candidate for key in ("delta", "text", "content", "response", "output", "result")):
            continue
        value = _first_value(
            candidate.get("delta"),
            candidate.get("text"),
            candidate.get("content"),
            candidate.get("response"),
            candidate.get("output"),
            candidate.get("result"),
        )
        if isinstance(value, str):
            chunks.append(value)

    return text_type, "".join(chunks)


def _normalize_tool_event(event: Dict[str, Any], part: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw_type = str(event.get("type", "")).lower()
    part_type = str(part.get("type", "")).lower()
    data = _as_dict(event.get("data"))
    state = _as_dict(_first_value(part.get("state"), event.get("state"), data.get("state")))
    function = _as_dict(_first_value(part.get("function"), event.get("function"), data.get("function")))
    has_tool_shape = (
        "tool" in raw_type
        or part_type == "tool"
        or any(key in part for key in ("tool", "tool_name", "tool_call_id"))
        or any(key in event for key in ("tool", "tool_name", "tool_call_id"))
        or any(key in data for key in ("tool", "tool_name", "tool_call_id"))
        or bool(function)
    )

    tool_name = _first_value(
        part.get("tool"),
        part.get("name"),
        part.get("tool_name"),
        function.get("name"),
        event.get("tool"),
        event.get("name"),
        data.get("tool"),
        data.get("name"),
    )

    if not has_tool_shape:
        return None

    return {
        "event_type": event.get("type", "unknown"),
        "tool": tool_name or "unknown",
        "tool_call_id": _first_value(
            part.get("tool_call_id"),
            part.get("id"),
            event.get("tool_call_id"),
            event.get("id"),
            data.get("tool_call_id"),
            data.get("id"),
        ),
        "status": _first_value(
            part.get("status"),
            state.get("status"),
            event.get("status"),
            data.get("status"),
        ),
        "input": _first_value(
            part.get("input"),
            part.get("arguments"),
            part.get("args"),
            part.get("params"),
            part.get("parameters"),
            state.get("input"),
            event.get("input"),
            event.get("arguments"),
            data.get("input"),
            data.get("arguments"),
        ),
        "output": _first_value(
            part.get("output"),
            part.get("result"),
            part.get("response"),
            state.get("output"),
            state.get("result"),
            event.get("output"),
            event.get("result"),
            data.get("output"),
            data.get("result"),
        ),
        "error": _first_value(
            part.get("error"),
            state.get("error"),
            event.get("error"),
            data.get("error"),
        ),
        "raw": event,
    }


def _format_tool_content(tool_event: Dict[str, Any]) -> str:
    tool_name = tool_event.get("tool") or "unknown"
    status = tool_event.get("status")

    if tool_event.get("error") is not None:
        return f"Tool {tool_name} failed"
    if tool_event.get("output") is not None:
        return f"Tool {tool_name} result"
    if tool_event.get("input") is not None:
        return f"Tool {tool_name} call"
    if status:
        return f"Tool {tool_name} {status}"
    return f"Tool {tool_name}"


def _parse_opencode_json_output(output: str) -> tuple[str, str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    response_parts: List[str] = []
    reasoning_parts: List[str] = []
    events: List[Dict[str, Any]] = []
    tools: List[Dict[str, Any]] = []

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            line = strip_ansi(line).strip()
            if line and not line.startswith('>') and not line.startswith('build'):
                response_parts.append(f"{line}\n")
            continue

        if not isinstance(event, dict):
            continue

        events.append(event)
        part = _get_event_part(event)

        text_type, text = _extract_event_text(event, part)
        if text:
            if text_type == "reasoning":
                reasoning_parts.append(text)
            else:
                response_parts.append(text)

        tool_event = _normalize_tool_event(event, part)
        if tool_event:
            tools.append(tool_event)

    return ''.join(response_parts).strip(), ''.join(reasoning_parts).strip(), events, tools


def _resolve_opencode_executable() -> str:
    candidates = [
        os.environ.get('OPENCODE_BIN'),
    ]

    appdata = os.environ.get('APPDATA')
    if appdata:
        candidates.append(os.path.join(appdata, 'npm', 'node_modules', 'opencode-ai', 'bin', 'opencode.exe'))

    candidates.extend([
        shutil.which('opencode.exe'),
        shutil.which('opencode.cmd'),
        shutil.which('opencode'),
    ])

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate

    return 'opencode'


def _build_opencode_run_args(message: str, current_model: Optional[str], output_format: str) -> List[str]:
    args = [_resolve_opencode_executable(), 'run', message, '--format', output_format, '--no-replay']
    if current_model:
        args.extend(['--model', current_model])
    return args


def _parse_opencode_default_output(output: str) -> str:
    output = strip_ansi(output).strip()
    cleaned_lines = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('>') or line.startswith('build'):
            continue
        cleaned_lines.append(line)
    return '\n'.join(cleaned_lines).strip()


def _run_opencode_capture(
    message: str,
    current_model: Optional[str],
    work_dir: str,
    output_format: str,
    timeout: int = 120,
) -> tuple[str, str, int]:
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    result = subprocess.run(
        _build_opencode_run_args(message, current_model, output_format),
        cwd=work_dir,
        capture_output=True,
        text=False,
        timeout=timeout,
        env=env,
    )
    stdout = result.stdout.decode('utf-8', errors='replace')
    stderr = result.stderr.decode('utf-8', errors='replace')
    return stdout, stderr, result.returncode


async def _stream_text(text: str, event_type: str, session_id: str) -> AsyncGenerator[str, None]:
    """将文本逐字符流式发送"""
    for char in text:
        sse_event = {
            'type': event_type,
            'content': char,
            'session_id': session_id
        }
        yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.005)


async def chat_stream_generator_legacy(session_id: str, message: str) -> AsyncGenerator[str, None]:
    """
    SSE 流式生成器

    使用 asyncio 异步子进程读取 opencode 输出，
    并将文本内容逐字符发送给客户端，实现真正的流式体验。

    Yields:
        SSE 格式的事件字符串
    """
    session = session_manager.get_session(session_id)
    if not session:
        yield f"data: {json.dumps({'type': 'error', 'content': '会话不存在'}, ensure_ascii=False)}\n\n"
        return

    work_dir = session['work_dir']
    current_model = session.get('current_model')
    history = session['history']

    # 构建上下文消息
    full_message = build_context(history, message)

    # 构建命令
    model_arg = f'--model {current_model}' if current_model else ''
    ps_command = (
        f'[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; '
        f'Set-Location -LiteralPath "{work_dir}"; '
        f'opencode run "{full_message}" --format json --no-replay {model_arg}'
    )

    full_response = []
    tool_events = []

    try:
        # 设置 PYTHONUNBUFFERED 避免 stdout 缓冲
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'

        # 使用异步子进程，避免阻塞事件循环
        process = await asyncio.create_subprocess_exec(
            'powershell', '-Command', ps_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )

        # 异步逐行读取输出
        while True:
            line = await process.stdout.readline()
            if not line:
                break

            try:
                line_str = line.decode('utf-8', errors='replace').strip()
                if not line_str:
                    continue

                event = json.loads(line_str)
                if not isinstance(event, dict):
                    continue

                part = _get_event_part(event)
                text_type, text = _extract_event_text(event, part)
                tool_event = _normalize_tool_event(event, part)
                event_type = event.get('type', 'unknown')

                if event_type == 'text':
                    text = part.get('text', '')
                    full_response.append(text)
                    async for chunk in _stream_text(text, 'text', session_id):
                        yield chunk

                elif event_type == 'reasoning':
                    text = part.get('text', '')
                    async for chunk in _stream_text(text, 'reasoning', session_id):
                        yield chunk

                elif event_type == 'tool':
                    tool_name = part.get('tool', '')
                    sse_event = {
                        'type': 'tool',
                        'content': f'使用工具: {tool_name}',
                        'tool': tool_name,
                        'session_id': session_id
                    }
                    yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"

            except json.JSONDecodeError:
                line_str = strip_ansi(line_str).strip()
                if line_str and not line_str.startswith('>'):
                    full_response.append(line_str)
                    async for chunk in _stream_text(line_str, 'text', session_id):
                        yield chunk

        # 等待进程完成
        await process.wait()

        if process.returncode != 0:
            stderr = (await process.stderr.read()).decode('utf-8', errors='replace')
            sse_event = {
                'type': 'error',
                'content': stderr,
                'session_id': session_id
            }
            yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"
        else:
            # 完成事件
            full_text = ''.join(full_response)
            sse_event = {
                'type': 'done',
                'content': full_text,
                'session_id': session_id
            }
            yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"

            # 保存到历史记录
            session_manager.add_message(session_id, 'user', message)
            session_manager.add_message(session_id, 'assistant', full_text)

    except Exception as e:
        sse_event = {
            'type': 'error',
            'content': str(e),
            'session_id': session_id
        }
        yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"

    # SSE 结束标记
    yield "data: [DONE]\n\n"


async def chat_stream_generator(session_id: str, message: str) -> AsyncGenerator[str, None]:
    session = session_manager.get_session(session_id)
    if not session:
        yield f"data: {json.dumps({'type': 'error', 'content': '会话不存在'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    work_dir = session['work_dir']
    current_model = session.get('current_model')
    full_message = build_context(session['history'], message)

    full_response: List[str] = []
    tool_events: List[Dict[str, Any]] = []

    try:
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        process = await asyncio.create_subprocess_exec(
            *_build_opencode_run_args(full_message, current_model, 'json'),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env=env
        )

        while True:
            line = await process.stdout.readline()
            if not line:
                break

            line_str = line.decode('utf-8', errors='replace').strip()
            if not line_str:
                continue

            try:
                event = json.loads(line_str)
            except json.JSONDecodeError:
                clean_line = strip_ansi(line_str).strip()
                if clean_line and not clean_line.startswith('>'):
                    full_response.append(clean_line)
                    async for chunk in _stream_text(clean_line, 'text', session_id):
                        yield chunk
                continue

            if not isinstance(event, dict):
                continue

            part = _get_event_part(event)
            text_type, text = _extract_event_text(event, part)
            if text:
                if text_type == 'text':
                    full_response.append(text)
                async for chunk in _stream_text(text, text_type or 'text', session_id):
                    yield chunk

            tool_event = _normalize_tool_event(event, part)
            if tool_event:
                tool_events.append(tool_event)
                sse_event = {
                    'type': 'tool',
                    'content': _format_tool_content(tool_event),
                    'tool': tool_event.get('tool'),
                    'tool_call_id': tool_event.get('tool_call_id'),
                    'status': tool_event.get('status'),
                    'input': tool_event.get('input'),
                    'output': tool_event.get('output'),
                    'error': tool_event.get('error'),
                    'event_type': tool_event.get('event_type'),
                    'raw': tool_event.get('raw'),
                    'session_id': session_id
                }
                yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"

        await process.wait()

        if process.returncode != 0:
            stderr = (await process.stderr.read()).decode('utf-8', errors='replace')
            sse_event = {
                'type': 'error',
                'content': stderr,
                'session_id': session_id
            }
            yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"
        else:
            full_text = ''.join(full_response)
            if not full_text.strip() and not tool_events:
                fallback_output, fallback_stderr, fallback_code = _run_opencode_capture(
                    full_message,
                    current_model,
                    work_dir,
                    'default',
                )
                if fallback_code != 0:
                    sse_event = {
                        'type': 'error',
                        'content': fallback_stderr or 'opencode produced no displayable response.',
                        'session_id': session_id
                    }
                    yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"
                else:
                    full_text = _parse_opencode_default_output(fallback_output)
                    if not full_text.strip():
                        sse_event = {
                            'type': 'error',
                            'content': 'opencode produced no displayable response.',
                            'session_id': session_id
                        }
                        yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"
                    else:
                        async for chunk in _stream_text(full_text, 'text', session_id):
                            yield chunk
                        sse_event = {
                            'type': 'done',
                            'content': full_text,
                            'tools': tool_events,
                            'fallback': 'default',
                            'session_id': session_id
                        }
                        yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"
                        session_manager.add_message(session_id, 'user', message)
                        session_manager.add_message(session_id, 'assistant', full_text)
            else:
                sse_event = {
                    'type': 'done',
                    'content': full_text,
                    'tools': tool_events,
                    'session_id': session_id
                }
                yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"

                session_manager.add_message(session_id, 'user', message)
                session_manager.add_message(session_id, 'assistant', full_text)

    except Exception as e:
        sse_event = {
            'type': 'error',
            'content': str(e),
            'session_id': session_id
        }
        yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"

    yield "data: [DONE]\n\n"


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    对话接口（非流式）

    Args:
        request: {
            "message": "你好",
            "stream": false,
            "session_id": "可选，不传则创建新会话"
        }

    Returns:
        {
            "session_id": "xxx",
            "response": "你好！有什么我可以帮你的吗？",
            "model": "provider/model"
        }
    """
    # 获取或创建会话
    if request.session_id:
        session = session_manager.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        session_id = request.session_id
    else:
        session_id = session_manager.create_session()
        session = session_manager.get_session(session_id)

    work_dir = session['work_dir']
    current_model = session.get('current_model')
    history = session['history']

    # 构建上下文消息
    full_message = build_context(history, request.message)

    # 构建命令
    full_message = build_context(history, request.message)

    try:
        output, stderr, returncode = _run_opencode_capture(
            full_message,
            current_model,
            work_dir,
            'json',
        )

        if returncode != 0:
            raise HTTPException(status_code=500, detail=f"对话失败: {stderr}")

        response_text, reasoning_text, events, tools = _parse_opencode_json_output(output)
        fallback = None

        if not response_text.strip() and not reasoning_text.strip() and not tools:
            fallback_output, fallback_stderr, fallback_code = _run_opencode_capture(
                full_message,
                current_model,
                work_dir,
                'default',
            )
            if fallback_code != 0:
                raise HTTPException(status_code=500, detail=f"瀵硅瘽澶辫触: {fallback_stderr}")
            response_text = _parse_opencode_default_output(fallback_output)
            fallback = 'default'
            if not response_text.strip():
                raise HTTPException(status_code=502, detail="opencode produced no displayable response.")

        # 清理输出

        # 保存到历史记录
        session_manager.add_message(session_id, 'user', request.message)
        session_manager.add_message(session_id, 'assistant', response_text)

        return {
            "session_id": session_id,
            "response": response_text,
            "reasoning": reasoning_text,
            "events": events,
            "tools": tools,
            "fallback": fallback,
            "model": current_model,
            "message_count": len(session_manager.get_session(session_id)['history'])
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="请求超时")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"对话失败: {str(e)}")


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    对话接口（SSE 流式输出）

    Args:
        request: {
            "message": "你好",
            "session_id": "可选，不传则创建新会话"
        }

    Returns:
        SSE 流式事件:
        data: {"type": "text", "content": "你好", "session_id": "xxx"}
        data: {"type": "done", "content": "完整回复", "session_id": "xxx"}
        data: [DONE]
    """
    # 获取或创建会话
    if request.session_id:
        session = session_manager.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        session_id = request.session_id
    else:
        session_id = session_manager.create_session()

    return StreamingResponse(
        chat_stream_generator(session_id, request.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-ID": session_id
        }
    )
