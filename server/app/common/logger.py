"""
日志管理模块
按天自动分割日志文件，自动清理30天前的旧日志
"""
import logging
import os
import re
import time
from contextvars import ContextVar
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .config import get_settings

# 线程安全的上下文变量，用于在日志中记录当前会话ID
_thread_id_ctx: ContextVar[str] = ContextVar("thread_id", default="-")


class DailyRotatingFileHandler(TimedRotatingFileHandler):
    """自定义按天分割的日志处理器，日志文件名格式: app_YYYY-MM-DD.log"""

    def __init__(self, log_dir: Path, level: str = "INFO"):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # 当天日志文件名
        filename = str(log_dir / f'app_{datetime.now().strftime("%Y-%m-%d")}.log')
        super().__init__(
            filename=filename,
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        self.suffix = "%Y-%m-%d"
        # 设置日志级别
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARN": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        self.setLevel(level_map.get(level.upper(), logging.INFO))

    def doRollover(self):
        """执行日志轮转，同时触发旧日志清理"""
        super().doRollover()
        # 清理30天前的日志
        self._cleanup_old_logs()

    def _cleanup_old_logs(self):
        """删除30天前的日志文件"""
        cutoff_date = datetime.now() - timedelta(days=30)
        pattern = re.compile(r"app_(\d{4}-\d{2}-\d{2})\.log")

        for file_path in self.log_dir.iterdir():
            if not file_path.is_file():
                continue
            match = pattern.match(file_path.name)
            if not match:
                continue
            try:
                file_date = datetime.strptime(match.group(1), "%Y-%m-%d")
                if file_date < cutoff_date:
                    file_path.unlink()
            except (ValueError, OSError):
                pass


class ThreadIdFilter(logging.Filter):
    """将当前协程/线程的 thread_id 注入日志记录"""

    def filter(self, record):
        record.thread_id = _thread_id_ctx.get()
        return True


# 全局日志实例缓存
_logger_cache: dict[str, logging.Logger] = {}


def setup_logging() -> None:
    """初始化全局日志系统（在应用启动时调用一次）"""
    settings = get_settings()
    log_dir = settings.log_dir_abs
    log_dir.mkdir(parents=True, exist_ok=True)

    # 配置根日志器
    root_logger = logging.getLogger("smart_cleaner")
    root_logger.setLevel(logging.DEBUG)

    # 避免重复添加处理器
    if root_logger.handlers:
        return

    # 文件处理器（按天分割）
    file_handler = DailyRotatingFileHandler(log_dir, settings.log_level)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-5s | [%(thread_id)s] | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    file_handler.addFilter(ThreadIdFilter())
    root_logger.addHandler(file_handler)

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-5s | [%(thread_id)s] | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    console_handler.addFilter(ThreadIdFilter())
    root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的日志器"""
    return logging.getLogger(f"smart_cleaner.{name}")


def set_thread_id(thread_id: str) -> None:
    """设置当前上下文的会话ID"""
    _thread_id_ctx.set(thread_id)
