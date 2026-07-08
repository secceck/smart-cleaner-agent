"""
知识库检索模块
基于 Chroma 向量库进行 Top-K 相似度检索
"""
from typing import Optional

from ..common.config import get_settings
from ..common.logger import get_logger
from .vectorstore import get_vectorstore

logger = get_logger(__name__)


def search_knowledge(
    query: str,
    top_k: Optional[int] = None,
    filter_filename: Optional[str] = None,
) -> list[dict]:
    """
    知识库相似度检索

    Args:
        query: 检索查询文本
        top_k: 返回结果数量（默认从配置读取）
        filter_filename: 可选的文档名过滤（用于故障排查按产品手册搜索）

    Returns:
        检索结果列表，每项包含 content, metadata, score
    """
    settings = get_settings()
    top_k = top_k or settings.rag_top_k

    vectorstore = get_vectorstore()

    # 构建过滤条件
    search_kwargs = {"k": top_k}
    if filter_filename:
        search_kwargs["filter"] = {"filename": filter_filename}

    try:
        results = vectorstore.similarity_search_with_score(query, **search_kwargs)
    except Exception as e:
        logger.error(f"向量检索失败: {e}")
        return []

    formatted_results = []
    for doc, score in results:
        formatted_results.append({
            "content": doc.page_content,
            "metadata": doc.metadata,
            # 将距离转换为相似度分数（Chroma 默认使用 L2 或 cosine 距离）
            "score": round(float(score), 4),
        })

    logger.info(
        f"知识库检索完成: query='{query[:50]}...', "
        f"top_k={top_k}, 实际返回 {len(formatted_results)} 条结果"
    )

    return formatted_results


def search_knowledge_as_context(
    query: str,
    top_k: Optional[int] = None,
    filter_filename: Optional[str] = None,
) -> str:
    """
    以拼接好的上下文文本形式返回检索结果
    适用于直接注入 LLM 提示词

    Args:
        query: 检索查询文本
        top_k: 返回结果数量
        filter_filename: 可选的文档名过滤

    Returns:
        拼接后的上下文字符串
    """
    results = search_knowledge(query, top_k, filter_filename)

    if not results:
        return ""

    parts = []
    for i, item in enumerate(results, 1):
        source = item["metadata"].get("filename", "未知来源")
        parts.append(f"【参考资料 {i}】来源: {source}\n{item['content']}")

    return "\n\n".join(parts)
