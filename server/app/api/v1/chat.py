"""
会话与消息管理 API
提供 SSE 流式对话、会话 CRUD、消息查询/清空接口
"""
import json
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from ...agents.react_agent import get_agent_graph, messages_to_langchain, stream_agent_response
from ...common.llm_factory import MaxRetriesExceededError
from ...common.logger import get_logger, set_thread_id
from ...models.database import MessageRepository, SessionRepository
from ...models.schemas import (
    ChatStreamRequest,
    ErrorResponse,
    MessageResponse,
    SessionCreate,
    SessionResponse,
)

logger = get_logger(__name__)

router = APIRouter(tags=["chat"])


# ============================================================
# 依赖注入辅助
# ============================================================

def _get_repos(request: Request) -> tuple[SessionRepository, MessageRepository]:
    """从 app.state 获取仓库实例"""
    return request.app.state.session_repo, request.app.state.message_repo


# ============================================================
# SSE 流式对话
# ============================================================

@router.post(
    "/chat/stream",
    summary="SSE 流式对话",
    description="发送用户消息，返回 SSE 实时文本流",
    responses={
        200: {"description": "SSE 事件流"},
        400: {"model": ErrorResponse, "description": "参数异常"},
    },
)
async def chat_stream(body: ChatStreamRequest, request: Request):
    """
    SSE 流式对话接口

    事件类型:
    - token: 文本片段实时输出
    - tool_start: 工具调用开始
    - tool_end: 工具调用结束
    - done: 对话完成
    """
    thread_id = body.thread_id
    set_thread_id(thread_id)

    session_repo, message_repo = _get_repos(request)

    # 验证会话存在
    session = await session_repo.get_by_thread_id(thread_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话 {thread_id} 不存在")

    logger.info(f"SSE 对话请求: thread_id={thread_id}, message_len={len(body.message)}")

    # 保存用户消息
    await message_repo.save(thread_id, "user", body.message)
    await session_repo.update_timestamp(thread_id)

    # 加载历史消息并转换为 LangChain 格式
    history = await message_repo.get_by_thread_id(thread_id)
    lc_messages = messages_to_langchain(history)

    async def event_generator():
        """SSE 事件生成器"""
        full_response = ""

        try:
            async for event in stream_agent_response(lc_messages, thread_id):
                event_type = event.get("type", "")

                if event_type == "token":
                    full_response += event.get("content", "")

                elif event_type == "done":
                    # 保存助手回复
                    if full_response:
                        await message_repo.save(thread_id, "assistant", full_response)
                        await session_repo.update_timestamp(thread_id)
                        # 自动更新会话标题（取用户第一条消息的前30字）
                        if session["title"] == "新的聊天":
                            new_title = body.message[:30] + ("..." if len(body.message) > 30 else "")
                            await session_repo.update_title(thread_id, new_title)

                elif event_type == "error":
                    logger.error(f"SSE 流式错误: {event.get('content')}")
                    full_response = "抱歉，处理您的请求时遇到了问题，请稍后重试。"

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"SSE 生成器异常: {type(e).__name__}: {e}")
            error_event = json.dumps(
                {"type": "error", "content": f"服务内部异常，请稍后重试"},
                ensure_ascii=False,
            )
            yield f"data: {error_event}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "http://127.0.0.1:8501",
        },
    )


# ============================================================
# 会话管理
# ============================================================

@router.get(
    "/chat/sessions",
    summary="获取会话列表",
    response_model=list[SessionResponse],
)
async def list_sessions(request: Request):
    """获取所有历史会话，按最后活跃时间降序排列"""
    session_repo, _ = _get_repos(request)
    sessions = await session_repo.get_all()
    return sessions


@router.post(
    "/chat/sessions",
    summary="创建新会话",
    response_model=SessionResponse,
    status_code=201,
)
async def create_session(body: SessionCreate, request: Request):
    """创建新会话，返回包含唯一 thread_id 的会话信息"""
    session_repo, _ = _get_repos(request)
    thread_id = uuid.uuid4().hex[:16]
    session = await session_repo.create(thread_id, body.title)
    logger.info(f"新会话创建: thread_id={thread_id}, title={body.title}")
    return session


@router.delete(
    "/chat/sessions/{thread_id}",
    summary="删除会话",
    status_code=204,
)
async def delete_session(thread_id: str, request: Request):
    """删除指定会话及其所有消息记录"""
    session_repo, _ = _get_repos(request)
    deleted = await session_repo.delete(thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"会话 {thread_id} 不存在")
    logger.info(f"会话已删除: thread_id={thread_id}")


# ============================================================
# 消息管理
# ============================================================

@router.get(
    "/chat/messages",
    summary="获取会话消息",
    response_model=list[MessageResponse],
)
async def get_messages(thread_id: str = Query(..., description="会话ID"), request: Request = None):
    """获取指定会话的所有历史聊天记录，按时间升序"""
    session_repo, message_repo = _get_repos(request)

    # 验证会话存在
    session = await session_repo.get_by_thread_id(thread_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话 {thread_id} 不存在")

    messages = await message_repo.get_by_thread_id(thread_id)
    return messages


@router.delete(
    "/chat/messages",
    summary="清空会话消息",
    status_code=204,
)
async def clear_messages(thread_id: str = Query(..., description="会话ID"), request: Request = None):
    """清空指定会话的所有消息，保留会话本身"""
    session_repo, message_repo = _get_repos(request)

    # 验证会话存在
    session = await session_repo.get_by_thread_id(thread_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话 {thread_id} 不存在")

    count = await message_repo.delete_by_thread_id(thread_id)
    logger.info(f"会话消息已清空: thread_id={thread_id}, 删除 {count} 条消息")
