"""Agent 协同方案（P1-P4）实现测试：意见契约 / 一致性链 / 编排器 / 写作包。"""
import json

import pytest

from app import db
from app.models import (Novel, Chapter, ChapterVersion, Foreshadowing,
                        PendingExtraction, Setting)
from app.services import opinions as op
from app.services import consistency_check as cc
from app.services import chapter_runner as runner
from app.services import writer_chain as wc
from app.services import extraction_queue as eq
from app.services.llm import LLMError
from app.services.prompt_builder import build_writer_prompt


# ---------------------------------------------------------------------------
# P1 统一意见 Schema
# ---------------------------------------------------------------------------

def test_build_merged_opinions():
    issues = [{"dimension": "pacing", "severity": "high",
               "issue": "中段拖沓", "suggestion": "压缩过渡"}]
    blind = [{"key": "yafu", "verdict": "弃稿", "review": "钩子太软。"},
             {"key": "baigu", "verdict": "追读", "review": ""}]
    merged = op.build_merged_opinions(critic_issues=issues,
                                      blind_reviews=blind)
    ids = [o["id"] for o in merged]
    assert ids == ["critic-1", "yafu-1"]  # 白骨空意见不入列
    assert merged[0]["severity"] == "high"
    assert merged[1]["severity"] == "high"  # 弃稿 → high
    assert "pacing" in merged[0]["issue"]


def test_format_and_filter_opinions():
    merged = op.build_merged_opinions(
        critic_issues=[{"dimension": "d", "severity": "low", "issue": "i"}])
    block = op.format_opinions_block(merged)
    assert "critic·low" in block and "i" in block
    picked = op.filter_opinions(merged, ["critic-1"])
    assert len(picked) == 1
    assert op.format_opinions_block([]) == ""


def test_rewrite_stream_accepts_opinions(app, client, monkeypatch):
    n = Novel(title="意见改写")
    db.session.add(n)
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=1, title="t")
    db.session.add(ch)
    db.session.commit()
    ver = ChapterVersion(chapter_id=ch.id, version_number=1, content="原稿", source="ai")
    db.session.add(ver)
    db.session.commit()

    captured = {}

    def fake_stream_chat(messages, cfg):
        captured["messages"] = messages
        yield "done", "改写后的正文"

    monkeypatch.setattr("app.routes.review._stream_chat", fake_stream_chat)
    opinions = [{"id": "critic-1", "source": "critic", "severity": "high",
                 "quote": "", "issue": "中段拖沓", "suggestion": "压缩"}]
    resp = client.post("/api/rewrite-stream", data={
        "version_id": ver.id, "novel_title": "t",
        "opinions": json.dumps(opinions),
    })
    assert resp.status_code == 200
    assert "中段拖沓" in captured["messages"][1]["content"]


# ---------------------------------------------------------------------------
# P2 一致性链
# ---------------------------------------------------------------------------

def _seed_consistency(app):
    n = Novel(title="一致性测试")
    db.session.add(n)
    db.session.commit()
    # 时序真相：第 1 章灵力为「枯竭」，第 3 章变更为「充沛」→ 旧值闭合
    from app.services.temporal_truth import add_truth, update_truth
    add_truth(n.id, "林晚", "灵力", "枯竭", 1)
    update_truth(n.id, "林晚", "灵力", "充沛", 3)
    # 已回收伏笔（标题会复现）
    f_done = Foreshadowing(novel_id=n.id, title="青铜镜的裂纹",
                           description="裂纹暗示封印松动",
                           planted_chapter=1, status="resolved")
    # 回收逾期：约定第 2 章回收，当前第 5 章
    f_late = Foreshadowing(novel_id=n.id, title="信里的暗号",
                           description="暗号指向内鬼",
                           planted_chapter=1, resolve_chapter=2,
                           status="buried")
    db.session.add_all([f_done, f_late])
    db.session.commit()
    return n


def test_deterministic_consistency_checks(app, _seed_consistency_helper=None):
    n = _seed_consistency(app)
    text = ("林晚感受着体内枯竭的灵力，握紧了青铜镜的裂纹边缘。" * 5)
    suspects = cc.run_deterministic_checks(text, n.id, 5)
    kinds = {s["kind"] for s in suspects}
    assert "truth_regression" in kinds       # 旧值「枯竭」回潮
    assert "foreshadow_reappear" in kinds    # 已回收伏笔复现
    assert "foreshadow_overdue" in kinds     # 回收逾期
    assert any("枯竭" in s["detail"] for s in suspects)
    assert any("青铜镜" in s["title"] for s in suspects)


def test_consistency_route_without_adjudication(app, client):
    n = _seed_consistency(app)
    resp = client.post("/api/consistency-check", json={
        "novel_id": n.id, "chapter_number": 5,
        "text": "林晚的灵力依然枯竭。" * 20,
    })
    data = resp.get_json()
    assert data["passed"] is False
    assert data["verdicts"] == []  # 未开启裁决


def test_extraction_queue_roundtrip(app):
    n = Novel(title="队列测试")
    db.session.add(n)
    db.session.commit()
    payloads = [{"subject": "林晚", "property": "status", "value": "重伤",
                 "from_chapter": 2}]
    assert eq.queue_extractions(n.id, "truth", payloads, 2) == 1

    pending = eq.list_pending(n.id)
    assert len(pending) == 1 and pending[0]["status"] == "pending"

    # 采纳 → 写回真相库
    ok, msg = eq.resolve_extraction(pending[0]["id"], adopt=True)
    assert ok, msg
    from app.services.temporal_truth import _get_truths
    values = [t.get("value") for t in _get_truths(n.id)]
    assert "重伤" in values

    # 丢弃
    eq.queue_extractions(n.id, "truth", [{"subject": "x", "property": "p",
                                          "value": "v", "from_chapter": 1}], 1)
    item = eq.list_pending(n.id)[0]
    ok2, _ = eq.resolve_extraction(item["id"], adopt=False)
    assert ok2
    assert eq.list_pending(n.id) == []


# ---------------------------------------------------------------------------
# P3 chapter_runner 编排器
# ---------------------------------------------------------------------------

def test_runner_full_pipeline_with_auto_save(app, monkeypatch):
    n = Novel(title="编排器测试")
    db.session.add(n)
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=1, title="第一章",
                 outline="既有大纲：主角进入北境。")
    db.session.add(ch)
    db.session.commit()

    body = "主角踏入北境的雪原，风声像刀子一样刮过耳边。" * 12  # >200 字
    monkeypatch.setattr(runner, "collect_full_text",
                        lambda messages, cfg, word_target=None: body)
    monkeypatch.setattr("app.services.ai_metric.analyze_ai_tone",
                        lambda text: {"passed": True, "human_score": 95})
    # mock 门禁通过：测试验证编排器流程，不应依赖真实 skill_gate 对 mock 文本的判定
    monkeypatch.setattr("app.services.skill_gate.run_gate",
                        lambda text, active_skills=None: {"passed": True, "checks": []})

    result = runner.run_chapter_pipeline(n.id, 1, auto_save=True)
    assert "error" not in result
    stage_names = [s["stage"] for s in result["stages"]]
    assert stage_names == ["outline", "body", "gates", "converge", "save"]
    assert result["stages"][0].get("skipped") == "已有大纲"
    assert result["saved_version_id"]

    # 版本落库 + 大纲指纹已打点（大纲未变 → 不失配）
    ver = ChapterVersion.query.get(result["saved_version_id"])
    assert ver.content and ver.source == "ai"
    ch = Chapter.query.get(ch.id)
    assert ch.outline_stale() is False


def test_runner_generates_missing_outline(app, monkeypatch):
    n = Novel(title="编排器测试2")
    db.session.add(n)
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=1, title="第一章", outline="")
    db.session.add(ch)
    db.session.commit()

    calls = {"outline": False}

    def fake_collect(messages, cfg, word_target=None):
        # 大纲链的 system prompt 含「章节大纲」字样，正文链没有 → 以此区分阶段
        if any("章节大纲" in m.get("content", "") for m in messages if isinstance(m, dict)):
            calls["outline"] = True
            return "大纲：主角进入北境，遭遇伏击。"
        return "正文若干。" * 40

    monkeypatch.setattr(runner, "collect_full_text", fake_collect)
    # mock 门禁与检测通过：测试验证编排器流程，不依赖真实规则对 mock 文本的判定
    monkeypatch.setattr("app.services.skill_gate.run_gate",
                        lambda text, active_skills=None: {"passed": True, "checks": []})
    monkeypatch.setattr("app.services.ai_metric.analyze_ai_tone",
                        lambda text: {"passed": True, "human_score": 95})
    result = runner.run_chapter_pipeline(n.id, 1)
    assert calls["outline"] is True
    assert result["stages"][0]["stage"] == "outline"
    assert result["stages"][-1]["stage"] == "human_gate"  # 默认停在人工闸门
    db.session.expire_all()
    assert Chapter.query.get(ch.id).outline.startswith("大纲：")


def test_runner_stops_when_final_gate_fails(app, monkeypatch):
    """终稿门禁失败时不能越过人工闸门，更不能 auto_save 落库。"""
    n = Novel(title="门禁失败测试")
    db.session.add(n)
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=1, title="第一章",
                 outline="既有大纲")
    db.session.add(ch)
    db.session.commit()

    monkeypatch.setattr(runner, "collect_full_text",
                        lambda messages, cfg, word_target=None: "首先，她进门。其次，她坐下。")
    monkeypatch.setattr("app.services.skill_gate.run_gate",
                        lambda text, active_skills=None: {"passed": False, "checks": []})

    result = runner.run_chapter_pipeline(n.id, 1, auto_save=True)
    assert "error" in result
    assert result["stages"][-1]["stage"] == "gates_final"
    assert result["stages"][-1]["ok"] is False
    assert ChapterVersion.query.filter_by(chapter_id=ch.id).count() == 0


def test_pipeline_route(app, client, monkeypatch):
    sentinel = {"text": "正文", "stages": [], "human_score": 95}
    monkeypatch.setattr(runner, "run_chapter_pipeline",
                        lambda *a, **kw: sentinel)
    resp = client.post("/api/chapter-pipeline",
                       json={"novel_id": 1, "chapter_number": 1})
    assert resp.get_json() == sentinel

    resp2 = client.post("/api/chapter-pipeline", json={})
    assert resp2.status_code == 400


# ---------------------------------------------------------------------------
# P4 写作包 / 风格备忘录 / 偏好档案
# ---------------------------------------------------------------------------

def test_style_memo_and_preferences_injected(app, monkeypatch):
    n = Novel(title="写作包测试", author_intent="复仇外壳写救赎",
              style_memo_json=json.dumps([
                  {"chapter": 1, "note": "雨景意象贯穿"},
                  {"chapter": 2, "note": "对话短促带机锋"},
              ], ensure_ascii=False))
    db.session.add(n)
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=1, title="t")
    db.session.add(ch)
    db.session.commit()
    # 测试库跨运行持久：get-or-update，避免撞 settings.key 唯一约束
    pref_value = json.dumps({"style": "冷峻克制", "taboos": "不写真实品牌",
                             "audience": "男频"}, ensure_ascii=False)
    pref = Setting.query.get("creator_preferences")
    if pref:
        pref.value = pref_value
    else:
        db.session.add(Setting(key="creator_preferences", value=pref_value))
    db.session.commit()

    kw, novel = wc.build_writer_kwargs(n.id, 1, "大纲")
    assert "雨景意象贯穿" in kw["style_memo"]
    assert "对话短促带机锋" in kw["style_memo"]  # 最近 3 条全注入
    assert "冷峻克制" in kw["creator_preferences"]

    msgs = build_writer_prompt(novel_title="t", **kw)
    user = msgs[1]["content"]
    assert "近期文体备忘" in user and "创作偏好档案" in user


def test_approve_collects_style_memo(app, monkeypatch):
    from app.services import chapter_approval as ca

    responses = iter([
        "摘要：主角负伤撤离。",  # summary 调用
        json.dumps({"summary": "负伤撤离", "style_note": "短对话+雨景意象",
                    "key_events": []}),  # memory 调用
    ])

    def fake_llm(**kw):
        return next(responses)

    monkeypatch.setattr(ca, "call_llm_sync", fake_llm)

    n = Novel(title="备忘录采集", style_memo_json="[]")
    db.session.add(n)
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=3, title="t")
    db.session.add(ch)
    db.session.commit()
    ver = ChapterVersion(chapter_id=ch.id, version_number=1,
                         content="正文" * 60, source="ai")
    db.session.add(ver)
    db.session.commit()

    result = ca.approve_chapter_version(ver, generate_summary=True)
    assert result["approved"] is True
    db.session.expire_all()
    n = Novel.query.get(n.id)
    memos = json.loads(n.style_memo_json)
    assert memos[-1]["note"] == "短对话+雨景意象"
    assert memos[-1]["chapter"] == 3


def test_preferences_routes(app, client):
    resp = client.post("/settings/api/creator-preferences", json={
        "style": "克制", "taboos": "无", "audience": "女频"})
    assert resp.get_json()["ok"] is True
    got = client.get("/settings/api/creator-preferences").get_json()
    assert got["style"] == "克制" and got["audience"] == "女频"


def test_keeper_configs_marked_reserved(app):
    from app.routes.settings import AGENT_TYPES
    for key in ("character_check", "lore_check", "foreshadow_check"):
        assert "预留" in AGENT_TYPES[key]["name"]
