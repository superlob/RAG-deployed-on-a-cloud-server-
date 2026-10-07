"""文档上传与管理 API 路由"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from rag.auth.deps import get_current_user
from rag.auth.models import UserResponse
from rag.db import get_user_connection
from rag.documents.models import DocumentListResponse, DocumentResponse

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

# 允许的文件扩展名 -> 文件类型标识
ALLOWED_EXTENSIONS = {
    ".pdf": "pdf",
    ".doc": "doc",
    ".docx": "docx",
}

# 上传大小上限（字节）：50MB
MAX_UPLOAD_SIZE = 50 * 1024 * 1024


def _get_file_type(filename: str) -> str:
    """根据文件名后缀返回文件类型，不支持则抛出 400"""
    lower = filename.lower()
    for ext, ftype in ALLOWED_EXTENSIONS.items():
        if lower.endswith(ext):
            return ftype
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"不支持的文件类型，仅支持 {', '.join(ALLOWED_EXTENSIONS.keys())}",
    )


def _record_to_document(row) -> DocumentResponse:
    """将 asyncpg Record 转换为 DocumentResponse（不读取 file_data）"""
    return DocumentResponse(
        id=row["id"],
        original_filename=row["original_filename"],
        file_type=row["file_type"],
        file_size=row["file_size"],
        created_at=row["created_at"],
        processing_status=row.get("processing_status", "not_processed"),
        status_error=row.get("status_error"),
        chunk_count=row.get("chunk_count", 0),
        embedded_at=row.get("embedded_at"),
    )


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    user: UserResponse = Depends(get_current_user),
):
    """上传文档（PDF / Word），文件内容以 BYTEA 存入 PostgreSQL"""
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未提供文件名")

    file_type = _get_file_type(file.filename)

    # 读取文件内容
    file_data = await file.read()
    file_size = len(file_data)

    if file_size == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件为空")
    if file_size > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件过大，最大允许 {MAX_UPLOAD_SIZE // (1024 * 1024)}MB",
        )

    # RLS 策略的 WITH CHECK 会自动校验 user_id 与 current_user_id 一致
    async with get_user_connection(str(user.id)) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO documents (user_id, original_filename, file_type, file_size, file_data)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, original_filename, file_type, file_size, created_at
            """,
            user.id,
            file.filename,
            file_type,
            file_size,
            file_data,
        )

    return _record_to_document(row)


@router.get("", response_model=DocumentListResponse)
@router.get("/", response_model=DocumentListResponse)
async def list_documents(user: UserResponse = Depends(get_current_user)):
    """列出当前用户的所有文档（仅元数据）"""
    async with get_user_connection(str(user.id)) as conn:
        rows = await conn.fetch(
            """
            SELECT id, original_filename, file_type, file_size, created_at,
                   processing_status, status_error, chunk_count, embedded_at
            FROM documents
            ORDER BY created_at DESC
            """
        )

    documents = [_record_to_document(row) for row in rows]
    return DocumentListResponse(documents=documents, total=len(documents))


@router.get("/{document_id}")
async def download_document(
    document_id: UUID,
    user: UserResponse = Depends(get_current_user),
):
    """下载文档的原始文件内容"""
    async with get_user_connection(str(user.id)) as conn:
        row = await conn.fetchrow(
            "SELECT original_filename, file_type, file_data FROM documents WHERE id = $1",
            document_id,
        )

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    filename = row["original_filename"]
    file_type = row["file_type"]
    file_data = bytes(row["file_data"])

    # 根据 file_type 推断 Content-Type
    content_type = {
        "pdf": "application/pdf",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(file_type, "application/octet-stream")

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(len(file_data)),
    }

    def iter_data():
        yield file_data

    return StreamingResponse(iter_data(), media_type=content_type, headers=headers)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    user: UserResponse = Depends(get_current_user),
):
    """删除文档（RLS 保证只能删除自己的）"""
    async with get_user_connection(str(user.id)) as conn:
        result = await conn.execute(
            "DELETE FROM documents WHERE id = $1",
            document_id,
        )

    # asyncpg execute 返回 "DELETE N" 形式，N 为受影响行数
    if result.split()[-1] != "1":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
