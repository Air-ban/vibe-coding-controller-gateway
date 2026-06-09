"""
FastAPI gateway for opencode and Claude Code.

The public API keeps the existing openremote routes. Requests use opencode by
default. Send {"provider": "claude"} in /api/chat to route a conversation turn
through Claude Code.
"""

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


GATEWAY_VERSION = "1.1.0"
VALID_PROVIDERS = {"opencode", "claude"}
CLAUDE_PERMISSION_MODES = {
    "acceptEdits",
    "auto",
    "bypassPermissions",
    "default",
    "dontAsk",
    "plan",
}
CLAUDE_PERMISSION_WORDS = (
    "permission",
    "approval",
    "authorize",
    "authorization",
    "denied",
    "rejected",
    "not allowed",
)


class WorkDirRequest(BaseModel):
    path: str = Field(..., description="Working directory path.")


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message.")
    stream: bool = Field(default=False, description="Reserved for compatibility.")
    session_id: Optional[str] = Field(default=None, description="Gateway session ID.")
    provider: Optional[str] = Field(
        default=None,
        description="Backend provider: opencode or claude. Defaults to opencode.",
    )
    permission_mode: Optional[str] = Field(
        default=None,
        description="Claude Code permission mode, for example bypassPermissions.",
    )


class ModelRequest(BaseModel):
    model: str = Field(..., description="Model ID or Claude Code model alias.")
    provider: Optional[str] = Field(default=None, description="opencode or claude.")


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: str
    work_dir: Optional[str] = None
    provider: Optional[str] = None


class SessionInfo(BaseModel):
    session_id: str
    work_dir: str
    provider: str = "opencode"
    current_model: Optional[str] = None
    provider_session_id: Optional[str] = None
    message_count: int
    created_at: str
    updated_at: str


def strip_ansi(text: str) -> str:
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


def _get_data_dir() -> str:
    data_dir = os.path.join(os.path.expanduser("~"), ".openremote")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def _normalize_provider(provider: Optional[str]) -> str:
    normalized = (provider or "opencode").strip().lower()
    if normalized not in VALID_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider '{provider}'. Use opencode or claude.",
        )
    return normalized


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _run_command(args: List[str], work_dir: Optional[str] = None, timeout: int = 120) -> tuple[str, str, int]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        result = subprocess.run(
            args,
            cwd=work_dir,
            capture_output=True,
            text=False,
            timeout=timeout,
            env=env,
        )
        return _decode(result.stdout), _decode(result.stderr), result.returncode
    except subprocess.TimeoutExpired:
        return "", f"Command timed out after {timeout} seconds.", -1
    except Exception as exc:
        return "", str(exc), -1


def _resolve_opencode_executable() -> str:
    candidates = [os.environ.get("OPENCODE_BIN")]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(os.path.join(appdata, "npm", "node_modules", "opencode-ai", "bin", "opencode.exe"))
    candidates.extend([
        shutil.which("opencode.exe"),
        shutil.which("opencode.cmd"),
        shutil.which("opencode"),
    ])
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return "opencode"


def _resolve_claude_executable() -> str:
    candidates = [os.environ.get("CLAUDE_BIN")]
    candidates.extend([
        shutil.which("claude.exe"),
        shutil.which("claude.cmd"),
        shutil.which("claude"),
    ])
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return "claude"


def _run_opencode_command(args: List[str], work_dir: Optional[str] = None) -> tuple[str, str, int]:
    return _run_command([_resolve_opencode_executable(), *args], work_dir=work_dir)


def _run_claude_command(args: List[str], work_dir: Optional[str] = None) -> tuple[str, str, int]:
    return _run_command([_resolve_claude_executable(), *args], work_dir=work_dir, timeout=180)


class SessionManager:
    def __init__(self) -> None:
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.history_dir = os.path.join(_get_data_dir(), "sessions")
        os.makedirs(self.history_dir, exist_ok=True)

    def create_session(self, work_dir: Optional[str] = None, provider: str = "opencode") -> str:
        session_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        session = {
            "session_id": session_id,
            "work_dir": os.path.abspath(work_dir or os.getcwd()),
            "provider": _normalize_provider(provider),
            "current_model": None,
            "provider_session_id": None,
            "permission_mode": None,
            "history": [],
            "created_at": now,
            "updated_at": now,
        }
        self.sessions[session_id] = session
        self._save_session(session_id)
        return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if session_id in self.sessions:
            session = self.sessions[session_id]
            self._ensure_defaults(session)
            return session

        session_file = os.path.join(self.history_dir, f"{session_id}.json")
        if not os.path.exists(session_file):
            return None

        try:
            with open(session_file, "r", encoding="utf-8") as handle:
                session = json.load(handle)
            self._ensure_defaults(session)
            self.sessions[session_id] = session
            return session
        except Exception:
            return None

    def update_session(self, session_id: str, updates: Dict[str, Any]) -> bool:
        session = self.get_session(session_id)
        if not session:
            return False
        session.update(updates)
        session["updated_at"] = datetime.now().isoformat()
        self._save_session(session_id)
        return True

    def add_message(self, session_id: str, role: str, content: str) -> bool:
        session = self.get_session(session_id)
        if not session:
            return False
        session["history"].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "work_dir": session.get("work_dir"),
            "provider": session.get("provider", "opencode"),
        })
        session["updated_at"] = datetime.now().isoformat()
        if len(session["history"]) > 50:
            session["history"] = session["history"][-50:]
        self._save_session(session_id)
        return True

    def clear_history(self, session_id: str) -> bool:
        session = self.get_session(session_id)
        if not session:
            return False
        session["history"] = []
        session["provider_session_id"] = None
        session["updated_at"] = datetime.now().isoformat()
        self._save_session(session_id)
        return True

    def delete_session(self, session_id: str) -> bool:
        self.sessions.pop(session_id, None)
        session_file = os.path.join(self.history_dir, f"{session_id}.json")
        if os.path.exists(session_file):
            os.remove(session_file)
            return True
        return False

    def list_sessions(self) -> List[Dict[str, Any]]:
        sessions = []
        for filename in os.listdir(self.history_dir):
            if not filename.endswith(".json"):
                continue
            session = self.get_session(filename[:-5])
            if session:
                sessions.append(self.session_summary(session))
        return sessions

    def session_summary(self, session: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_defaults(session)
        return {
            "session_id": session["session_id"],
            "work_dir": session["work_dir"],
            "provider": session.get("provider", "opencode"),
            "current_model": session.get("current_model"),
            "provider_session_id": session.get("provider_session_id"),
            "message_count": len(session.get("history", [])),
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
        }

    def _ensure_defaults(self, session: Dict[str, Any]) -> None:
        session.setdefault("provider", "opencode")
        session.setdefault("current_model", None)
        session.setdefault("provider_session_id", None)
        session.setdefault("permission_mode", None)
        session.setdefault("history", [])
        session.setdefault("work_dir", os.getcwd())
        session.setdefault("created_at", datetime.now().isoformat())
        session.setdefault("updated_at", session["created_at"])

    def _save_session(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if not session:
            return
        session_file = os.path.join(self.history_dir, f"{session_id}.json")
        with open(session_file, "w", encoding="utf-8") as handle:
            json.dump(session, handle, ensure_ascii=False, indent=2)


session_manager = SessionManager()
_opencode_version_cache: Optional[str] = None
_claude_version_cache: Optional[str] = None


def get_opencode_version() -> str:
    global _opencode_version_cache
    if _opencode_version_cache is None:
        stdout, _, returncode = _run_opencode_command(["--version"])
        _opencode_version_cache = stdout.strip() if returncode == 0 else "unknown"
    return _opencode_version_cache


def get_claude_version() -> str:
    global _claude_version_cache
    if _claude_version_cache is None:
        stdout, _, returncode = _run_claude_command(["--version"])
        _claude_version_cache = stdout.strip() if returncode == 0 else "unknown"
    return _claude_version_cache


def get_computer_name() -> str:
    return socket.gethostname()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Openremote API Gateway starting...")
    print(f"Session directory: {session_manager.history_dir}")
    yield
    print("Openremote API Gateway stopped.")


app = FastAPI(
    title="Openremote API Gateway",
    description="HTTP API gateway for opencode and Claude Code.",
    version=GATEWAY_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def build_context(history: List[Dict[str, Any]], user_message: str, max_history: int = 10) -> str:
    if not history:
        return user_message
    lines = ["The following is the recent conversation history:", ""]
    for message in history[-max_history:]:
        role = message.get("role", "user")
        content = message.get("content", "")
        lines.append(f"{role}: {content}")
    lines.extend(["", f"New user message: {user_message}", "", "Answer the new user message using the history above."])
    return "\n".join(lines)


def _extract_event_text(event: Dict[str, Any]) -> str:
    chunks: List[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            value_type = str(value.get("type", "")).lower()
            for key in ("delta", "text", "content", "response", "output", "result"):
                item = value.get(key)
                if isinstance(item, str) and (value_type in ("text", "reasoning", "") or key != "content"):
                    chunks.append(item)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(event)
    return "".join(chunks)


def _normalize_tool_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw_type = str(event.get("type", "")).lower()
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    part = event.get("part") if isinstance(event.get("part"), dict) else {}
    if "tool" not in raw_type and not any(key in event or key in data or key in part for key in ("tool", "tool_name", "tool_call_id")):
        return None
    return {
        "event_type": event.get("type", "unknown"),
        "tool": part.get("tool") or part.get("name") or data.get("tool") or data.get("name") or event.get("tool") or event.get("name") or "unknown",
        "tool_call_id": part.get("tool_call_id") or data.get("tool_call_id") or event.get("tool_call_id") or part.get("id") or data.get("id") or event.get("id"),
        "status": part.get("status") or data.get("status") or event.get("status"),
        "input": part.get("input") or part.get("arguments") or data.get("input") or data.get("arguments") or event.get("input") or event.get("arguments"),
        "output": part.get("output") or part.get("result") or data.get("output") or data.get("result") or event.get("output") or event.get("result"),
        "error": part.get("error") or data.get("error") or event.get("error"),
        "raw": event,
    }


def _coerce_json_events(output: str) -> List[Dict[str, Any]]:
    clean_output = strip_ansi(output).strip()
    if not clean_output:
        return []

    events: List[Dict[str, Any]] = []
    for raw_line in clean_output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)

    if events:
        return events

    try:
        item = json.loads(clean_output)
    except json.JSONDecodeError:
        return []
    return [item] if isinstance(item, dict) else []


def _event_contains_words(value: Any, words: tuple[str, ...]) -> bool:
    if isinstance(value, dict):
        return any(_event_contains_words(child, words) for child in value.values())
    if isinstance(value, list):
        return any(_event_contains_words(child, words) for child in value)
    if isinstance(value, str):
        lower = value.lower()
        for word in words:
            needle = word.lower()
            if " " in needle:
                if needle in lower:
                    return True
                continue
            if re.search(rf"(?<![a-z]){re.escape(needle)}(?![a-z])", lower):
                return True
    return False


def _format_dynamic_value(value: Any) -> Any:
    if isinstance(value, list) and len(value) == 1:
        item = value[0]
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            return item["text"]
    return value


def _extract_claude_permission_signal(event: Dict[str, Any]) -> Optional[Any]:
    event_type = str(event.get("type", "")).lower()
    subtype = str(event.get("subtype", "")).lower()

    for key in ("permission_denials", "permissionDenials"):
        value = event.get(key)
        if value:
            return value

    if any(marker in event_type for marker in ("permission", "approval", "authoriz")):
        return event
    if any(marker in subtype for marker in ("permission", "approval", "authoriz")):
        return event

    is_error_event = event_type == "error" or subtype in {"error", "failure", "failed"} or bool(event.get("is_error"))
    if is_error_event:
        for key in ("error", "reason", "message", "result", "content", "detail", "details"):
            value = event.get(key)
            if value is not None and _event_contains_words(value, CLAUDE_PERMISSION_WORDS):
                return value

    ignored_permission_keys = {"permissionmode", "permission_mode"}
    for key, value in event.items():
        key_text = str(key).lower()
        if key_text in ignored_permission_keys or value in (None, "", [], {}):
            continue
        if any(marker in key_text for marker in ("approval", "authorization", "authorize")):
            return value
        if "permission" in key_text and _event_contains_words(value, CLAUDE_PERMISSION_WORDS):
            return value

    return None


def _normalize_permission_status(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False).lower() if not isinstance(value, str) else value.lower()
    if any(word in text for word in ("denied", "rejected", "blocked", "not allowed", "permission denied")):
        return "permission_denied"
    if any(word in text for word in ("approved", "accepted", "allowed", "granted")):
        return "permission_granted"
    if any(word in text for word in ("request", "requires", "permission", "approval", "authorize", "authorization")):
        return "permission_required"
    return "permission"


def _normalize_claude_stream(output: str) -> Dict[str, Any]:
    events = _coerce_json_events(output)
    if not events:
        clean_output = strip_ansi(output).strip()
        permissions = []
        if _event_contains_words(clean_output, CLAUDE_PERMISSION_WORDS):
            permissions.append({
                "event_type": "permission",
                "provider": "claude",
                "tool": "unknown",
                "tool_call_id": None,
                "status": _normalize_permission_status(clean_output),
                "reason": clean_output,
                "raw": clean_output,
            })
        return {
            "response": clean_output,
            "provider_session_id": None,
            "events": [],
            "tools": [],
            "permissions": permissions,
            "error": clean_output if permissions else None,
        }

    tool_names: Dict[str, str] = {}
    assistant_text_parts: List[str] = []
    result_text = ""
    provider_session_id: Optional[str] = None
    tools: List[Dict[str, Any]] = []
    permissions: List[Dict[str, Any]] = []
    error_text: Optional[str] = None

    for event in events:
        if isinstance(event.get("session_id"), str):
            provider_session_id = event["session_id"]
        elif isinstance(event.get("sessionId"), str):
            provider_session_id = event["sessionId"]
        elif isinstance(event.get("sessionID"), str):
            provider_session_id = event["sessionID"]

        event_type = str(event.get("type", "")).lower()

        if event_type == "result":
            value = event.get("result") or event.get("response") or event.get("content") or event.get("text")
            if isinstance(value, str):
                result_text = value
            elif value is not None:
                result_text = json.dumps(value, ensure_ascii=False)
            if event.get("is_error") or str(event.get("subtype", "")).lower() in {"error", "failure", "failed"}:
                error_text = result_text or _extract_error_message(event) or "Claude Code returned an error."

        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        content = message.get("content")
        if isinstance(content, str):
            if event_type == "assistant":
                assistant_text_parts.append(content)
        elif isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type", "")).lower()
                if item_type == "text" and isinstance(item.get("text"), str) and event_type == "assistant":
                    assistant_text_parts.append(item["text"])
                elif item_type == "tool_use":
                    tool_call_id = item.get("id") or item.get("tool_use_id") or item.get("tool_call_id")
                    tool_name = item.get("name") or item.get("tool") or "unknown"
                    if isinstance(tool_call_id, str):
                        tool_names[tool_call_id] = str(tool_name)
                    tools.append({
                        "event_type": "tool_use",
                        "provider": "claude",
                        "tool": tool_name,
                        "tool_call_id": tool_call_id,
                        "status": "requested",
                        "input": item.get("input"),
                        "output": None,
                        "error": None,
                        "requires_approval": False,
                        "raw": event,
                    })
                elif item_type == "tool_result":
                    tool_call_id = item.get("tool_use_id") or item.get("id") or item.get("tool_call_id")
                    tool_name = tool_names.get(str(tool_call_id), "unknown") if tool_call_id is not None else "unknown"
                    content_value = _format_dynamic_value(item.get("content"))
                    is_error = bool(item.get("is_error"))
                    is_permission = _event_contains_words(content_value, CLAUDE_PERMISSION_WORDS)
                    status = _normalize_permission_status(content_value) if is_permission else ("error" if is_error else "completed")
                    tool_event = {
                        "event_type": "tool_result",
                        "provider": "claude",
                        "tool": tool_name,
                        "tool_call_id": tool_call_id,
                        "status": status,
                        "input": None,
                        "output": None if is_error else content_value,
                        "error": content_value if is_error else None,
                        "requires_approval": is_permission,
                        "raw": event,
                    }
                    tools.append(tool_event)
                    if is_permission:
                        permissions.append({
                            "event_type": "permission",
                            "provider": "claude",
                            "tool": tool_name,
                            "tool_call_id": tool_call_id,
                            "status": status,
                            "reason": content_value,
                            "raw": event,
                        })

        permission_signal = _extract_claude_permission_signal(event)
        if permission_signal is not None:
            permissions.append({
                "event_type": event.get("type", "permission"),
                "provider": "claude",
                "tool": event.get("tool") or event.get("name") or "unknown",
                "tool_call_id": event.get("tool_call_id") or event.get("tool_use_id") or event.get("id"),
                "status": _normalize_permission_status(permission_signal),
                "reason": event.get("message") or event.get("reason") or event.get("error") or permission_signal,
                "raw": event,
            })

    response = (result_text or "".join(assistant_text_parts)).strip()
    return {
        "response": response,
        "provider_session_id": provider_session_id,
        "events": events,
        "tools": tools,
        "permissions": permissions,
        "error": error_text,
    }


def _format_tool_content(tool_event: Dict[str, Any]) -> str:
    tool_name = tool_event.get("tool") or "unknown"
    status = str(tool_event.get("status") or "")
    if status.startswith("permission"):
        return f"Tool {tool_name} permission"
    if tool_event.get("error") is not None:
        return f"Tool {tool_name} failed"
    if tool_event.get("output") is not None:
        return f"Tool {tool_name} result"
    if tool_event.get("input") is not None:
        return f"Tool {tool_name} call"
    return f"Tool {tool_name}"


def _format_permission_content(permission_event: Dict[str, Any]) -> str:
    tool_name = permission_event.get("tool") or "unknown"
    status = permission_event.get("status") or "permission"
    return f"Permission {status} for {tool_name}"


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
            clean = strip_ansi(line).strip()
            if clean and not clean.startswith(">") and not clean.startswith("build"):
                response_parts.append(clean + "\n")
            continue
        if not isinstance(event, dict):
            continue
        events.append(event)
        text = _extract_event_text(event)
        if text:
            if "reasoning" in str(event.get("type", "")).lower():
                reasoning_parts.append(text)
            else:
                response_parts.append(text)
        tool_event = _normalize_tool_event(event)
        if tool_event:
            tools.append(tool_event)

    return "".join(response_parts).strip(), "".join(reasoning_parts).strip(), events, tools


def _parse_default_output(output: str) -> str:
    clean_lines = []
    for line in strip_ansi(output).splitlines():
        line = line.strip()
        if line and not line.startswith(">") and not line.startswith("build"):
            clean_lines.append(line)
    return "\n".join(clean_lines).strip()


def _extract_error_message(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        message = value.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        for child in value.values():
            found = _extract_error_message(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _extract_error_message(child)
            if found:
                return found
    return None


def _extract_opencode_error(events: List[Dict[str, Any]]) -> Optional[str]:
    for event in events:
        event_type = str(event.get("type", "")).lower()
        if event_type == "error" or event.get("error") is not None:
            return _extract_error_message(event) or json.dumps(event.get("error", event), ensure_ascii=False)
    return None


def _run_opencode_chat(session: Dict[str, Any], message: str) -> Dict[str, Any]:
    full_message = build_context(session.get("history", []), message)
    args = [_resolve_opencode_executable(), "run", full_message, "--format", "json", "--no-replay"]
    if session.get("current_model"):
        args.extend(["--model", session["current_model"]])

    output, stderr, returncode = _run_command(args, work_dir=session["work_dir"])
    if returncode != 0:
        raise HTTPException(status_code=500, detail=f"opencode chat failed: {stderr}")

    response_text, reasoning_text, events, tools = _parse_opencode_json_output(output)
    event_error = _extract_opencode_error(events)
    if event_error:
        raise HTTPException(status_code=500, detail=f"opencode chat failed: {event_error}")

    fallback = None
    if not response_text.strip() and not reasoning_text.strip() and not tools:
        fallback_args = [_resolve_opencode_executable(), "run", full_message, "--format", "default", "--no-replay"]
        if session.get("current_model"):
            fallback_args.extend(["--model", session["current_model"]])
        fallback_output, fallback_stderr, fallback_code = _run_command(fallback_args, work_dir=session["work_dir"])
        if fallback_code != 0:
            raise HTTPException(status_code=500, detail=f"opencode fallback failed: {fallback_stderr}")
        response_text = _parse_default_output(fallback_output)
        fallback = "default"

    if not response_text.strip() and not tools:
        raise HTTPException(status_code=502, detail="opencode produced no displayable response.")

    return {
        "response": response_text,
        "reasoning": reasoning_text,
        "events": events,
        "tools": tools,
        "fallback": fallback,
    }


def _build_claude_args(session: Dict[str, Any], message: str, permission_mode: Optional[str] = None) -> List[str]:
    prompt = message
    args = [
        _resolve_claude_executable(),
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-hook-events",
    ]
    if session.get("current_model"):
        args.extend(["--model", session["current_model"]])

    selected_permission_mode = permission_mode or session.get("permission_mode") or os.environ.get("CLAUDE_PERMISSION_MODE")
    if selected_permission_mode:
        if selected_permission_mode not in CLAUDE_PERMISSION_MODES:
            raise HTTPException(status_code=400, detail=f"Unsupported Claude permission_mode: {selected_permission_mode}")
        args.extend(["--permission-mode", selected_permission_mode])
        session["permission_mode"] = selected_permission_mode

    if session.get("provider_session_id"):
        args.extend(["--resume", session["provider_session_id"]])
    elif session.get("history"):
        prompt = build_context(session["history"], message)

    args.append(prompt)
    return args


def _parse_claude_output(output: str) -> tuple[str, Optional[str], Dict[str, Any]]:
    clean_output = strip_ansi(output).strip()
    if not clean_output:
        return "", None, {}
    try:
        data = json.loads(clean_output)
    except json.JSONDecodeError:
        return clean_output, None, {}
    if not isinstance(data, dict):
        return json.dumps(data, ensure_ascii=False), None, {}
    response = data.get("result") or data.get("response") or data.get("content") or data.get("text") or ""
    if not isinstance(response, str):
        response = json.dumps(response, ensure_ascii=False)
    provider_session_id = data.get("session_id") or data.get("sessionId") or data.get("sessionID")
    return response.strip(), provider_session_id if isinstance(provider_session_id, str) else None, data


def _run_claude_chat(session: Dict[str, Any], message: str, permission_mode: Optional[str] = None) -> Dict[str, Any]:
    args = _build_claude_args(session, message, permission_mode)
    output, stderr, returncode = _run_command(args, work_dir=session["work_dir"], timeout=180)
    parsed = _normalize_claude_stream(output)
    if stderr.strip() and (returncode != 0 or _event_contains_words(stderr, CLAUDE_PERMISSION_WORDS)):
        stderr_parsed = _normalize_claude_stream(stderr)
        if not parsed.get("response"):
            parsed["response"] = stderr_parsed.get("response", "")
        parsed["events"].extend(stderr_parsed.get("events", []))
        parsed["tools"].extend(stderr_parsed.get("tools", []))
        parsed["permissions"].extend(stderr_parsed.get("permissions", []))
        parsed["error"] = parsed.get("error") or stderr_parsed.get("error") or stderr.strip()

    backend_error = parsed.get("error")
    if returncode != 0 and not parsed.get("tools") and not parsed.get("permissions"):
        raise HTTPException(status_code=500, detail=f"Claude Code chat failed: {stderr or backend_error}")
    if backend_error and not parsed.get("tools") and not parsed.get("permissions"):
        raise HTTPException(status_code=500, detail=f"Claude Code chat failed: {parsed['error']}")

    response_text = parsed["response"] or backend_error or ""
    provider_session_id = parsed.get("provider_session_id")
    if provider_session_id:
        session["provider_session_id"] = provider_session_id
    if not response_text.strip() and not parsed.get("tools") and not parsed.get("permissions"):
        raise HTTPException(status_code=502, detail="Claude Code produced no displayable response.")
    return {
        "response": response_text,
        "reasoning": "",
        "events": parsed.get("events", []),
        "tools": parsed.get("tools", []),
        "permissions": parsed.get("permissions", []),
        "error": backend_error,
        "fallback": None,
    }


def _prepare_session(request: ChatRequest) -> tuple[str, Dict[str, Any]]:
    requested_provider = _normalize_provider(request.provider)
    if request.session_id:
        session = session_manager.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session does not exist.")
        session_id = request.session_id
        if request.provider and session.get("provider") != requested_provider:
            session["provider"] = requested_provider
            session["provider_session_id"] = None
    else:
        session_id = session_manager.create_session(provider=requested_provider)
        session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=500, detail="Failed to create session.")
    return session_id, session


def _run_provider_chat(session: Dict[str, Any], message: str, permission_mode: Optional[str] = None) -> Dict[str, Any]:
    provider = _normalize_provider(session.get("provider"))
    if provider == "claude":
        return _run_claude_chat(session, message, permission_mode)
    return _run_opencode_chat(session, message)


async def _stream_text(text: str, event_type: str, session_id: str, provider: str) -> AsyncGenerator[str, None]:
    for char in text:
        event = {
            "type": event_type,
            "content": char,
            "session_id": session_id,
            "provider": provider,
        }
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.002)


async def chat_stream_generator(session_id: str, message: str, permission_mode: Optional[str] = None) -> AsyncGenerator[str, None]:
    session = session_manager.get_session(session_id)
    if not session:
        yield f"data: {json.dumps({'type': 'error', 'content': 'Session does not exist.', 'session_id': session_id}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    provider = _normalize_provider(session.get("provider"))
    try:
        result = await asyncio.to_thread(_run_provider_chat, session, message, permission_mode)
        response_text = result["response"]
        for permission_event in result.get("permissions", []):
            event = {
                "type": "permission",
                "content": _format_permission_content(permission_event),
                "session_id": session_id,
                "provider": provider,
                "tool": permission_event.get("tool"),
                "tool_call_id": permission_event.get("tool_call_id"),
                "status": permission_event.get("status"),
                "reason": permission_event.get("reason"),
                "raw": permission_event.get("raw"),
            }
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        for tool_event in result.get("tools", []):
            event = {
                "type": "tool",
                "content": _format_tool_content(tool_event),
                "session_id": session_id,
                "provider": provider,
                "tool": tool_event.get("tool"),
                "tool_call_id": tool_event.get("tool_call_id"),
                "status": tool_event.get("status"),
                "input": tool_event.get("input"),
                "output": tool_event.get("output"),
                "error": tool_event.get("error"),
                "requires_approval": tool_event.get("requires_approval", False),
                "event_type": tool_event.get("event_type"),
                "raw": tool_event.get("raw"),
            }
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        async for chunk in _stream_text(response_text, "text", session_id, provider):
            yield chunk
        session_manager.add_message(session_id, "user", message)
        session_manager.add_message(session_id, "assistant", response_text)
        session_manager.update_session(session_id, {
            "provider": provider,
            "current_model": session.get("current_model"),
            "provider_session_id": session.get("provider_session_id"),
            "permission_mode": session.get("permission_mode"),
        })
        done_event = {
            "type": "done",
            "content": response_text,
            "session_id": session_id,
            "provider": provider,
            "provider_session_id": session.get("provider_session_id"),
            "tools": result.get("tools", []),
            "permissions": result.get("permissions", []),
            "error": result.get("error"),
            "fallback": result.get("fallback"),
        }
        yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
    except HTTPException as exc:
        error = {"type": "error", "content": exc.detail, "session_id": session_id, "provider": provider}
        yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
    except Exception as exc:
        error = {"type": "error", "content": str(exc), "session_id": session_id, "provider": provider}
        yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@app.get("/")
async def root():
    return {
        "name": "Openremote API Gateway",
        "version": GATEWAY_VERSION,
        "providers": ["opencode", "claude"],
        "docs": "/docs",
    }


@app.get("/api/discover")
async def discover():
    return {
        "service": "openremote-api-gateway",
        "name": "Openremote API Gateway",
        "gateway_version": GATEWAY_VERSION,
        "opencode_version": get_opencode_version(),
        "claude_version": get_claude_version(),
        "providers": ["opencode", "claude"],
        "computer_name": get_computer_name(),
        "port": 8000,
        "docs_url": "/docs",
    }


@app.get("/api/version")
async def get_version():
    opencode_version = get_opencode_version()
    return {
        "version": opencode_version,
        "opencode_version": opencode_version,
        "claude_version": get_claude_version(),
        "gateway_version": GATEWAY_VERSION,
        "providers": ["opencode", "claude"],
    }


@app.get("/api/models")
async def list_models(provider: str = "opencode"):
    selected_provider = _normalize_provider(provider)
    if selected_provider == "claude":
        models = [{"id": "sonnet", "name": "sonnet"}, {"id": "opus", "name": "opus"}]
        return {"provider": "claude", "models": models, "count": len(models)}

    stdout, stderr, returncode = _run_opencode_command(["models"])
    if returncode != 0:
        raise HTTPException(status_code=500, detail=f"Failed to list opencode models: {stderr}")
    models = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if line and not line.startswith(">"):
            models.append({"id": line, "name": line})
    return {"provider": "opencode", "models": models, "count": len(models)}


@app.post("/api/sessions")
async def create_session(work_dir: Optional[str] = None, provider: str = "opencode"):
    selected_provider = _normalize_provider(provider)
    if work_dir and not os.path.isdir(work_dir):
        raise HTTPException(status_code=400, detail=f"Directory does not exist: {work_dir}")
    session_id = session_manager.create_session(work_dir, selected_provider)
    session = session_manager.get_session(session_id)
    return {
        "session_id": session_id,
        "work_dir": session["work_dir"],
        "provider": session["provider"],
        "created_at": session["created_at"],
    }


@app.get("/api/sessions")
async def list_sessions():
    sessions = session_manager.list_sessions()
    return {"sessions": sessions, "count": len(sessions)}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session does not exist.")
    return session_manager.session_summary(session)


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    if not session_manager.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session does not exist.")
    return {"message": "Session deleted."}


@app.get("/api/sessions/{session_id}/model")
async def get_current_model(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session does not exist.")
    return {
        "session_id": session_id,
        "provider": session.get("provider", "opencode"),
        "current_model": session.get("current_model"),
        "work_dir": session["work_dir"],
    }


@app.post("/api/sessions/{session_id}/model")
async def set_model(session_id: str, request: ModelRequest):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session does not exist.")
    provider = _normalize_provider(request.provider or session.get("provider"))
    if provider == "opencode":
        stdout, stderr, returncode = _run_opencode_command(["models"])
        if returncode != 0:
            raise HTTPException(status_code=500, detail=f"Failed to list opencode models: {stderr}")
        available_models = [line.strip() for line in stdout.splitlines() if line.strip() and not line.strip().startswith(">")]
        if request.model not in available_models:
            raise HTTPException(status_code=400, detail=f"Model '{request.model}' is not available.")
    session_manager.update_session(session_id, {"provider": provider, "current_model": request.model})
    return {"session_id": session_id, "provider": provider, "model": request.model, "message": "Model updated."}


@app.get("/api/sessions/{session_id}/workdir")
async def get_workdir(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session does not exist.")
    return {"session_id": session_id, "work_dir": session["work_dir"]}


@app.post("/api/sessions/{session_id}/workdir")
async def set_workdir(session_id: str, request: WorkDirRequest):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session does not exist.")
    if not os.path.isdir(request.path):
        raise HTTPException(status_code=400, detail=f"Directory does not exist: {request.path}")
    abs_path = os.path.abspath(request.path)
    session_manager.update_session(session_id, {"work_dir": abs_path, "provider_session_id": None})
    return {"session_id": session_id, "work_dir": abs_path, "message": "Working directory updated."}


@app.get("/api/sessions/{session_id}/history")
async def get_history(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session does not exist.")
    return {"session_id": session_id, "history": session["history"], "count": len(session["history"])}


@app.delete("/api/sessions/{session_id}/history")
async def clear_history(session_id: str):
    if not session_manager.clear_history(session_id):
        raise HTTPException(status_code=404, detail="Session does not exist.")
    return {"message": "History cleared."}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    session_id, session = _prepare_session(request)
    provider = _normalize_provider(session.get("provider"))
    try:
        result = _run_provider_chat(session, request.message, request.permission_mode)
        response_text = result["response"]
        session_manager.add_message(session_id, "user", request.message)
        session_manager.add_message(session_id, "assistant", response_text)
        session_manager.update_session(session_id, {
            "provider": provider,
            "current_model": session.get("current_model"),
            "provider_session_id": session.get("provider_session_id"),
            "permission_mode": session.get("permission_mode"),
        })
        updated = session_manager.get_session(session_id)
        return {
            "session_id": session_id,
            "provider": provider,
            "provider_session_id": updated.get("provider_session_id"),
            "response": response_text,
            "reasoning": result.get("reasoning", ""),
            "events": result.get("events", []),
            "tools": result.get("tools", []),
            "permissions": result.get("permissions", []),
            "error": result.get("error"),
            "fallback": result.get("fallback"),
            "model": updated.get("current_model"),
            "message_count": len(updated.get("history", [])),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chat failed: {exc}")


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    session_id, session = _prepare_session(request)
    provider = _normalize_provider(session.get("provider"))
    return StreamingResponse(
        chat_stream_generator(session_id, request.message, request.permission_mode),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-ID": session_id,
            "X-Provider": provider,
        },
    )
