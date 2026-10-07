"""文档分块：Document-aware 匹配分组 + Recursive/Sentence 递归切分"""

from dataclasses import dataclass, field

from rag.processing.extraction import ExtractedBlock


@dataclass
class Chunk:
    """文档分块结果"""

    content: str
    chunk_index: int
    section_title: str | None = None
    page_number: int | None = None
    metadata: dict = field(default_factory=dict)


# 递归切分使用的分隔符列表（从粗到细）
_RECURSIVE_SEPARATORS = [
    "\n\n",
    "\n",
    "。",
    "！",
    "？",
    ". ",
    "! ",
    "? ",
    "; ",
    "，",
    ",",
    " ",
    "",
]


def _split_text(text: str, separators: list[str]) -> list[str]:
    """递归按分隔符切分文本

    在 separator 位置切分后保留分隔符附在前一段末尾（对中文句号/感叹号合理；
    英文句尾的 . ! ? 也附在前一段后面，保持语义完整）。
    """
    if not text:
        return []

    sep = separators[0] if separators else ""
    if sep == "":
        # 最终兜底：按字符切
        return list(text)

    splits = text.split(sep)
    # 除最后一段外，每段末尾补回分隔符
    result: list[str] = []
    for i, s in enumerate(splits):
        s = s.strip()
        if not s:
            continue
        if i < len(splits) - 1 and sep:
            s = s + sep
        result.append(s)

    return result


def _recursive_split(
    text: str,
    separators: list[str],
    chunk_size: int,
) -> list[str]:
    """递归切分：当片段长度不满足约束时，用下一级分隔符继续切分"""

    if not text:
        return []

    sep = separators[0] if separators else ""
    remaining_seps = separators[1:] if len(separators) > 1 else []

    if sep == "" or not remaining_seps:
        # 没有更细的分隔符了，直接按 chunk_size 硬切
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    fragments = _split_text(text, [sep])

    result: list[str] = []
    for frag in fragments:
        if len(frag) <= chunk_size:
            result.append(frag)
        else:
            result.extend(_recursive_split(frag, remaining_seps, chunk_size))

    return result


def _merge_splits_with_overlap(
    splits: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """将切分后的片段按 chunk_size 合并，相邻 chunk 之间保留 chunk_overlap 字符重叠"""

    if not splits:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for split in splits:
        split_len = len(split)

        if current_len + split_len <= chunk_size:
            current.append(split)
            current_len += split_len
        else:
            # 保存当前 chunk
            if current:
                chunks.append("".join(current))

            # 处理当前 split 单独超过 chunk_size 的情况
            if split_len > chunk_size:
                # 超长片段：强行按 chunk_size 取（无法在这级分割 — 应该是 _recursive_split 后不应出现）
                chunks.append(split[:chunk_size])
                current = [split[max(0, split_len - chunk_overlap) :]]
                current_len = len(current[0])
            else:
                # 新 chunk 从当前 split 开始
                current = [split]
                current_len = split_len

    if current:
        chunks.append("".join(current))

    # 应用 overlap：从第 2 个 chunk 开始，在前面补上前一 chunk 末尾的 overlap 文本
    if chunk_overlap > 0 and len(chunks) > 1:
        overlapped: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            # 取 prev 末尾的 overlap 长度文本，尽量在第一个分隔符处截断
            if len(prev) > chunk_overlap:
                overlap_text = prev[-chunk_overlap:]
            else:
                overlap_text = prev
            overlapped.append(overlap_text + chunks[i])
        chunks = overlapped

    return chunks


def _build_sections(blocks: list[ExtractedBlock]) -> list[dict]:
    """将 ExtractedBlock 列表按标题边界构建 section 结构

    每个 section = {title, level, pages, text}
    """
    sections: list[dict] = []
    current_title: str | None = None
    current_level: int | None = None
    current_pages: list[int] = []
    current_lines: list[str] = []

    def _flush():
        nonlocal current_title, current_level, current_pages, current_lines
        if current_lines:
            text = "".join(current_lines)
            sections.append(
                {
                    "title": current_title,
                    "level": current_level,
                    "page_numbers": list(set(current_pages)),
                    "text": text,
                }
            )
        current_lines = []
        current_pages = []

    for block in blocks:
        if block.heading_level is not None:
            # 遇到新标题：先保存前一个 section，再开新 section
            _flush()
            current_title = block.text
            current_level = block.heading_level
        else:
            current_lines.append(block.text)
            if block.page_number is not None:
                current_pages.append(block.page_number)

    _flush()
    return sections


def build_chunks(
    blocks: list[ExtractedBlock],
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> list[Chunk]:
    """主入口：将提取的文本块构建为分块列表

    1. 按 ExtractedBlock 的 heading_level 边界构建 section
    2. 对每个 section 的完整文本递归切分 + overlap 合并
    3. 输出有序 Chunk 列表，保留标题和页码元数据
    """

    sections = _build_sections(blocks)
    chunks: list[Chunk] = []
    chunk_index = 0

    for section in sections:
        section_text = section["text"]
        if not section_text.strip():
            continue

        # 递归切分
        splits = _recursive_split(
            section_text,
            separators=_RECURSIVE_SEPARATORS,
            chunk_size=chunk_size,
        )

        # overlap 合并
        merged = _merge_splits_with_overlap(splits, chunk_size, chunk_overlap)

        page = (
            min(section["page_numbers"])
            if section["page_numbers"]
            else None
        )

        for text in merged:
            chunks.append(
                Chunk(
                    content=text.strip(),
                    chunk_index=chunk_index,
                    section_title=section["title"],
                    page_number=page,
                    metadata={
                        "section_level": section["level"],
                        "section_pages": section["page_numbers"],
                    },
                )
            )
            chunk_index += 1

    return chunks