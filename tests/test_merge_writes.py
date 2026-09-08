"""merge-assessment 快赢项测试：收敛回滚环(A2)、锚例反向提取(A3)、
大纲失配标记(A1v1)、字数超标压缩(A5)。"""
import pytest

from app import db
from app.models import Novel, Chapter, ChapterVersion
from app.models.novel import outline_hash_of
from app.services import tone_convergence as tc
from app.services.llm import LLMError
from app.services.style_fingerprint import extract_anchor_candidate


# ---------------------------------------------------------------------------
# A2 收敛回滚环
# ---------------------------------------------------------------------------

def test_converge_adopts_improvement(app, monkeypatch):
    """重写产物人味分更高 → 采纳，converged=True。"""
    monkeypatch.setattr(tc, "analyze_ai_tone",
                        lambda t: {"passed": "不是" not in t,
                                   "human_score": 70 if "不是" in t else 90})
    monkeypatch.setattr(tc, "build_tone_instructions",
                        lambda t: "- 禁翻案腔" if "不是" in t else "")
    monkeypatch.setattr(tc, "call_llm_sync", lambda **kw: "干净流畅的正文。" * 30)

    result = tc.converge_tone("不是风而是人。" * 30, {"model_name": "m"})
    assert result["converged"] is True
    assert result["original_score"] == 70
    assert result["final_score"] == 90
    assert "不是" not in result["text"]


def test_converge_rolls_back_on_no_improvement(app, monkeypatch):
    """重写产物人味分不升 → 回滚，text 保持原稿（绝不保留更差版本）。"""
    monkeypatch.setattr(tc, "analyze_ai_tone",
                        lambda t: {"passed": False, "human_score": 70})
    monkeypatch.setattr(tc, "build_tone_instructions", lambda t: "- 禁翻案腔")
    # 产物仍是带违规的文本 → 分数不升
    monkeypatch.setattr(tc, "call_llm_sync",
                        lambda **kw: "不是风而是人的坏稿子。" * 30)

    original = "不是风而是人的坏稿子。" * 30
    result = tc.converge_tone(original, {"model_name": "m"})
    assert result["converged"] is False
    assert result["text"] == original  # 回滚
    assert any("回滚" in r["action"] for r in result["rounds"])


def test_converge_survives_llm_failure(app, monkeypatch):
    def boom(**kw):
        raise LLMError("厂商不可用")

    monkeypatch.setattr(tc, "analyze_ai_tone",
                        lambda t: {"passed": False, "human_score": 70})
    monkeypatch.setattr(tc, "build_tone_instructions", lambda t: "- 修复项")
    monkeypatch.setattr(tc, "call_llm_sync", boom)

    original = "普通原稿。" * 50
    result = tc.converge_tone(original, {"model_name": "m"})
    assert result["converged"] is False
    assert result["text"] == original
    assert "重写调用失败" in result["rounds"][-1]["action"]


def test_converge_too_short(app):
    result = tc.converge_tone("太短", {"model_name": "m"})
    assert result["converged"] is False
    assert result["reason"]


def test_condense_threshold_and_success(app, monkeypatch):
    short = "短文。" * 30  # 90 字，低于阈值
    result = tc.condense_text(short, {"model_name": "m"})
    assert result["ok"] is False and result["text"] == short

    long_text = "细节描写很多很冗长的句子。" * 400  # 5200 字
    monkeypatch.setattr(tc, "call_llm_sync",
                        lambda **kw: "压缩后的正文。" * 200)  # 1400 字
    result = tc.condense_text(long_text, {"model_name": "m"}, target_chars=2500)
    assert result["ok"] is True
    assert result["original_chars"] == len(long_text)
    assert result["condensed_chars"] < len(long_text)


def test_condense_rejects_bad_product(app, monkeypatch):
    long_text = "冗长正文。" * 500
    # 产物没变短 → 保留原稿
    monkeypatch.setattr(tc, "call_llm_sync", lambda **kw: "冗长正文。" * 500)
    result = tc.condense_text(long_text, {"model_name": "m"})
    assert result["ok"] is False
    assert result["text"] == long_text


# ---------------------------------------------------------------------------
# A3 锚例反向提取
# ---------------------------------------------------------------------------

def test_extract_anchor_prefers_dialogue(app):
    plain = "这是一段没有对话的普通叙述段落，描写了环境与动作，长度也足够参与候选评选。" * 2
    dialogue = "「你到底想说什么。」她把杯子放下，盯着他看了很久才继续开口说话。" * 2
    text = plain + "\n" + dialogue
    cand = extract_anchor_candidate(text)
    assert cand is not None
    assert "「" in cand  # 含对话的段落优先


def test_extract_anchor_none_when_too_short(app):
    assert extract_anchor_candidate("太短\n很短\n不够长") is None


def test_approve_human_version_returns_anchor_candidate(app, monkeypatch):
    """人工版本审批 → 返回 anchor_candidate；LLM 挂掉走摘要兜底不影响。"""
    from app.services.chapter_approval import approve_chapter_version

    def boom(**kw):
        raise LLMError("LLM 不可用")

    monkeypatch.setattr("app.services.chapter_approval.call_llm_sync", boom)

    n = Novel(title="锚例提取")
    db.session.add(n)
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=1, title="t")
    db.session.add(ch)
    db.session.commit()
    para = "她把筷子搁下，半天没夹那块排骨。窗外有人在收衣服，动作很慢。" * 3
    ver = ChapterVersion(chapter_id=ch.id, version_number=1,
                         content=para + "\n" + para, source="human")
    db.session.add(ver)
    db.session.commit()

    result = approve_chapter_version(ver, generate_summary=True)
    assert result["approved"] is True
    assert "anchor_candidate" in result
    assert result["summary"]  # 摘要兜底仍生效

    # AI 版本不提取
    ver2 = ChapterVersion(chapter_id=ch.id, version_number=2,
                          content=para + "\n" + para, source="ai")
    db.session.add(ver2)
    db.session.commit()
    result2 = approve_chapter_version(ver2, generate_summary=False)
    assert "anchor_candidate" not in result2


# ---------------------------------------------------------------------------
# A1v1 大纲失配标记
# ---------------------------------------------------------------------------

def test_outline_stale_lifecycle(app, client):
    n = Novel(title="失配测试")
    db.session.add(n)
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=1, title="t", outline="大纲v1")
    db.session.add(ch)
    db.session.commit()

    # 保存版本 → 打指纹，不失配
    resp = client.post(f"/novel/{n.id}/chapter/1/save-version",
                       data={"content": "正文内容", "source": "ai"})
    assert resp.status_code == 200
    db.session.expire_all()
    ch = Chapter.query.filter_by(novel_id=n.id, chapter_number=1).first()
    assert ch.outline_hash == outline_hash_of("大纲v1")
    assert ch.outline_stale() is False

    # 改大纲 → 失配
    resp = client.post(f"/novel/{n.id}/chapter/1/save-outline",
                       data={"outline": "大纲v2 改了情节走向"})
    assert resp.status_code == 200
    db.session.expire_all()
    ch = Chapter.query.filter_by(novel_id=n.id, chapter_number=1).first()
    assert ch.outline_stale() is True

    # 依据新大纲再保存 → 失配消除
    resp = client.post(f"/novel/{n.id}/chapter/1/save-version",
                       data={"content": "新大纲下的正文", "source": "ai"})
    db.session.expire_all()
    ch = Chapter.query.filter_by(novel_id=n.id, chapter_number=1).first()
    assert ch.outline_stale() is False

    # 从未据大纲生成（无指纹）不算失配
    ch2 = Chapter(novel_id=n.id, chapter_number=2, title="t2", outline="独立大纲")
    db.session.add(ch2)
    db.session.commit()
    assert ch2.outline_stale() is False


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

def test_tone_converge_route(app, client, monkeypatch):
    sentinel = {"converged": False, "text": "x", "original_score": 80,
                "final_score": 80, "rounds": []}
    monkeypatch.setattr(tc, "converge_tone", lambda text, cfg: sentinel)
    resp = client.post("/api/tone-converge",
                       json={"text": "一些正文内容" * 40, "novel_id": None})
    assert resp.get_json() == sentinel

    resp2 = client.post("/api/tone-converge", json={"text": ""})
    assert resp2.status_code == 400


def test_condense_route(app, client, monkeypatch):
    monkeypatch.setattr(tc, "condense_text",
                        lambda text, cfg, target_chars=2500:
                        {"ok": True, "text": "压", "original_chars": 9,
                         "condensed_chars": 1})
    resp = client.post("/api/condense", json={"text": "很长很长很长很长很长"})
    data = resp.get_json()
    assert data["ok"] is True

    resp2 = client.post("/api/condense", json={})
    assert resp2.status_code == 400
