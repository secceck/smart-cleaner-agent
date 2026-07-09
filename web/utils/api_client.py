"""
后端 API 客户端封装
包含 SSE 流式解析和所有 REST API 调用
"""
import json
from typing import Generator

import requests
import streamlit as st

# 从 Streamlit secrets 读取 API 地址
API_BASE_URL = st.secrets.get("API_BASE_URL", "http://127.0.0.1:8000/api/v1")


def _url(path: str) -> str:
    """构建完整 API URL"""
    return f"{API_BASE_URL}{path}"


# ============================================================
# SSE 流式对话
# ============================================================

def stream_chat(message: str, thread_id: str) -> Generator[dict, None, None]:
    """
    SSE 流式对话生成器
    逐事件返回后端推送的数据

    Args:
        message: 用户消息
        thread_id: 会话ID

    Yields:
        dict: SSE 事件数据
    """
    try:
        response = requests.post(
            _url("/chat/stream"),
            json={"message": message, "thread_id": thread_id},
            stream=True,
            timeout=120,
        )

        if response.status_code != 200:
            yield {
                "type": "error",
                "content": f"请求失败 (HTTP {response.status_code}): {response.text[:200]}",
            }
            yield {"type": "done"}
            return

        for line in response.iter_lines():
            if not line:
                continue
            line_str = line.decode("utf-8") if isinstance(line, bytes) else line

            if line_str.startswith("data: "):
                data_str = line_str[6:]
                try:
                    event = json.loads(data_str)
                    yield event
                except json.JSONDecodeError:
                    continue

    except requests.ConnectionError:
        yield {
            "type": "error",
            "content": "❌ 无法连接到后端服务。请确保 FastAPI 服务已启动 (端口 8000)。",
        }
        yield {"type": "done"}
    except requests.Timeout:
        yield {
            "type": "error",
            "content": "⏰ 请求超时，后端服务响应过慢。请稍后重试。",
        }
        yield {"type": "done"}
    except Exception as e:
        yield {
            "type": "error",
            "content": f"❌ 连接异常: {str(e)}",
        }
        yield {"type": "done"}


# ============================================================
# 会话管理 API
# ============================================================

def get_sessions() -> list[dict]:
    """获取所有会话列表"""
    try:
        resp = requests.get(_url("/chat/sessions"), timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []


def create_session(title: str = "新的聊天") -> dict | None:
    """创建新会话"""
    try:
        resp = requests.post(
            _url("/chat/sessions"),
            json={"title": title},
            timeout=10,
        )
        if resp.status_code == 201:
            return resp.json()
        return None
    except Exception:
        return None


def delete_session(thread_id: str) -> bool:
    """删除会话"""
    try:
        resp = requests.delete(
            _url(f"/chat/sessions/{thread_id}"),
            timeout=10,
        )
        return resp.status_code == 204
    except Exception:
        return False


# ============================================================
# 消息管理 API
# ============================================================

def get_messages(thread_id: str) -> list[dict]:
    """获取会话历史消息"""
    try:
        resp = requests.get(
            _url("/chat/messages"),
            params={"thread_id": thread_id},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []


def clear_messages(thread_id: str) -> bool:
    """清空会话消息"""
    try:
        resp = requests.delete(
            _url("/chat/messages"),
            params={"thread_id": thread_id},
            timeout=10,
        )
        return resp.status_code == 204
    except Exception:
        return False


# ============================================================
# 知识库 API
# ============================================================

def upload_knowledge(files: list) -> list[dict]:
    """上传知识库文档"""
    try:
        file_tuples = [
            ("files", (f.name, f.getvalue(), f.type))
            for f in files
        ]
        resp = requests.post(
            _url("/knowledge/upload"),
            files=file_tuples,
            timeout=120,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("files", [])
        return [{"filename": "unknown", "status": "error", "message": f"HTTP {resp.status_code}"}]
    except Exception as e:
        return [{"filename": "unknown", "status": "error", "message": str(e)}]


# ============================================================
# 位置上报 API
# ============================================================

def set_location(thread_id: str, city: str, lat: float = 0.0, lng: float = 0.0) -> bool:
    """上报用户地理位置到后端"""
    try:
        resp = requests.post(
            _url("/location"),
            json={"thread_id": thread_id, "city": city, "lat": lat, "lng": lng},
            timeout=5,
        )
        return resp.status_code == 200
    except Exception:
        return False


def get_location(thread_id: str) -> dict | None:
    """从后端获取当前会话的地理位置缓存"""
    try:
        resp = requests.get(
            _url("/location"),
            params={"thread_id": thread_id},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "ok":
                return {"city": data["city"], "lat": data.get("lat", 0), "lng": data.get("lng", 0)}
        return None
    except Exception:
        return None
