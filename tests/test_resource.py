"""资源库测试:入库/嵌入/语义检索/快路回退/删除。"""
import pytest

from app import create_app, db
from app.models import Novel, ResourceBook, ResourceChunk


@pytest.fixture
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        max_novel = db.session.query(db.func.max(Novel.id)).scalar() or 0
        max_res = db.session.query(db.func.max(ResourceBook.id)).scalar() or 0
        yield app
        # FK ON:先删孤儿 chunks,再走 ORM 级联删 books
        valid_ids = [r[0] for r in db.session.query(ResourceBook.id)]
        ResourceChunk.query.filter(
            ResourceChunk.resource_id.notin_(valid_ids)
        ).delete(synchronize_session=False)
        for b in ResourceBook.query.filter(ResourceBook.id > max_res).all():
            db.session.delete(b)  # ORM 级联收 chunks
        Novel.query.filter(Novel.id > max_novel).delete(synchronize_session=False)
        db.session.commit()


class TestResourceCRUD:
    def test_add_and_retrieve(self, app_ctx):
        from app.services.resource_service import add_resource
        book = add_resource("测试书", "第一章 开端\n主角出场。\n第二章 发展\n主角升级。")
        assert book.id > 0
        assert book.total_chars > 0
        assert book.chapter_count == 2
        assert book.embedded is True
        chunks = ResourceChunk.query.filter_by(resource_id=book.id).all()
        assert len(chunks) == 2
        assert all(c.embedding for c in chunks)  # 嵌入已生成(降级向量也非空)

    def test_delete_cascades(self, app_ctx):
        from app.services.resource_service import add_resource
        book = add_resource("级联书", "第一章 测试\n内容。" * 100)
        rid = book.id
        db.session.delete(book)
        db.session.commit()
        assert ResourceChunk.query.filter_by(resource_id=rid).count() == 0


class TestSemanticSearch:
    def test_search_returns_relevant(self, app_ctx):
        from app.services.resource_service import add_resource, semantic_search
        add_resource("武侠书", "第一章 比武\n主角在擂台上一拳打飞了对手，全场震惊。\n第二章 修炼\n主角开始在山中修炼内功。")
        results = semantic_search("比武打斗")
        assert len(results) > 0
        assert results[0]["score"] > 0

    def test_novel_scoped_search(self, app_ctx):
        novel = Novel(title="作用域书", genre="都市")
        db.session.add(novel)
        db.session.commit()
        # 无拆书任务 → 空结果
        from app.services.resource_service import semantic_search
        assert semantic_search("任意", novel_id=novel.id) == []
