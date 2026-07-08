"""
Streamlit 会话状态管理
管理当前 thread_id、消息缓存等前端状态
"""
import streamlit as st


def init_session_state():
    """初始化所有 Streamlit session_state 变量"""
    defaults = {
        "thread_id": None,              # 当前活跃会话ID
        "messages": [],                 # 当前会话消息缓存 (dict列表)
        "sessions": [],                 # 全部会话列表
        "sidebar_need_refresh": False,  # 侧边栏是否需要刷新
        "user_city": None,              # 用户地理位置城市名
        "report_mode": False,           # 是否为报告生成模式
    }

    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


def switch_session(thread_id: str):
    """切换到指定会话"""
    st.session_state.thread_id = thread_id


def add_message(role: str, content: str, tool_name: str = None):
    """添加消息到当前会话缓存"""
    st.session_state.messages.append({
        "role": role,
        "content": content,
        "tool_name": tool_name,
    })


def load_messages_from_db(thread_id: str):
    """从后端加载消息到缓存"""
    from .api_client import get_messages
    messages = get_messages(thread_id)
    st.session_state.messages = messages
    return messages


def clear_message_cache():
    """清空消息缓存"""
    st.session_state.messages = []
