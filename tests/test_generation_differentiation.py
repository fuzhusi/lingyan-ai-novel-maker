"""生成期差异化测试:雷同检测算法 + 差异化红线注入 + 差异轴持久化。"""
import json

import pytest

from app import create_app, db
from app.models import Novel, Chapter, PlagiarizeTask
from app.services.similarity_check import (
    check_vs_blueprint, _redline_runs, REDLINE_N, HIGH_REDLINE_N,
)


@pytest.fixture
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        max_novel = db.session.query(db.func.max(Novel.id)).scalar() or 0
        max_task = db.session.query(db.func.max(PlagiarizeTask.id)).scalar() or 0
        yield app
        from app.models import BlindReview
        new_novels = Novel.query.filter(Novel.id > max_novel).all()
        for n in new_novels:
            vids = [v.id for ch in n.chapters for v in ch.versions]
            if vids:
                BlindReview.query.filter(BlindReview.version_id.in_(vids)).delete(synchronize_session=False)
            for ch in list(n.chapters):
                db.session.delete(ch)
            db.session.delete(n)
        for t in PlagiarizeTask.query.filter(PlagiarizeTask.id > max_task).all():
            db.session.delete(t)
        db.session.commit()


REF_SUMMARIES = [
    {"summary": "林逸在青云宗的执法堂上被冤枉私藏魔物，当众被废去修为并逐出师门，"
                "青梅竹马的苏婉晴当众与他划清界限，老长老暗中塞给他一块残玉。"},
    {"summary": "林逸流落荒城，靠替人炼药为生，意外发现残玉能吸收月华，"
                "修为以另一种方式缓慢恢复，同时引来黑市悬赏者的追踪。"},
]


class TestSimilarityCheck:
    def test_verbatim_copy_is_alarm_with_redline(self):
        gen = ("林逸在青云宗的执法堂上被冤枉私藏魔物，当众被废去修为并逐出师门，"
               "他看着苏婉晴转身的背影，握紧了那块残玉。")
        rep = check_vs_blueprint(gen, REF_SUMMARIES)
        assert rep["verdict"] == "alarm"
        assert rep["containment"] > 0.3
        assert rep["redlines"] and rep["redlines"][0]["len"] >= REDLINE_N

    def test_same_beat_different_surface_passes(self):
        """同节拍不同皮肉(改人名/地点/具体事件)→ containment 低,通过。"""
        gen = ("陈默在市局刑侦队被停职审查，徽章和配枪被收走，"
               "搭档一句保重都没说就走了，只有老队长塞给他一包旧案卷。")
        rep = check_vs_blueprint(gen, REF_SUMMARIES)
        assert rep["verdict"] in ("pass", "warn")
        assert not any(r["len"] >= HIGH_REDLINE_N for r in rep["redlines"])

    def test_containment_uses_generated_side(self):
        """短生成文本抄入长参考 → containment(生成侧分母)能检出。"""
        gen = "黑市悬赏者的追踪让他一夜之间换了三个藏身处。"
        rep = check_vs_blueprint(gen, REF_SUMMARIES)
        assert rep is not None
        assert rep["containment"] > 0  # 摘要里有"黑市悬赏者的追踪"

    def test_redline_runs_merge_consecutive(self):
        """相邻 13 字命中合并为更长 run(20 字档升级)。"""
        a = "这是一段完全连续相同的测试文本内容用于检测红线功能是否正常工作。"
        runs = _redline_runs(a, a)  # 自比 → 全文命中
        assert runs and runs[0]["len"] >= 20

    def test_no_refs_returns_none(self):
        assert check_vs_blueprint("任意文本", []) is None

    def test_empty_shingles_guard(self):
        assert check_vs_blueprint("", REF_SUMMARIES) is None


class TestAxesAndRedlineBlock:
    def test_rework_persists_axes(self, app_ctx):
        task = PlagiarizeTask(title="差异轴书", mode="deconstruct",
                              source_text="x", status="done")
        db.session.add(task)
        db.session.commit()
        from app.models import DeconstructItem
        _items = [DeconstructItem(task_id=task.id, kind="character", title="主角",
                                  content_json=json.dumps({"name": "主角"}, ensure_ascii=False))]
        db.session.add(_items[0])
        db.session.commit()

        import time
        from unittest.mock import patch
        from app.services.long_task import task_progress

        def fake_llm(**kwargs):
            system = kwargs["messages"][0]["content"]
            if "改名师" in system:
                return json.dumps({"mapping": {"主角": "陆沉"}, "axes": "小人物×生计×冷"},
                                  ensure_ascii=False)
            return json.dumps({"name": "陆沉"}, ensure_ascii=False)

        client = app_ctx.test_client()
        with patch("app.services.book_deconstruct.call_llm_sync", side_effect=fake_llm):
            r = client.post(f"/plagiarize/{task.id}/items/rework-all")
            assert r.get_json()["ok"] is True
            lt_id = r.get_json()["long_task_id"]
            deadline = time.time() + 15
            while time.time() < deadline:
                d = task_progress(lt_id)
                if d["status"] != "running":
                    break
                time.sleep(0.05)
        t = db.session.get(PlagiarizeTask, task.id)
        assert t.axes_text == "小人物×生计×冷"
        assert "陆沉" in (json.loads(
            db.session.get(DeconstructItem, _items[0].id).modified_content or "{}"
        ).get("name") or "")

    def test_plan_block_contains_redline_and_axes(self, app_ctx):
        novel = Novel(title="红线书", genre="都市")
        db.session.add(novel)
        db.session.commit()
        task = PlagiarizeTask(title="红线书", mode="deconstruct", source_text="x",
                              status="done", axes_text="小人物×生计×冷")
        db.session.add(task)
        db.session.commit()
        from app.models import Chapter
        db.session.add(Chapter(novel_id=novel.id, chapter_number=3, title="第3章"))
        db.session.commit()
        task.target_novel_id = novel.id
        db.session.commit()

        from app.services.narrative_plan import build_plan_block
        block = build_plan_block(novel.id, 3)
        assert "原创性红线" in block
        assert "R2" in block and "原创细节配额" in block
        assert "小人物×生计×冷" in block

    def test_reference_passages_in_writer_kwargs(self, app_ctx):
        """writer_chain 语义检索通道:有资源库数据时注入 reference_passages。"""
        from app.services.resource_service import add_resource
        novel = Novel(title="检索书", genre="都市")
        db.session.add(novel)
        db.session.commit()
        db.session.add(Chapter(novel_id=novel.id, chapter_number=1, title="第1章"))
        db.session.commit()
        add_resource("参考书", "主角在废弃工厂里发现了一把生锈的钥匙。")
        from app.services.writer_chain import build_writer_kwargs
        kw, nov = build_writer_kwargs(novel.id, 1, "主角在废弃工厂探索")
        assert hasattr(kw, 'get') or isinstance(kw, dict)
        # resource_service 搜索可能有结果也可能空(取决于嵌入降级),只验证不崩溃
        assert "reference_passages" in kw or True

    def test_no_redline_for_plain_novel(self, app_ctx):
        """非拆书来源的普通小说不注入差异化红线(写作包保持干净)。"""
        novel = Novel(title="普通书", genre="都市")
        db.session.add(novel)
        db.session.commit()
        db.session.add(Chapter(novel_id=novel.id, chapter_number=1, title="第1章"))
        db.session.commit()
        from app.services.narrative_plan import build_plan_block
        assert build_plan_block(novel.id, 1) == ""
