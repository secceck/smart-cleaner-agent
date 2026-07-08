"""
报告上下文聚合工具
Agent 调用此工具表示"进入报告生成模式"，系统会收集已获取的上下文数据，
并触发动态 Prompt 切换到 REPORT_PROMPT。
"""
from langchain_core.tools import tool

from ..common.logger import get_logger

logger = get_logger(__name__)


@tool
def fill_context_for_report(
    location: str = "",
    weather_summary: str = "",
    user_id: str = "",
) -> str:
    """
    在生成清扫报告之前调用此工具，收集并验证上下文数据是否齐全。
    调用后系统会自动切换到报告生成模式，使用标准报告模板输出。

    使用场景：
    - 用户要求"生成报告"、"清扫报告"、"周报"、"月报"时
    - Agent 应先收集数据（get_location / weather_query / get_user_id / query_usage_records）
    - 确认数据齐全后调用此工具，触发报告模式

    Args:
        location: 用户城市（从 get_location 获取），如"杭州"
        weather_summary: 天气摘要（从 weather_query 获取的关键信息）
        user_id: 用户会话ID（从 get_user_id 获取）
    """
    missing = []
    if not location or location == "未知":
        missing.append("位置信息")
    if not weather_summary:
        missing.append("天气数据")
    if not user_id:
        missing.append("用户标识")

    if missing:
        logger.info(f"报告上下文缺失: {', '.join(missing)}")
        return (
            f"⚠️ 报告上下文不完整，缺少: {', '.join(missing)}。\n"
            f"请先调用相关工具获取缺失数据，然后重新调用此工具。\n"
            f"需要的工具: "
            + ("" if location else "get_location ") +
            ("" if weather_summary else "weather_query ") +
            ("" if user_id else "get_user_id ")
        )

    logger.info(f"报告上下文已就绪: location={location}, user={user_id}")
    return (
        f"✅ 报告上下文已就绪！\n\n"
        f"📋 可用数据:\n"
        f"- 用户位置: {location}\n"
        f"- 用户标识: {user_id}\n"
        f"- 天气摘要: {weather_summary}\n\n"
        f"🔔 **系统已切换到报告生成模式**。\n"
        f"请严格按照标准报告模板（五大模块）生成 Markdown 格式清扫报告。\n"
        f"报告必须基于 query_usage_records 返回的真实数据，禁止编造。"
    )
