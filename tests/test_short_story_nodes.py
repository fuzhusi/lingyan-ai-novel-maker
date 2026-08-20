"""短篇节点内容存储 + 局部编辑测试。

覆盖：
- _rebuild_content_from_nodes / _nodes_have_content
- write_from_concept 节点内容存储
- rewrite_node / continue_story / expand_selection / rewrite_selection
- save_content 分歧清节点
"""
import json
import pytest
from unittest.mock import patch
from app import create_app, db
from app.models.short_story import ShortStory


@pytest.fixture
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        # 记录测试前的 ID 范围，测试后清理
        from app.models.short_story import ShortStory, ShortStoryVersion, ShortStoryReview
        max_id = db.session.query(db.func.max(ShortStory.id)).scalar() or 0
        yield app
        # 清理测试写入的数据
        new_ids = [s.id for s in ShortStory.query.filter(ShortStory.id > max_id).all()]
        if new_ids:
            new_ver_ids = [v.id for v in ShortStoryVersion.query.filter(ShortStoryVersion.story_id.in_(new_ids)).all()]
            if new_ver_ids:
                ShortStoryReview.query.filter(ShortStoryReview.version_id.in_(new_ver_ids)).delete(synchronize_session=False)
            ShortStoryVersion.query.filter(ShortStoryVersion.story_id.in_(new_ids)).delete(synchronize_session=False)
            ShortStory.query.filter(ShortStory.id.in_(new_ids)).delete(synchronize_session=False)
            db.session.commit()


@pytest.fixture
def client(app_ctx):
    return app_ctx.test_client()


def _make_story(mode="inspiration", content="", concept="", outline_nodes="", status="concept_ready"):
    s = ShortStory(
        title="测试短篇", mode=mode, inspiration="灵感",
        content=content, concept=concept,
        outline_nodes=outline_nodes, status=status,
        word_target=3600, genre="奇幻",
    )
    db.session.add(s)
    db.session.commit()
    return s


# ---- _rebuild_content_from_nodes / _nodes_have_content ----

class TestRebuildAndHaveContent:

    def test_rebuild_simple(self, app_ctx):
        from app.routes.short_story.generate import _rebuild_content_from_nodes
        nodes = [
            {"id": 1, "status": "done", "content": "段落一"},
            {"id": 2, "status": "done", "content": "段落二"},
        ]
        assert _rebuild_content_from_nodes(nodes) == "段落一\n\n段落二"

    def test_rebuild_skips_pending(self, app_ctx):
        from app.routes.short_story.generate import _rebuild_content_from_nodes
        nodes = [
            {"id": 1, "status": "done", "content": "段一"},
            {"id": 2, "status": "pending"},
        ]
        assert _rebuild_content_from_nodes(nodes) == "段一"

    def test_rebuild_skips_no_content(self, app_ctx):
        from app.routes.short_story.generate import _rebuild_content_from_nodes
        nodes = [
            {"id": 1, "status": "done", "content": ""},
            {"id": 2, "status": "done", "content": "段二"},
        ]
        assert _rebuild_content_from_nodes(nodes) == "段二"

    def test_rebuild_empty(self, app_ctx):
        from app.routes.short_story.generate import _rebuild_content_from_nodes
        assert _rebuild_content_from_nodes([]) == ""

    def test_nodes_have_content_true(self, app_ctx):
        from app.routes.short_story.generate import _nodes_have_content
        nodes = [
            {"id": 1, "status": "done", "content": "有内容"},
            {"id": 2, "status": "pending"},
        ]
        assert _nodes_have_content(nodes) is True

    def test_nodes_have_content_missing(self, app_ctx):
        from app.routes.short_story.generate import _nodes_have_content
        nodes = [
            {"id": 1, "status": "done", "content": ""},
        ]
        assert _nodes_have_content(nodes) is False

    def test_nodes_have_content_no_done(self, app_ctx):
        from app.routes.short_story.generate import _nodes_have_content
        nodes = [{"id": 1, "status": "pending"}]
        assert _nodes_have_content(nodes) is False


# ---- save_content 分歧清节点 ----

class TestSaveContentDivergence:

    def test_save_clears_nodes_on_diverge(self, client, app_ctx):
        """手动保存与节点拼接不一致时，清除节点正文。"""
        nodes = [
            {"id": 1, "act": "正文", "title": "节点一", "summary": "s", "word_count": 1000, "status": "done", "content": "ABC"},
            {"id": 2, "act": "正文", "title": "节点二", "summary": "s", "word_count": 1000, "status": "done", "content": "DEF"},
        ]
        s = _make_story(
            content="ABC\n\nDEF",
            concept="核心概念",
            outline_nodes=json.dumps(nodes, ensure_ascii=False),
            status="done",
        )
        resp = client.post(f"/short/{s.id}/save", data={"content": "完全不同的内容"})
        assert resp.status_code == 200
        db.session.refresh(s)
        reloaded = json.loads(s.outline_nodes)
        for n in reloaded:
            assert "content" not in n or n["content"] is None or n["content"] == ""

    def test_save_keeps_nodes_on_match(self, client, app_ctx):
        """手动保存与节点拼接一致时，保留节点正文。"""
        nodes = [
            {"id": 1, "act": "正文", "title": "节点一", "summary": "s", "word_count": 1000, "status": "done", "content": "ABC"},
        ]
        s = _make_story(
            content="ABC",
            concept="核心概念",
            outline_nodes=json.dumps(nodes, ensure_ascii=False),
            status="done",
        )
        resp = client.post(f"/short/{s.id}/save", data={"content": "A  B C"})
        assert resp.status_code == 200
        db.session.refresh(s)
        reloaded = json.loads(s.outline_nodes)
        assert reloaded[0]["content"] == "ABC"


# ---- rewrite_node ----

class TestRewriteNode:

    @patch("app.routes.short_story.generate._stream_ai_tokens")
    def test_rewrite_node_success(self, mock_stream, client, app_ctx):
        mock_stream.return_value = iter(["新段落内容"])
        nodes = [
            {"id": 1, "act": "正文", "title": "节点一", "summary": "s", "word_count": 1000, "status": "done", "content": "旧内容"},
        ]
        s = _make_story(
            content="旧内容",
            concept="核心概念",
            outline_nodes=json.dumps(nodes, ensure_ascii=False),
            status="done",
        )
        resp = client.post(f"/short/{s.id}/node/1/rewrite")
        assert resp.status_code == 200
        text = resp.data.decode()
        assert "===NODE:1:" in text
        assert "新段落内容" in text
        mock_stream.assert_called_once()

    def test_rewrite_node_no_nodes(self, client, app_ctx):
        s = _make_story(content="一些内容", outline_nodes="[]")
        resp = client.post(f"/short/{s.id}/node/1/rewrite")
        assert resp.status_code == 400

    def test_rewrite_node_not_found(self, client, app_ctx):
        nodes = [{"id": 1, "act": "正文", "title": "t", "summary": "s", "word_count": 1000, "status": "done", "content": "c"}]
        s = _make_story(content="c", outline_nodes=json.dumps(nodes))
        resp = client.post(f"/short/{s.id}/node/99/rewrite")
        assert resp.status_code == 404


# ---- continue_story ----

class TestContinueStory:

    @patch("app.routes.short_story.generate._stream_ai_tokens")
    def test_continue_with_nodes(self, mock_stream, client, app_ctx):
        mock_stream.return_value = iter(["续写段落"])
        nodes = [
            {"id": 1, "act": "正文", "title": "节点一", "summary": "s", "word_count": 1000, "status": "done", "content": "段一"},
        ]
        s = _make_story(
            content="段一", concept="核心概念",
            outline_nodes=json.dumps(nodes, ensure_ascii=False), status="done",
        )
        resp = client.post(f"/short/{s.id}/continue", data={"words": "500"})
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "续写段落" in body
        mock_stream.assert_called_once()

    @patch("app.routes.short_story.generate._stream_ai_tokens")
    def test_continue_without_nodes(self, mock_stream, client, app_ctx):
        mock_stream.return_value = iter(["续写文字"])
        s = _make_story(content="旧内容", outline_nodes="[]", status="done")
        resp = client.post(f"/short/{s.id}/continue", data={"words": "300"})
        assert resp.status_code == 200
        assert "续写文字" in resp.data.decode()

    def test_continue_empty_content(self, client, app_ctx):
        s = _make_story(content="")
        resp = client.post(f"/short/{s.id}/continue")
        assert resp.status_code == 400


# ---- expand_selection ----

class TestExpandSelection:

    @patch("app.routes.short_story.generate._stream_ai_tokens")
    def test_expand_selection(self, mock_stream, client, app_ctx):
        mock_stream.return_value = iter(["扩写后的完整段落内容很长"])
        s = _make_story(content="原始段落")
        resp = client.post(f"/short/{s.id}/expand-selection", data={
            "text": "原始段落",
            "before": "",
            "words": "300",
        })
        assert resp.status_code == 200
        assert "扩写后的完整段落" in resp.data.decode()

    def test_expand_no_text(self, client, app_ctx):
        s = _make_story(content="x")
        resp = client.post(f"/short/{s.id}/expand-selection", data={"text": "", "before": ""})
        assert resp.status_code == 400


# ---- rewrite_selection ----

class TestRewriteSelection:

    @patch("app.routes.short_story.generate._stream_ai_tokens")
    def test_rewrite_selection(self, mock_stream, client, app_ctx):
        mock_stream.return_value = iter(["重写后的文字"])
        s = _make_story(content="原文")
        resp = client.post(f"/short/{s.id}/rewrite-selection", data={
            "text": "原文",
            "instruction": "改成第一人称",
            "before": "",
        })
        assert resp.status_code == 200
        assert "重写后的文字" in resp.data.decode()

    def test_rewrite_no_text(self, client, app_ctx):
        s = _make_story(content="x")
        resp = client.post(f"/short/{s.id}/rewrite-selection", data={
            "text": "", "instruction": "改", "before": "",
        })
        assert resp.status_code == 400

    def test_rewrite_no_instruction(self, client, app_ctx):
        s = _make_story(content="x")
        resp = client.post(f"/short/{s.id}/rewrite-selection", data={
            "text": "选中文字", "instruction": "", "before": "",
        })
        assert resp.status_code == 400


# ---- story_list 新结构 ----

class TestStoryListNewStructure:

    def test_list_returns_dicts(self, client, app_ctx):
        """story_list 返回 item dict 而非裸对象。"""
        nodes = [
            {"id": 1, "act": "正文", "title": "t", "summary": "s", "word_count": 1000, "status": "done", "content": "段一"},
            {"id": 2, "act": "正文", "title": "t2", "summary": "s", "word_count": 1000, "status": "pending"},
        ]
        _make_story(
            content="段一",
            outline_nodes=json.dumps(nodes, ensure_ascii=False),
            status="done",
        )
        resp = client.get("/short/")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "1/2" in html
        assert "202" in html


# ---- rewrite_node 前置节点无 content 时应报错 ----

class TestRewriteNodePrecondition:

    def test_rewrite_node_prev_missing_content(self, client, app_ctx):
        """前置节点缺少 content 时拒绝重写。"""
        nodes = [
            {"id": 1, "act": "正文", "title": "t", "summary": "s", "word_count": 1000, "status": "done"},
            {"id": 2, "act": "正文", "title": "t2", "summary": "s", "word_count": 1000, "status": "done", "content": "c"},
        ]
        s = _make_story(
            content="全文",
            concept="核心概念",
            outline_nodes=json.dumps(nodes, ensure_ascii=False),
            status="done",
        )
        resp = client.post(f"/short/{s.id}/node/2/rewrite")
        assert resp.status_code == 400
        assert "旧数据" in resp.data.decode()
