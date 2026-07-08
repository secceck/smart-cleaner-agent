"""
工具注册表
收集所有 @tool 装饰的自定义工具，供 ReAct 智能体使用
"""
from .weather import weather_query
from .location import get_location
from .user import get_user_id
from .usage_records import query_usage_records
from .product_info import product_info_search
from .troubleshoot import troubleshoot
from .report_context import fill_context_for_report

# 所有可用工具列表
ALL_TOOLS = [
    weather_query,
    get_location,
    get_user_id,
    query_usage_records,
    product_info_search,
    troubleshoot,
    fill_context_for_report,
]

# 工具名称映射
TOOL_NAME_MAP = {tool.name: tool for tool in ALL_TOOLS}

__all__ = [
    "ALL_TOOLS",
    "TOOL_NAME_MAP",
    "weather_query",
    "get_location",
    "get_user_id",
    "query_usage_records",
    "product_info_search",
    "troubleshoot",
]
