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


# ============== Session Manager ==============

class SessionManager:
    """会话管理器"""
    
    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.history_dir = os.path.join(os.path.dirname(__file__), 'sessions')
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


async def chat_stream_generator(session_id: str, message: str) -> AsyncGenerator[str, None]:
    """
    SSE 流式生成器
    
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
    
    try:
        process = subprocess.Popen(
            ['powershell', '-Command', ps_command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # 逐行读取输出
        while True:
            line = process.stdout.readline()
            if not line:
                break
            
            try:
                line = line.decode('utf-8', errors='replace').strip()
                if not line:
                    continue
                
                event = json.loads(line)
                event_type = event.get('type', 'unknown')
                part = event.get('part', {})
                
                if event_type == 'text':
                    text = part.get('text', '')
                    full_response.append(text)
                    sse_event = {
                        'type': 'text',
                        'content': text,
                        'session_id': session_id
                    }
                    yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"
                    
                elif event_type == 'reasoning':
                    text = part.get('text', '')
                    sse_event = {
                        'type': 'reasoning',
                        'content': text,
                        'session_id': session_id
                    }
                    yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"
                    
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
                line = strip_ansi(line).strip()
                if line and not line.startswith('>'):
                    sse_event = {
                        'type': 'text',
                        'content': line,
                        'session_id': session_id
                    }
                    yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"
                    full_response.append(line)
        
        # 等待进程完成
        process.wait()
        
        if process.returncode != 0:
            stderr = process.stderr.read().decode('utf-8', errors='replace')
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
    model_arg = f'--model {current_model}' if current_model else ''
    ps_command = (
        f'[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; '
        f'Set-Location -LiteralPath "{work_dir}"; '
        f'opencode run "{full_message}" --format default --no-replay {model_arg}'
    )
    
    try:
        result = subprocess.run(
            ['powershell', '-Command', ps_command],
            capture_output=True,
            text=False,
            timeout=120
        )
        
        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8', errors='replace')
            raise HTTPException(status_code=500, detail=f"对话失败: {stderr}")
        
        output = result.stdout.decode('utf-8', errors='replace')
        output = strip_ansi(output).strip()
        
        # 清理输出
        lines = output.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('>') and not line.startswith('build'):
                cleaned_lines.append(line)
        
        response_text = '\n'.join(cleaned_lines)
        
        # 保存到历史记录
        session_manager.add_message(session_id, 'user', request.message)
        session_manager.add_message(session_id, 'assistant', response_text)
        
        return {
            "session_id": session_id,
            "response": response_text,
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


# ============== Main ==============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
