"""
清扫报告组件
渲染和下载标准化清扫报告
"""
import streamlit as st


def render_report_card(content: str):
    """
    渲染报告卡片
    带有特殊样式和下载按钮
    """
    # 报告卡片样式
    st.markdown(
        """
        <style>
        .report-container {
            border: 2px solid #4CAF50;
            border-radius: 12px;
            padding: 20px;
            margin: 10px 0;
            background: linear-gradient(135deg, #f5fff5 0%, #ffffff 50%, #f0f8f0 100%);
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .report-header {
            text-align: center;
            border-bottom: 2px solid #4CAF50;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="report-container">', unsafe_allow_html=True)
    st.markdown(content)
    st.markdown('</div>', unsafe_allow_html=True)

    # 下载按钮
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="📥 下载 Markdown",
            data=content,
            file_name=f"清扫报告.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with col2:
        st.download_button(
            label="📄 下载文本",
            data=content,
            file_name=f"清扫报告.txt",
            mime="text/plain",
            use_container_width=True,
        )
