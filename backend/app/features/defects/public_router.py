"""免登录缺陷分享接口。

不使用平台 JWT。访问凭证来自 Authorization Bearer，对应 URL Fragment 中的 token。
这里的 404/403 文案只描述链接状态，不返回缺陷主键、堆栈或未授权字段。
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database.session import get_db
from app.core.http.errors import bad_request, not_found
from app.features.defects.schemas_share import PublicBatchResponse, PublicDefectResponse, PublicResolveRequest, PublicResolveResponse
from app.features.defects.services.public_rate_limit import enforce_public_share_limit
from app.features.defects.services.share_service import DefectShareService

router = APIRouter(prefix="/public/defect-shares", tags=["公开缺陷分享"])
SERVICE = DefectShareService()
PUBLIC_SHARE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
}


def apply_public_share_headers(path: str, response) -> None:
    """给公开分享 API 加上禁止缓存和禁止索引的响应头。"""
    if path.startswith("/api/v1/public/defect-shares"):
        for key, value in PUBLIC_SHARE_HEADERS.items():
            response.headers[key] = value


def _bearer_token(request: Request) -> str:
    """从 Authorization 读取分享凭证。缺失时与错误凭证使用同一文案。"""
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        raise not_found("分享链接无效或无权访问")
    token = header[7:].strip()
    if not token or len(token) > 200 or any(char.isspace() for char in token):
        raise not_found("分享链接无效或无权访问")
    return token


def _limit_body(request: Request) -> None:
    """拒绝明显过大的公开写请求。字段长度仍由契约再次限制。"""
    raw = request.headers.get("content-length")
    if raw and raw.isdigit() and int(raw) > 16384:
        raise bad_request("请求体过大")


def _guard(request: Request, bucket: str, action, *, share_id: str | None = None):
    """先限流，再把错误凭证计入失败桶。"""
    enforce_public_share_limit(request, bucket, share_id=share_id)
    try:
        return action()
    except HTTPException as exc:
        if exc.status_code == 404:
            enforce_public_share_limit(request, "failure", share_id=share_id)
        raise


@router.get("/{share_id}", response_model=PublicDefectResponse)
def view_public_defect(share_id: str, request: Request, db: Session = Depends(get_db)):
    """验证分享凭证并返回允许展示的缺陷详情。"""
    token = _bearer_token(request)

    def action():
        return SERVICE.view_public(db, share_id, token)

    return _guard(request, "view", action, share_id=share_id)


@router.get("/batches/{public_id}", response_model=PublicBatchResponse)
def view_public_batch(public_id: str, request: Request, db: Session = Depends(get_db)):
    token = _bearer_token(request)
    return _guard(request, "view", lambda: SERVICE.view_public_batch(db, public_id, token), share_id=public_id)


@router.get("/batches/{public_id}/items/{share_id}", response_model=PublicDefectResponse)
def view_public_batch_item(public_id: str, share_id: str, request: Request, db: Session = Depends(get_db)):
    token = _bearer_token(request)
    return _guard(request, "view", lambda: SERVICE.view_public_batch_item(db, public_id, token, share_id), share_id=public_id)


@router.post("/batches/{public_id}/items/{share_id}/views", status_code=204)
def record_public_batch_view(public_id: str, share_id: str, request: Request, db: Session = Depends(get_db)):
    token = _bearer_token(request)
    _guard(request, "view", lambda: SERVICE.record_batch_view(db, public_id, token, share_id), share_id=public_id)
    return None


@router.get("/batches/{public_id}/items/{share_id}/attachments/{attachment_id}")
def read_public_batch_attachment(public_id: str, share_id: str, attachment_id: int, request: Request, download: bool = Query(default=False), db: Session = Depends(get_db)):
    token = _bearer_token(request)

    def action():
        row, content_type, inline = SERVICE.public_batch_attachment(db, public_id, token, share_id, attachment_id)
        disposition = "attachment" if download or not inline else "inline"
        return Response(content=row.content, media_type=content_type, headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(row.filename, safe='')}",
            "Content-Length": str(row.size),
        })

    return _guard(request, "view", action, share_id=public_id)


@router.post("/batches/{public_id}/items/{share_id}/resolve", response_model=PublicResolveResponse)
def resolve_public_batch_item(public_id: str, share_id: str, body: PublicResolveRequest, request: Request, db: Session = Depends(get_db), _body_limit: None = Depends(_limit_body)):
    token = _bearer_token(request)
    return _guard(request, "resolve", lambda: SERVICE.resolve_public_batch_item(db, public_id, token, share_id, body), share_id=public_id)


@router.post("/{share_id}/views", status_code=204)
def record_public_view(share_id: str, request: Request, db: Session = Depends(get_db)):
    """记录访问次数。不改变缺陷状态。"""
    token = _bearer_token(request)

    def action():
        SERVICE.record_view(db, share_id, token)
        return None

    _guard(request, "view", action, share_id=share_id)
    return None


@router.get("/{share_id}/attachments/{attachment_id}")
def read_public_attachment(
    share_id: str,
    attachment_id: int,
    request: Request,
    download: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """每次读取都验证分享凭证、附件快照授权和缺陷归属。"""
    token = _bearer_token(request)

    def action():
        row, content_type, inline = SERVICE.public_attachment(db, share_id, token, attachment_id)
        disposition = "attachment" if download or not inline else "inline"
        return Response(
            content=row.content,
            media_type=content_type,
            headers={
                "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(row.filename, safe='')}",
                "Content-Length": str(row.size),
            },
        )

    return _guard(request, "view", action, share_id=share_id)


@router.post("/{share_id}/resolve", response_model=PublicResolveResponse)
def resolve_public_defect(
    share_id: str,
    body: PublicResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
    _body_limit: None = Depends(_limit_body),
):
    """提交开发修复结果，并复用缺陷状态服务回写为已修复。"""
    token = _bearer_token(request)

    def action():
        return SERVICE.resolve_public(db, share_id, token, body)

    return _guard(request, "resolve", action, share_id=share_id)
