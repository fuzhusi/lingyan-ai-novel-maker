"""大纲树 ↔ 章节 单一事实源同步测试。

覆盖：
- 「章」节点创建时自动落关联章节（章节列表即刻可见，幂等）
- 节点编辑（大纲树侧 / 章节创作页内联）双向同步章节标题与大纲
- compose_node_outline 实时组装（节点摘要 + 场景分幕指引）
- 流水线 stage 1 对已关联空大纲章节用节点大纲，不再现编
- 章节创作页模板回归：本章大纲快照块已并入大纲树规划块
"""
import pytest
from unittest.mock import patch

from app import create_app, db
from app.models import Novel, Chapter, OutlineNode
from app.services.outline_sync import (
    compose_node_outline, ensure_chapter_for_node, sync_chapter_from_node,
)


@pytest.fixture
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        max_novel_id = db.session.query(db.func.max(Novel.id)).scalar() or 0
        yield app
        # FK ON：先清子表再清父表，只清理本测试新建的书
        novels = Novel.query.filter(Novel.id > max_novel_id).all()
        for n in novels:
            Chapter.query.filter(Chapter.novel_id == n.id).delete(
                synchronize_session=False)
            OutlineNode.query.filter(OutlineNode.novel_id == n.id).delete(
                synchronize_session=False)
            db.session.delete(n)
        db.session.commit()


def _make_novel(**kwargs):
    defaults = dict(title="同步测试书", genre="玄幻")
    defaults.update(kwargs)
    n = Novel(**defaults)
    db.session.add(n)
    db.session.commit()
    return n


def _make_node(novel_id, node_type="chapter", title="第1章 试炼", summary="主角进入试炼场"):
    node = OutlineNode(novel_id=novel_id, node_type=node_type,
                       title=title, summary=summary, sort_order=1)
    db.session.add(node)
    db.session.commit()
    return node


class TestComposeNodeOutline:
    def test_summary_only(self, app_ctx):
        node = _make_node(_make_novel().id)
        assert compose_node_outline(node) == "主角进入试炼场"

    def test_with_scenes(self, app_ctx):
        novel = _make_novel()
        node = _make_node(novel.id)
        db.session.add_all([
            OutlineNode(novel_id=novel.id, parent_id=node.id, node_type="scene",
                        title="入场", summary="检测灵根", sort_order=1),
            OutlineNode(novel_id=novel.id, parent_id=node.id, node_type="scene",
                        title="冲突", summary="遭人暗算", sort_order=2),
        ])
        db.session.commit()
        text = compose_node_outline(node)
        assert text.startswith("主角进入试炼场")
        assert "分幕指引：" in text
        assert "【入场】检测灵根" in text
        assert "【冲突】遭人暗算" in text

    def test_empty_node(self, app_ctx):
        assert compose_node_outline(None) == ""


class TestEnsureChapterForNode:
    def test_auto_create(self, app_ctx):
        novel = _make_novel()
        node = _make_node(novel.id)
        ch = ensure_chapter_for_node(node)
        db.session.commit()
        assert ch.id is not None
        assert ch.novel_id == novel.id
        assert ch.chapter_number == 1
        assert ch.title == "第1章 试炼"
        assert ch.outline == "主角进入试炼场"
        assert ch.outline_node_id == node.id

    def test_idempotent(self, app_ctx):
        novel = _make_novel()
        node = _make_node(novel.id)
        first = ensure_chapter_for_node(node)
        db.session.commit()
        second = ensure_chapter_for_node(node)
        assert second.id == first.id
        assert Chapter.query.filter_by(novel_id=novel.id).count() == 1

    def test_non_chapter_node_returns_none(self, app_ctx):
        novel = _make_novel()
        node = _make_node(novel.id, node_type="volume", title="第一卷")
        assert ensure_chapter_for_node(node) is None

    def test_number_auto_increment(self, app_ctx):
        novel = _make_novel()
        db.session.add(Chapter(novel_id=novel.id, chapter_number=3,
                               title="已有章"))
        db.session.commit()
        node = _make_node(novel.id)
        ch = ensure_chapter_for_node(node)
        db.session.commit()
        assert ch.chapter_number == 4


class TestSyncChapterFromNode:
    def test_sync_updates_title_and_outline(self, app_ctx):
        novel = _make_novel()
        node = _make_node(novel.id)
        ch = ensure_chapter_for_node(node)
        db.session.commit()
        node.title = "第1章 改名"
        node.summary = "新摘要"
        sync_chapter_from_node(ch, node)
        assert ch.title == "第1章 改名"
        assert ch.outline == "新摘要"

    def test_stale_fingerprint_still_works_after_sync(self, app_ctx):
        """同步不刷新指纹：大纲改了而正文还是旧的 → stale 如实报警。"""
        from app.models.novel import outline_hash_of
        novel = _make_novel()
        node = _make_node(novel.id)
        ch = ensure_chapter_for_node(node)
        ch.outline_hash = outline_hash_of(ch.outline)  # 模拟已据旧大纲生成
        db.session.commit()
        node.summary = "大纲被改了"
        sync_chapter_from_node(ch, node)
        db.session.commit()
        assert ch.outline_stale() is True


class TestOutlineRoutes:
    def test_create_chapter_node_auto_creates_chapter(self, app_ctx):
        novel = _make_novel()
        client = app_ctx.test_client()
        r = client.post(f"/novel/{novel.id}/outline/create", data={
            "node_type": "chapter", "title": "第2章 自动建",
            "summary": "自动建章节的摘要",
        })
        assert r.status_code == 302
        ch = Chapter.query.filter_by(novel_id=novel.id).first()
        assert ch is not None
        assert ch.title == "第2章 自动建"
        assert ch.outline == "自动建章节的摘要"
        assert ch.outline_node_id is not None

    def test_create_scene_node_does_not_create_chapter(self, app_ctx):
        novel = _make_novel()
        client = app_ctx.test_client()
        client.post(f"/novel/{novel.id}/outline/create", data={
            "node_type": "scene", "title": "场景", "summary": "s",
        })
        assert Chapter.query.filter_by(novel_id=novel.id).count() == 0

    def test_tree_edit_syncs_linked_chapter(self, app_ctx):
        novel = _make_novel()
        node = _make_node(novel.id)
        ensure_chapter_for_node(node)
        db.session.commit()
        client = app_ctx.test_client()
        r = client.post(f"/novel/{novel.id}/outline/{node.id}/edit", data={
            "title": "第1章 树侧改名", "summary": "树侧改的摘要",
            "node_type": "chapter",
        })
        assert r.status_code == 302
        ch = Chapter.query.filter_by(outline_node_id=node.id).first()
        assert ch.title == "第1章 树侧改名"
        assert ch.outline == "树侧改的摘要"

    def test_edit_summary_json_endpoint(self, app_ctx):
        novel = _make_novel()
        node = _make_node(novel.id)
        ensure_chapter_for_node(node)
        db.session.add(OutlineNode(novel_id=novel.id, parent_id=node.id,
                                   node_type="scene", title="场景A",
                                   summary="打斗", sort_order=1))
        db.session.commit()
        client = app_ctx.test_client()
        r = client.post(f"/novel/{novel.id}/outline/{node.id}/edit-summary",
                        data={"summary": "内联改的摘要"},
                        headers={"Accept": "application/json"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["summary"] == "内联改的摘要"
        # outline_text 由服务端实时组装，含分幕指引
        assert "内联改的摘要" in data["outline_text"]
        assert "【场景A】打斗" in data["outline_text"]
        ch = Chapter.query.filter_by(outline_node_id=node.id).first()
        assert ch.outline == data["outline_text"]

    def test_edit_summary_requires_summary_field(self, app_ctx):
        novel = _make_novel()
        node = _make_node(novel.id)
        client = app_ctx.test_client()
        r = client.post(f"/novel/{novel.id}/outline/{node.id}/edit-summary",
                        data={}, headers={"Accept": "application/json"})
        assert r.status_code == 400

    def test_edit_summary_cross_novel_404(self, app_ctx):
        other = _make_novel()
        node = _make_node(other.id)
        novel = _make_novel()
        client = app_ctx.test_client()
        r = client.post(f"/novel/{novel.id}/outline/{node.id}/edit-summary",
                        data={"summary": "x"}, headers={"Accept": "application/json"})
        assert r.status_code == 404

    def test_create_chapter_button_idempotent(self, app_ctx):
        """旧入口（未关联节点手动创建）与新自动建共存不重复。"""
        novel = _make_novel()
        node = _make_node(novel.id)
        ensure_chapter_for_node(node)
        db.session.commit()
        client = app_ctx.test_client()
        r = client.post(f"/novel/{novel.id}/outline/{node.id}/create-chapter")
        assert r.status_code == 302
        assert Chapter.query.filter_by(novel_id=novel.id).count() == 1


class TestWritePageTemplate:
    def test_plan_block_renders_node_summary(self, app_ctx):
        novel = _make_novel()
        node = _make_node(novel.id, summary="节点摘要X")
        ensure_chapter_for_node(node)
        db.session.commit()
        client = app_ctx.test_client()
        r = client.get(f"/novel/{novel.id}/chapter/1/write")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert 'id="outline-plan-details"' in html
        assert "节点摘要X" in html
        assert "节点实时组装" in html or "outlinePlanText" in html

    def test_legacy_snapshot_details_removed(self, app_ctx):
        """模板回归：独立「本章大纲」details 块已删除。"""
        novel = _make_novel()
        node = _make_node(novel.id)
        ensure_chapter_for_node(node)
        db.session.commit()
        client = app_ctx.test_client()
        html = client.get(f"/novel/{novel.id}/chapter/1/write").get_data(as_text=True)
        assert 'id="outline-details"' not in html

    def test_unlinked_chapter_fallback_outline(self, app_ctx):
        novel = _make_novel()
        db.session.add(Chapter(novel_id=novel.id, chapter_number=1,
                               title="自由章", outline="自由章旧大纲"))
        db.session.add(Chapter(novel_id=novel.id, chapter_number=2,
                               title="无大纲章", outline=""))
        db.session.commit()
        client = app_ctx.test_client()
        html = client.get(f"/novel/{novel.id}/chapter/1/write").get_data(as_text=True)
        assert "自由章旧大纲" in html
        # 无大纲的未关联章节：显示引导提示而非空白
        html2 = client.get(f"/novel/{novel.id}/chapter/2/write").get_data(as_text=True)
        assert "未关联大纲树节点" in html2


class TestRunnerNodeOutline:
    def test_runner_seeds_node_outline(self, app_ctx):
        """流水线 stage 1：已关联节点且章节无大纲 → 用节点大纲，不调 AI 现编。"""
        from app.services.chapter_runner import run_chapter_pipeline
        novel = _make_novel()
        node = _make_node(novel.id, summary="流水线用节点大纲")
        ch = ensure_chapter_for_node(node)
        ch.outline = ""  # 模拟旧数据：关联了节点但快照为空
        db.session.commit()

        def _fail_collect(*a, **kw):
            raise AssertionError("关联节点时不应调用 AI 生成大纲")

        with patch("app.services.chapter_runner.collect_full_text",
                   side_effect=_fail_collect):
            result = run_chapter_pipeline(novel.id, ch.chapter_number)
        # stage1 之后大纲来自节点；正文阶段才会真正调 AI（此处被 mock 拦截属预期失败）
        ch2 = db.session.get(Chapter, ch.id)
        assert "流水线用节点大纲" in (ch2.outline or "")
        assert any(s["stage"] == "outline" and s.get("skipped") == "已有大纲"
                   for s in result.get("stages", []))
