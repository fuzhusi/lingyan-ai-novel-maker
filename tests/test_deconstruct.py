"""拆书复刻测试：拆解解析/章节切分/报告合成/条目采纳/复刻生成接线。

覆盖：
- 六维拆解 JSON 稳健解析（明文/代码围栏/垃圾输入）
- 章节切分（有章节标记 / 无标记定长分块）
- 拆书报告合成
- 条目采纳（保存修改稿 + 标记状态，不写知识库）
- 拆书路由：mock LLM 流 → 落 elements + 报告 + 待确认条目
- 复刻为长篇：建小说 + 已采纳条目落知识库（角色/世界观/大纲/章节）+ 兜底章节
- 复刻为短篇：建短篇 + 策划字段 + 大纲节点
- 丢弃防护（已落库不可丢）/ LLM 输出防御性转换
"""
import json
import re
import time

import pytest
from unittest.mock import patch

from app import create_app, db
from app.models import (
    PlagiarizeTask, DeconstructItem, Novel, Character, WorldSetting, OutlineNode,
    Chapter, ChapterVersion, ShortStory, Foreshadowing, BlindReview,
)
from app.services.book_deconstruct import (
    _extract_json, _split_chapters, compose_report, adopt_item, adopt_all_items,
)

SAMPLE_ELEMENTS = {
    "opening_rhythm": {
        "hook": {"type": "悬念", "description": "主角开局被杀穿越", "reader_expectation": "金手指何时出现"},
        "first_200_words": "死亡开局",
        "rhythm_steps": [{"step": "开局事件", "description": "主角死亡穿越"}],
        "migratable_methods": ["第一页出钩子"],
    },
    "golden_finger": {
        "name": "签到系统", "type": "系统",
        "rules": ["每日签到得奖励"], "growth_design": "签到奖励随等级成长",
        "satisfaction_points": [{"type": "打脸爽", "description": "签到打脸"}],
        "migratable_methods": ["金手指带成长线"],
    },
    "structure": {
        "main_conflict": "复仇", "theme": "救赎",
        "stages": [
            {"stage_name": "第一卷 崛起", "chapter_start": 1, "chapter_end": 10,
             "stage_outline": "主角觉醒系统", "key_events": ["觉醒系统", "首战告捷"]},
        ],
        "turning_points": [{"moment": "第10章", "impact": "身份暴露"}],
        "migratable_methods": ["每阶段一个钩子"],
    },
    "characters": [
        {"name": "主角", "role": "主角", "personality": "隐忍", "speaking_style": "寡言",
         "background": "孤儿", "motivation": "复仇", "arc_direction": "从隐忍到爆发",
         "first_event": "觉醒系统", "exit_event": "首战告捷", "exit_mode": "弧光完成"},
        {"name": "反派", "role": "反派", "personality": "残暴"},
    ],
    "world": [
        {"category": "规则", "title": "灵气复苏", "content": "世界灵气复苏，人人可修行"},
    ],
    "foreshadows": [
        {"title": "神秘玉佩", "description": "第1章玉佩异动，回收时揭晓身世",
         "planted_event": "觉醒系统", "resolve_event": "首战告捷", "importance": 8},
    ],
    "style": {"tone": "热血", "rhythm": "短句快节奏", "migratable_methods": ["打斗用短句"]},
}


@pytest.fixture
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        # 清理孤儿行（SQLite 无 AUTOINCREMENT，rowid 复用会串台到新对象）
        valid_task_ids = db.session.query(PlagiarizeTask.id)
        DeconstructItem.query.filter(
            DeconstructItem.task_id.notin_(valid_task_ids)
        ).delete(synchronize_session=False)
        valid_novel_ids = db.session.query(Novel.id)
        Character.query.filter(Character.novel_id.notin_(valid_novel_ids)).delete(synchronize_session=False)
        WorldSetting.query.filter(WorldSetting.novel_id.notin_(valid_novel_ids)).delete(synchronize_session=False)
        OutlineNode.query.filter(OutlineNode.novel_id.notin_(valid_novel_ids)).delete(synchronize_session=False)
        Chapter.query.filter(Chapter.novel_id.notin_(valid_novel_ids)).delete(synchronize_session=False)
        # 章节版本孤儿行也要清：rowid 复用会让旧版本撞唯一约束、污染「已写」判断
        ChapterVersion.query.filter(
            ChapterVersion.chapter_id.notin_(db.session.query(Chapter.id))
        ).delete(synchronize_session=False)
        # 伏笔孤儿行：rowid 复用会让新小说看到上一轮测试的伏笔计划
        Foreshadowing.query.filter(Foreshadowing.novel_id.notin_(valid_novel_ids)).delete(synchronize_session=False)
        db.session.commit()
        max_task = db.session.query(db.func.max(PlagiarizeTask.id)).scalar() or 0
        max_novel = db.session.query(db.func.max(Novel.id)).scalar() or 0
        max_story = db.session.query(db.func.max(ShortStory.id)).scalar() or 0
        yield app
        # 先清外围引用(盲审挂版本/短篇),再走 ORM 级联删除(FK ON 下 bulk delete 会被拦截)
        new_novel_ids = [r[0] for r in db.session.query(Novel.id).filter(Novel.id > max_novel)]
        new_story_ids = [r[0] for r in db.session.query(ShortStory.id).filter(ShortStory.id > max_story)]
        if new_novel_ids:
            vids = [r[0] for r in db.session.query(ChapterVersion.id)
                    .filter(ChapterVersion.chapter_id.in_(
                        db.session.query(Chapter.id).filter(Chapter.novel_id.in_(new_novel_ids))))]
            if vids:
                BlindReview.query.filter(BlindReview.version_id.in_(vids)).delete(synchronize_session=False)
        if new_story_ids:
            BlindReview.query.filter(BlindReview.story_id.in_(new_story_ids)).delete(synchronize_session=False)
        task_ids = [r[0] for r in db.session.query(PlagiarizeTask.id)
                    .filter(PlagiarizeTask.id > max_task)]
        if task_ids:
            DeconstructItem.query.filter(DeconstructItem.task_id.in_(task_ids)) \
                .delete(synchronize_session=False)
        PlagiarizeTask.query.filter(PlagiarizeTask.id > max_task).delete(synchronize_session=False)
        for n in Novel.query.filter(Novel.id > max_novel).all():
            for ch in list(n.chapters):
                db.session.delete(ch)  # 先删章节(大纲节点级联不做章节置空)
            db.session.delete(n)  # ORM 级联收角色/世界观/大纲/伏笔/关系/状态
        for s in ShortStory.query.filter(ShortStory.id > max_story).all():
            db.session.delete(s)
        db.session.commit()



def _wait_task(client, lt_id, timeout=20):
    """轮询长任务至结束(须在 mock patch 上下文内调用)。"""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = client.get(f"/plagiarize/long-tasks/{lt_id}").get_json()
        if d.get("status") != "running":
            return d
        time.sleep(0.05)
    raise AssertionError("长任务超时未完成")


def _make_task(app_ctx, **kwargs):
    defaults = dict(title="测试对标书", mode="deconstruct",
                    source_text="第一章 觉醒\n主角穿越。\n第二章 修炼\n主角变强。",
                    status="pending")
    defaults.update(kwargs)
    t = PlagiarizeTask(**defaults)
    db.session.add(t)
    db.session.commit()
    return t


def _make_items(task, kinds=("character", "character", "world", "outline", "outline")):
    """按 SAMPLE_ELEMENTS 落条目，返回条目列表（按 kind 顺序）。"""
    items = []
    char_data = SAMPLE_ELEMENTS["characters"]
    world_data = SAMPLE_ELEMENTS["world"]
    stages = SAMPLE_ELEMENTS["structure"]["stages"]
    fs_data = SAMPLE_ELEMENTS["foreshadows"]
    idx_c, idx_w, idx_o, idx_f = 0, 0, 0, 0
    key_events = stages[0]["key_events"]
    for kind in kinds:
        if kind == "character":
            d = char_data[idx_c % len(char_data)]
            idx_c += 1
            item = DeconstructItem(task_id=task.id, kind="character", title=d["name"],
                                   content_json=json.dumps(d, ensure_ascii=False))
        elif kind == "world":
            d = world_data[idx_w % len(world_data)]
            idx_w += 1
            item = DeconstructItem(task_id=task.id, kind="world", title=d["title"],
                                   content_json=json.dumps(d, ensure_ascii=False))
        elif kind == "foreshadow":
            d = fs_data[idx_f % len(fs_data)]
            idx_f += 1
            item = DeconstructItem(task_id=task.id, kind="foreshadow", title=d["title"],
                                   content_json=json.dumps(d, ensure_ascii=False))
        else:
            ev = key_events[idx_o % len(key_events)]
            idx_o += 1
            item = DeconstructItem(
                task_id=task.id, kind="outline", title=ev,
                content_json=json.dumps(
                    {"phase": stages[0]["stage_name"], "title": ev, "summary": stages[0]["stage_outline"]},
                    ensure_ascii=False))
        db.session.add(item)
        items.append(item)
    db.session.commit()
    return items


# ---------------------------------------------------------------------------
# 解析与合成
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_plain_json(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_trailing_text(self):
        assert _extract_json('好的，结果如下：{"a": 1} 完') == {"a": 1}

    def test_garbage(self):
        assert _extract_json("这不是 JSON") is None

    def test_empty(self):
        assert _extract_json("") is None


class TestSplitChapters:
    def test_with_markers(self):
        body = "主角在废墟中醒来，浑身是伤。" * 5
        text = f"第一章 觉醒\n{body}\n\n第二章 修炼\n{body}\n\n第三章 突破\n{body}"
        chunks = _split_chapters(text)
        assert len(chunks) == 3
        assert chunks[0][0].startswith("第一章")

    def test_toc_only_falls_back_to_chunks(self):
        """全是章节标题行（目录）时回退定长分块。"""
        text = "第一章 觉醒\n第二章 修炼\n第三章 突破\n" + "正文内容。" * 200
        chunks = _split_chapters(text)
        assert len(chunks) >= 1

    def test_no_markers_chunked(self):
        text = "甲" * 9000
        chunks = _split_chapters(text)
        assert len(chunks) >= 2

    def test_empty(self):
        assert _split_chapters("") == []


class TestComposeReport:
    def test_builds_markdown(self):
        report = compose_report(SAMPLE_ELEMENTS)
        assert "开篇节奏" in report
        assert "金手指" in report
        assert "整体架构" in report
        assert "人物" in report
        assert "世界观" in report
        assert "文风" in report

    def test_empty(self):
        assert compose_report({}) == ""


# ---------------------------------------------------------------------------
# 条目采纳
# ---------------------------------------------------------------------------

class TestAdoptItem:
    def test_adopt_marks_and_saves_modified(self, app_ctx):
        task = _make_task(app_ctx)
        items = _make_items(task, kinds=("character",))
        item = items[0]
        ok, msg, target_id = adopt_item(item.id, modified={"name": "新主角", "personality": "冷静"})
        assert ok
        assert target_id is None  # 采纳只确认，不写知识库
        item2 = db.session.get(DeconstructItem, item.id)
        assert item2.status == "adopted"
        assert json.loads(item2.modified_content)["name"] == "新主角"

    def test_adopt_all(self, app_ctx):
        task = _make_task(app_ctx)
        _make_items(task, kinds=("character", "world", "outline"))
        ok, msg = adopt_all_items(task.id)
        assert ok
        assert db.session.query(DeconstructItem).filter_by(
            task_id=task.id, status="pending").count() == 0


# ---------------------------------------------------------------------------
# 拆书路由（mock LLM 流）
# ---------------------------------------------------------------------------

class TestDeconstructRoute:
    def test_deconstruct_creates_items(self, app_ctx):
        task = _make_task(app_ctx)
        client = app_ctx.test_client()

        def fake_stream(**kwargs):
            yield json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)

        with patch("app.services.book_deconstruct.stream_llm_tokens", side_effect=fake_stream):
            r = client.post(f"/plagiarize/{task.id}/deconstruct")
            assert r.get_json()["ok"] is True
            # 轮询须在 patch 上下文内(后台线程执行时 mock 需生效)
            data = _wait_task(client, r.get_json()["long_task_id"])["progress"]
        assert "拆解完成" in data

        t = db.session.get(PlagiarizeTask, task.id)
        assert t.status == "done"
        assert json.loads(t.elements_json)["golden_finger"]["name"] == "签到系统"
        assert "开篇节奏" in t.report_text
        items = DeconstructItem.query.filter_by(task_id=task.id).all()
        kinds = sorted(i.kind for i in items)
        assert kinds.count("character") == 2
        assert kinds.count("world") == 1
        assert kinds.count("outline") == 2


# ---------------------------------------------------------------------------
# 复刻生成
# ---------------------------------------------------------------------------

class TestGenerateLong:
    def test_creates_novel_and_materializes(self, app_ctx):
        task = _make_task(app_ctx)
        task.elements_json = json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)
        db.session.commit()
        items = _make_items(task, kinds=("character", "character", "world", "outline"))
        for it in items:
            it.status = "adopted"
        db.session.commit()

        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/{task.id}/generate-long",
                        data={"title": "新书", "genre": "都市", "chapters": "5", "run": "0"})
        assert r.get_json()["ok"] is True
        data = _wait_task(client, r.get_json()["long_task_id"])["progress"]
        assert "[NOVEL_ID:" in data

        t = db.session.get(PlagiarizeTask, task.id)
        novel = db.session.get(Novel, t.target_novel_id)
        assert novel is not None
        assert novel.title == "新书"
        assert Character.query.filter_by(novel_id=novel.id).count() == 2
        assert WorldSetting.query.filter_by(novel_id=novel.id).count() == 1
        assert OutlineNode.query.filter_by(novel_id=novel.id, node_type="chapter").count() == 1
        assert Chapter.query.filter_by(novel_id=novel.id).count() == 1
        # 条目回填 target_id
        assert all(db.session.get(DeconstructItem, i.id).target_id for i in items)

    def test_requires_deconstruction(self, app_ctx):
        """未拆书直接 generate-long → 400 拒绝（三入口行为统一）。"""
        task = _make_task(app_ctx)
        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/{task.id}/generate-long", data={"title": "x", "run": "0"})
        assert r.status_code == 400
        assert "尚未完成拆书" in r.get_json()["message"]

    def test_fallback_chapters_when_nothing_adopted(self, app_ctx):
        """未采纳任何大纲条目时按 fallback_chapters 建空大纲章节兜底。"""
        task = _make_task(app_ctx)
        task.elements_json = json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)
        db.session.commit()
        _make_items(task, kinds=("character", "world", "outline"))  # 全部保持 pending

        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/{task.id}/generate-long",
                        data={"title": "兜底书", "run": "0", "chapters": "3"})
        assert r.get_json()["ok"] is True
        data = _wait_task(client, r.get_json()["long_task_id"])["progress"]
        m = re.search(r"\[NOVEL_ID: (\d+)\]", data)
        assert m
        novel = db.session.get(Novel, int(m.group(1)))
        # 兜底 3 章空大纲（流水线会自动补大纲），pending 条目不进知识库
        assert Chapter.query.filter_by(novel_id=novel.id).count() == 3
        assert Character.query.filter_by(novel_id=novel.id).count() == 0

    def test_invalid_target_novel_returns_400(self, app_ctx):
        """target_novel_id 指向不存在的小说 → 400 而非 500。"""
        task = _make_task(app_ctx)
        task.elements_json = json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)
        db.session.commit()
        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/{task.id}/generate-long",
                        data={"title": "x", "run": "0", "target_novel_id": "999999"})
        assert r.get_json()["ok"] is True
        d = _wait_task(client, r.get_json()["long_task_id"])
        assert d["status"] == "failed"
        assert "不存在" in d["progress"]

    def test_regenerate_message_when_already_materialized(self, app_ctx):
        """二次落地：无新增章节时提示「此前已入书」，不再误导「请先采纳」；带新增计数。"""
        task = _make_task(app_ctx)
        task.elements_json = json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)
        db.session.commit()
        items = _make_items(task, kinds=("outline",))
        for it in items:
            it.status = "adopted"
        db.session.commit()

        client = app_ctx.test_client()
        r1 = client.post(f"/plagiarize/{task.id}/generate-long",
                         data={"title": "首跑", "run": "0", "chapters": "0"})
        _wait_task(client, r1.get_json()["long_task_id"])
        r = client.post(f"/plagiarize/{task.id}/generate-long",
                        data={"title": "二跑", "run": "0", "chapters": "0"})
        data = _wait_task(client, r.get_json()["long_task_id"])["progress"]
        assert "此前已全部入书" in data
        assert "请先" not in data
        assert "新增：人物 0 / 世界观 0 / 大纲 0" in data  # 幂等跳过不计入新增

    def test_run_generates_unwritten_chapters(self, app_ctx):
        """run=1 且无新增章节时，补生成目标书尚无正文的章节。"""
        task = _make_task(app_ctx, modifications_text="指令Y")
        task.elements_json = json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)
        db.session.commit()
        items = _make_items(task, kinds=("outline",))
        for it in items:
            it.status = "adopted"
        db.session.commit()

        client = app_ctx.test_client()
        # 首跑落地（建 1 章无正文）
        r0 = client.post(f"/plagiarize/{task.id}/generate-long",
                         data={"title": "首跑", "run": "0", "chapters": "0"})
        _wait_task(client, r0.get_json()["long_task_id"])

        captured = {}

        def fake_pipeline(novel_id, chapter_number, user_directive="", auto_save=False):
            captured["directive"] = user_directive
            return {"human_score": 77, "stages": [], "text": "正文", "saved_version_id": 1}

        with patch("app.services.chapter_runner.run_chapter_pipeline", side_effect=fake_pipeline):
            r = client.post(f"/plagiarize/{task.id}/generate-long",
                            data={"title": "二跑", "run": "1", "chapters": "5"})
            data = _wait_task(client, r.get_json()["long_task_id"])["progress"]
        assert "补生成" in data
        assert captured["directive"] == "指令Y"


class TestTemplateRegression:
    """复审 P0 回归锁:工作台/新建页的关键 DOM 与 JS 必须存在。"""

    def _setup(self, app_ctx):
        task = _make_task(app_ctx, status="done", modifications_text="换都市")
        db.session.add(DeconstructItem(task_id=task.id, kind="character", title="主角",
                                       content_json='{"name":"主角"}'))
        db.session.commit()
        return task

    def test_new_page_key_elements(self, app_ctx):
        """新建页:id=source_text(缺失会让上传 JS 整块死亡)+ 字数计数器。"""
        client = app_ctx.test_client()
        body = client.get("/plagiarize/new").get_data(as_text=True)
        assert 'id="source_text"' in body
        assert "src-count" in body

    def test_workbench_key_elements(self, app_ctx):
        """工作台:markAdoptedCard 定义/折叠/取消按钮/局部更新/步骤条/恢复轮询钩子。"""
        task = _make_task(app_ctx, status="done", modifications_text="换都市")
        client = app_ctx.test_client()
        body = client.get(f"/plagiarize/{task.id}").get_data(as_text=True)
        assert "function markAdoptedCard" in body      # 采纳局部更新
        assert 'id="adopted-count"' in body
        assert "card-actions" in body and "toggleFields" in body
        assert "btn-cancel-task" in body and "cancelTask" in body
        assert "restoreItem" in body
        assert "① 拆书" in body and "④ 复刻生成" in body
        assert "running_lt" in body or "pollTask(" in body

class TestUnwrittenChapters:
    """unwritten_chapters：排序/过滤/limit 归一（0 与负数不得退化成无上限）。"""

    def _setup(self, app_ctx, n=5, written=(1,)):
        novel = Novel(title="补生成书", genre="")
        db.session.add(novel)
        db.session.commit()
        from app.models import ChapterVersion
        for i in range(1, n + 1):
            ch = Chapter(novel_id=novel.id, chapter_number=i, title=f"第{i}章")
            db.session.add(ch)
            db.session.flush()
            if i in written:
                db.session.add(ChapterVersion(chapter_id=ch.id, version_number=1, content="正文"))
        db.session.commit()
        return novel

    def test_filters_written_and_sorted(self, app_ctx):
        novel = self._setup(app_ctx, n=5, written=(1, 3))
        from app.services.book_deconstruct import unwritten_chapters
        got = unwritten_chapters(novel.id)
        assert [c.chapter_number for c in got] == [2, 4, 5]

    def test_limit_clamps(self, app_ctx):
        novel = self._setup(app_ctx, n=5, written=())
        from app.services.book_deconstruct import unwritten_chapters
        assert len(unwritten_chapters(novel.id, limit=2)) == 2
        # 0/负数兜底为 1，绝不退化成无上限全本
        assert len(unwritten_chapters(novel.id, limit=0)) == 1
        assert len(unwritten_chapters(novel.id, limit=-3)) == 1
        assert len(unwritten_chapters(novel.id)) == 5  # None = 不限


class TestHeartbeatStream:
    """_stream_elements：心跳不污染 collected、错误路径、取消路径。"""

    def test_heartbeat_yielded_but_not_collected(self, app_ctx):
        """慢速 mock 流 + 极短心跳窗口：心跳被 yield 但 JSON 仍完整解析。"""
        _make_task(app_ctx)
        payload = json.dumps({"golden_finger": {"name": "系统"}})

        def slow_stream(**kwargs):
            yield payload[:10]
            time.sleep(0.05)  # 超过心跳窗口，应触发至少一次心跳
            yield payload[10:]

        from app.services.book_deconstruct import _stream_elements
        gen = _stream_elements("sys", "user", "测试", heartbeat_secs=0.01)
        with patch("app.services.book_deconstruct.stream_llm_tokens", side_effect=slow_stream):
            chunks = []
            try:
                while True:
                    chunks.append(next(gen))
            except StopIteration as stop:
                elements, err = stop.value
        assert err is None
        assert elements["golden_finger"]["name"] == "系统"
        assert any("仍在生成" in c for c in chunks)

    def test_stream_error_returns_error(self, app_ctx):
        from app.services.book_deconstruct import _stream_elements
        from app.services.llm import LLMError

        def failing_stream(**kwargs):
            yield '{"partial"'
            raise LLMError("接口故障")

        gen = _stream_elements("sys", "user", "测试", heartbeat_secs=0.01)
        with patch("app.services.book_deconstruct.stream_llm_tokens", side_effect=failing_stream):
            try:
                while True:
                    next(gen)
            except StopIteration as stop:
                elements, err = stop.value
        assert elements is None
        assert "接口故障" in err

    def test_cancel_on_close(self, app_ctx):
        """close() 触发 GeneratorExit：状态兜底置 failed（断开不卡「拆解中」）。"""
        task = _make_task(app_ctx, status="deconstructing")

        def endless_stream(**kwargs):
            yield "chunk1"
            time.sleep(0.3)
            yield "chunk2"

        from app.services.book_deconstruct import deconstruct_source
        gen = deconstruct_source(task.id)
        with patch("app.services.book_deconstruct.stream_llm_tokens", side_effect=endless_stream):
            next(gen)  # 消费一个 chunk
            gen.close()  # 模拟客户端断开
        assert db.session.get(PlagiarizeTask, task.id).status == "failed"


class TestDiscardGuard:
    def test_cannot_discard_materialized_item(self, app_ctx):
        """已落库（adopted + target_id）的条目不可丢弃。"""
        task = _make_task(app_ctx)
        items = _make_items(task, kinds=("world",))
        items[0].status = "adopted"
        items[0].target_id = 123
        db.session.commit()
        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/items/{items[0].id}/discard")
        assert r.status_code == 400
        assert db.session.get(DeconstructItem, items[0].id).status == "adopted"

    def test_can_discard_adopted_without_target(self, app_ctx):
        """已采纳但未落库的条目可反悔丢弃。"""
        task = _make_task(app_ctx)
        items = _make_items(task, kinds=("world",))
        items[0].status = "adopted"
        items[0].target_id = None
        db.session.commit()
        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/items/{items[0].id}/discard")
        assert r.status_code == 200
        assert db.session.get(DeconstructItem, items[0].id).status == "discarded"


class TestDefensiveCoercion:
    def test_build_items_with_nonstring_fields(self, app_ctx):
        """LLM 输出非字符串字段（如数字 name）不崩溃。"""
        task = _make_task(app_ctx)
        elements = {
            "characters": [{"name": 12345, "role": "主角"}],
            "world": [{"category": "规则", "title": 67890, "content": "x"}],
            "structure": {"stages": [{"stage_name": "第一卷", "key_events": ["事件A", 42]}]},
        }
        from app.services.book_deconstruct import _build_items
        counts = _build_items(task, elements)
        assert counts["characters"] == 1
        assert counts["world"] == 1
        assert counts["outline"] == 2
        item = DeconstructItem.query.filter_by(task_id=task.id, kind="character").first()
        assert item.title == "12345"

    def test_build_items_with_container_types(self, app_ctx):
        """structure 为 list/str 等异常容器类型不崩溃。"""
        task = _make_task(app_ctx)
        from app.services.book_deconstruct import _build_items, compose_report
        assert _build_items(task, {"structure": ["意外"]})["outline"] == 0
        assert _build_items(task, {"structure": "意外", "characters": "单字符串"})["outline"] == 0
        # compose_report 对字符串型列表字段按整条输出，不逐字拆行
        report = compose_report({"structure": {"migratable_methods": "每章留钩子"}})
        assert "迁移方法：每章留钩子" in report


class TestDeconstructFailurePaths:
    def test_unparseable_output_marks_failed(self, app_ctx):
        """LLM 输出无法解析为 JSON → status=failed。"""
        task = _make_task(app_ctx)
        client = app_ctx.test_client()

        def fake_stream(**kwargs):
            yield "这不是 JSON，也找不到花括号"

        with patch("app.services.book_deconstruct.stream_llm_tokens", side_effect=fake_stream):
            r = client.post(f"/plagiarize/{task.id}/deconstruct")
            d = _wait_task(client, r.get_json()["long_task_id"])
        assert d["status"] == "failed"
        assert "拆解失败" in d["progress"]
        assert db.session.get(PlagiarizeTask, task.id).status == "failed"

    def test_no_source_text_rejected(self, app_ctx):
        task = _make_task(app_ctx, source_text="")
        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/{task.id}/deconstruct")
        assert r.status_code == 400


class TestSummarizePipeline:
    def test_long_text_summarizes_then_deconstructs(self, app_ctx):
        """超长文本先逐章摘要（mock call_llm_sync）再拆解。"""
        task = _make_task(app_ctx)
        chapter_body = "主角一路升级打怪，收获颇多。" * 100  # ~1400 字
        task.source_text = "".join(f"第{i}章 试炼\n{chapter_body}\n" for i in range(1, 16))
        db.session.commit()

        from app.services.book_deconstruct import summarize_chapters

        def fake_summarize(**kwargs):
            content = kwargs["messages"][1]["content"]
            n = content.count("【第")
            return json.dumps(
                [{"chapter_no": i + 1, "summary": "主角升级打怪的章节摘要。"} for i in range(n)],
                ensure_ascii=False)

        with patch("app.services.book_deconstruct.call_llm_sync", side_effect=fake_summarize):
            chunks = list(summarize_chapters(task.id))
        t = db.session.get(PlagiarizeTask, task.id)
        summaries = json.loads(t.chapters_summary_json)
        assert len(summaries) == 15
        assert summaries[0]["summary"] == "主角升级打怪的章节摘要。"
        assert any("章级摘要完成" in c for c in chunks)

    def test_summarize_resumable(self, app_ctx):
        """断点续跑：已完成的章摘要跳过，只补剩余章（合批后 4 章 = 1 次调用）。"""
        task = _make_task(app_ctx)
        chapter_body = "主角一路升级打怪，收获颇多。" * 5
        task.source_text = "".join(f"第{i}章 试炼\n{chapter_body}\n" for i in range(1, 6))
        task.chapters_summary_json = json.dumps(
            [{"index": 1, "title": "第1章 试炼", "summary": "已完成的摘要。"}], ensure_ascii=False)
        db.session.commit()
        from app.services.book_deconstruct import summarize_chapters

        calls = []

        def fake_summarize(**kwargs):
            calls.append(kwargs["messages"][1]["content"][:20])
            content = kwargs["messages"][1]["content"]
            n = content.count("【第")
            return json.dumps(
                [{"chapter_no": i + 1, "summary": "新摘要。"} for i in range(n)],
                ensure_ascii=False)

        with patch("app.services.book_deconstruct.call_llm_sync", side_effect=fake_summarize):
            list(summarize_chapters(task.id))
        assert len(calls) == 1  # 4 章剩余 → 1 批 1 次调用
        t = db.session.get(PlagiarizeTask, task.id)
        summaries = json.loads(t.chapters_summary_json)
        assert len(summaries) == 5
        assert summaries[0]["summary"] == "已完成的摘要。"


    def test_summarize_batch_shuffled_chapter_no(self, app_ctx):
        """合批返回乱序 chapter_no 也能按号落位（模型串号防护）。"""
        task = _make_task(app_ctx)
        body = "主角推进剧情。" * 50
        task.source_text = "".join(f"第{i}章 试炼\n{body}\n" for i in range(1, 5))
        db.session.commit()
        from app.services.book_deconstruct import summarize_chapters

        def fake_summarize(**kwargs):
            content = kwargs["messages"][1]["content"]
            nos = [int(m) for m in re.findall(r"【第(\d+)章", content)]
            entries = [{"chapter_no": n, "summary": f"摘要{n}"} for n in nos]
            entries.reverse()  # 故意乱序返回
            return json.dumps(entries, ensure_ascii=False)

        with patch("app.services.book_deconstruct.call_llm_sync", side_effect=fake_summarize):
            list(summarize_chapters(task.id))
        t = db.session.get(PlagiarizeTask, task.id)
        summaries = json.loads(t.chapters_summary_json)
        assert [s["summary"] for s in summaries] == ["摘要1", "摘要2", "摘要3", "摘要4"]


class TestVolumeConsolidation:
    def test_consolidates_groups_of_50(self, app_ctx):
        """L2 归并：每 50 章一组，逐组落库。"""
        task = _make_task(app_ctx)
        task.chapters_summary_json = json.dumps(
            [{"index": i, "title": f"第{i}章", "summary": f"第{i}章摘要。"} for i in range(1, 121)],
            ensure_ascii=False)
        db.session.commit()
        from app.services.book_deconstruct import consolidate_volumes

        def fake_consolidate(**kwargs):
            return "本卷主线归并摘要。"

        with patch("app.services.book_deconstruct.call_llm_sync", side_effect=fake_consolidate):
            chunks = list(consolidate_volumes(task.id))
        t = db.session.get(PlagiarizeTask, task.id)
        volumes = json.loads(t.volumes_summary_json)
        assert len(volumes) == 3  # 120 章 / 50 = 3 组
        assert volumes[0]["start"] == 1 and volumes[0]["end"] == 50
        assert volumes[2]["end"] == 120
        assert any("卷级归并完成" in c for c in chunks)


class TestMergeElements:
    def test_merge_authoritative_ownership(self):
        """L0 拥有节奏/文风/金手指，L3 拥有架构，人物世界观合并去重。"""
        from app.services.book_deconstruct import _merge_elements
        opening = {
            "opening_rhythm": {"hook": {"description": "开局被杀"}},
            "style": {"tone": "热血"},
            "golden_finger": {"name": "签到系统", "growth_design": "初始形态"},
            "characters": [{"name": "主角", "role": "主角"}],
            "world": [{"title": "灵气复苏", "category": "规则", "content": "x"}],
        }
        glob = {
            "structure": {"main_conflict": "复仇", "stages": [{"stage_name": "卷一"}]},
            "characters": [{"name": "主角", "role": "主角"}, {"name": "反派", "role": "反派"}],
            "world": [{"title": "灵气复苏", "category": "规则", "content": "x"},
                      {"title": "宗门体系", "category": "势力", "content": "y"}],
            "golden_finger_growth": "全书成长线：签到奖励随境界进化",
        }
        merged = _merge_elements(opening, glob)
        assert merged["opening_rhythm"]["hook"]["description"] == "开局被杀"
        assert merged["style"]["tone"] == "热血"
        assert merged["structure"]["main_conflict"] == "复仇"
        assert merged["golden_finger"]["growth_design"] == "全书成长线：签到奖励随境界进化"
        assert merged["golden_finger"]["name"] == "签到系统"
        assert [c["name"] for c in merged["characters"]] == ["主角", "反派"]
        assert len(merged["world"]) == 2

    def test_merge_empty(self):
        from app.services.book_deconstruct import _merge_elements
        assert _merge_elements({}, {}) == {}


class TestTimelineMaterialization:
    """落库时间轴：事件锚 → 章节号换算，伏笔双锚点 + 人物 plan。"""

    def test_foreshadow_anchors_resolved(self, app_ctx):
        task = _make_task(app_ctx)
        task.elements_json = json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)
        db.session.commit()
        # 两个大纲条目(觉醒系统/首战告捷) + 伏笔条目,全部采纳
        items = _make_items(task, kinds=("outline", "outline", "foreshadow"))
        for it in items:
            it.status = "adopted"
        db.session.commit()

        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/{task.id}/generate-long",
                        data={"title": "锚点书", "run": "0", "chapters": "0"})
        _wait_task(client, r.get_json()["long_task_id"])
        t = db.session.get(PlagiarizeTask, task.id)
        novel = db.session.get(Novel, t.target_novel_id)
        # 两个事件 → 章 1/2;伏笔埋于事件1(章1),预期收于事件2(章2)
        fs = Foreshadowing.query.filter_by(novel_id=novel.id).first()
        assert fs is not None
        assert fs.planted_chapter == 1
        assert fs.expected_resolve_chapter == 2
        assert fs.earliest_resolve_chapter == 2  # 不可早于埋设章+1
        assert fs.status == "planned"
        assert "觉醒系统" in (fs.source_event or "")
        # 幂等:再跑一次不重复落库
        r2 = client.post(f"/plagiarize/{task.id}/generate-long",
                         data={"title": "二跑", "run": "0", "chapters": "0"})
        _wait_task(client, r2.get_json()["long_task_id"])
        assert Foreshadowing.query.filter_by(novel_id=novel.id).count() == 1

    def test_unmapped_anchor_warns_not_guesses(self, app_ctx):
        """锚点事件未建章 → 降级 null + 警告,不瞎猜章号(StoryForge 纪律)。"""
        task = _make_task(app_ctx)
        task.elements_json = json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)
        db.session.commit()
        items = _make_items(task, kinds=("outline", "foreshadow"))
        # 只采纳伏笔,不采纳大纲 → 锚点无章可换
        for it in items:
            it.status = "adopted" if it.kind == "foreshadow" else "pending"
        db.session.commit()

        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/{task.id}/generate-long",
                        data={"title": "警告书", "run": "0", "chapters": "2"})
        d = _wait_task(client, r.get_json()["long_task_id"])
        t = db.session.get(PlagiarizeTask, task.id)
        novel = db.session.get(Novel, t.target_novel_id)
        fs = Foreshadowing.query.filter_by(novel_id=novel.id).first()
        assert fs is not None
        assert fs.planted_chapter is None
        assert fs.expected_resolve_chapter is None
        # 兜底章节也会进映射吗?不会——兜底章无大纲节点,事件映射为空
        assert "没有对应章节" in d["progress"]

    def test_character_plan_into_status_json(self, app_ctx):
        task = _make_task(app_ctx)
        task.elements_json = json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)
        db.session.commit()
        items = _make_items(task, kinds=("character",))
        items[0].status = "adopted"
        db.session.commit()

        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/{task.id}/generate-long",
                        data={"title": "计划书", "run": "0", "chapters": "0"})
        _wait_task(client, r.get_json()["long_task_id"])
        t = db.session.get(PlagiarizeTask, task.id)
        char = Character.query.filter_by(novel_id=t.target_novel_id).first()
        import json as _json
        plan = (_json.loads(char.status_json or "{}").get("plan") or {})
        assert plan.get("first_event") == "觉醒系统"
        assert plan.get("exit_mode") == "弧光完成"

    def test_adopt_merges_preserving_plan_keys(self, app_ctx):
        """UI 表单只提交可见字段时,时间轴锚点等不可见键从现稿保留。"""
        task = _make_task(app_ctx)
        items = _make_items(task, kinds=("character",))
        ok, msg, _ = adopt_item(items[0].id, modified={"name": "新名"})
        assert ok
        saved = json.loads(db.session.get(DeconstructItem, items[0].id).modified_content)
        assert saved["name"] == "新名"
        assert saved.get("first_event") == "觉醒系统"  # 不可见键保留
        assert saved.get("arc_direction") == "从隐忍到爆发"


class TestRework:
    """AI 差异化改写:单条/批量成套/同名校验/还原。"""

    REWORKED = {"name": "陆沉", "role": "主角", "personality": "冷静克制", "speaking_style": "简短",
                "appearance": "瘦高", "background": "市井出身", "motivation": "护住家人",
                "arc_direction": "从隐忍到爆发", "relationships": "与反派宿敌",
                "migratable_methods": "小人物视角", "first_event": "觉醒系统",
                "exit_event": "首战告捷", "exit_mode": "弧光完成"}

    def test_rework_single_writes_modified(self, app_ctx):
        task = _make_task(app_ctx, modifications_text="换都市题材")
        items = _make_items(task, kinds=("character",))
        client = app_ctx.test_client()
        with patch("app.services.book_deconstruct.call_llm_sync",
                   return_value=json.dumps(self.REWORKED, ensure_ascii=False)):
            r = client.post(f"/plagiarize/items/{items[0].id}/rework")
        j = r.get_json()
        assert j["ok"] is True
        assert j["warnings"] == []  # 名字改了,锚点没动
        saved = json.loads(db.session.get(DeconstructItem, items[0].id).modified_content)
        assert saved["name"] == "陆沉"
        assert saved["first_event"] == "觉醒系统"  # 锚点保留

    def test_rework_name_unchanged_warns(self, app_ctx):
        task = _make_task(app_ctx)
        items = _make_items(task, kinds=("character",))
        unchanged = dict(self.REWORKED, name="主角")  # 偷懒没改名
        client = app_ctx.test_client()
        with patch("app.services.book_deconstruct.call_llm_sync",
                   return_value=json.dumps(unchanged, ensure_ascii=False)):
            r = client.post(f"/plagiarize/items/{items[0].id}/rework")
        j = r.get_json()
        assert j["ok"] is True
        assert "名称未改" in j["warnings"]

    def test_rework_foreshadow_anchor_changed_warns(self, app_ctx):
        task = _make_task(app_ctx)
        items = _make_items(task, kinds=("foreshadow",))
        bad = dict(SAMPLE_ELEMENTS["foreshadows"][0],
                   description="全新情节",
                   planted_event="随便编的事件")  # 锚点被改
        client = app_ctx.test_client()
        with patch("app.services.book_deconstruct.call_llm_sync",
                   return_value=json.dumps(bad, ensure_ascii=False)):
            r = client.post(f"/plagiarize/items/{items[0].id}/rework")
        assert "事件锚点被改动" in r.get_json()["warnings"]

    def test_rework_refused_when_materialized(self, app_ctx):
        task = _make_task(app_ctx)
        items = _make_items(task, kinds=("character",))
        items[0].status = "adopted"
        items[0].target_id = 777
        db.session.commit()
        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/items/{items[0].id}/rework")
        assert r.get_json()["ok"] is False

    def test_reset_clears_modified(self, app_ctx):
        task = _make_task(app_ctx)
        items = _make_items(task, kinds=("character",))
        items[0].modified_content = json.dumps({"name": "改过的"}, ensure_ascii=False)
        db.session.commit()
        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/items/{items[0].id}/reset")
        assert r.get_json()["ok"] is True
        assert db.session.get(DeconstructItem, items[0].id).modified_content == ""

    def test_rework_all_with_mapping(self, app_ctx):
        """批量成套改写:先映射表,再逐条;改写稿带映射新名。"""
        task = _make_task(app_ctx, modifications_text="换都市")
        items = _make_items(task, kinds=("character", "world"))
        client = app_ctx.test_client()

        def fake_llm(**kwargs):
            system = kwargs["messages"][0]["content"]
            if "改名师" in system:
                return json.dumps({"mapping": {"主角": "陆沉", "灵气复苏": "元气潮汐"},
                                   "axes": "小人物×生计×冷"}, ensure_ascii=False)
            return json.dumps(self.REWORKED, ensure_ascii=False)

        with patch("app.services.book_deconstruct.call_llm_sync", side_effect=fake_llm):
            r = client.post(f"/plagiarize/{task.id}/items/rework-all")
            data = _wait_task(client, r.get_json()["long_task_id"])["progress"]
        assert "新旧名映射表" in data
        assert "差异轴" in data
        assert "批量改写完成" in data
        for it in items:
            assert db.session.get(DeconstructItem, it.id).modified_content

    def test_build_items_counts_foreshadow(self, app_ctx):
        """拆解路由后伏笔候选进队列。"""
        task = _make_task(app_ctx)
        client = app_ctx.test_client()

        def fake_stream(**kwargs):
            yield json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)

        with patch("app.services.book_deconstruct.stream_llm_tokens", side_effect=fake_stream):
            r = client.post(f"/plagiarize/{task.id}/deconstruct")
            d = _wait_task(client, r.get_json()["long_task_id"])
        items = DeconstructItem.query.filter_by(task_id=task.id, kind="foreshadow").all()
        assert len(items) == 1
        assert "拆解完成" in d["progress"]


class TestBlueprintInjection:
    """P0-1/P0-2：节奏/文风进创作罗盘，微创新指令进生成链。"""

    def test_author_intent_includes_rhythm_style_and_modifications(self, app_ctx):
        task = _make_task(app_ctx, modifications_text="换都市题材；金手指加代价")
        task.elements_json = json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)
        db.session.commit()
        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/{task.id}/generate-long",
                        data={"title": "注入书", "run": "0", "chapters": "0"})
        _wait_task(client, r.get_json()["long_task_id"])
        t = db.session.get(PlagiarizeTask, task.id)
        novel = db.session.get(Novel, t.target_novel_id)
        assert "开篇钩子（复刻）" in novel.author_intent          # opening_rhythm 注入
        assert "节奏手法（复刻）" in novel.author_intent
        assert "文风（复刻）" in novel.author_intent              # style 注入
        assert "微创新方向（必须执行）" in novel.author_intent     # 微创新注入
        assert "换都市题材" in novel.author_intent

    def test_author_intent_budget_capped(self, app_ctx):
        """罗盘承诺不超预算（约 500 字）。"""
        from app.services.book_deconstruct import _compose_author_intent
        big = {"structure": {"main_conflict": "冲" * 300, "theme": "救赎"},
               "opening_rhythm": {"hook": {"description": "钩" * 200},
                                  "pacing_features": ["节" * 100] * 5,
                                  "migratable_methods": ["法" * 100] * 5},
               "golden_finger": {"name": "系统", "growth_design": "长" * 200},
               "style": {"tone": "热" * 100, "migratable_methods": ["手" * 100] * 5}}
        intent = _compose_author_intent(big["structure"], big["golden_finger"],
                                        big["opening_rhythm"], big["style"], "微" * 300)
        assert len(intent) <= 500

    def test_short_story_gets_extra_instructions(self, app_ctx):
        task = _make_task(app_ctx, modifications_text="短篇微创新：女主视角")
        task.elements_json = json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)
        db.session.commit()
        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/{task.id}/generate-short",
                        data={"title": "注入短篇", "word_target": "3000"})
        j = r.get_json()
        assert j["ok"] is True
        story = db.session.get(ShortStory, j["story_id"])
        assert story.extra_instructions == "短篇微创新：女主视角"

    def test_generate_long_passes_directive_to_pipeline(self, app_ctx):
        """run=1 时微创新指令作为 user_directive 下传章节流水线。"""
        task = _make_task(app_ctx, modifications_text="微创新指令X")
        task.elements_json = json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)
        db.session.commit()
        items = _make_items(task, kinds=("outline",))
        for it in items:
            it.status = "adopted"
        db.session.commit()

        captured = {}

        def fake_pipeline(novel_id, chapter_number, user_directive="", auto_save=False):
            captured["directive"] = user_directive
            return {"human_score": 80, "stages": [], "text": "正文", "saved_version_id": 1}

        client = app_ctx.test_client()
        with patch("app.services.chapter_runner.run_chapter_pipeline", side_effect=fake_pipeline):
            r = client.post(f"/plagiarize/{task.id}/generate-long",
                            data={"title": "指令书", "run": "1", "chapters": "0"})
            _wait_task(client, r.get_json()["long_task_id"])
        assert captured["directive"] == "微创新指令X"


class TestFunnelPipeline:
    def test_long_book_four_stage_funnel(self, app_ctx):
        """长书走四层漏斗：摘要→归并→开篇精读→全局拆解，产物合并。"""
        task = _make_task(app_ctx)
        chapter_body = "主角一路升级打怪。" * 120  # ~1080 字/章，20 章 ≈ 2.1 万字，超过快路阈值
        task.source_text = "".join(f"第{i}章 试炼\n{chapter_body}\n" for i in range(1, 21))
        db.session.commit()
        assert len(task.source_text) > 20000

        opening_json = json.dumps({
            "opening_rhythm": {"hook": {"description": "开局被杀穿越"}},
            "style": {"tone": "热血短句"},
            "golden_finger": {"name": "签到系统"},
            "characters": [{"name": "主角", "role": "主角"}],
        }, ensure_ascii=False)
        global_json = json.dumps({
            "structure": {"main_conflict": "复仇", "theme": "救赎",
                          "stages": [{"stage_name": "卷一 崛起", "chapter_start": 1, "chapter_end": 20,
                                      "stage_outline": "主角觉醒", "key_events": ["觉醒系统"]}]},
            "characters": [{"name": "主角", "role": "主角"}, {"name": "反派", "role": "反派"}],
            "world": [{"category": "规则", "title": "灵气复苏", "content": "x"}],
            "golden_finger_growth": "签到奖励随境界进化",
        }, ensure_ascii=False)

        def fake_stream(**kwargs):
            sys_prompt = kwargs["messages"][0]["content"]
            # L0 开篇精读的系统提示含「开篇原文」，L3 全局拆解的不含
            if "开篇原文" in sys_prompt:
                yield opening_json
            else:
                yield global_json

        def fake_llm_sync(**kwargs):
            return "摘要或归并文本。"

        client = app_ctx.test_client()
        with patch("app.services.book_deconstruct.stream_llm_tokens", side_effect=fake_stream), \
             patch("app.services.book_deconstruct.call_llm_sync", side_effect=fake_llm_sync):
            r = client.post(f"/plagiarize/{task.id}/deconstruct")
            data = _wait_task(client, r.get_json()["long_task_id"])["progress"]
        assert "拆解完成" in data

        t = db.session.get(PlagiarizeTask, task.id)
        assert t.status == "done"
        volumes = json.loads(t.volumes_summary_json)
        assert len(volumes) == 1  # 20 章 → 1 卷
        elements = json.loads(t.elements_json)
        # 节奏/文风来自 L0（原文），架构来自 L3（全书摘要）
        assert elements["opening_rhythm"]["hook"]["description"] == "开局被杀穿越"
        assert elements["style"]["tone"] == "热血短句"
        assert elements["structure"]["main_conflict"] == "复仇"
        assert elements["golden_finger"]["growth_design"] == "签到奖励随境界进化"
        # 人物合并去重：主角来自开篇（优先），反派来自全局补充
        assert [c["name"] for c in elements["characters"]] == ["主角", "反派"]
        items = DeconstructItem.query.filter_by(task_id=task.id).all()
        assert len([i for i in items if i.kind == "outline"]) == 1

    def test_summarize_llm_error_falls_back_to_body(self, app_ctx):
        """单章摘要 LLM 失败时用截断正文兜底，不中断管线。"""
        task = _make_task(app_ctx)
        chapter_body = "这一章的内容足够长，可以用来兜底。" * 30
        task.source_text = f"第一章 试炼\n{chapter_body}\n第二章 突破\n{chapter_body}"
        db.session.commit()
        from app.services.book_deconstruct import summarize_chapters
        from app.services.llm import LLMError

        def fake_fail(**kwargs):
            raise LLMError("模拟接口故障")

        with patch("app.services.book_deconstruct.call_llm_sync", side_effect=fake_fail):
            list(summarize_chapters(task.id))
        t = db.session.get(PlagiarizeTask, task.id)
        summaries = json.loads(t.chapters_summary_json)
        assert len(summaries) == 2
        assert "第一章" in summaries[0]["summary"]  # 截断正文兜底保留了章节标题


class TestIdempotency:
    def test_double_generate_long_no_duplicate_knowledge(self, app_ctx):
        """连续两次 generate-long 不重复落知识库（target_id 幂等守卫）。"""
        task = _make_task(app_ctx)
        task.elements_json = json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)
        db.session.commit()
        items = _make_items(task, kinds=("character", "world", "outline"))
        for it in items:
            it.status = "adopted"
        db.session.commit()

        client = app_ctx.test_client()
        for _ in range(2):
            r = client.post(f"/plagiarize/{task.id}/generate-long",
                            data={"title": "新书", "run": "0", "chapters": "0"})
            _wait_task(client, r.get_json()["long_task_id"])
        t = db.session.get(PlagiarizeTask, task.id)
        assert Character.query.filter_by(novel_id=t.target_novel_id).count() == 1
        assert WorldSetting.query.filter_by(novel_id=t.target_novel_id).count() == 1
        assert OutlineNode.query.filter_by(novel_id=t.target_novel_id, node_type="chapter").count() == 1


class TestReadoptAndRedeconstruct:
    def test_cannot_adopt_materialized_item(self, app_ctx):
        """已落库条目不可再采纳（防 target_id 被清空产生孤儿）。"""
        task = _make_task(app_ctx)
        items = _make_items(task, kinds=("character",))
        items[0].status = "adopted"
        items[0].target_id = 456
        db.session.commit()
        ok, msg, tid = adopt_item(items[0].id, modified={"name": "改名"})
        assert not ok
        assert db.session.get(DeconstructItem, items[0].id).target_id == 456

    def test_adopt_non_dict_modified_rejected(self, app_ctx):
        task = _make_task(app_ctx)
        items = _make_items(task, kinds=("character",))
        ok, msg, _ = adopt_item(items[0].id, modified=["不是字典"])
        assert not ok

    def test_redeconstruct_blocked_when_materialized(self, app_ctx):
        """已有落库条目（实体仍存在）时重拆 → 409。"""
        task = _make_task(app_ctx)
        items = _make_items(task, kinds=("world",))
        items[0].status = "adopted"
        # 必须指向真实存在的实体（新守卫校验实体存活，假 id 会被判为已删除而放行）
        ws = WorldSetting(novel_id=None, category="规则", title="守卫实体")
        from app.models import Novel as _Novel
        n = _Novel(title="守卫书")
        db.session.add(n)
        db.session.flush()
        ws.novel_id = n.id
        db.session.add(ws)
        db.session.flush()
        items[0].target_id = ws.id
        db.session.commit()
        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/{task.id}/deconstruct")
        assert r.status_code == 409

    def test_redeconstruct_allowed_when_entities_deleted(self, app_ctx):
        """知识库实体已被删除 → 不再阻止重拆（无「假逃生通道」）。"""
        task = _make_task(app_ctx)
        items = _make_items(task, kinds=("world",))
        items[0].status = "adopted"
        items[0].target_id = 999999  # 指向不存在的实体
        db.session.commit()
        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/{task.id}/deconstruct")
        assert r.status_code != 409


class TestSaveReport:
    def test_save_and_clear(self, app_ctx):
        task = _make_task(app_ctx)
        task.report_text = "旧报告"
        task.modifications_text = "旧指令"
        db.session.commit()
        client = app_ctx.test_client()
        # 显式清空（空串也落值）
        r = client.post(f"/plagiarize/{task.id}/save-report",
                        data={"report_text": "", "modifications_text": "新指令"})
        assert r.status_code == 200
        t = db.session.get(PlagiarizeTask, task.id)
        assert t.report_text == ""
        assert t.modifications_text == "新指令"


class TestGenerateShort:
    def test_creates_short_story(self, app_ctx):
        task = _make_task(app_ctx)
        task.elements_json = json.dumps(SAMPLE_ELEMENTS, ensure_ascii=False)
        db.session.commit()
        _make_items(task, kinds=("character", "character", "world", "outline", "outline"))
        # 采纳 2 人物 1 世界观 2 大纲
        for it in DeconstructItem.query.filter_by(task_id=task.id).all():
            it.status = "adopted"
        db.session.commit()

        client = app_ctx.test_client()
        r = client.post(f"/plagiarize/{task.id}/generate-short",
                        data={"title": "复刻短篇", "genre": "都市", "word_target": "3000"})
        j = r.get_json()
        assert r.status_code == 200
        assert j["ok"] is True
        story = db.session.get(ShortStory, j["story_id"])
        assert story.title == "复刻短篇"
        assert "主角" in (story.plan_characters or "")
        assert "灵气复苏" in (story.plan_setting or "")
        nodes = json.loads(story.outline_nodes or "[]")
        assert len(nodes) == 2
        assert db.session.get(PlagiarizeTask, task.id).target_short_story_id == story.id
