"""
位置获取工具 + 服务端地理编码
- 内存缓存: thread_id -> location_info
- 服务端反查: GPS坐标 → 城市名（不走浏览器，避免国内网络限制）
- 服务端 IP 定位: 客户端 IP → 城市名（无 CORS 问题）
"""
import httpx
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from ..common.logger import get_logger

logger = get_logger(__name__)

# 内存缓存: thread_id -> location_info
_location_cache: dict[str, dict] = {}


def set_location_cache(thread_id: str, city: str, lat: float = 0.0, lng: float = 0.0) -> None:
    """由 API 层调用，写入用户位置信息"""
    _location_cache[thread_id] = {
        "city": city,
        "lat": lat,
        "lng": lng,
    }
    logger.info(f"会话 {thread_id} 位置已缓存: {city}")


def get_location_cache(thread_id: str) -> dict | None:
    """读取缓存的位置信息"""
    return _location_cache.get(thread_id)


# ================================================================
# 服务端地理编码（解决浏览器端国内网络限制）
# ================================================================

# 可用的 IP 定位服务（按优先级）
_IP_GEO_SERVICES = [
    "http://ip-api.com/json/?lang=zh-CN",       # 免费，国内可用，HTTP
    "https://api.ip.sb/geoip",                   # 备选
]


# 反向地理编码服务（GPS坐标 → 城市名），按优先级排列
_GEOCODE_SERVICES = [
    {
        "name": "Photon",
        "url": "https://photon.komoot.io/reverse?lat={lat}&lon={lng}",
        "parser": "photon",
    },
    {
        "name": "BigDataCloud",
        "url": "https://api.bigdatacloud.net/data/reverse-geocode-client"
               "?latitude={lat}&longitude={lng}&localityLanguage=zh",
        "parser": "bigdatacloud",
    },
    {
        "name": "Nominatim",
        "url": "https://nominatim.openstreetmap.org/reverse"
               "?lat={lat}&lon={lng}&format=json&accept-language=zh",
        "parser": "nominatim",
    },
]


def _parse_geocode_result(parser: str, data: dict) -> str | None:
    """解析不同反向地理编码服务的响应"""
    if parser == "photon":
        features = data.get("features", [])
        if features:
            props = features[0].get("properties", {})
            return props.get("city") or props.get("name")
    elif parser == "bigdatacloud":
        return data.get("city") or data.get("principalSubdivision")
    elif parser == "nominatim":
        addr = data.get("address", {})
        return addr.get("city") or addr.get("town") or addr.get("county") or addr.get("state")
    return None


async def resolve_city_from_coords(lat: float, lng: float) -> str | None:
    """
    服务端反向地理编码：GPS 坐标 → 城市名。
    顺序尝试 Photon → BigDataCloud → Nominatim，任意成功即返回。
    Photon 和 BigDataCloud 在国内可用，Nominatim 作为国际兜底。
    """
    if not lat and not lng:
        return None

    for svc in _GEOCODE_SERVICES:
        try:
            url = svc["url"].format(lat=lat, lng=lng)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "SmartCleanerAgent/1.0"},
                )
                if resp.status_code != 200:
                    logger.warning(f"坐标反查({svc['name']}) HTTP {resp.status_code}")
                    continue

                data = resp.json()
                city = _parse_geocode_result(svc["parser"], data)
                if city:
                    logger.info(f"坐标反查({svc['name']}) 成功: ({lat},{lng}) -> {city}")
                    return city
        except Exception as e:
            logger.warning(f"坐标反查({svc['name']}) 异常: {e}")

    return None


async def resolve_city_from_ip(client_ip: str) -> str | None:
    """
    服务端 IP 定位：客户端 IP → 城市名。
    服务端请求无 CORS 限制。
    """
    if not client_ip or client_ip in ("127.0.0.1", "::1", "localhost"):
        logger.info("本地回环地址，跳过 IP 定位")
        return None

    for url in _IP_GEO_SERVICES:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers={"User-Agent": "SmartCleanerAgent/1.0"})
                if resp.status_code != 200:
                    logger.warning(f"IP 定位({url}) 失败: HTTP {resp.status_code}")
                    continue

                data = resp.json()
                city = data.get("city")
                if city:
                    logger.info(f"IP 定位({url}) 成功: {client_ip} -> {city}")
                    return city
        except Exception as e:
            logger.warning(f"IP 定位({url}) 异常: {e}")

    return None


# ================================================================
# Agent 工具
# ================================================================

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
