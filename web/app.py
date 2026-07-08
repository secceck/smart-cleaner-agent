"""
Streamlit 前端主入口
扫地机器人智能客服 Agent 交互页面
"""
import time

import streamlit as st

from components.chat import render_chat_history
from components.sidebar import render_sidebar
from utils import api_client
from utils.location import inject_location_script
from utils.session import (
    add_message,
    init_session_state,
    load_messages_from_db,
    switch_session,
)


# ============================================================
# 页面配置
# ============================================================

st.set_page_config(
    page_title="扫地机器人智能客服",
    page_icon="🧹",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": "扫地机器人智能客服 Agent v0.1\n本地单机部署 | ReAct + RAG",
    },
)


# ============================================================
# 自定义样式
# ============================================================

st.markdown(
    """
    <style>
    /* 全局字体 */
    html, body, [class*="css"] {
        font-family: "Microsoft YaHei", "微软雅黑", sans-serif;
    }

    /* 侧边栏优化 */
    [data-testid="stSidebar"] {
        min-width: 280px;
        max-width: 350px;
    }

    /* ── 聊天气泡：自适应内容宽度 ── */
    [data-testid="stChatMessage"] {
        max-width: 80% !important;
        margin: 2px 0 !important;
    }

    /* 用户消息：右对齐 + 浅蓝背景 */
    [data-testid="stChatMessage"]:has(
        [data-testid="stChatMessageAvatarUser"]
    ) {
        margin-left: auto !important;
        margin-right: 0 !important;
    }
    [data-testid="stChatMessage"]:has(
        [data-testid="stChatMessageAvatarUser"]
    ) > div:last-child {
        background: #e8f0fe !important;
        border-radius: 16px 4px 16px 16px !important;
        padding: 10px 16px !important;
    }

    /* 助手消息：左对齐 */
    [data-testid="stChatMessage"]:has(
        [data-testid="stChatMessageAvatarAssistant"]
    ) {
        margin-left: 0 !important;
        margin-right: auto !important;
    }

    /* 段落间距收紧 */
    .stChatMessage p {
        margin-bottom: 2px !important;
    }
    .stChatMessage p:last-child {
        margin-bottom: 0 !important;
    }

    /* 工具状态标签 */
    .tool-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.8em;
        background: #e3f2fd;
        color: #1565c0;
        margin: 2px;
    }

    /* 移动端适配 */
    @media (max-width: 768px) {
        [data-testid="stChatMessage"] {
            max-width: 90% !important;
        }
        .stChatMessage {
            font-size: 14px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# 初始化
# ============================================================

def main():
    # 初始化会话状态
    init_session_state()

    # ---- 侧边栏 ----
    render_sidebar()

    # ---- 主内容区 ----
    st.title("🧹 扫地机器人智能客服")

    # 如果没有活跃会话，自动创建或提示
    if not st.session_state.thread_id:
        # 尝试自动创建会话
        sessions = api_client.get_sessions()
        if sessions:
            # 选择最近的会话
            st.session_state.thread_id = sessions[0]["thread_id"]
            load_messages_from_db(st.session_state.thread_id)
        else:
            # 创建第一个会话
            result = api_client.create_session("新的聊天")
            if result:
                st.session_state.thread_id = result["thread_id"]
            else:
                st.error("⚠️ 无法连接到后端服务。请确保已启动 FastAPI 服务（端口 8000）。")
                st.info("启动命令: `cd server && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000`")
                st.stop()

    # 注入位置获取脚本（必须在 thread_id 确定之后）
    current_thread_id = st.session_state.thread_id
    inject_location_script(current_thread_id, api_client.API_BASE_URL)

    # ---- 消息历史展示 ----
    chat_container = st.container()
    with chat_container:
        render_chat_history()

    # ---- 底部输入框 ----
    handle_user_input(current_thread_id)


# ============================================================
# 用户输入处理
# ============================================================

def handle_user_input(thread_id: str):
    """处理用户消息输入和 SSE 流式响应"""

    # 聊天输入框
    if prompt := st.chat_input("输入您的问题，按 Enter 发送…", key="chat_input"):
        # 1. 立即显示用户消息
        add_message("user", prompt)

        # 2. 立即刷新显示用户消息
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)

        # 3. 显示助手回复占位
        with st.chat_message("assistant", avatar="🤖"):
            message_placeholder = st.empty()
            tool_status_placeholder = st.empty()

            full_response = ""
            tool_calls_in_progress = {}

            # 4. SSE 流式读取
            try:
                for event in api_client.stream_chat(prompt, thread_id):
                    event_type = event.get("type", "")

                    if event_type == "token":
                        # 逐字追加文本
                        token = event.get("content", "")
                        full_response += token
                        message_placeholder.markdown(full_response + "▌")

                    elif event_type == "tool_start":
                        tool_name = event.get("tool", "unknown")
                        args = event.get("args", {})
                        tool_calls_in_progress[tool_name] = "running"

                        # 显示工具调用状态
                        args_str = str(args)[:100]
                        tool_status_placeholder.info(
                            f"🔧 正在调用工具: **{tool_name}**\n\n参数: `{args_str}...`"
                        )

                    elif event_type == "tool_end":
                        tool_name = event.get("tool", "unknown")
                        output = event.get("output", "")[:200]
                        tool_calls_in_progress[tool_name] = "done"

                        tool_status_placeholder.success(
                            f"✅ 工具 **{tool_name}** 执行完成\n\n结果: {output}..."
                        )
                        # 2秒后清除工具状态
                        time.sleep(0.5)
                        tool_status_placeholder.empty()

                    elif event_type == "error":
                        error_content = event.get("content", "未知错误")
                        full_response = f"❌ {error_content}"
                        message_placeholder.markdown(full_response)
                        tool_status_placeholder.empty()

                    elif event_type == "done":
                        # 清除光标指示器
                        if full_response:
                            message_placeholder.markdown(full_response)
                        else:
                            message_placeholder.markdown("*（未收到回复）*")
                        break

            except Exception as e:
                full_response = f"❌ 对话异常: {str(e)}"
                message_placeholder.markdown(full_response)

            # 5. 更新消息缓存
            if full_response:
                # 移除之前临时添加的 user 消息（因为 add_message 会再调一次）
                # 实际上我们在前面用 add_message 添加了，这里不需要重复
                add_message("assistant", full_response)

            # 6. 刷新页面状态
            st.rerun()


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    main()
