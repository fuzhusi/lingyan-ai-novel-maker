"""语义检索服务测试:实体嵌入/语义选角色/设定/自我重复检测。"""
import pytest

from app import create_app, db
from app.models import Novel, Character, WorldSetting, Foreshadowing, Chapter, ChapterVersion


@pytest.fixture
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        max_novel = db.session.query(db.func.max(Novel.id)).scalar() or 0
        yield app
        from app.models import BlindReview, PendingExtraction
        from app.models.entity_embedding import EntityEmbedding
        for n in Novel.query.filter(Novel.id > max_novel).all():
            vids = [v.id for ch in n.chapters for v in ch.versions]
            if vids:
                BlindReview.query.filter(BlindReview.version_id.in_(vids)).delete(synchronize_session=False)
            PendingExtraction.query.filter_by(novel_id=n.id).delete(synchronize_session=False)
            EntityEmbedding.query.filter_by(novel_id=n.id).delete(synchronize_session=False)
            for ch in list(n.chapters):
                db.session.delete(ch)
            db.session.delete(n)
        db.session.commit()


def _setup(app_ctx):
    novel = Novel(title="语义书", genre="都市")
    db.session.add(novel)
    db.session.commit()
    db.session.add(Character(novel_id=novel.id, name="林默", personality="冷静隐忍",
                             background="市井出身", motivation="查清父亲死因"))
    db.session.add(Character(novel_id=novel.id, name="赵铁", personality="暴烈",
                             background="退役特种兵", motivation="报复社会"))
    db.session.add(WorldSetting(novel_id=novel.id, title="灵能规则",
                                content="灵能者每释放一次能力需休息24小时"))
    db.session.add(Foreshadowing(novel_id=novel.id, title="父亲遗言",
                                 description='父亲临终前说：去找姓陈的', importance=8))
    db.session.commit()
    return novel


class TestEmbedAndSearch:
    def test_embed_and_search_characters(self, app_ctx):
        novel = _setup(app_ctx)
        from app.services.semantic_service import embed_novel_entities, search_relevant
        count = embed_novel_entities(novel.id)
        assert count >= 3  # 2 character + 1 world + 1 foreshadowing

        # 搜"冷静"应命中林默
        results = search_relevant(novel.id, "冷静隐忍的人调查真相",
                                  entity_types=("character",), top_k=2)
        assert any(r["entity_id"] for r in results)

    def test_search_returns_relevant_world(self, app_ctx):
        novel = _setup(app_ctx)
        from app.services.semantic_service import embed_novel_entities, search_relevant
        embed_novel_entities(novel.id)
        results = search_relevant(novel.id, "释放能力后的冷却时间限制",
                                  entity_types=("world",), top_k=1)
        assert len(results) == 1
        assert "灵能" in results[0]["text_snippet"] or results[0]["score"] > 0


class TestSelectRelevantEntities:
    def test_returns_ids(self, app_ctx):
        novel = _setup(app_ctx)
        from app.services.semantic_service import (
            embed_novel_entities, select_relevant_entities)
        embed_novel_entities(novel.id)
        selected = select_relevant_entities(novel.id, "林默调查父亲的死因，遭遇暴力阻挠")
        assert isinstance(selected, dict)
        assert "character_ids" in selected and "world_ids" in selected


class TestSelfRepetition:
    def test_detects_self_copy(self, app_ctx):
        novel = _setup(app_ctx)
        prev_text = "他缓缓走过那条熟悉的小巷，回忆像潮水般涌来。"
        db.session.add(Chapter(novel_id=novel.id, chapter_number=1, title="第1章"))
        db.session.commit()
        ch = Chapter.query.filter_by(novel_id=novel.id, chapter_number=1).first()
        db.session.add(ChapterVersion(chapter_id=ch.id, version_number=1, content=prev_text))
        db.session.commit()
        from app.services.similarity_check import check_self_repetition
        rep = check_self_repetition(novel.id, 2, "他缓缓走过那条熟悉的小巷，回忆像潮水般涌来。")
        assert rep is not None
        assert rep["verdict"] in ("warn", "alarm")

    def test_no_self_copy_passes(self, app_ctx):
        novel = _setup(app_ctx)
        db.session.add(Chapter(novel_id=novel.id, chapter_number=1, title="第1章"))
        db.session.commit()
        ch = Chapter.query.filter_by(novel_id=novel.id, chapter_number=1).first()
        db.session.add(ChapterVersion(chapter_id=ch.id, version_number=1, content="完全不同的开头。"))
        db.session.commit()
        from app.services.similarity_check import check_self_repetition
        rep = check_self_repetition(novel.id, 2, "全新的场景，全新的对话。")
        assert rep is None or rep["verdict"] == "pass"
