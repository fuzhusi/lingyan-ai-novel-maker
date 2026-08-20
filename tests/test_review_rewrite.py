"""短篇根据评审重写测试：多轮逐节点二次生成。

覆盖：
- 有节点结构时走逐节点重写分支（每个已完成节点独立重写，其余保持）
- 无节点结构时回退全文重写
- 逐节点重写后全文正确汇总，节点正文更新
"""
import json
import pytest
from unittest.mock import patch
from app import create_app, db
from app.models import ShortStory, ShortStoryVersion, ShortStoryReview


@pytest.fixture
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        # 自愈式清理：先清掉历史残留（pytest 被超时杀死时 teardown 不会执行）
        _cleanup_test_data()
        yield app
        _cleanup_test_data()


def _cleanup_test_data():
    """删除所有 [TEST] 标记的故事及其版本、评审 + 孤儿评审。

    - 用标题前缀 [TEST] 识别测试数据（而非仅 id > max_id），
      即使上次运行被 kill 也能在本次启动时自愈清理
    - 评审挂在版本 id 上：先收集版本 id 再删，修复原先 version_id == 0 永不匹配的 bug
    """
    stories = ShortStory.query.filter(ShortStory.title.like('[TEST]%')).all()
    for s in stories:
        ver_ids = [v.id for v in ShortStoryVersion.query.filter_by(story_id=s.id).all()]
        if ver_ids:
            ShortStoryReview.query.filter(ShortStoryReview.version_id.in_(ver_ids)).delete(
                synchronize_session=False)
        ShortStoryVersion.query.filter_by(story_id=s.id).delete(synchronize_session=False)
        db.session.delete(s)
    # 孤儿评审（version_id 指向已不存在的版本）
    all_ver_ids = {v.id for v in ShortStoryVersion.query.all()}
    orphan_ids = [r.id for r in ShortStoryReview.query.all()
                  if r.version_id not in all_ver_ids]
    if orphan_ids:
        ShortStoryReview.query.filter(ShortStoryReview.id.in_(orphan_ids)).delete(
            synchronize_session=False)
    if stories or orphan_ids:
        db.session.commit()


def _make_node_story():
    """创建带节点结构的故事（3 个已完成节点各有独立正文）。"""
    nodes = [
        {"id": 1, "act": "正文", "title": "开局", "summary": "主角登场",
         "word_count": 1000, "status": "done", "content": "节点1的正文内容。"},
        {"id": 2, "act": "正文", "title": "发展", "summary": "冲突升级",
         "word_count": 1000, "status": "done", "content": "节点2的正文内容。冲突爆发。"},
        {"id": 3, "act": "正文", "title": "结尾", "summary": "收尾",
         "word_count": 1000, "status": "done", "content": "节点3的正文内容。故事结束。"},
    ]
    s = ShortStory(title="[TEST]节点重写", mode="inspiration", inspiration="测试灵感",
                   word_target=2000, content="节点1的正文内容。节点2的正文内容。冲突爆发。节点3的正文内容。故事结束。")
    s.outline_nodes = json.dumps(nodes, ensure_ascii=False)
    db.session.add(s)
    db.session.commit()
    # 加一个版本供关联评审
    ver = ShortStoryVersion(story_id=s.id, version_number=1, content=s.content, source="ai")
    db.session.add(ver)
    db.session.commit()
    review = ShortStoryReview(version_id=ver.id, overall_comment="人物塑造单薄，节奏太快")
    db.session.add(review)
    db.session.commit()
    return s


def _collect_stream(resp):
    """收集流式响应全部文本（强制消费完整响应体）。"""
    return resp.get_data(as_text=True)


class TestRewriteByNodes:
    def test_node_story_uses_rewrite_by_nodes(self, app_ctx):
        """有节点结构时走逐节点重写：每个完成节点被重写，节点保持。"""
        s = _make_node_story()
        client = app_ctx.test_client()
        with patch("app.routes.short_story.review.stream_llm_tokens",
                   side_effect=lambda **kw: iter(["重写后的", "节点内容"])) as m:
            resp = client.post(f"/short/{s.id}/rewrite-with-feedback")
            assert resp.status_code == 200
            # 必须在 patch 块内消费流（generator 惰性执行）
            _collect_stream(resp)
            assert m.call_count >= 3  # 每个节点一次重写调用
        # 全文应包含重写后内容 + 节点标记
        # 注意：流式 generator 内部用了独立 app context（独立 session），
        # 提交的更改对外层 session 的 identity map 不可见，需 expire 后重读
        db.session.expire_all()
        s2 = db.session.get(ShortStory, s.id)
        nodes = json.loads(s2.outline_nodes)
        assert all(n["status"] == "done" for n in nodes)
        assert all(n["content"] for n in nodes)
        # 重写后的内容被保存到节点和全文
        assert "重写后的节点内容" in s2.content
        # 保存为新版本
        versions = ShortStoryVersion.query.filter_by(story_id=s.id).order_by(
            ShortStoryVersion.version_number).all()
        assert len(versions) == 2  # 原版本 + 重写版本
        assert versions[-1].source == "rewrite"

    def test_plain_story_falls_back_to_full_rewrite(self, app_ctx):
        """无节点结构时回退全文重写。"""
        s = ShortStory(title="[TEST]无节点", mode="inspiration", inspiration="灵感",
                       word_target=1000, content="这是没有节点结构的原文内容。")
        db.session.add(s)
        db.session.commit()
        client = app_ctx.test_client()
        with patch("app.routes.short_story.review.stream_llm_tokens",
                   side_effect=lambda **kw: iter(["重写后的完整"])):
            resp = client.post(f"/short/{s.id}/rewrite-with-feedback")
            assert resp.status_code == 200
            _collect_stream(resp)  # 在 patch 块内消费流
        db.session.expire_all()
        s2 = db.session.get(ShortStory, s.id)
        assert "重写后的完整" in s2.content

class TestRewritePreservesStructure:
    def test_node_count_preserved(self, app_ctx):
        """逐节点重写后节点数量不变（只重写内容，不增删节点）。"""
        s = _make_node_story()
        client = app_ctx.test_client()
        with patch("app.routes.short_story.review.stream_llm_tokens",
                   side_effect=lambda **kw: iter(["重写内容"])):
            resp = client.post(f"/short/{s.id}/rewrite-with-feedback")
            _collect_stream(resp)  # 在 patch 块内消费流
        db.session.expire_all()
        s2 = db.session.get(ShortStory, s.id)
        assert len(json.loads(s2.outline_nodes)) == 3
