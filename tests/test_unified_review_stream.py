"""统一评审真流式 + 字段映射修复测试。

覆盖（code review 发现的问题回归锁定）：
- _merge_report 字段映射：issue=问题描述（此前被 quote 覆盖丢弃）、
  quote 独立保留、severity 透传（此前恒为 medium → 高优先级统计恒 0）
- _save_review：paragraph_index 保留真实值（此前硬编码 0 → 段落标注全错位）
- /api/unified-review-stream 真流式：critic token 逐帧流出、盲审并行、
  报告与 done 事件、CriticReview 落库
- 改写阶段流式（include_rewrite=1）
- critic LLM 失败 → error 事件，不落库
- version_id 归属不匹配 → error 事件
"""
import json

import pytest
from unittest.mock import patch

from app import create_app, db
from app.models import Novel, Chapter, ChapterVersion, CriticReview
from app.services.unified_review import _merge_report, _save_review
from app.services.llm import LLMError


@pytest.fixture
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        max_novel_id = db.session.query(db.func.max(Novel.id)).scalar() or 0
        yield app
        novels = Novel.query.filter(Novel.id > max_novel_id).all()
        for n in novels:
            CriticReview.query.filter(
                CriticReview.version_id.in_(
                    [v.id for v in ChapterVersion.query.join(
                        Chapter, ChapterVersion.chapter_id == Chapter.id)
                     .filter(Chapter.novel_id == n.id).all()])).delete(
                synchronize_session=False)
            ChapterVersion.query.filter(ChapterVersion.chapter_id.in_(
                [c.id for c in Chapter.query.filter_by(novel_id=n.id).all()])
            ).delete(synchronize_session=False)
            Chapter.query.filter(Chapter.novel_id == n.id).delete(
                synchronize_session=False)
            db.session.delete(n)
        db.session.commit()


def _make_version(content="第一章正文，足够长。"):
    novel = Novel(title="评审测试书", genre="玄幻")
    db.session.add(novel)
    db.session.flush()
    chapter = Chapter(novel_id=novel.id, chapter_number=1, title="第1章",
                      outline="大纲")
    db.session.add(chapter)
    db.session.flush()
    version = ChapterVersion(chapter_id=chapter.id, version_number=1,
                             content=content, source="ai")
    db.session.add(version)
    db.session.commit()
    return novel, chapter, version


def _parse_sse(raw: bytes):
    events = []
    for frame in raw.split(b"\n\n"):
        for line in frame.split(b"\n"):
            if line.startswith(b"data: "):
                try:
                    events.append(json.loads(line[6:].decode("utf-8")))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
    return events


_CRITIC_JSON_TOKENS = [
    '{"overall_score": 7.5, "overall_comment": "整体成立，细节需要打磨", ',
    '"dimensions": [{"name": "文笔质量", "score": 7, "comment": "ok"}], '
    '"annotations": [{"paragraph_index": 2, "quote": "他推开门", '
    '"issue": "动作太直白，缺环境反馈", "suggestion": "加一段环境互动", '
    '"severity": "high"}]}',
]


class TestMergeReport:
    def test_issue_fields_preserved(self):
        critic = {
            "overall_score": 7.5,
            "overall_comment": "整体成立",
            "dimensions": [],
            "annotations": [{
                "paragraph_index": 2, "quote": "他推开门",
                "issue": "动作太直白，缺环境反馈",
                "suggestion": "加一段环境互动", "severity": "high",
            }],
        }
        report = _merge_report(critic, {"editors": [], "elapsed": 0.0})
        issue = report["issues"][0]
        # 修复点：issue 是问题描述而非引文；quote 独立保留
        assert issue["issue"] == "动作太直白，缺环境反馈"
        assert issue["quote"] == "他推开门"
        assert issue["paragraph_index"] == 2
        assert issue["location"] == "第3段"
        # 修复点：severity 透传 → 高优先级统计不再恒 0
        assert issue["severity"] == "high"
        assert report["high_issue_count"] == 1
        assert report["total_issue_count"] == 1

    def test_severity_defaults_medium_when_absent(self):
        critic = {"overall_score": 6, "overall_comment": "c", "dimensions": [],
                  "annotations": [{"paragraph_index": 0, "quote": "q",
                                   "issue": "i", "suggestion": "s"}]}
        report = _merge_report(critic, {"editors": [], "elapsed": 0.0})
        assert report["issues"][0]["severity"] == "medium"
        assert report["high_issue_count"] == 0


class TestSaveReview:
    def test_paragraph_index_kept(self, app_ctx):
        novel, chapter, version = _make_version()
        critic = {"overall_score": 7.5, "overall_comment": "c",
                  "dimensions": [{"name": "文笔", "score": 7, "comment": "ok"}],
                  "annotations": [{"paragraph_index": 2, "quote": "他推开门",
                                   "issue": "动作太直白", "suggestion": "s"}]}
        report = _merge_report(critic, {"editors": [], "elapsed": 0.0})
        _save_review(version.id, report, critic)
        row = CriticReview.query.filter_by(version_id=version.id).first()
        assert row is not None
        anns = json.loads(row.annotations_json)
        assert anns[0]["paragraph_index"] == 2
        assert anns[0]["issue"] == "动作太直白"
        assert anns[0]["quote"] == "他推开门"


class TestUnifiedReviewStream:
    def test_token_report_done_sequence(self, app_ctx):
        novel, chapter, version = _make_version()
        client = app_ctx.test_client()

        def fake_stream(**kw):
            yield from _CRITIC_JSON_TOKENS

        editors = [{"key": "yafu", "name": "尖酸嘴 · 阎浮",
                    "verdict": "追读", "review": "开头摁得住人。"}]
        with patch("app.services.unified_review.stream_llm_tokens",
                   side_effect=fake_stream), \
             patch("app.services.unified_review.run_dual_review",
                   return_value={"editors": editors, "elapsed": 0.1}):
            rv = client.post("/api/unified-review-stream", data={
                "novel_id": novel.id, "chapter_number": 1,
                "version_id": version.id, "include_rewrite": "0",
            })
            # 流式响应是惰性消费的：必须在 patch 作用域内取 .data，
            # 否则生成器在 mock 卸载后才迭代，会打到真实 LLM
            events = _parse_sse(rv.data)

        # critic token 逐帧流出且有序
        tokens = [e["token"] for e in events if "token" in e and e.get("phase") == "critic"]
        assert tokens == _CRITIC_JSON_TOKENS
        # 阶段与报告事件齐全
        stages = [e["status"]["stage"] for e in events if "status" in e]
        assert "review_start" in stages
        assert "critic_done" in stages
        assert "blind_done" in stages
        report_ev = [e for e in events if "report" in e]
        assert len(report_ev) == 1
        assert report_ev[0]["report"]["overall_score"] == 7.5
        assert report_ev[0]["report"]["blind_reviews"][0]["key"] == "yafu"
        assert {"done": True} in events
        # 评审落库
        row = CriticReview.query.filter_by(version_id=version.id).first()
        assert row is not None
        assert row.overall_score == 7.5

    def test_rewrite_streams_after_report(self, app_ctx):
        novel, chapter, version = _make_version()
        client = app_ctx.test_client()
        calls = []

        def fake_stream(**kw):
            calls.append(kw)
            if len(calls) == 1:
                yield from _CRITIC_JSON_TOKENS
            else:
                yield "改写后的第一段。"
                yield "改写后的第二段。"

        with patch("app.services.unified_review.stream_llm_tokens",
                   side_effect=fake_stream), \
             patch("app.services.unified_review.run_dual_review",
                   return_value={"editors": [], "elapsed": 0.0}):
            rv = client.post("/api/unified-review-stream", data={
                "novel_id": novel.id, "chapter_number": 1,
                "version_id": version.id, "include_rewrite": "1",
            })
            events = _parse_sse(rv.data)  # patch 作用域内消费流（见上文注释）
        rw_tokens = [e["token"] for e in events
                     if "token" in e and e.get("phase") == "rewrite"]
        assert rw_tokens == ["改写后的第一段。", "改写后的第二段。"]
        stages = [e["status"]["stage"] for e in events if "status" in e]
        assert "rewrite_start" in stages
        assert "rewrite_done" in stages

    def test_llm_failure_yields_error_no_save(self, app_ctx):
        novel, chapter, version = _make_version()
        client = app_ctx.test_client()

        def fail_stream(**kw):
            raise LLMError("API 401")
            yield  # pragma: no cover

        with patch("app.services.unified_review.stream_llm_tokens",
                   side_effect=fail_stream), \
             patch("app.services.unified_review.run_dual_review",
                   return_value={"editors": [], "elapsed": 0.0}):
            rv = client.post("/api/unified-review-stream", data={
                "novel_id": novel.id, "chapter_number": 1,
                "version_id": version.id,
            })
            events = _parse_sse(rv.data)  # patch 作用域内消费流（见上文注释）
        assert any("评审失败" in e.get("error", "") for e in events)
        assert {"done": True} in events
        assert not [e for e in events if "report" in e]
        assert CriticReview.query.filter_by(version_id=version.id).first() is None

    def test_version_mismatch_error(self, app_ctx):
        novel, chapter, _ = _make_version()
        # 另一章的版本，归属校验必须拦截
        other = Chapter(novel_id=novel.id, chapter_number=2, title="第2章")
        db.session.add(other)
        db.session.flush()
        other_ver = ChapterVersion(chapter_id=other.id, version_number=1,
                                   content="x", source="ai")
        db.session.add(other_ver)
        db.session.commit()
        client = app_ctx.test_client()
        rv = client.post("/api/unified-review-stream", data={
            "novel_id": novel.id, "chapter_number": 1,
            "version_id": other_ver.id,
        })
        events = _parse_sse(rv.data)
        assert any("不匹配" in e.get("error", "") for e in events)

    def test_dual_review_sends_two_llm_requests(self, app_ctx):
        """实证（用户问询 2026-09-17）：双盲审是两位编辑各发一次 LLM 请求
        （ThreadPoolExecutor 并行，共 2 个），不是一个请求输出一份合并 JSON。
        前端看到的单个 JSON 是 critic 的输出（critic 提示词要求 JSON 格式）。"""
        from app.services import blind_review as br
        calls = []

        def fake_llm(**kwargs):
            calls.append(kwargs.get("messages"))
            return "【判决】追读\n意见正文……"

        with patch.object(br, "call_llm_sync", side_effect=fake_llm):
            result = br.run_dual_review("正文内容……")
        assert len(calls) == 2  # 两位编辑 = 两次独立请求
        keys = [e["key"] for e in result["editors"]]
        assert len(set(keys)) == 2  # 两位不同编辑（阎浮/白骨）
        assert all(e["verdict"] == "追读" for e in result["editors"])
