"""
故障排查工具
基于 RAG 知识库检索故障解决方案
支持错误码精确匹配和故障现象语义搜索
"""
import re

from langchain_core.tools import tool

from ..common.logger import get_logger
from ..rag.retriever import search_knowledge

logger = get_logger(__name__)


def _extract_error_code(text: str) -> str | None:
    """从用户输入中提取可能的错误码"""
    patterns = [
        (r'错误码[：:\s]*(\w[\w-]*)', True),   # 错误码：E01 (有捕获组)
        (r'[Ee]\d{2,3}', False),              # E01, E123
        (r'ERR[-\s]?\d+', False),             # ERR-101
        (r'[Ww]\d{2,3}', False),              # W01, W02 (warning)
    ]
    for pattern, has_group in patterns:
        match = re.search(pattern, text)
        if match:
            code = match.group(1) if has_group else match.group(0)
            if code and len(code) >= 2:
                return code.upper()
    return None


@tool
def troubleshoot(error_description: str) -> str:
    """
    根据用户描述的故障现象或错误码，搜索知识库获取解决方案。
    支持自然语言描述故障和精确错误码查询。

    使用场景：
    - 用户报告扫地机器人出现异常（如不启动、噪音大、无法回充等）
    - 用户提供设备屏幕上的错误码
    - 需要诊断设备故障

    Args:
        error_description: 故障描述或错误码，例如"E04错误"、"机器人不启动了"、"充电失败"
    """
    if not error_description or not error_description.strip():
        return "请描述您遇到的故障现象或错误码，例如: 显示 E04 错误、无法开机等。"

    desc = error_description.strip()
    logger.info(f"故障排查查询: {desc[:100]}")

    # 提取错误码
    error_code = _extract_error_code(desc)

    # 构建增强查询
    if error_code:
        enhanced_query = f"错误码 {error_code} 故障 解决方案 {desc}"
    else:
        enhanced_query = f"故障排查 解决方法 {desc}"

    results = search_knowledge(enhanced_query)

    if not results:
        # 尝试更宽泛的搜索
        results = search_knowledge(f"故障 {desc}")

    if not results:
        return (
            f"## 🔧 故障排查结果\n\n"
            f"**故障描述**: {desc}\n"
            f"{'**检测到错误码**: ' + error_code if error_code else ''}\n\n"
            f"⚠️ 知识库中暂未找到与您描述匹配的故障解决方案。\n\n"
            f"建议：\n"
            f"1. 请先上传产品故障手册（PDF/TXT）到知识库\n"
            f"2. 尝试用更具体的关键词描述故障\n"
            f"3. 重启设备并观察是否恢复正常\n"
            f"4. 如问题持续，建议联系官方售后服务"
        )

    parts = [
        f"## 🔧 故障排查结果\n\n"
        f"**故障描述**: {desc}"
    ]
    if error_code:
        parts.append(f"**检测到错误码**: {error_code}")
    parts.append("")

    for i, item in enumerate(results, 1):
        source = item["metadata"].get("filename", "未知文档")
        # Chroma 返回的是距离值，转为 0-100 匹配度（越低越相似 → 越高越匹配）
        score = round(100 / (1 + item["score"]), 1)
        parts.append(f"### 方案 {i} (匹配度: {score}%)")
        parts.append(f"📄 来源: {source}")
        parts.append(item["content"])
        parts.append("")

    parts.append("---")
    parts.append("> ⚠️ 以上方案来源于知识库，如故障仍无法解决，请联系官方售后支持。")

    return "\n".join(parts)
