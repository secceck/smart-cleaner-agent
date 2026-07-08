"""
位置获取工具
从内存缓存读取用户地理位置信息
前端通过浏览器 Geolocation API 或 IP 定位获取城市后写入后端
"""
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from ..common.logger import get_logger

logger = get_logger(__name__)

# 内存缓存: thread_id -> location_info
_location_cache: dict[str, dict] = {}


def set_location_cache(thread_id: str, city: str, lat: float = 0.0, lng: float = 0.0) -> None:
    """由 API 层调用，写入前端上报的用户位置信息"""
    _location_cache[thread_id] = {
        "city": city,
        "lat": lat,
        "lng": lng,
    }
    logger.info(f"会话 {thread_id} 位置已缓存: {city}")


def get_location_cache(thread_id: str) -> dict | None:
    """读取缓存的位置信息"""
    return _location_cache.get(thread_id)


@tool
def get_location(config: RunnableConfig) -> str:
    """
    获取当前用户的地理位置信息（城市名）。
    如果用户已授权浏览器定位或手动输入过城市，返回对应的城市名称。
    如果未获取到位置信息，会提示用户手动输入城市名。

    使用场景：
    - 需要根据用户位置查询天气
    - 生成清扫报告时需要用户位置信息

    无需参数，自动从当前会话上下文中提取。
    """
    thread_id = config.get("configurable", {}).get("thread_id", "")

    if thread_id and thread_id in _location_cache:
        loc = _location_cache[thread_id]
        city = loc.get("city", "")
        logger.info(f"返回缓存位置: thread_id={thread_id}, city={city}")
        return f"用户当前所在城市: {city}"

    logger.info(f"未找到会话 {thread_id} 的位置缓存")
    return (
        "未能获取到您的位置信息。请直接告诉我您所在的城市名称，"
        "例如: 我在北京、我在上海浦东等。"
    )
