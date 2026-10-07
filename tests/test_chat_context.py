"""上下文管理单元测试（Cycle 1，纯本地，无网络/无数据库）"""

import json

from rag.chat.context import (
    StoredMessage,
    Turn,
    build_context,
    estimate_message_tokens,
    estimate_tokens,
    filter_complete_turns,
    group_turns,
    message_to_api,
    turn_to_api_messages,
)


def make_turn(idx: int, question: str, answer: str, status: str = "completed") -> Turn:
    """构造一个标准轮次：user + assistant"""
    return Turn(
        turn_index=idx,
        messages=[
            StoredMessage(turn_index=idx, seq=idx * 2, role="user", content=question),
            StoredMessage(
                turn_index=idx, seq=idx * 2 + 1, role="assistant", content=answer, status=status
            ),
        ],
    )


def extract_user_contents(messages: list[dict]) -> list[str]:
    return [m["content"] for m in messages if m["role"] == "user"]


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens(None) == 0

    def test_english_roughly_quarter_length(self):
        text = "a" * 100
        assert estimate_tokens(text) == 25

    def test_cjk_one_token_per_char(self):
        text = "中" * 50
        assert estimate_tokens(text) == 50

    def test_mixed(self):
        # 4 个中文 + 8 个英文 → 4 + 2 = 6
        assert estimate_tokens("中文测试abcdabcd") == 6

    def test_monotonic(self):
        assert estimate_tokens("短文本") < estimate_tokens("短文本" * 100)

    def test_message_overhead(self):
        assert estimate_message_tokens({"role": "user", "content": ""}) == 4
        assert estimate_message_tokens({"role": "user", "content": "中文"}) == 6

    def test_tool_calls_counted(self):
        msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "retrieve_documents", "arguments": "{}"}}],
        }
        assert estimate_message_tokens(msg) > estimate_message_tokens({"role": "assistant", "content": None})


class TestGroupTurns:
    def test_groups_by_turn_index_and_sorts_by_seq(self):
        msgs = [
            StoredMessage(turn_index=1, seq=3, role="assistant", content="a1"),
            StoredMessage(turn_index=0, seq=1, role="user", content="q0"),
            StoredMessage(turn_index=1, seq=2, role="user", content="q1"),
            StoredMessage(turn_index=0, seq=0, role="user", content="q0"),
        ]
        turns = group_turns(msgs)
        assert [t.turn_index for t in turns] == [0, 1]
        assert [m.seq for m in turns[0].messages] == [0, 1]
        assert [m.seq for m in turns[1].messages] == [2, 3]

    def test_is_complete_requires_user_and_ok_assistant(self):
        assert make_turn(0, "q", "a").is_complete is True
        assert make_turn(0, "q", "a", status="failed").is_complete is False
        assert make_turn(0, "q", "a", status="cancelled").is_complete is False

    def test_user_only_turn_incomplete(self):
        turn = Turn(turn_index=0, messages=[StoredMessage(turn_index=0, seq=0, role="user", content="q")])
        assert turn.is_complete is False

    def test_filter_complete_turns(self):
        turns = [make_turn(0, "q0", "a0"), make_turn(1, "q1", "a1", status="failed"), make_turn(2, "q2", "a2")]
        assert [t.turn_index for t in filter_complete_turns(turns)] == [0, 2]


class TestMessageToApi:
    def test_user_message(self):
        msg = StoredMessage(turn_index=0, seq=0, role="user", content="你好")
        assert message_to_api(msg) == {"role": "user", "content": "你好"}

    def test_assistant_plain(self):
        msg = StoredMessage(turn_index=0, seq=1, role="assistant", content="回答")
        assert message_to_api(msg) == {"role": "assistant", "content": "回答"}

    def test_assistant_with_tool_calls(self):
        msg = StoredMessage(
            turn_index=0,
            seq=1,
            role="assistant",
            content="",
            tool_calls=[{"id": "call_1", "name": "retrieve_documents", "arguments": {"query": "向量数据库"}}],
        )
        api = message_to_api(msg)
        assert api["role"] == "assistant"
        assert api["content"] is None
        call = api["tool_calls"][0]
        assert call["id"] == "call_1"
        assert call["type"] == "function"
        assert call["function"]["name"] == "retrieve_documents"
        # arguments 必须是 JSON 字符串
        assert json.loads(call["function"]["arguments"]) == {"query": "向量数据库"}

    def test_tool_message(self):
        msg = StoredMessage(
            turn_index=0, seq=2, role="tool", content='{"results": []}',
            tool_call_id="call_1", tool_name="retrieve_documents",
        )
        api = message_to_api(msg)
        assert api == {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": '{"results": []}',
            "name": "retrieve_documents",
        }

    def test_unknown_role_ignored(self):
        assert message_to_api(StoredMessage(turn_index=0, seq=0, role="system", content="x")) is None

    def test_tool_call_roundtrip_preserves_order(self):
        turn = Turn(
            turn_index=0,
            messages=[
                StoredMessage(turn_index=0, seq=0, role="user", content="文档里说了什么"),
                StoredMessage(
                    turn_index=0, seq=1, role="assistant", content="",
                    tool_calls=[{"id": "c1", "name": "retrieve_documents", "arguments": {"query": "q"}}],
                ),
                StoredMessage(turn_index=0, seq=2, role="tool", content="结果", tool_call_id="c1", tool_name="retrieve_documents"),
                StoredMessage(turn_index=0, seq=3, role="assistant", content="最终回答"),
            ],
        )
        api = turn_to_api_messages(turn)
        assert [m["role"] for m in api] == ["user", "assistant", "tool", "assistant"]
        assert api[1]["tool_calls"][0]["id"] == "c1"
        assert api[2]["tool_call_id"] == "c1"
        assert api[3]["content"] == "最终回答"


class TestBuildContext:
    def test_no_history(self):
        messages, stats = build_context([], "当前问题", system_prompt="SYS")
        assert [m["role"] for m in messages] == ["system", "user"]
        assert messages[0]["content"] == "SYS"
        assert messages[-1]["content"] == "当前问题"
        assert stats.total_turns == 0
        assert stats.included_turns == 0
        assert stats.dropped_turns == 0
        assert stats.truncated_by_budget is False
        assert stats.estimated_tokens > 0

    def test_chronological_order(self):
        turns = [make_turn(i, f"q{i}", f"a{i}") for i in range(3)]
        messages, stats = build_context(turns, "q3", system_prompt="SYS")
        assert stats.included_turns == 3
        assert extract_user_contents(messages) == ["q0", "q1", "q2", "q3"]

    def test_max_turns_keeps_most_recent(self):
        turns = [make_turn(i, f"q{i}", f"a{i}") for i in range(15)]
        messages, stats = build_context(turns, "q15", max_turns=10, token_budget=100000, system_prompt="SYS")
        assert stats.total_turns == 15
        assert stats.included_turns == 10
        assert stats.dropped_turns == 5
        assert extract_user_contents(messages) == [f"q{i}" for i in range(5, 15)] + ["q15"]

    def test_budget_drops_oldest_first(self):
        long_answer = "长" * 500  # 每轮 assistant ≈ 504 tokens
        turns = [make_turn(i, f"q{i}", long_answer) for i in range(4)]
        messages, stats = build_context(
            turns, "当前问题", max_turns=10, token_budget=1200, system_prompt="SYS"
        )
        # 预算只够最新的 2 轮
        assert stats.included_turns == 2
        assert stats.dropped_turns == 2
        assert stats.truncated_by_budget is True
        assert extract_user_contents(messages) == ["q2", "q3", "当前问题"]

    def test_current_message_always_preserved(self):
        huge = "字" * 5000
        turns = [make_turn(0, "q0", "a0")]
        messages, stats = build_context(turns, huge, max_turns=10, token_budget=100, system_prompt="SYS")
        assert messages[-1] == {"role": "user", "content": huge}
        assert stats.included_turns == 0
        assert stats.dropped_turns == 1

    def test_failed_turns_excluded(self):
        turns = [
            make_turn(0, "q0", "a0"),
            make_turn(1, "q1", "出错了", status="failed"),
            make_turn(2, "q2", "a2"),
        ]
        messages, stats = build_context(turns, "q3", system_prompt="SYS")
        assert stats.total_turns == 2  # 失败轮次不计入完整轮次
        assert extract_user_contents(messages) == ["q0", "q2", "q3"]
        assert "出错了" not in json.dumps(messages, ensure_ascii=False)

    def test_tool_messages_included_when_required(self):
        turn = Turn(
            turn_index=0,
            messages=[
                StoredMessage(turn_index=0, seq=0, role="user", content="文档里说了什么"),
                StoredMessage(
                    turn_index=0, seq=1, role="assistant", content="",
                    tool_calls=[{"id": "c1", "name": "retrieve_documents", "arguments": {"query": "文档"}}],
                ),
                StoredMessage(turn_index=0, seq=2, role="tool", content="检索结果", tool_call_id="c1", tool_name="retrieve_documents"),
                StoredMessage(turn_index=0, seq=3, role="assistant", content="根据文档……[1]"),
            ],
        )
        messages, stats = build_context([turn], "继续", system_prompt="SYS")
        roles = [m["role"] for m in messages]
        assert roles == ["system", "user", "assistant", "tool", "assistant", "user"]
        assert stats.included_turns == 1

    def test_default_settings_used(self):
        from rag.config import settings

        turns = [make_turn(i, f"q{i}", f"a{i}") for i in range(settings.CHAT_HISTORY_TURNS + 5)]
        messages, stats = build_context(turns, "now")
        assert stats.included_turns == settings.CHAT_HISTORY_TURNS
        assert messages[0]["role"] == "system"

    def test_estimated_tokens_reported(self):
        turns = [make_turn(0, "q0", "a0")]
        messages, stats = build_context(turns, "q1", system_prompt="SYS")
        manual = sum(estimate_message_tokens(m) for m in messages)
        assert stats.estimated_tokens == manual
