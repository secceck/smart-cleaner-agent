"""
Pydantic v2 数据校验模型
包含所有API接口的请求参数和响应数据结构
"""
from pydantic import BaseModel, Field


# ============================================================
# 请求模型
# ============================================================

class ChatStreamRequest(BaseModel):
    """SSE 流式对话请求"""
    message: str = Field(..., min_length=1, max_length=10000, description="用户提问文本")
    thread_id: str = Field(..., min_length=1, max_length=64, description="会话唯一标识")


class SessionCreate(BaseModel):
    """创建新会话请求"""
    title: str = Field(default="新的聊天", max_length=200, description="会话标题")


class KnowledgeSearchRequest(BaseModel):
    """知识库检索请求"""
    query: str = Field(..., min_length=1, max_length=2000, description="检索查询文本")
    top_k: int = Field(default=3, ge=1, le=20, description="返回结果数量")


# ============================================================
# 响应模型
# ============================================================

class SessionResponse(BaseModel):
    """会话信息响应"""
    id: int
    thread_id: str
    title: str
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    """消息记录响应"""
    id: int
    thread_id: str
    role: str
    content: str
    tool_name: str | None = None
    created_at: str


class KnowledgeSearchItem(BaseModel):
    """知识库检索单条结果"""
    content: str
    metadata: dict
    score: float


class KnowledgeSearchResponse(BaseModel):
    """知识库检索响应"""
    results: list[KnowledgeSearchItem]
    query: str
    total: int


class KnowledgeUploadItem(BaseModel):
    """单个文件上传结果"""
    filename: str
    chunks_count: int = 0
    status: str = "success  # success | partial | error"
    message: str = ""


class KnowledgeUploadResponse(BaseModel):
    """知识库上传响应"""
    files: list[KnowledgeUploadItem]


class ErrorResponse(BaseModel):
    """通用错误响应"""
    detail: str
    status_code: int = 500


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "ok"
    version: str = "0.1.0"
    freellmapi_connected: bool = False
    chroma_ready: bool = False
    models_available: list[str] = []
