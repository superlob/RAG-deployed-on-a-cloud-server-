"""分块算法单元测试"""

from rag.processing.chunking import (
    _recursive_split,
    _merge_splits_with_overlap,
    _build_sections,
    build_chunks,
)
from rag.processing.extraction import ExtractedBlock


class TestRecursiveSplit:
    """递归切分"""

    def test_small_text_no_split(self):
        result = _recursive_split("短文本", ["\n", ""], 100)
        assert result == ["短文本"]

    def test_split_on_newline(self):
        text = "第一行\n第二行\n第三行"
        result = _recursive_split(text, ["\n", ""], 10)
        assert result == ["第一行\n", "第二行\n", "第三行"]

    def test_split_on_sentence_boundary(self):
        text = "这是第一句话。这是第二句话。这是第三句话。"
        result = _recursive_split(text, ["\n\n", "\n", "。", ""], 9)
        # 每句话都应完整保留（带句号）
        for r in result:
            assert r.endswith("。"), f"片段 {r!r} 不以句号结尾"
            assert len(r) <= 9 + len("。"), f"片段 {r!r} 过长"

    def test_no_separator_match_falls_back(self):
        """无分隔符匹配时按字符硬切"""
        text = "ABCDEFGHIJ"
        result = _recursive_split(text, ["\n\n", ""], 3)
        assert "".join(result) == text

    def test_empty_text(self):
        result = _recursive_split("", ["\n", ""], 100)
        assert result == []


class TestMergeSplits:
    """overlap 合并"""

    def test_single_split(self):
        result = _merge_splits_with_overlap(["短文本"], 100, 20)
        assert result == ["短文本"]

    def test_merge_within_size(self):
        result = _merge_splits_with_overlap(
            ["a", "b", "c"], chunk_size=100, chunk_overlap=10
        )
        assert result == ["abc"]

    def test_merge_exceeding_size(self):
        result = _merge_splits_with_overlap(
            ["AAA", "BBB", "CCC"], chunk_size=6, chunk_overlap=0
        )
        # AAA + BBB = 6, CCC 单独
        assert result == ["AAABBB", "CCC"]

    def test_overlap_present(self):
        """overlap 文本应在相邻 chunk 间出现"""
        result = _merge_splits_with_overlap(
            ["AAA ", "BBB ", "CCC "], chunk_size=8, chunk_overlap=3
        )
        # chunk1: "AAA BBB " (8 chars), chunk2: 保留 tail 3 chars from chunk1
        assert len(result) >= 2
        # 第二块应以前一块的末尾开始
        prev_tail = result[0][-3:]
        assert result[1].startswith(prev_tail), (
            f"chunk2 {result[1]!r} should start with {prev_tail!r}"
        )


class TestBuildSections:
    """section 构建"""

    def test_heading_splits_sections(self):
        blocks = [
            ExtractedBlock(text="第一章", heading_level=1),
            ExtractedBlock(text="正文内容一。"),
            ExtractedBlock(text="第二章", heading_level=1),
            ExtractedBlock(text="正文内容二。"),
        ]
        sections = _build_sections(blocks)
        assert len(sections) == 2
        assert sections[0]["title"] == "第一章"
        assert sections[1]["title"] == "第二章"

    def test_no_headings_single_section(self):
        blocks = [
            ExtractedBlock(text="段落一"),
            ExtractedBlock(text="段落二"),
        ]
        sections = _build_sections(blocks)
        assert len(sections) == 1
        assert sections[0]["title"] is None


class TestBuildChunks:
    """端到端分块"""

    def test_basic_chunking(self):
        blocks = [
            ExtractedBlock(text="简短文本。"),
            ExtractedBlock(text="继续文本。"),
        ]
        chunks = build_chunks(blocks, chunk_size=100, chunk_overlap=0)
        assert len(chunks) >= 1
        # 所有 chunk 有递增索引
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_chunk_size_respected(self):
        """验证每个 chunk 长度不超过 chunk_size"""
        import string

        # 生成较长文本
        text = "。".join(string.ascii_lowercase[i : i + 20] for i in range(0, 200, 20)) + "。"
        blocks = [ExtractedBlock(text=text)]
        chunks = build_chunks(blocks, chunk_size=100, chunk_overlap=0)

        for c in chunks:
            assert len(c.content) <= 100, (
                f"chunk_index={c.chunk_index} length={len(c.content)} > 100"
            )

    def test_chunk_overlap_present(self):
        """验证 overlap 在相邻 chunk 中生效"""
        text = (
            "这是测试文本一。这是测试文本二。这是测试文本三。"
            "这是测试文本四。这是测试文本五。这是测试文本六。"
        )
        blocks = [ExtractedBlock(text=text)]
        chunks = build_chunks(blocks, chunk_size=30, chunk_overlap=10)

        if len(chunks) >= 2:
            tail = chunks[0].content[-10:]
            head = chunks[1].content[:10]
            # overlap: chunk2 前部应和 chunk1 后部有共同子串
            overlap_chars = set(tail) & set(head)
            assert len(overlap_chars) > 0, "重叠区域应共享部分字符"

    def test_section_title_preserved(self):
        blocks = [
            ExtractedBlock(text="标题", heading_level=1),
            ExtractedBlock(text="正文内容就在标题后面。"),
        ]
        chunks = build_chunks(blocks, chunk_size=100, chunk_overlap=0)
        for c in chunks:
            assert c.section_title == "标题"

    def test_page_number_preserved(self):
        blocks = [
            ExtractedBlock(text="首页内容。", page_number=3),
            ExtractedBlock(text="同一页继续。", page_number=3),
        ]
        chunks = build_chunks(blocks, chunk_size=100, chunk_overlap=0)
        for c in chunks:
            assert c.page_number == 3

    def test_empty_blocks(self):
        chunks = build_chunks([], chunk_size=100, chunk_overlap=10)
        assert chunks == []