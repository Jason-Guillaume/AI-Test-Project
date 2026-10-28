"""将支持的知识文档解析为带章节、段落或页码定位的纯文本片段。"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree


@dataclass(frozen=True)
class ParsedChunk:
    """正文块及其原文位置。"""

    ordinal: int
    heading_path: str | None
    locator: str
    content: str


def parse_document(file_name: str, data: bytes) -> list[ParsedChunk]:
    """按扩展名解析 Markdown、TXT、DOCX、文本 PDF 与 JSON/YAML。"""
    suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if suffix in {"md", "markdown", "txt", "json", "yaml", "yml"}:
        text = data.decode("utf-8-sig", errors="strict")
        if suffix == "json":
            text = _format_api_spec(_format_json_if_valid(text))
        elif suffix in {"yaml", "yml"}:
            text = _format_api_spec(text)
        return _split_text(text)
    if suffix == "docx":
        return _split_text(_read_docx(data))
    if suffix == "pdf":
        return _read_pdf(data)
    raise ValueError("仅支持 Markdown、TXT、DOCX、文本型 PDF、JSON 和 YAML 文件")


def _format_json_if_valid(text: str) -> str:
    """可识别为 JSON 时格式化显示；普通文本 JSON 保留原文。"""
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        return text


def _format_api_spec(text: str) -> str:
    """接口规范走现有 OpenAPI / Swagger / Postman 安全解析器。"""
    try:
        from app.features.api_catalog.parsers.document_parser import parse_api_document

        apis = parse_api_document(text, required=False)
    except (ValueError, TypeError):
        return text
    if not apis:
        return text
    return "\n\n".join(
        f"接口：{api.method} {api.path}\n名称：{api.name}\n说明：{api.description or ''}\n"
        f"请求参数：{json.dumps([item.model_dump(mode='json') for item in api.parameters], ensure_ascii=False)}\n"
        f"请求体：{json.dumps(api.body.model_dump(mode='json'), ensure_ascii=False)}\n"
        f"响应：{json.dumps([item.model_dump(mode='json') for item in api.responses], ensure_ascii=False)}"
        for api in apis
    )


def _read_docx(data: bytes) -> str:
    """从 DOCX 的主文档 XML 读取段落与表格文本，不解压到文件系统。"""
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000:
                raise ValueError("DOCX 文件包含过多压缩条目")
            document = archive.getinfo("word/document.xml")
            if document.file_size > 16 * 1024 * 1024:
                raise ValueError("DOCX 正文超过解析大小上限")
            xml_data = archive.read(document)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError("DOCX 文件结构无效") from exc
    root = ElementTree.fromstring(xml_data)
    output: list[str] = []
    body = root.find("w:body", namespace)
    if body is None:
        return ""
    for node in body:
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "p":
            value = "".join(item.text or "" for item in node.findall(".//w:t", namespace)).strip()
            style = node.find("w:pPr/w:pStyle", namespace)
            style_name = style.attrib.get(f"{{{namespace['w']}}}val", "") if style is not None else ""
            if value:
                level = int(style_name[-1]) if style_name.lower().startswith("heading") and style_name[-1:].isdigit() else 0
                output.append(f"{'#' * min(level, 6)} {value}" if level else value)
        elif tag == "tbl":
            for row in node.findall(".//w:tr", namespace):
                cells = [" ".join("".join(item.text or "" for item in p.findall(".//w:t", namespace)).split())
                         for p in row.findall("w:tc/w:p", namespace)]
                if any(cells):
                    output.append(" | ".join(cells))
    return "\n\n".join(output)


def _read_pdf(data: bytes) -> list[ParsedChunk]:
    """按页读取文本型 PDF；空文本扫描件明确失败，不当作解析成功。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 由 requirements 固定提供
        raise ValueError("PDF 解析组件未安装，请联系管理员完成依赖部署") from exc
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        pages = [(index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages)]
    except Exception as exc:  # noqa: BLE001 — PDF 解析器错误不向用户暴露内部堆栈。
        raise ValueError("PDF 文件损坏或无法读取") from exc
    chunks: list[ParsedChunk] = []
    for page_number, page_text in pages:
        chunks.extend(_split_text(page_text, start_ordinal=len(chunks) + 1, locator_prefix=f"第 {page_number} 页"))
    if not any(chunk.content.strip() for chunk in chunks):
        raise ValueError("PDF 未提取到文本，扫描件或图片型 PDF 暂不支持")
    return chunks


def _split_text(text: str, *, start_ordinal: int = 1, locator_prefix: str = "段落") -> list[ParsedChunk]:
    """保留 Markdown 标题，并将超长段落按字符边界拆分。"""
    heading_stack: list[tuple[int, str]] = []
    sections: list[tuple[str | None, str]] = []
    current: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line.strip())
        if match:
            if current:
                sections.extend((" / ".join(title for _, title in heading_stack) or None, part)
                                for part in _paragraphs("\n".join(current)))
                current = []
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_stack = [(depth, value) for depth, value in heading_stack if depth < level]
            heading_stack.append((level, title))
        elif line.strip():
            current.append(line.strip())
        elif current:
            sections.extend((" / ".join(title for _, title in heading_stack) or None, part)
                            for part in _paragraphs("\n".join(current)))
            current = []
    if current:
        sections.extend((" / ".join(title for _, title in heading_stack) or None, part)
                        for part in _paragraphs("\n".join(current)))
    chunks: list[ParsedChunk] = []
    for heading, paragraph in sections:
        for part in _bounded_parts(paragraph):
            chunks.append(ParsedChunk(len(chunks) + start_ordinal, heading, f"{locator_prefix} {len(chunks) + start_ordinal}", part))
    if not chunks:
        raise ValueError("文档未提取到可检索文本")
    return chunks


def _paragraphs(text: str) -> list[str]:
    """将段落合并为可定位的纯文本单元。"""
    return [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]


def _bounded_parts(text: str, limit: int = 2400) -> list[str]:
    """按句子边界切分超长段落，保留完整文本。"""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = max(remaining.rfind(mark, 0, limit) for mark in ("。", "！", "？", ". ", "\n"))
        if split_at < limit // 2:
            split_at = limit
        else:
            split_at += 1
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return parts
