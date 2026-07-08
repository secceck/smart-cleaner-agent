"""
知识库管理 API
提供文档上传（PDF/TXT）和相似度检索接口
"""
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from ...common.logger import get_logger
from ...models.schemas import (
    ErrorResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeUploadItem,
    KnowledgeUploadResponse,
)
from ...rag.loader import ALLOWED_EXTENSIONS, process_document, save_uploaded_file
from ...rag.retriever import search_knowledge

logger = get_logger(__name__)

router = APIRouter(tags=["knowledge"])


# ============================================================
# 知识库上传
# ============================================================

@router.post(
    "/knowledge/upload",
    summary="上传知识库文档",
    response_model=KnowledgeUploadResponse,
    responses={
        200: {"description": "处理完成，返回每个文件的结果"},
        400: {"model": ErrorResponse, "description": "参数异常"},
        413: {"model": ErrorResponse, "description": "文件过大"},
    },
)
async def upload_knowledge(
    request: Request,
    files: list[UploadFile] = File(..., description="PDF或TXT文档，支持批量上传"),
):
    """
    上传知识库文档（支持批量）
    - 仅支持 PDF、TXT 格式
    - 单文件最大 50MB
    - 自动完成分片、向量化、存储
    """
    results: list[KnowledgeUploadItem] = []

    for file in files:
        item = KnowledgeUploadItem(filename=file.filename or "unknown")

        if not file.filename:
            item.status = "error"
            item.message = "文件名为空"
            results.append(item)
            continue

        # 校验扩展名
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            item.status = "error"
            item.message = f"不支持的文件类型: {ext}，仅支持 PDF、TXT"
            results.append(item)
            continue

        # 读取文件内容
        try:
            content = await file.read()
        except Exception as e:
            item.status = "error"
            item.message = f"读取文件失败: {e}"
            results.append(item)
            continue

        if not content:
            item.status = "error"
            item.message = "文件内容为空"
            results.append(item)
            continue

        # 校验大小
        max_size = 50 * 1024 * 1024  # 50MB
        if len(content) > max_size:
            item.status = "error"
            item.message = f"文件过大: {len(content) / 1024 / 1024:.1f}MB，最大 50MB"
            results.append(item)
            continue

        # 保存并处理文档
        try:
            # 保存原始文件
            file_path = save_uploaded_file(content, file.filename)

            # 处理文档（加载→分片→向量化）
            chunks_count = process_document(str(file_path), file.filename)

            item.chunks_count = chunks_count
            item.status = "success"
            item.message = f"文档处理完成，共生成 {chunks_count} 个知识片段"
            logger.info(f"文档上传成功: {file.filename} → {chunks_count} chunks")

        except ValueError as e:
            item.status = "error"
            item.message = str(e)
            logger.warning(f"文档处理失败(ValueError): {file.filename}: {e}")

        except Exception as e:
            item.status = "error"
            item.message = f"文档处理异常: {type(e).__name__}"
            logger.error(f"文档处理失败: {file.filename}: {type(e).__name__}: {e}")

        results.append(item)

    return KnowledgeUploadResponse(files=results)


# ============================================================
# 知识库检索
# ============================================================

@router.post(
    "/knowledge/search",
    summary="知识库相似度检索",
    response_model=KnowledgeSearchResponse,
    responses={
        200: {"description": "检索完成"},
        400: {"model": ErrorResponse, "description": "参数异常"},
    },
)
async def search_knowledge_api(body: KnowledgeSearchRequest):
    """
    知识库相似度检索
    - 基于查询文本在 Chroma 向量库中进行 Top-K 检索
    - 返回匹配的知识库片段及其相似度分数
    """
    logger.info(f"知识库检索请求: query={body.query[:50]}..., top_k={body.top_k}")

    try:
        results = search_knowledge(body.query, top_k=body.top_k)
    except Exception as e:
        logger.error(f"知识库检索异常: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"知识库检索失败: {e}")

    return KnowledgeSearchResponse(
        results=results,
        query=body.query,
        total=len(results),
    )
