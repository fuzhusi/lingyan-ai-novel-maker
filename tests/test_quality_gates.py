"""Phase A 质量门禁回归：断章四法 / 爽点间距账本 / 信息密度 / 钩子递进。

阈值经书1《你应该好好爱自己》24 章 + 书4 第 25 章实测定标
（响基调 13/24 触发、安静基调 0/24 误杀、终稿以决定/发现通过）。
"""
from app.services.tension_bus import pacing_debt, hook_progression
from app.services.web_novel_gate import _chapter_ending, _info_density


# ---------------------------------------------------------------------------
# A1 断章四法
# ---------------------------------------------------------------------------

def test_chapter_ending_four_signals_pass():
    cases = [
        "她站起来，说明天就去报名。",                 # 决定
        "他翻开最后一页，原来签名是父亲的。",         # 发现
        "「你不是早知道了吗？」他这才明白自己认错了人。",  # 误判（以为…其实变体亦同）
        "奖金泡汤了，那个月的房租也没了着落。",       # 代价
    ]
    for tail in cases:
        r = _chapter_ending("正文。" * 40 + tail)
        assert r["passed"], (tail, r["detail"])


def test_chapter_ending_summary_tail_fails_loud_passes_quiet():
    loud = "正文。" * 40 + "夜色很美。他想起很多事。也许生活就是这样吧。"
    r = _chapter_ending(loud, quiet_register=False)
    assert not r["passed"]
    assert "总结式" in r["detail"]
    # 安静基调：氛围收尾合法，不扣分
    q = _chapter_ending(loud, quiet_register=True)
    assert q["passed"]


def test_chapter_ending_empty_tail_passes():
    assert _chapter_ending("   ")["passed"]


# ---------------------------------------------------------------------------
# A2 爽点间距账本
# ---------------------------------------------------------------------------

def test_pacing_debt_streak_over_two_chapters():
    hist = [{"chapter": i, "density": 10.0} for i in range(1, 6)]
    hist += [{"chapter": i, "density": 2.0} for i in range(6, 10)]  # 连续4章低位
    notes = pacing_debt(hist)
    assert notes and "压抑超期" in notes[0] and "4 章" in notes[0]


def test_pacing_debt_two_low_chapters_ok():
    hist = [{"chapter": i, "density": 10.0} for i in range(1, 8)]
    hist += [{"chapter": 8, "density": 2.0}, {"chapter": 9, "density": 2.0}]
    assert pacing_debt(hist) == []          # 连续 2 章压抑未超期（>2 才报）


def test_pacing_debt_flat_beats_flagged():
    assert any("无峰值拍" in n for n in pacing_debt([], beat_tensions=[2, 2, 2]))
    assert pacing_debt([], beat_tensions=[2, 3, 2]) == []


def test_pacing_debt_insufficient_history():
    assert pacing_debt([{"chapter": 1, "density": 5.0}]) == []
    assert pacing_debt([]) == []


# ---------------------------------------------------------------------------
# A3 信息密度
# ---------------------------------------------------------------------------

def test_info_density_first_chapter_requires_person_and_anomaly():
    good = "陈屿推开宿舍门，床上居然躺着个陌生人。"
    assert _info_density(good, protagonist_names=["陈屿"],
                         is_first_chapter=True)["passed"]
    no_person = "宿舍门开着，床上居然躺着个陌生人。"
    r = _info_density(no_person, protagonist_names=["陈屿"],
                      is_first_chapter=True)
    assert not r["passed"] and "具名人物" in r["detail"]
    no_anomaly = "陈屿推开宿舍门，把行李放在床上。"
    r = _info_density(no_anomaly, protagonist_names=["陈屿"],
                      is_first_chapter=True)
    assert not r["passed"] and "异常" in r["detail"]


def test_info_density_event_count():
    r = _info_density("正文。" * 50, event_count=1)
    assert not r["passed"] and "有效事件" in r["detail"]
    assert _info_density("正文。" * 50, event_count=3)["passed"]
    # event_count=None（调用方拿不到事件）跳过事件子检查
    assert _info_density("正文。" * 50)["passed"]


# ---------------------------------------------------------------------------
# A4 钩子递进
# ---------------------------------------------------------------------------

def test_hook_progression_none_when_no_prev():
    assert hook_progression("", "他决定明天就去。") is None


def test_hook_progression_full_score():
    prev = "他站在门口，进也不是退也不是。"
    curr = "「周五之前」四个字钉在排班表上，陈屿把辞职信折了又折。"
    r = hook_progression(prev, curr, protagonist_names=["陈屿"])
    assert r["score"] == 3 and r["notes"] == []


def test_hook_progression_flat_scores_zero_with_notes():
    prev = "雨下起来了，事情还没有结束。"
    curr = "雨还在下，事情依然没有结束。"
    r = hook_progression(prev, curr, protagonist_names=["陈屿"])
    assert r["score"] == 0 and len(r["notes"]) == 3
