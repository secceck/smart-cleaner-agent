"""
用户标识工具
返回当前会话的唯一标识，用于关联设备历史数据
"""
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from ..common.logger import get_logger

logger = get_logger(__name__)


@tool
def get_user_id(config: RunnableConfig) -> str:
    """
    获取当前会话的唯一用户标识（thread_id）。
    用于关联该用户的设备使用记录、历史清扫数据等。

    使用场景：
    - 查询用户设备使用记录前需要获取用户标识
    - 生成清扫报告时关联用户数据

    无需参数，自动从当前会话上下文中提取。
    """
    thread_id = config.get("configurable", {}).get("thread_id", "unknown")
    logger.debug(f"获取用户ID: {thread_id}")
    return f"当前用户会话ID: {thread_id}"
