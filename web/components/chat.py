"""
聊天消息渲染组件
区分用户/AI 消息样式，支持 Markdown 渲染和报告展示
"""
import streamlit as st


def render_message(role: str, content: str, index: int = 0):
    """
    渲染单条消息

    Args:
        role: 消息角色 (user / assistant / tool)
        content: 消息内容
        index: 消息索引（用于唯一 key）
    """
    if role == "user":
        # 用户消息 - 右侧气泡（由 CSS 控制样式）
        with st.chat_message("user", avatar="👤"):
            st.markdown(content)

    elif role == "assistant":
        # AI 消息 - 左侧气泡（由 CSS 控制样式）
        with st.chat_message("assistant", avatar="🤖"):
            if _is_report(content):
                _render_report_message(content)
            else:
                st.markdown(content)

    elif role == "tool":
        # 工具消息 - 折叠显示（调试用）
        with st.expander(f"🔧 工具调用详情", expanded=False):
            st.text(content)


def _is_report(content: str) -> bool:
    """检测消息是否为清扫报告"""
    report_markers = [
        "扫地机器人清扫报告",
        "## 一、设备使用概况",
        "## 二、清扫数据统计",
    ]
    return any(marker in content for marker in report_markers)


def _render_report_message(content: str):
    """渲染清扫报告消息（带绿色边框的特殊卡片）"""
    st.markdown(
        """
        <style>
        .report-card {
            border: 2px solid #4CAF50;
            border-radius: 10px;
            padding: 5px;
            margin: 10px 0;
            background: linear-gradient(135deg, #f0fff0 0%, #ffffff 100%);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container():
        st.markdown('<div class="report-card">', unsafe_allow_html=True)
        st.markdown(content)
        st.markdown('</div>', unsafe_allow_html=True)

        # 下载按钮
        st.download_button(
            label="📥 下载报告 (Markdown)",
            data=content,
            file_name="清扫报告.md",
            mime="text/markdown",
            key=f"download_report_{hash(content) % 10000}",
        )


def render_chat_history():
    """渲染当前会话的全部聊天记录"""
    messages = st.session_state.get("messages", [])

    if not messages:
        _render_welcome()
        return

    for i, msg in enumerate(messages):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        render_message(role, content, i)


def _render_welcome():
    """渲染欢迎页面"""
    st.markdown("""
    ## 👋 欢迎使用扫地机器人智能客服！

    我是您的专属智能助手，可以帮助您：

    | 功能 | 说明 |
    |------|------|
    | 💬 **产品咨询** | 查询扫地机器人型号参数、功能对比 |
    | 🔧 **故障排查** | 根据错误码或故障现象提供解决方案 |
    | 🛠️ **保养指导** | 提供设备清洁、耗材更换建议 |
    | 🌤️ **清扫建议** | 结合天气和环境给出清扫模式推荐 |
    | 📊 **报告生成** | 生成标准化清扫报告（说"生成报告"即可） |

    ### 💡 试试问我：
    - "SmartClean S1 Pro 的最大吸力是多少？"
    - "我的机器人显示 E04 错误怎么办？"
    - "今天适合清扫吗？"
    - "帮我生成本周的清扫报告"

    > ⚠️ 使用前请先在侧边栏上传产品手册到知识库，以获得更准确的回答！
    """)
