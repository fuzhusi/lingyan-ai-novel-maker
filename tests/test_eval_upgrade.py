"""P2 评估升级回归：4 人格面板 / 阈值线 / 可预测率 / best-of-N 选优。"""
import json

from app import db
from app.models import BlindReview, Chapter, ChapterVersion, Novel
from app.services.blind_review import (
    EDITORS, run_dual_review, save_blind_review, threshold_check,
)
from app.services import chapter_runner as runner
from app.services.predictability import predict_consistency


# ---------------------------------------------------------------------------
# C1 四人格面板
# ---------------------------------------------------------------------------

def test_panel_four_editors(client, monkeypatch):
    """面板扩到 4 人格：4 次独立调用、结果带 color、可按 key 取子集。"""
    calls = []

    def fake_llm(model, messages, **kwargs):
        calls.append(messages)
        return "【总评】毒舌。\n【判决】追读：能翻。"

    monkeypatch.setattr("app.services.blind_review.call_llm_auto", fake_llm)
    result = run_dual_review("正文内容，够长够真实。")
    assert len(result["editors"]) == 4
    assert {e["key"] for e in result["editors"]} == {"yafu", "baigu", "zhui", "guge"}
    assert all(e.get("color") for e in result["editors"])   # color 入结果（前端泛化）
    assert len(calls) == 4

    sub = run_dual_review("正文内容。", editor_keys=["yafu", "baigu"])
    assert {e["key"] for e in sub["editors"]} == {"yafu", "baigu"}   # 成本分层


def test_editors_have_distinct_perspectives():
    """四人格体系性互斥：读者/文学/留存/结构各有专属关注面。"""
    blob = " ".join(e["system"] for e in EDITORS).replace("\n", " ")
    assert "爽" in blob or "追" in blob          # 市场线（阎浮/快嘴）
    assert "真的" in blob                        # 文学线（白骨）
    assert "弃书" in blob                        # 留存线（快嘴专属）
    assert "骨架" in blob or "结构" in blob       # 结构线（骨架师）


# ---------------------------------------------------------------------------
# C2 阈值线：连续 3 章弃稿 → 整改清单
# ---------------------------------------------------------------------------

def _mk_chapter_with_review(client, novel_id, number, verdict):
    n_ver = (ChapterVersion.query.join(Chapter)
             .filter(Chapter.novel_id == novel_id,
                     Chapter.chapter_number == number)
             .order_by(ChapterVersion.version_number.desc()).first())
    if n_ver is None:
        ch = Chapter(novel_id=novel_id, chapter_number=number, title=f"第{number}章")
        db.session.add(ch)
        db.session.flush()
        ver = ChapterVersion(chapter_id=ch.id, version_number=1,
                             content=f"第{number}章正文。", source="ai")
        db.session.add(ver)
        db.session.flush()
    else:
        ver = n_ver
    editors = ([{"key": "yafu", "name": "阎浮", "verdict": verdict,
                 "review": "【只准改一处】把章末断在事件发生那一拍。"}]
               if verdict == "弃稿" else
               [{"key": "yafu", "name": "阎浮", "verdict": verdict, "review": "ok"}])
    row = BlindReview(kind="chapter", version_id=ver.id,
                      title=f"第{number}章", word_count=100,
                      editors_json=json.dumps(editors, ensure_ascii=False))
    db.session.add(row)
    db.session.commit()
    return ver


def test_threshold_check_three_consecutive_rejections(client):
    n = Novel(title="阈值测试", genre="都市")
    db.session.add(n)
    db.session.commit()
    base_max = db.session.query(db.func.max(BlindReview.id)).scalar() or 0
    for num, verdict in [(1, "追读"), (2, "弃稿"), (3, "弃稿"), (4, "弃稿")]:
        _mk_chapter_with_review(client, n.id, num, verdict)
    ver4 = (ChapterVersion.query.join(Chapter)
            .filter(Chapter.novel_id == n.id, Chapter.chapter_number == 4)
            .first())
    thr = threshold_check("chapter", ver4.id)
    assert thr and thr["chapters"] == [4, 3, 2]
    assert any("把章末断在事件发生那一拍" in r for r in thr["rectification"])
    # 只有 2 章弃稿 → 不触发（第 1 章追读在窗口内）
    _mk_chapter_with_review(client, n.id, 5, "追读")
    ver5 = (ChapterVersion.query.join(Chapter)
            .filter(Chapter.novel_id == n.id, Chapter.chapter_number == 5)
            .first())
    assert threshold_check("chapter", ver5.id) is None
    # 清场：delete_cascade 用全局盲审计数做基线，本测试的行不能留在共享库
    BlindReview.query.filter(BlindReview.id > base_max).delete()
    db.session.commit()


def test_save_blind_review_returns_threshold(client):
    """save 返回结构化 {id, threshold}（调用方已适配 dict）。"""
    n = Novel(title="保存测试", genre="都市")
    db.session.add(n)
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=1, title="第1章")
    db.session.add(ch)
    db.session.flush()
    ver = ChapterVersion(chapter_id=ch.id, version_number=1, content="正文",
                         source="ai")
    db.session.add(ver)
    db.session.commit()
    result = {"editors": [{"key": "yafu", "name": "阎浮", "color": "var(--accent)",
                           "verdict": "追读", "review": "ok"}], "elapsed": 1.0}
    base_max = db.session.query(db.func.max(BlindReview.id)).scalar() or 0
    saved = save_blind_review("chapter", result, 100, version_id=ver.id,
                              title="第1章")
    assert saved["id"] and saved["threshold"] is None   # 单章不触发阈值
    BlindReview.query.filter(BlindReview.id > base_max).delete()
    db.session.commit()


# ---------------------------------------------------------------------------
# C4 可预测率
# ---------------------------------------------------------------------------

def test_predict_consistency_identical_samples(client, monkeypatch):
    """三次预测完全一致 → 一致性 1.0（高可预测警报）。"""
    n = Novel(title="预测测试", genre="都市")
    db.session.add(n)
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=1, title="第1章")
    db.session.add(ch)
    db.session.flush()
    db.session.add(ChapterVersion(chapter_id=ch.id, version_number=1,
                                  content="开局正文。" * 120, source="ai"))
    db.session.commit()

    monkeypatch.setattr("app.services.predictability.get_model_config",
                        lambda agent_type: {"model_name": "m", "api_key": "k",
                                            "base_url": "u", "provider_type": "p",
                                            "timeout": 10})
    monkeypatch.setattr("app.services.predictability.call_llm_auto",
                        lambda **kw: "主角去找反派算账。\n反派设下陷阱。\n主角中计。")
    rep = predict_consistency(n.id, 2, samples=3)
    assert rep["consistency"] == 1.0
    assert "高可预测" in rep["verdict"]


def test_predict_consistency_diverse_samples(client, monkeypatch):
    """三次预测完全不同 → 一致性低（新颖性富余）。"""
    n = Novel(title="预测多样", genre="都市")
    db.session.add(n)
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=1, title="第1章")
    db.session.add(ch)
    db.session.flush()
    db.session.add(ChapterVersion(chapter_id=ch.id, version_number=1,
                                  content="开局正文。" * 120, source="ai"))
    db.session.commit()
    monkeypatch.setattr("app.services.predictability.get_model_config",
                        lambda agent_type: {"model_name": "m", "api_key": "k",
                                            "base_url": "u", "provider_type": "p",
                                            "timeout": 10})
    variants = iter([
        "主角去菜市场买菜。\n遇到多年未见的老友。\n两人一起去钓鱼。",
        "陨石坠落校园操场。\n全校紧急疏散到体育馆。\n主角捡到一块发光碎片。",
        "奶奶从乡下寄来一箱橘子。\n箱底藏着一封旧信。\n信里提到一座老宅。",
    ])
    monkeypatch.setattr("app.services.predictability.call_llm_auto",
                        lambda **kw: next(variants))
    rep = predict_consistency(n.id, 2, samples=3)
    assert rep["consistency"] < 0.35
    assert "新颖性" in rep["verdict"]


# ---------------------------------------------------------------------------
# C3 best-of-N 选优
# ---------------------------------------------------------------------------

def test_best_of_n_selects_higher_score(client, monkeypatch):
    """--variants 2：两稿过门禁，按人味+可读分选优（确定性，非盲审）。"""
    n = Novel(title="选优测试", genre="都市", synopsis="s", world_intro="w")
    db.session.add(n)
    db.session.commit()
    db.session.add(Chapter(novel_id=n.id, chapter_number=1,
                           outline="【本章定位】推进：开局建立人物与异常，门禁与选优回归。\n"
                                   "【本章契约】他要什么：查明短信来源；谁拦他：没有线索；"
                                   "不做成会失去什么：主动权。\n"
                                   "【核心事件】1.开局事件；2.转折事件。\n"
                                   "【场景节拍】1.宿舍收到短信，内容反常；2.操场对峙，关系变质。\n"
                                   "【结尾钩子】短信署名是个从未见过的名字。"))
    db.session.commit()
    from app.models import Character
    db.session.add(Character(novel_id=n.id, name="陈屿", personality="沉默"))
    db.session.commit()

    texts = iter(["弱稿。" * 60,                 # 人味 80 / 可读 60
                  "强稿。冲突全面爆发，摔了杯子！" * 60])  # 人味 95 / 可读 90

    def fake_collect(messages, cfg, word_target=None, scene_plan=None):
        return next(texts)

    monkeypatch.setattr(runner, "collect_full_text", fake_collect)
    monkeypatch.setattr("app.services.skill_gate.run_gate",
                        lambda text, active_skills=None: {"passed": True, "checks": []})
    human = {"弱稿": 80, "强稿": 95}
    read = {"弱稿": 60, "强稿": 90}
    monkeypatch.setattr(
        "app.services.ai_metric.analyze_ai_tone",
        lambda text, mode="generate": {"passed": True, "human_score": human.get(text[:2], 85)})
    monkeypatch.setattr(
        "app.services.web_novel_gate.analyze_web_novel",
        lambda text, outline="", event_count=None, is_first_chapter=False,
        protagonist_names=None: {"passed": True, "readability_score": read.get(text[:2], 80),
                                 "checks": [], "hint": ""})

    result = runner.run_chapter_pipeline(n.id, 1, auto_save=False, converge=False,
                                         variants=2)
    assert "error" not in result, result.get("error")
    stage = next(s for s in result["stages"] if s["stage"] == "variants")
    assert stage["count"] == 2
    assert stage["candidates"][1]["human"] == 95      # 强稿分数被识别
    assert result["text"].startswith("强稿")           # 选优采纳强稿
