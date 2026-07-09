"""
侧边栏组件
展示会话列表、新建/删除会话、知识库上传入口
"""
import streamlit as st

from utils import api_client
from utils.session import load_messages_from_db, switch_session


def render_sidebar():
    """渲染侧边栏"""
    with st.sidebar:
        st.title("🧹 智能客服")

        # ---- 新建会话按钮 ----
        if st.button("➕ 新建会话", use_container_width=True, type="primary"):
            result = api_client.create_session()
            if result:
                st.session_state.thread_id = result["thread_id"]
                st.session_state.messages = []
                st.session_state.sidebar_need_refresh = True
                st.rerun()
            else:
                st.error("创建会话失败，请检查后端服务是否运行")

        st.divider()

        # ---- 手动城市输入 ----
        location_set = st.session_state.get("location_set", False)
        current_city = st.session_state.get("current_city", "")
        location_pending = st.session_state.get("_location_pending", False)

        # 定位未完成时默认展开面板，让用户看到状态
        expander_default = not location_set
        with st.expander("📍 我的位置", expanded=expander_default):
            if location_set and current_city:
                st.success(f"✅ 当前城市: **{current_city}**")
            elif location_pending:
                st.info("⏳ 正在获取定位…（如未生效请手动输入）")
            else:
                st.caption("若自动定位未生效，可在此手动输入城市")

            manual_city = st.text_input(
                "输入城市名",
                value="",
                placeholder="例如: 北京、上海浦东、深圳",
                key="manual_city_input",
                label_visibility="collapsed",
            )
            if manual_city and manual_city != st.session_state.get("_last_manual_city", ""):
                st.session_state["_last_manual_city"] = manual_city
                thread_id = st.session_state.get("thread_id", "")
                if thread_id:
                    if api_client.set_location(thread_id, manual_city):
                        st.session_state["location_set"] = True
                        st.session_state["current_city"] = manual_city
                        st.toast(f"📍 位置已设置为: {manual_city}", icon="✅")
                        st.rerun()
                    else:
                        st.warning("设置位置失败，请检查后端服务")

        # ---- 会话列表 ----
        st.subheader("📋 会话列表")
        sessions = api_client.get_sessions()
        st.session_state.sessions = sessions

        if not sessions:
            st.info("暂无会话，点击上方按钮创建")

        for session in sessions:
            thread_id = session["thread_id"]
            title = session.get("title", "未命名")
            updated_at = session.get("updated_at", "")

            # 截取时间
            if updated_at and len(updated_at) > 16:
                time_str = updated_at[5:16]  # MM-DD HH:MM
            else:
                time_str = ""

            is_active = st.session_state.thread_id == thread_id

            col1, col2 = st.columns([4, 1])

            with col1:
                # 会话按钮
                button_label = f"{'🔵 ' if is_active else ''}{title}"
                if time_str:
                    button_label += f"\n`{time_str}`"

                if st.button(
                    button_label,
                    key=f"session_{thread_id}",
                    use_container_width=True,
                    type="secondary" if not is_active else "primary",
                ):
                    switch_session(thread_id)
                    load_messages_from_db(thread_id)
                    st.rerun()

            with col2:
                # 删除按钮
                if st.button("🗑️", key=f"del_{thread_id}", help=f"删除会话: {title}"):
                    if api_client.delete_session(thread_id):
                        if st.session_state.thread_id == thread_id:
                            st.session_state.thread_id = None
                            st.session_state.messages = []
                        st.session_state.sidebar_need_refresh = True
                        st.rerun()
                    else:
                        st.error("删除失败")

        st.divider()

        # ---- 知识库上传 ----
        with st.expander("📚 知识库管理", expanded=False):
            st.markdown("上传 PDF 或 TXT 文档到知识库")
            uploaded_files = st.file_uploader(
                "选择文件",
                type=["pdf", "txt"],
                accept_multiple_files=True,
                key="knowledge_uploader",
                help="支持 PDF、TXT 格式，单文件最大 50MB",
            )

            if uploaded_files:
                if st.button("📤 上传到知识库", use_container_width=True):
                    with st.spinner("正在处理文档..."):
                        results = api_client.upload_knowledge(uploaded_files)
                        for r in results:
                            if r.get("status") == "success":
                                st.success(f"✅ {r['filename']}: {r.get('message', '成功')}")
                            else:
                                st.error(f"❌ {r['filename']}: {r.get('message', '失败')}")

        # ---- 底部信息 ----
        st.divider()
        st.caption("🐍 扫地机器人智能客服 Agent v0.1")
        st.caption("本地单机部署 | ReAct + RAG")
