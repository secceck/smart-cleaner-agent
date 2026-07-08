"""
文档加载与分片处理模块
支持 PDF、TXT 格式，单文件最大 50MB
使用 RecursiveCharacterTextSplitter 递归分片策略
"""
import uuid
from pathlib import Path
from typing import Optional

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..common.config import get_settings
from ..common.logger import get_logger
from .vectorstore import get_vectorstore

logger = get_logger(__name__)

# 允许的文件类型
ALLOWED_EXTENSIONS = {".pdf", ".txt"}


def validate_file(filename: str, file_size: int) -> None:
    """
    文件校验：检查扩展名和大小

    Args:
        filename: 原始文件名
        file_size: 文件大小（字节）

    Raises:
        ValueError: 文件类型不支持或文件过大
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"不支持的文件类型: {ext}。仅支持 PDF 和 TXT 格式。"
        )

    settings = get_settings()
    max_size = settings.max_upload_size_bytes
    if file_size > max_size:
        raise ValueError(
            f"文件过大: {file_size / 1024 / 1024:.1f}MB，"
            f"最大允许 {settings.max_upload_size_mb}MB。"
        )


def load_document(file_path: str, original_filename: str) -> list[Document]:
    """
    加载文档内容

    Args:
        file_path: 文件本地路径
        original_filename: 原始文件名（用于识别扩展名）

    Returns:
        Document 对象列表
    """
    ext = Path(original_filename).suffix.lower()

    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
    else:
        loader = TextLoader(file_path, encoding="utf-8")

    documents = loader.load()
    logger.info(f"加载文档 {original_filename}，共 {len(documents)} 页/段")

    # 丰富元数据
    for doc in documents:
        doc.metadata["filename"] = original_filename
        doc.metadata["source"] = file_path

    return documents


def split_documents(
    documents: list[Document],
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> list[Document]:
    """
    递归分片文档
    优先保留完整段落语义，超长段落自动拆分句子

    Args:
        documents: 待分片的文档列表
        chunk_size: 分片大小（默认从配置读取）
        chunk_overlap: 分片重叠大小（默认从配置读取）

    Returns:
        分片后的 Document 列表
    """
    settings = get_settings()
    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap

    # 中文友好的分隔符优先级
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", " ", ""],
        length_function=len,
        is_separator_regex=False,
    )

    chunks = splitter.split_documents(documents)

    # 添加分片索引
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = i

    logger.info(
        f"文档分片完成: {len(documents)} 个文档 -> {len(chunks)} 个分片 "
        f"(chunk_size={chunk_size}, overlap={chunk_overlap})"
    )
    return chunks


def process_document(file_path: str, original_filename: str) -> int:
    """
    完整的文档处理流程：加载 -> 分片 -> 向量化存储

    Args:
        file_path: 临时文件路径
        original_filename: 原始文件名

    Returns:
        创建的分片数量

    Raises:
        ValueError: 文件校验失败
    """
    # 1. 校验
    file_size = Path(file_path).stat().st_size
    validate_file(original_filename, file_size)

    # 2. 加载
    documents = load_document(file_path, original_filename)
    if not documents:
        raise ValueError(f"文档 {original_filename} 内容为空，无法处理。")

    # 3. 分片
    chunks = split_documents(documents)

    if not chunks:
        raise ValueError(f"文档 {original_filename} 分片后无有效内容。")

    # 4. 存储到 Chroma
    vectorstore = get_vectorstore()
    vectorstore.add_documents(chunks)

    logger.info(f"文档 {original_filename} 处理完成，共 {len(chunks)} 个分片已存入向量库")
    return len(chunks)


def save_uploaded_file(file_content: bytes, original_filename: str) -> Path:
    """
    保存上传文件到本地知识库目录

    Args:
        file_content: 文件二进制内容
        original_filename: 原始文件名

    Returns:
        保存后的文件路径
    """
    settings = get_settings()
    knowledge_dir = settings.get_absolute_path("../data/knowledge")
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    # 使用 UUID 避免文件名冲突
    unique_name = f"{uuid.uuid4().hex}_{original_filename}"
    file_path = knowledge_dir / unique_name

    file_path.write_bytes(file_content)
    logger.info(f"文件已保存: {file_path}")
    return file_path


def delete_document(filename: str) -> bool:
    """
    从知识库删除文档（文件 + 向量数据）

    Args:
        filename: 原始文件名

    Returns:
        是否成功删除
    """
    settings = get_settings()

    # 删除原始文件
    knowledge_dir = settings.get_absolute_path("../data/knowledge")
    deleted_file = False
    for f in knowledge_dir.iterdir():
        if f.is_file() and f.name.endswith(f"_{filename}"):
            f.unlink()
            deleted_file = True
            logger.info(f"已删除文件: {f}")

    # 从 Chroma 中删除对应向量
    try:
        vectorstore = get_vectorstore()
        # Chroma 的 delete 通过 metadata 过滤
        collection = vectorstore._collection
        collection.delete(where={"filename": filename})
        logger.info(f"已从向量库删除文档: {filename}")
    except Exception as e:
        logger.error(f"从向量库删除文档失败: {e}")

    return deleted_file
