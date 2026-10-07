"""文档文本提取：PDF（pypdf + 标题检测）和 DOCX（python-docx）"""

from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO


@dataclass
class ExtractedBlock:
    """从文档中提取的文本块"""

    text: str
    page_number: int | None = None
    heading_level: int | None = None  # 1-6 或 None（正文）


class ProcessingError(Exception):
    """文档处理异常"""

    def __init__(self, message: str):
        super().__init__(message)


# ---------- PDF ----------


def _font_size_heuristic(texts: list[str], font_sizes: list[float]) -> list[ExtractedBlock]:
    """基于字号启发式检测标题：

    - 统计全文中出现最频繁的字号，定为「正文字号」
    - 字号 >= 正文字号 × 1.3 且文本长度 ≤ 80 字符的，判定为标题
    - 逐级赋予 heading_level（相对差值越大级别越高）
    """

    if not texts:
        return []

    # 正文字号 = 出现次数最多的字号
    size_counter = Counter(font_sizes)
    body_size = size_counter.most_common(1)[0][0]

    # 同样字号的文本收集起来做标题判断
    size_texts: dict[float, list[str]] = {}
    for text, fs in zip(texts, font_sizes):
        size_texts.setdefault(fs, []).append(text)

    # 找出所有候选标题字号（>= body * 1.3）并从大到小排序
    heading_sizes = sorted(
        [fs for fs in size_texts if fs >= body_size * 1.3],
        reverse=True,
    )

    # 映射字号 → heading_level
    size_to_level: dict[float, int] = {}
    for i, hs in enumerate(heading_sizes):
        # 最多 6 级标题，只有位于 title 位置的书签文本赋予 heading_level
        level = min(i + 1, 6)
        # 仅当该字号下的所有文本都足够短时才标记为标题
        candidates = size_texts[hs]
        if all(len(t) <= 80 for t in candidates):
            size_to_level[hs] = level

    blocks: list[ExtractedBlock] = []
    for text, fs in zip(texts, font_sizes):
        level = size_to_level.get(fs)
        blocks.append(ExtractedBlock(text=text, heading_level=level))

    return blocks


class _PdfPageAccumulator:
    """pypdf visitor：按页收集文本行"""

    def __init__(self):
        self._page_lines: dict[int, list[str]] = {}
        self._page_font_sizes: dict[int, list[float]] = {}

    def add_line(self, page_number: int, text: str, font_size: float):
        self._page_lines.setdefault(page_number, []).append(text)
        self._page_font_sizes.setdefault(page_number, []).append(font_size)

    def to_blocks(self) -> list[ExtractedBlock]:
        """按页逐行生成 ExtractedBlock，每行内做标题检测"""
        all_blocks: list[ExtractedBlock] = []
        for pg in sorted(self._page_lines):
            texts = self._page_lines[pg]
            sizes = self._page_font_sizes[pg]
            page_blocks = _font_size_heuristic(texts, sizes)
            for b in page_blocks:
                b.page_number = pg
            all_blocks.extend(page_blocks)
        return all_blocks


def _extract_pdf_text(file_data: bytes) -> list[ExtractedBlock]:
    """使用 pypdf 提取 PDF 文本，按行收集并做标题检测"""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(file_data))
    acc = _PdfPageAccumulator()

    for page_index, page in enumerate(reader.pages, start=1):
        # 使用 visitor 逐段提取文本及字号
        def visitor_text(text, cm, tm, font_dict, font_size):
            # 跳过空白行
            stripped = text.strip()
            if stripped:
                acc.add_line(page_index, stripped, font_size or 8.0)

        page.extract_text(visitor_text=visitor_text)

    return acc.to_blocks()


# ---------- DOCX ----------


def _extract_docx_text(file_data: bytes) -> list[ExtractedBlock]:
    """使用 python-docx 提取 DOCX 文本，保留标题级别和表格内容"""
    from docx import Document
    from docx.oxml.ns import qn

    doc = Document(BytesIO(file_data))
    blocks: list[ExtractedBlock] = []

    # 遍历 body 子元素以保持段落和表格的出现顺序
    body = doc.element.body
    for child in body:
        tag = child.tag.split("}")[-1]  # 去除命名空间前缀

        if tag == "p":
            # 段落
            para = _paragraph_from_element(doc, child)
            text = para.text.strip()
            if not text:
                continue

            # 检测标题样式
            style_name = para.style.name if para.style else ""
            heading_level = None
            if style_name and style_name.startswith("Heading"):
                try:
                    heading_level = int(style_name.split()[-1])
                except ValueError:
                    heading_level = 1

            blocks.append(ExtractedBlock(text=text, heading_level=heading_level))

        elif tag == "tbl":
            # 表格：逐行拼接单元格文本
            rows = child.findall(qn("w:tr"))
            for row_el in rows:
                cells = row_el.findall(qn("w:tc"))
                row_texts: list[str] = []
                for cell_el in cells:
                    # 提取单元格内所有段落文本
                    cell_paras = cell_el.findall(qn("w:p"))
                    cell_text = " ".join(
                        "".join(
                            t.text or ""
                            for t in p.findall(".//" + qn("w:t"))
                        )
                        for p in cell_paras
                    ).strip()
                    row_texts.append(cell_text)
                line = " | ".join(row_texts)
                if line.strip():
                    blocks.append(ExtractedBlock(text=line))

    return blocks


def _paragraph_from_element(doc, element):
    """从 oxml 元素获取对应的 Paragraph 对象"""
    from docx.text.paragraph import Paragraph

    return Paragraph(element, doc)


# ---------- 统一入口 ----------

SUPPORTED_TYPES = {"pdf", "docx", "doc"}


def extract_text(file_type: str, file_data: bytes) -> list[ExtractedBlock]:
    """统一提取入口，根据 file_type 分派提取器

    Args:
        file_type: 'pdf' / 'docx' / 'doc'
        file_data: 文件二进制内容

    Returns:
        提取出的文本块列表（按文档出现顺序）
    """
    if file_type == "pdf":
        return _extract_pdf_text(file_data)
    elif file_type == "docx":
        return _extract_docx_text(file_data)
    elif file_type == "doc":
        raise ProcessingError("暂不支持 .doc 格式，请转换为 .docx 后上传")
    else:
        raise ProcessingError(f"不支持的文件类型: {file_type}")