"""短篇剧情大纲节点解析测试。

验证从发散 Agent 输出的构思文本中解析节点列表的逻辑。
"""
import json
import pytest
from app.routes.short_story.generate import (
    parse_outline_nodes, load_outline_nodes,
    _parse_expander_output, _format_concept,
)
from app import create_app, db


class TestParseOutlineNodes:
    """测试 parse_outline_nodes。"""

    def test_parse_valid_nodes(self):
        """正常解析多个节点。"""
        concept = """【核心概念】测试。

【剧情大纲】
节点1（第一幕·开端，约1200字）：执法堂当众控诉 —— 师妹当众指控师兄偷丹
节点2（第一幕·开端，约1000字）：师兄暗中针对 —— 抢灵草少分战利品
节点3（第二幕·发展，约1500字）：魔修朋友之死 —— 恨意达到顶点
"""
        nodes = parse_outline_nodes(concept, 10000)
        assert len(nodes) == 3
        assert nodes[0]["id"] == 1
        assert nodes[0]["act"] == "第一幕·开端"
        assert nodes[0]["word_count"] == 1200
        assert "执法堂" in nodes[0]["title"]
        assert nodes[0]["status"] == "pending"

    def test_parse_empty_concept(self):
        """空文本返回空列表。"""
        assert parse_outline_nodes("", 10000) == []
        assert parse_outline_nodes(None, 10000) == []

    def test_parse_no_nodes(self):
        """无节点行的构思返回空列表。"""
        concept = "【核心概念】没有大纲的构思。"
        assert parse_outline_nodes(concept, 10000) == []

    def test_parse_non_sequential_ids(self):
        """节点 id 不连续时返回空（防止乱序）。"""
        concept = """【剧情大纲】
节点1（幕，约1000字）：甲 —— 事件甲
节点3（幕，约1000字）：乙 —— 事件乙
"""
        assert parse_outline_nodes(concept, 10000) == []

    def test_parse_bad_format(self):
        """格式错误的节点行被忽略。"""
        concept = """【剧情大纲】
节点1（第二幕，约1500字）：正确的 —— 事件
节点A（幕，约1000字）：格式错误
节点B（幕）：完全错误
"""
        nodes = parse_outline_nodes(concept, 10000)
        assert len(nodes) == 1
        assert nodes[0]["id"] == 1


class TestParseExpanderOutput:
    """测试 _parse_expander_output（JSON 大纲解析）。"""

    def test_parse_valid_json(self):
        raw = ('{"concept": "核心创意", "nodes": ['
               '{"id": 1, "act": "正文", "title": "节点一", "summary": "描述一", "word_count": 1200},'
               '{"id": 2, "act": "正文", "title": "节点二", "summary": "描述二", "word_count": 1000}]}')
        concept, nodes = _parse_expander_output(raw)
        assert concept == "核心创意"
        assert len(nodes) == 2
        assert nodes[0]["title"] == "节点一"
        assert nodes[0]["summary"] == "描述一"
        assert nodes[0]["status"] == "pending"

    def test_parse_markdown_wrapped(self):
        raw = ('```json\n{"concept": "c", "nodes": ['
               '{"id": 1, "act": "正文", "title": "t", "summary": "s", "word_count": 1000}]}\n```')
        concept, nodes = _parse_expander_output(raw)
        assert concept == "c"
        assert len(nodes) == 1

    def test_parse_with_noise(self):
        raw = '好的，以下是结果：{"concept": "c", "nodes": [{"id": 1, "act": "正文", "title": "t", "summary": "s", "word_count": 1000}]} 希望对你有帮助'
        concept, nodes = _parse_expander_output(raw)
        assert concept == "c"
        assert len(nodes) == 1

    def test_parse_non_sequential_ids(self):
        raw = ('{"concept": "c", "nodes": ['
               '{"id": 1, "act": "正文", "title": "a", "word_count": 1000},'
               '{"id": 3, "act": "正文", "title": "b", "word_count": 1000}]}')
        concept, nodes = _parse_expander_output(raw)
        assert nodes == []

    def test_parse_bad_json(self):
        concept, nodes = _parse_expander_output("这不是JSON")
        assert concept is None
        assert nodes == []


class TestFormatConcept:
    """测试 _format_concept（格式化可读文本）。"""

    def test_format_and_roundtrip(self):
        concept = "核心创意"
        nodes = [
            {"id": 1, "act": "正文", "title": "节点一", "summary": "描述一", "word_count": 1200},
            {"id": 2, "act": "正文", "title": "节点二", "summary": "描述二", "word_count": 1000},
        ]
        fmt = _format_concept(concept, nodes)
        # 格式化文本应包含核心概念和节点
        assert "核心创意" in fmt
        assert "节点一" in fmt
        assert "节点2" in fmt
        # 往返：格式化文本能被 parse_outline_nodes 重新解析（编辑大纲后重解析用）
        roundtrip = parse_outline_nodes(fmt, 10000)
        assert len(roundtrip) == 2
        # 「标题 —— 描述」两段式：标题与描述分别归位（描述不再丢失）
        assert roundtrip[0]["title"] == "节点一"
        assert roundtrip[0]["summary"] == "描述一"
        assert roundtrip[1]["title"] == "节点二"
        assert roundtrip[1]["summary"] == "描述二"


class TestLoadOutlineNodes:
    """测试 load_outline_nodes。"""

    @pytest.fixture
    def app_ctx(self):
        app = create_app()
        app.config["TESTING"] = True
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        with app.app_context():
            db.create_all()
            yield

    def test_load_valid_json(self, app_ctx):
        from app.models import ShortStory, db
        s = ShortStory(title="t", mode="inspiration")
        s.outline_nodes = json.dumps([
            {"id": 1, "act": "幕", "title": "x", "word_count": 1000, "status": "done"},
        ], ensure_ascii=False)
        nodes = load_outline_nodes(s)
        assert len(nodes) == 1
        assert nodes[0]["status"] == "done"

    def test_load_empty(self, app_ctx):
        from app.models import ShortStory
        s = ShortStory(title="t", mode="inspiration")
        s.outline_nodes = ""
        assert load_outline_nodes(s) == []

    def test_load_corrupt(self, app_ctx):
        from app.models import ShortStory
        s = ShortStory(title="t", mode="inspiration")
        s.outline_nodes = "{corrupt json"
        assert load_outline_nodes(s) == []
