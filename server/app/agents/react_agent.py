"""
ReAct 智能体核心引擎
基于 LangGraph 实现 Think → Act → Observe 循环推理
支持 SSE 流式输出、工具并行调用、模型故障转移
"""
import asyncio
from typing import Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict, Annotated

from ..common.config import get_settings
from ..common.llm_factory import MaxRetriesExceededError, get_model_manager
from ..common.logger import get_logger, set_thread_id
from ..prompts.system_prompt import get_system_prompt
from ..tools import ALL_TOOLS

logger = get_logger(__name__)


# ============================================================
# Agent 状态定义
# ============================================================

class AgentState(TypedDict):
    """
    ReAct 智能体状态
    messages 使用 add_messages 作为 reducer，自动处理消息去重和追加
    """
    messages: Annotated[list, add_messages]


# ============================================================
# 智能体节点
# ============================================================

def _get_tools_list():
    """获取工具列表（排除需要 runtime config 的工具特殊处理）"""
    return ALL_TOOLS


def _is_report_mode(messages: list) -> bool:
    """
    检测是否已进入报告生成模式。
    判断依据：历史中有 fill_context_for_report 工具的成功返回。
    """
    for msg in messages:
        if hasattr(msg, "name") and getattr(msg, "name", "") == "fill_context_for_report":
            content = str(getattr(msg, "content", ""))
            if "报告上下文已就绪" in content:
                return True
    return False


async def agent_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    ReAct 推理节点
    调用 LLM 进行思考决策，返回 AI 响应（可能包含 tool_calls）

    内置故障转移：
    1. 从 ModelFailoverManager 获取会话粘性模型
    2. 调用 LLM，失败时自动切换模型（最多20次）
    3. 成功后记录粘性
    """
    thread_id = config.get("configurable", {}).get("thread_id", "unknown")
    set_thread_id(thread_id)

    settings = get_settings()
    model_manager = get_model_manager()
    tools = _get_tools_list()

    # 构建消息列表
    messages = list(state["messages"])

    # 动态 Prompt 切换：检测是否进入报告模式
    if _is_report_mode(messages):
        from ..prompts.report_prompt import get_report_prompt
        # 尝试从上下文中提取位置信息
        location = "未知"
        for msg in messages:
            content = str(getattr(msg, "content", ""))
            if "用户位置:" in content:
                location = content.split("用户位置:")[1].split("\n")[0].strip()
                break
        system_prompt = get_report_prompt(location)
        logger.info(f"Agent 进入报告生成模式: location={location}")
    else:
        system_prompt = get_system_prompt()

    # 如果第一条消息不是 SystemMessage，插入系统提示词
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt)] + messages
    else:
        # 替换已有的系统提示词（报告模式 vs 普通模式）
        messages[0] = SystemMessage(content=system_prompt)

    # 创建绑定工具的 LLM（模板，实际模型在 invoker 中动态选择）
    template_llm = model_manager.create_chat_llm()
    llm_with_tools = template_llm.bind_tools(tools)

    logger.info(f"Agent 节点开始推理: thread_id={thread_id}, messages_count={len(messages)}")

    try:
        response = await model_manager.invoke_with_retry(
            thread_id=thread_id,
            llm_with_tools=llm_with_tools,
            messages=messages,
        )
        logger.info(
            f"Agent 推理完成: thread_id={thread_id}, "
            f"has_tool_calls={bool(getattr(response, 'tool_calls', None))}"
        )
        return {"messages": [response]}

    except MaxRetriesExceededError as e:
        logger.error(f"Agent 模型调用全部失败: thread_id={thread_id}")
        # 返回友好的错误消息
        error_msg = AIMessage(
            content=str(e),
        )
        return {"messages": [error_msg]}

    except Exception as e:
        logger.error(f"Agent 推理异常: {type(e).__name__}: {e}")
        error_msg = AIMessage(
            content=f"抱歉，智能体处理您的请求时遇到了问题。请稍后重试。",
        )
        return {"messages": [error_msg]}


# ============================================================
# 条件路由
# ============================================================

def router(state: AgentState) -> Literal["tools", "__end__"]:
    """
    条件路由函数
    - 如果最后一条 AI 消息包含 tool_calls → 路由到 tools 节点
    - 否则 → 结束
    """
    last_message = state["messages"][-1]

    # 检查是否包含工具调用
    if isinstance(last_message, AIMessage):
        tool_calls = getattr(last_message, "tool_calls", None)
        if tool_calls and len(tool_calls) > 0:
            logger.info(
                f"路由到工具节点: {[tc.get('name', 'unknown') for tc in tool_calls]}"
            )
            return "tools"

    logger.info("路由到结束节点")
    return "__end__"


# ============================================================
# 构建编译图
# ============================================================

# 全局缓存的编译图
_compiled_graph = None


def build_agent() -> StateGraph:
    """
    构建 LangGraph 状态图

    拓扑结构:
        START → agent → [条件路由]
                         ├── tools → agent (循环)
                         └── END

    ToolNode 内置并行执行:
    当 LLM 返回多个 tool_calls 时，ToolNode 自动使用 asyncio.gather 并发执行
    """
    tools = _get_tools_list()

    # 创建状态图
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(tools))

    # 设置入口
    workflow.set_entry_point("agent")

    # 添加条件边：agent → tools 或 END
    workflow.add_conditional_edges("agent", router, {
        "tools": "tools",
        "__end__": END,
    })

    # tools 节点处理完后回到 agent 继续推理
    workflow.add_edge("tools", "agent")

    return workflow.compile()


def get_agent_graph():
    """
    获取编译好的智能体图（单例模式）
    每次调用返回相同的编译图实例
    """
    global _compiled_graph
    if _compiled_graph is None:
        logger.info("正在构建 LangGraph 智能体图...")
        _compiled_graph = build_agent()
        logger.info("LangGraph 智能体图构建完成")
    return _compiled_graph


# ============================================================
# 消息转换工具
# ============================================================

def messages_to_langchain(history: list[dict]) -> list:
    """
    将数据库中的消息记录转换为 LangChain 消息对象列表

    Args:
        history: 数据库查询结果列表，每项含 role, content, tool_name

    Returns:
        LangChain 消息对象列表
    """
    lc_messages = []
    for msg in history:
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))
        elif role == "tool":
            tool_name = msg.get("tool_name", "unknown")
            lc_messages.append(
                ToolMessage(content=content, tool_call_id=f"db_{tool_name}")
            )

    return lc_messages


async def stream_agent_response(
    messages: list,
    thread_id: str,
):
    """
    流式执行智能体，生成 SSE 事件

    Args:
        messages: LangChain 消息列表
        thread_id: 会话ID

    Yields:
        dict: SSE 事件数据
    """
    set_thread_id(thread_id)
    graph = get_agent_graph()
    config = {"configurable": {"thread_id": thread_id}}

    try:
        async for event in graph.astream_events(
            {"messages": messages},
            config,
            version="v2",
        ):
            kind = event.get("event", "")

            # --- Token 流式输出 ---
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk", {})
                content = getattr(chunk, "content", None)
                if content and isinstance(content, str):
                    yield {"type": "token", "content": content}

            # --- 工具调用开始 ---
            elif kind == "on_tool_start":
                tool_name = event.get("name", "unknown")
                tool_input = event.get("data", {}).get("input", {})
                # 过滤掉 RunnableConfig 类型参数
                safe_input = {
                    k: v for k, v in tool_input.items()
                    if not k.startswith("_") and k != "config"
                }
                yield {
                    "type": "tool_start",
                    "tool": tool_name,
                    "args": safe_input,
                }

            # --- 工具调用结束 ---
            elif kind == "on_tool_end":
                tool_name = event.get("name", "unknown")
                output = event.get("data", {}).get("output", "")
                output_str = str(output)
                # 截断过长输出
                if len(output_str) > 1000:
                    output_str = output_str[:1000] + "...(已截断)"
                yield {
                    "type": "tool_end",
                    "tool": tool_name,
                    "output": output_str,
                }

        # 完成信号
        yield {"type": "done"}

    except Exception as e:
        logger.error(f"流式执行异常: {type(e).__name__}: {e}")
        yield {"type": "error", "content": f"智能体执行异常: {str(e)}"}
        yield {"type": "done"}
