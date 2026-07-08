"""
产品信息查询工具
基于 RAG 知识库检索扫地机器人产品参数、功能说明、版本差异等
"""
from langchain_core.tools import tool

from ..common.logger import get_logger
from ..rag.retriever import search_knowledge, search_knowledge_as_context

logger = get_logger(__name__)


@tool
def product_info_search(query: str) -> str:
    """
    搜索扫地机器人产品知识库，获取产品型号参数、功能特性、版本差异等信息。
    适用于用户咨询产品规格、功能对比、使用说明等场景。

    使用场景：
    - 用户询问某型号扫地机器人的参数
    - 比较不同型号之间的差异
    - 查询产品功能和使用方法
    - 了解产品技术规格

    Args:
        query: 产品相关的搜索查询，例如"SmartClean S1 Pro 参数"、"各型号对比"、"最大吸力是多少"
    """
    if not query or not query.strip():
        return "请提供具体的产品查询内容，例如: 查询 SmartClean S1 Pro 的电池容量。"

    logger.info(f"产品信息查询: {query[:100]}")
    results = search_knowledge(query.strip())

    if not results:
        return (
            f"## 📦 产品信息查询结果\n\n"
            f"**查询**: {query}\n\n"
            f"⚠️ 知识库中暂无与「{query}」相关的产品信息。\n\n"
            f"建议：\n"
            f"1. 请先上传相关产品手册（PDF/TXT）到知识库\n"
            f"2. 尝试使用不同的关键词搜索\n"
            f"3. 直接描述你想了解的产品型号或功能"
        )

    parts = [f"## 📦 产品信息查询结果\n\n**查询**: {query}\n"]
    for i, item in enumerate(results, 1):
        source = item["metadata"].get("filename", "未知文档")
        # Chroma 返回的是距离值，转为 0-100 匹配度
        score = round(100 / (1 + item["score"]), 1)
        parts.append(f"### 结果 {i} (相关度: {score}%)")
        parts.append(f"📄 来源: {source}")
        parts.append(item["content"])
        parts.append("")

    return "\n".join(parts)
