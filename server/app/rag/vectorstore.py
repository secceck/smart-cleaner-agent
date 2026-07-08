"""
Chroma 向量数据库管理模块
提供全局单例 Chroma 客户端，避免 Windows 文件锁冲突
"""
from pathlib import Path
from typing import Optional

from chromadb import PersistentClient
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from ..common.config import get_settings
from ..common.logger import get_logger

logger = get_logger(__name__)

# 全局单例
_vectorstore: Optional[Chroma] = None
_embeddings: Optional[OpenAIEmbeddings] = None


def get_embeddings() -> OpenAIEmbeddings:
    """获取嵌入模型单例"""
    global _embeddings
    if _embeddings is None:
        settings = get_settings()
        _embeddings = OpenAIEmbeddings(
            base_url=settings.freellmapi_base_url,
            api_key=settings.freellmapi_api_key,
            model=settings.freellmapi_embedding_model,
            timeout=settings.api_timeout,
            max_retries=2,
            # 禁用 tiktoken 预分词和 base64 编码，兼容 FreeLLMAPI
            tiktoken_enabled=False,
            check_embedding_ctx_length=False,
        )
        logger.info(f"嵌入模型初始化完成: {settings.freellmapi_embedding_model}")
    return _embeddings


def get_vectorstore() -> Chroma:
    """
    获取 Chroma 向量库单例
    使用相同的 persist_directory 和 embedding_function
    """
    global _vectorstore

    if _vectorstore is None:
        settings = get_settings()
        persist_dir = str(settings.chroma_persist_path)
        Path(persist_dir).mkdir(parents=True, exist_ok=True)

        logger.info(f"正在初始化 Chroma 向量库，持久化目录: {persist_dir}")
        _vectorstore = Chroma(
            persist_directory=persist_dir,
            embedding_function=get_embeddings(),
            collection_name="smart_cleaner_knowledge",
        )
        logger.info("Chroma 向量库初始化完成")

    return _vectorstore


def reset_vectorstore() -> None:
    """重置向量库连接（用于测试或重新初始化）"""
    global _vectorstore, _embeddings
    _vectorstore = None
    _embeddings = None
    logger.info("向量库连接已重置")
