"""
知识库上传组件
提供文件上传、处理状态展示功能
（已集成到侧边栏中，此处预留独立组件的扩展能力）
"""
import streamlit as st

from utils import api_client


def render_knowledge_upload():
    """独立的知识库上传页面组件（预留）"""
    st.title("📚 知识库管理")

    st.markdown("""
    上传产品手册、故障指南等文档到知识库，系统会自动：
    1. 校验文件格式（PDF / TXT）
    2. 递归分片处理
    3. 向量化存储
    4. 建立检索索引
    """)

    col1, col2 = st.columns(2)
    with col1:
        st.metric("支持格式", "PDF, TXT")
    with col2:
        st.metric("单文件上限", "50 MB")

    uploaded_files = st.file_uploader(
        "拖拽或选择文件上传",
        type=["pdf", "txt"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        # 显示文件信息
        for f in uploaded_files:
            size_kb = len(f.getvalue()) / 1024
            size_mb = size_kb / 1024
            if size_mb > 1:
                st.text(f"📄 {f.name} ({size_mb:.1f} MB)")
            else:
                st.text(f"📄 {f.name} ({size_kb:.0f} KB)")

        if st.button("开始上传处理", type="primary", use_container_width=True):
            progress = st.progress(0, "正在处理...")
            results = api_client.upload_knowledge(uploaded_files)

            for i, r in enumerate(results):
                progress.progress((i + 1) / len(results))
                if r.get("status") == "success":
                    st.success(f"✅ {r['filename']}: {r.get('message', '')}")
                else:
                    st.error(f"❌ {r['filename']}: {r.get('message', '')}")

            progress.empty()
            st.rerun()
