"""
全局配置管理模块
基于 pydantic-settings 读取 .env 环境变量，提供单例配置访问
"""
import os
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings


# 项目根目录（server 的父目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class Settings(BaseSettings):
    """应用全局配置，所有值从 .env 文件加载"""

    # --- FreeLLMAPI 模型服务配置 ---
    freellmapi_base_url: str = "http://127.0.0.1:3001/v1"
    freellmapi_api_key: str = "freellmapi-xxx"
    freellmapi_chat_model: str = "auto"
    freellmapi_embedding_model: str = "auto"
    embedding_dimension: int = 1024
    api_timeout: int = 30

    # --- RAG 知识库默认参数 ---
    rag_top_k: int = 3
    chunk_size: int = 1024
    chunk_overlap: int = 200

    # --- 本地数据存储路径 ---
    chroma_persist_dir: str = "../data/chroma_db"
    sqlite_db_path: str = "../data/chat.db"

    # --- 日志配置 ---
    log_level: str = "INFO"
    log_dir: str = "../logs"

    # --- 会话粘性时间（秒） ---
    session_stickiness_seconds: int = 1800

    # --- 最大重试次数 ---
    max_retries: int = 20

    # --- 上传文件大小限制 ---
    max_upload_size_mb: int = 50

    class Config:
        env_file = str(PROJECT_ROOT / "server" / ".env")
        env_file_encoding = "utf-8"
        # 允许 .env 中的变量名大小写不敏感
        case_sensitive = False

    def get_absolute_path(self, relative_path: str) -> Path:
        """将相对路径转为基于项目根目录的绝对路径"""
        path = Path(relative_path)
        if path.is_absolute():
            return path
        return (PROJECT_ROOT / relative_path).resolve()

    @property
    def chroma_persist_path(self) -> Path:
        return self.get_absolute_path(self.chroma_persist_dir)

    @property
    def sqlite_db_path_abs(self) -> Path:
        return self.get_absolute_path(self.sqlite_db_path)

    @property
    def log_dir_abs(self) -> Path:
        return self.get_absolute_path(self.log_dir)

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
