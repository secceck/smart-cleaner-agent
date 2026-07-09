"""
FastAPI 服务主入口
负责应用组装、中间件配置、生命周期管理、路由注册
"""
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.react_agent import get_agent_graph
from app.api.v1.chat import router as chat_router
from app.api.v1.knowledge import router as knowledge_router
from app.common.config import get_settings
from app.common.llm_factory import init_model_manager
from app.common.logger import get_logger, setup_logging
from app.models.database import MessageRepository, SessionRepository, init_database
from app.models.schemas import HealthResponse
from app.rag.loader import process_document
from app.rag.vectorstore import get_vectorstore
from app.tools.location import (
    get_location_cache,
    resolve_city_from_coords,
    resolve_city_from_ip,
    set_location_cache,
)

logger = get_logger(__name__)


# ============================================================
# 内置知识库自动加载
# ============================================================

def _reload_knowledge_base(knowledge_file: Path, vectorstore) -> int:
    """
    清除旧分块并重新导入知识库文件，返回分块数。
    """
    # 删除旧版本
    collection = getattr(vectorstore, "_collection", None)
    if collection is not None:
        try:
            collection.delete(where={"filename": knowledge_file.name})
        except Exception:
            pass  # 首次启动时集合为空

    # 重新导入
    return process_document(str(knowledge_file), knowledge_file.name)


def _init_knowledge_base(settings, vectorstore) -> None:
    """
    每次启动自动将内置知识库同步到 Chroma。
    """
    knowledge_file = settings.get_absolute_path("data/knowledge/smart_cleaner_manual.txt")

    if not knowledge_file.exists():
        logger.info(f"内置知识库文件不存在，跳过: {knowledge_file}")
        return

    logger.info(f"正在加载内置知识库: {knowledge_file.name} ...")
    for attempt in range(1, 4):
        try:
            chunks = _reload_knowledge_base(knowledge_file, vectorstore)
            logger.info(f"内置知识库加载完成: {chunks} 个分块已入库")
            return
        except Exception as e:
            if attempt < 3:
                wait = 3 * attempt
                logger.warning(
                    f"内置知识库加载失败 (尝试 {attempt}/3): {e}，{wait}s 后重试..."
                )
                time.sleep(wait)
            else:
                logger.error(
                    f"内置知识库加载失败 (已重试 3 次): {e}。"
                    f"服务将继续运行，可通过 API 手动上传知识库。"
                )


# ============================================================
# 应用生命周期
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    startup: 初始化数据库、向量库、模型管理器、智能体
    shutdown: 清理资源
    """
    settings = get_settings()
    db = None

    # ======================== STARTUP ========================
    logger.info("=" * 60)
    logger.info("扫地机器人智能客服Agent 服务启动中...")
    logger.info("=" * 60)

    # 1. 初始化日志系统
    setup_logging()
    logger.info(f"日志系统已初始化: level={settings.log_level}, dir={settings.log_dir_abs}")

    # 2. 初始化 SQLite 数据库
    logger.info(f"正在连接数据库: {settings.sqlite_db_path_abs}")
    db = await init_database()
    app.state.db = db
    app.state.session_repo = SessionRepository(db)
    app.state.message_repo = MessageRepository(db)
    logger.info("数据库连接已建立")

    # 3. 初始化 Chroma 向量库
    chroma_ready = False
    vectorstore = None
    try:
        vectorstore = get_vectorstore()
        app.state.vectorstore = vectorstore
        chroma_ready = True
        logger.info(f"Chroma 向量库已就绪: {settings.chroma_persist_path}")
    except Exception as e:
        logger.error(f"Chroma 向量库初始化失败: {e}")
        app.state.vectorstore = None

    # 4. 初始化模型管理器
    freellmapi_connected = False
    models_available: list[str] = []
    try:
        model_manager = await init_model_manager()
        app.state.model_manager = model_manager
        freellmapi_connected = True
        models_available = model_manager.available_models
        logger.info(f"FreeLLMAPI 连接成功，可用模型: {models_available}")
    except Exception as e:
        logger.error(f"FreeLLMAPI 连接失败: {e}")
        app.state.model_manager = None

    # 4.5 自动加载内置知识库
    if chroma_ready and freellmapi_connected and vectorstore is not None:
        try:
            _init_knowledge_base(settings, vectorstore)
        except Exception as e:
            logger.warning(f"内置知识库加载失败（不影响服务运行）: {e}")

    # 5. 构建 ReAct 智能体
    try:
        agent_graph = get_agent_graph()
        app.state.agent_graph = agent_graph
        logger.info("ReAct 智能体图已构建")
    except Exception as e:
        logger.error(f"智能体构建失败: {e}")
        app.state.agent_graph = None

    # 6. 确保数据目录存在
    for dir_path in [
        settings.chroma_persist_path,
        settings.get_absolute_path("data/knowledge"),
        settings.log_dir_abs,
    ]:
        dir_path.mkdir(parents=True, exist_ok=True)

    # 存储状态信息
    app.state.freellmapi_connected = freellmapi_connected
    app.state.chroma_ready = chroma_ready
    app.state.models_available = models_available

    logger.info("=" * 60)
    logger.info("✅ 服务启动完成！")
    logger.info(f"   - API 文档: http://127.0.0.1:8000/docs")
    logger.info(f"   - FreeLLMAPI: {'✅ 已连接' if freellmapi_connected else '❌ 未连接'}")
    logger.info(f"   - Chroma: {'✅ 已就绪' if chroma_ready else '❌ 未就绪'}")
    logger.info(f"   - 可用模型: {models_available if models_available else '无'}")
    logger.info("=" * 60)

    yield

    # ======================== SHUTDOWN ========================
    logger.info("服务正在关闭...")
    if db is not None:
        await db.close()
    logger.info("✅ 服务已关闭")


# ============================================================
# FastAPI 应用实例
# ============================================================

app = FastAPI(
    title="扫地机器人智能客服 Agent API",
    description="基于 ReAct Agent + RAG 的本地智能客服系统",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ============================================================
# CORS 跨域中间件
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8501",
        "http://localhost:8501",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 路由注册
# ============================================================

app.include_router(chat_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1")


# ============================================================
# 健康检查
# ============================================================

@app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
async def health_check():
    """系统健康检查"""
    return HealthResponse(
        status="ok",
        version="0.1.0",
        freellmapi_connected=getattr(app.state, "freellmapi_connected", False),
        chroma_ready=getattr(app.state, "chroma_ready", False),
        models_available=getattr(app.state, "models_available", []),
    )


# ============================================================
# 位置信息设置接口（前端调用）
# ============================================================

class LocationSetRequest(BaseModel):
    thread_id: str
    city: str
    lat: float = 0.0
    lng: float = 0.0


@app.post("/api/v1/location", tags=["system"])
async def set_location(body: LocationSetRequest, request: Request):
    """
    设置用户地理位置信息（由前端 JS 或手动输入调用）。
    优先使用前端传入的 city；若为空则由服务端完成坐标反查和 IP 定位。
    """
    city = body.city
    lat = body.lat
    lng = body.lng

    # 1. 如果前端已带 city（手动输入或旧版 JS），直接使用
    if city:
        set_location_cache(body.thread_id, city, lat, lng)
        return {"status": "ok", "city": city}

    # 2. 服务端反查 GPS 坐标 → 城市名
    if lat and lng:
        city = await resolve_city_from_coords(lat, lng)

    # 3. 降级：服务端 IP 定位
    if not city:
        client_ip = request.client.host if request.client else "127.0.0.1"
        city = await resolve_city_from_ip(client_ip)

    if city:
        set_location_cache(body.thread_id, city, lat, lng)
    else:
        logger.warning(f"会话 {body.thread_id} 位置解析失败（坐标+IP均未命中）")

    return {"status": "ok" if city else "not_found", "city": city}


@app.get("/api/v1/location", tags=["system"])
async def get_location(thread_id: str):
    """获取当前会话的地理位置信息（由前端轮询）"""
    loc = get_location_cache(thread_id)
    if loc:
        return {"status": "ok", "city": loc["city"], "lat": loc["lat"], "lng": loc["lng"]}
    return {"status": "not_found", "city": None}


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
