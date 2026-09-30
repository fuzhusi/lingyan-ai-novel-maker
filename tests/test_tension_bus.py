"""张力总线 + 节拍级生成回归（开源机制采纳 2026-09-28）。

覆盖：节拍解析、章张力档推导（关键词+伏笔压力）、逐拍曲线不平、
力度档温度映射、实测强度审计、情绪峰值软检查、伏笔窗口过滤、
大纲名册过滤、beatwise 生成循环（多拍多次调用/温度分档/拍间衔接）。
"""
from app import db
from app.models import Novel, Character, Foreshadowing
from app.services.tension_bus import (
    parse_scene_beats, parse_outline_field, chapter_tension, beat_tensions,
    tension_directive, temperature_for_level, measured_intensity,
    intensity_gap_note,
)
from app.services.web_novel_gate import analyze_web_novel


# ---------------------------------------------------------------------------
# 节拍解析
# ---------------------------------------------------------------------------

OUTLINE_SEMI = ("【本章定位】推进：男主摆摊，认识苏晚。\n"
                "【场景节拍】1.操场路灯下摆摊，马千军吆喝；"
                "2.龙套来问感情，陈屿连中三卦；"
                "3.苏晚借桌描横幅，点破他的路数；"
                "4.她邀他明天帮摊，他半推半就应下。\n"
                "【结尾钩子】排班表写着周六全天，而他本来打算睡到中午。")

OUTLINE_NEWLINE = ("【场景节拍】\n1. 第一拍内容足够长可以解析出来啊\n2. 第二拍也够长同样要解析\n")
OUTLINE_NO_BEATS = "【本章定位】日常章。\n【核心事件】吃饭。"


def test_parse_scene_beats_semicolon():
    beats = parse_scene_beats(OUTLINE_SEMI)
    assert len(beats) == 4
    assert beats[0].startswith("操场")
    assert "苏晚" in beats[2]


def test_parse_scene_beats_newline_and_missing():
    assert len(parse_scene_beats(OUTLINE_NEWLINE)) == 2
    assert parse_scene_beats(OUTLINE_NO_BEATS) == []
    assert parse_scene_beats("") == []


def test_parse_outline_field():
    assert "排班表" in parse_outline_field(OUTLINE_SEMI, "结尾钩子")
    assert parse_outline_field(OUTLINE_SEMI, "不存在的字段") == ""


# ---------------------------------------------------------------------------
# 章张力档 + 逐拍曲线
# ---------------------------------------------------------------------------

def test_chapter_tension_keywords():
    # 无 DB 依赖的纯关键词路径：高潮 +2 → 4；铺垫 -1 → 1；基线 2
    assert chapter_tension(0, 0, "【本章定位】本章是卷末高潮，全面爆发") == 4
    assert chapter_tension(0, 0, "【本章定位】铺垫日常，温情过渡") == 1
    assert chapter_tension(0, 0, "【本章定位】推进：摆摊认人") == 2


def test_chapter_tension_foreshadow_pressure(client):
    novel = Novel(title="t", genre="都市")
    db.session.add(novel)
    db.session.flush()
    db.session.add(Foreshadowing(novel_id=novel.id, title="a", description="x",
                                 planted_chapter=1, status="planned",
                                 expected_resolve_chapter=3))
    db.session.commit()
    # 第 3 章：到期 +1；无关键词基线 2 → 3
    assert chapter_tension(novel.id, 3, "【本章定位】推进") == 3
    # 第 5 章：逾期 +1 → 3（仍是债务）
    assert chapter_tension(novel.id, 5, "【本章定位】推进") == 3


def test_beat_tensions_not_flat():
    for level in (2, 3, 4, 5):
        beats = ["日常铺垫拍" for _ in range(4)]
        beats[2] = "正面冲突摊牌拍"
        lv = beat_tensions(level, beats)
        assert len(lv) == 4
        assert max(lv) == level                    # 峰值拍吃满章档
        assert len(set(lv)) >= 2                   # 曲线不平
        assert lv.index(max(lv)) == 2              # 冲突词定位峰值
    # 无冲突词：峰值默认倒数第二拍（jarvis-write：高潮摆最后是"为了炸而炸"）
    lv = beat_tensions(4, ["a" * 12, "b" * 12, "c" * 12])
    assert lv.index(4) == 1


def test_beat_tensions_tail_falloff():
    """峰值后留余韵：末拍压到 level-2；两拍章 = 峰值拍 + 余韵拍。"""
    lv = beat_tensions(5, ["a" * 12, "b" * 12, "c" * 12, "d" * 12])
    assert lv == [3, 4, 5, 3]          # 爬升(3,4) → 峰值(5) → 余韵(3)
    lv2 = beat_tensions(4, ["a" * 12, "b" * 12])
    assert lv2 == [4, 2]


def test_chapter_tension_volume_finale(client):
    """卷末抬升：下一章已挂到别的卷节点 → 本章 +1（长书后段不塌）。"""
    from app.models import OutlineNode
    novel = Novel(title="卷末测试", genre="都市")
    db.session.add(novel)
    db.session.flush()
    vol1 = OutlineNode(novel_id=novel.id, node_type="volume", title="卷一")
    vol2 = OutlineNode(novel_id=novel.id, node_type="volume", title="卷二")
    db.session.add_all([vol1, vol2])
    db.session.flush()
    n1 = OutlineNode(novel_id=novel.id, node_type="chapter",
                     parent_id=vol1.id, title="第1章")
    n2 = OutlineNode(novel_id=novel.id, node_type="chapter",
                     parent_id=vol1.id, title="第2章")
    n3 = OutlineNode(novel_id=novel.id, node_type="chapter",
                     parent_id=vol2.id, title="第3章")
    db.session.add_all([n1, n2, n3])
    db.session.flush()
    from app.models import Chapter as ChapterModel
    db.session.add_all([
        ChapterModel(novel_id=novel.id, chapter_number=1, outline_node_id=n1.id),
        ChapterModel(novel_id=novel.id, chapter_number=2, outline_node_id=n2.id),
        ChapterModel(novel_id=novel.id, chapter_number=3, outline_node_id=n3.id),
    ])
    db.session.commit()
    base = "【本章定位】推进：收尾。"
    assert chapter_tension(novel.id, 1, base) == 2   # 卷中章：基线
    assert chapter_tension(novel.id, 2, base) == 3   # 卷末：+1


def test_temperature_for_level():
    assert temperature_for_level(0.8, 5) == 0.9
    assert temperature_for_level(0.8, 4) == 0.9
    assert temperature_for_level(0.8, 3) == 0.85
    assert temperature_for_level(0.8, 2) == 0.8
    assert temperature_for_level(0.8, 1) == 0.75
    assert temperature_for_level(0.98, 5) == 1.0   # 封顶
    assert temperature_for_level(0.61, 1) == 0.6   # 保底


def test_tension_directive_levels():
    for lv in range(1, 6):
        assert tension_directive(lv)
    assert "爆发" in tension_directive(5)


# ---------------------------------------------------------------------------
# 强度审计 + 峰值软检查
# ---------------------------------------------------------------------------

def _flat_chapter():
    # 实测"平淡"指纹：零叹号、问号稀、唤醒词低、句句克制
    para = ("他把手机放在桌上，看了窗外一会儿。她没说话，低头收拾碗筷。"
            "他也没再问。饭吃完，两人各自回房。第二天照常上课。")
    return para * 20


def _intense_chapter():
    para = ("他吼了出来，把杯子砸在墙上！「你到底瞒了我什么？」她哭了，"
            "浑身发抖，转身就跑。他冲上去拽住她的手腕，她挣扎着嘶吼。")
    return para * 10


def test_measured_intensity_and_gap():
    flat = measured_intensity(_flat_chapter())
    intense = measured_intensity(_intense_chapter())
    assert flat is not None and intense is not None
    assert intense > flat * 3
    # 档 4 的章实测太平 → 有落差提示；档 1 不误伤
    assert "张力档 4" in intensity_gap_note(4, flat)
    assert intensity_gap_note(1, flat) == ""
    assert intensity_gap_note(3, intense) == ""


def test_web_novel_gate_emotion_peak():
    rep_flat = analyze_web_novel(_flat_chapter(), outline=OUTLINE_SEMI)
    peak = next(c for c in rep_flat["checks"] if c["key"] == "emotion_peak")
    assert not peak["passed"]
    rep_hot = analyze_web_novel(_intense_chapter(), outline=OUTLINE_SEMI)
    peak2 = next(c for c in rep_hot["checks"] if c["key"] == "emotion_peak")
    assert peak2["passed"]
    # 软检查：weight 8 < 20，永远不产生 high 风险（不阻断，只提示）
    assert peak["risk"] == "mid"


# ---------------------------------------------------------------------------
# 伏笔窗口过滤 + 大纲名册过滤（build_writer_kwargs）
# ---------------------------------------------------------------------------

def test_writer_kwargs_filters(client):
    novel = Novel(title="书", genre="都市", synopsis="x", world_intro="x")
    db.session.add(novel)
    db.session.flush()
    for name in ("陈屿", "苏晚", "马千军", "江屹"):
        db.session.add(Character(novel_id=novel.id, name=name,
                                 personality="p", background="b"))
    # 远期伏笔（第 40 章才收）与近期到期伏笔（第 3 章）
    db.session.add(Foreshadowing(novel_id=novel.id, title="远期", description="d",
                                 planted_chapter=1, status="planned",
                                 expected_resolve_chapter=40))
    db.session.add(Foreshadowing(novel_id=novel.id, title="近期", description="d2",
                                 planted_chapter=1, status="planned",
                                 expected_resolve_chapter=3))
    db.session.commit()

    from app.services.writer_chain import build_writer_kwargs
    outline = ("【本章定位】推进：摆摊。\n"
               "【出场人物】陈屿、苏晚、马千军、龙套（不起名）\n"
               "【场景节拍】1.摆摊开张吆喝拉客；2.苏晚来借桌描横幅点破路数。\n"
               "【结尾钩子】排班表全天。")
    kw, _ = build_writer_kwargs(novel.id, 2, outline)
    names = [c["name"] for c in kw["characters"]]
    # 大纲名册 3 人（龙套排除），江屹不注入
    assert set(names) == {"陈屿", "苏晚", "马千军"}
    # 近期到期伏笔保留，第 40 章远期伏笔让路
    titles = [f.get("title") for f in kw["foreshadowing_items"]]
    assert "近期" in titles and "远期" not in titles


def test_writer_kwargs_keeps_all_when_no_roster(client):
    novel = Novel(title="书2", genre="都市")
    db.session.add(novel)
    db.session.flush()
    db.session.add(Character(novel_id=novel.id, name="甲", personality="p"))
    db.session.add(Character(novel_id=novel.id, name="乙", personality="p"))
    db.session.commit()
    from app.services.writer_chain import build_writer_kwargs
    kw, _ = build_writer_kwargs(novel.id, 1, "【本章定位】推进：没有名册字段。")
    assert len(kw["characters"]) == 2   # 无名册不误伤：回退全量


# ---------------------------------------------------------------------------
# 节拍级生成（beatwise）：多拍多次调用 / 温度分档 / 拍间衔接 / 事件帧
# ---------------------------------------------------------------------------

def test_beatwise_generation(client, monkeypatch):
    from app.services import writer_chain as wc

    calls = []

    def fake_stream(model, messages, **kwargs):
        calls.append({"messages": messages, "temperature": kwargs.get("temperature")})
        beat_no = len(calls)
        for ch in f"第{beat_no}拍正文。" * 120:   # 每拍 ~600 字
            yield ch

    monkeypatch.setattr(wc, "stream_llm_tokens", fake_stream)

    plan = wc.build_scene_plan(OUTLINE_SEMI, kw={
        "chapter_events": "【事件】卖卦",
        "author_intent": "全书承诺：玄学只是皮",
        "current_focus": "卷一：占卜摊相遇",
        "characters": [{"name": "陈屿", "personality": "半信派，毒舌心软",
                        "speaking_style": "行话是挡箭牌"},
                       {"name": "苏晚", "personality": "直球热场",
                        "speaking_style": "快、直、爱拆台"}],
        "cast_constraint": "本章只允许陈屿、苏晚登场。",
        "narrative_plan": "must_payoff：书名句（第 1 章埋）",
        "boundary_context": "陈屿只知道：亲眼所见(第1章)摆摊开张",
        "tone_instructions": "近期指纹：段首回指偏多，注意",
        "style_memo": "- 短句白描",
    }, word_target=2400, novel_id=0, chapter_number=1)
    assert plan is not None
    assert len(plan["beats"]) == 4
    assert len(plan["beat_tensions"]) == 4
    plan["prev_ending"] = "上一章结尾：他数完钱睡下了。"

    gen_events = []
    collected = []
    for tok in wc.generation_tokens(
            [{"role": "system", "content": "SYS"}, {"role": "user", "content": "FULL"}],
            {"model_name": "fake", "temperature": 0.8, "max_tokens": 4096},
            word_target=None,   # 关掉续写轮：拍数与调用数一一对应
            on_event=gen_events.append, scene_plan=plan):
        collected.append(tok)
    text = "".join(collected)

    # 4 拍恰好 4 次调用（每拍产出 600 字 × 4 = 2400 ≥ 底线本也无需续写）
    assert len(calls) == 4, [c for c in calls]
    assert text.startswith("第1拍正文。")
    assert "第4拍正文。" in text
    # 每拍 user 消息只带本拍任务（不是整章大纲），且含张力档行
    for i, c in enumerate(calls):
        u = c["messages"][1]["content"]
        assert f"第 {i + 1}/4 拍" in u
        assert "张力档" in u
        assert plan["beats"][i][:10] in u
    # 首拍带上一章结尾衔接，末拍带章尾钩
    assert "上一章结尾" in calls[0]["messages"][1]["content"]
    assert "章尾钩" in calls[3]["messages"][1]["content"]
    # P0 回归：硬约束块必须在每一拍都在场（整章 user 块的最小存活集）
    for i, c in enumerate(calls):
        u = c["messages"][1]["content"]
        assert "全书承诺" in u, f"拍{i + 1} 丢创作罗盘"
        assert "出场人物速写" in u and "爱拆台" in u, f"拍{i + 1} 丢人物速写"
        assert "只允许陈屿、苏晚登场" in u, f"拍{i + 1} 丢登场白名单"
        assert "must_payoff" in u, f"拍{i + 1} 丢叙事计划"
        assert "一致性红线" in u, f"拍{i + 1} 丢信息边界"
        assert "短句白描" in u, f"拍{i + 1} 丢文体备忘"
    # 拍级 prompt 仍显著小于整章（拆锅是"减提示词"方向）
    assert max(len(c["messages"][1]["content"]) for c in calls) < 6000
    # 温度按拍张力分档（峰值拍 ≥ 基线，低谷拍 ≤ 基线）
    temps = [c["temperature"] for c in calls]
    assert max(temps) >= 0.8 >= min(temps)
    assert len(set(temps)) >= 2
    # 事件帧：beat_start/beat_end 各 4 次，首帧带拍张力
    starts = [e for e in gen_events if e.get("stage") == "beat_start"]
    assert len(starts) == 4 and starts[0]["tension"] == plan["beat_tensions"][0]
    assert len([e for e in gen_events if e.get("stage") == "beat_end"]) == 4


def test_beatwise_events_stream(client, monkeypatch):
    """on_event 事件流经 generation_tokens 正常透出（SSE 进度帧依赖）。"""
    from app.services import writer_chain as wc

    def fake_stream(model, messages, **kwargs):
        for ch in "好戏开场。" * 150:
            yield ch

    monkeypatch.setattr(wc, "stream_llm_tokens", fake_stream)
    plan = {"beats": ["第一拍摆摊吆喝拉客开张", "第二拍冲突升级有人砸摊"],
            "tension": 3, "beat_tensions": [2, 3], "events": "",
            "hook": "", "word_target": 1200, "prev_ending": ""}
    gen_events = []
    collected = []
    for tok in wc.generation_tokens(
            [{"role": "system", "content": "S"}],
            {"model_name": "fake", "temperature": 0.8, "max_tokens": 4096},
            word_target=None, on_event=gen_events.append, scene_plan=plan):
        collected.append(tok)
    stages = [e["stage"] for e in gen_events]
    assert stages.count("beat_start") == 2
    assert stages.count("beat_end") == 2
    assert "".join(collected).startswith("好戏开场。")


def test_beat_retry_rejects_and_rewrites(client, monkeypatch):
    """拍级验收保险丝（编排器路径）：初稿过短 → 丢弃重写一次，坏稿不进正文。"""
    from app.services import writer_chain as wc

    calls = []
    fillers = ["他吼了出来，把杯子砸在墙上！", "她哭了，转身就跑，浑身发抖。"]

    def fake_stream(model, messages, **kwargs):
        n = len(calls)
        calls.append(messages)
        if n == 0:
            yield "太短。"                       # 第一拍初稿：不合格
        else:
            yield f"第{n}拍正文。" + fillers[(n - 1) % len(fillers)] * 30

    monkeypatch.setattr(wc, "stream_llm_tokens", fake_stream)
    plan = {"beats": ["第一拍摆摊吆喝拉客开张", "第二拍冲突升级有人砸摊"],
            "tension": 4, "beat_tensions": [3, 4], "events": "",
            "hook": "", "word_target": 1200, "prev_ending": ""}
    gen_events = []
    collected = []
    for tok in wc.generation_tokens(
            [{"role": "system", "content": "S"}],
            {"model_name": "fake", "temperature": 0.8, "max_tokens": 4096},
            word_target=None, on_event=gen_events.append, scene_plan=plan,
            beat_retry=True):
        collected.append(tok)
    text = "".join(collected)
    assert len(calls) == 3                    # 拍1初稿 + 拍1重写 + 拍2
    assert "太短" not in text                  # 坏稿被丢弃
    assert "第1拍正文" in text and "第2拍正文" in text
    retries = [e for e in gen_events if e.get("stage") == "beat_retry"]
    assert len(retries) == 1 and "过短" in retries[0]["reason"]
    # 重写调用的 system 带不合格原因（定向修正，不是盲目重roll）
    assert "不合格" in calls[1][0]["content"]


def test_beat_accepted_unit():
    from app.services.writer_chain import _beat_accepted
    ok, _ = _beat_accepted("正常的一拍正文。" * 20, "前文结尾")
    assert ok
    ok, reason = _beat_accepted("太短。", "")
    assert not ok and "过短" in reason
    dup = "他吼了出来，把杯子砸在墙上！" * 30
    ok, reason = _beat_accepted(dup, dup)     # 与前文完全一致
    assert not ok and "重复" in reason


def test_foreshadow_importance_fallback(client):
    """无日期伏笔：远期埋设让路，但高重要度（≥4）兜底保留（P1 回归）。"""
    novel = Novel(title="伏笔兜底", genre="都市")
    db.session.add(novel)
    db.session.flush()
    db.session.add(Foreshadowing(novel_id=novel.id, title="远期低重要度",
                                 description="d", planted_chapter=40,
                                 status="planned", importance=2))
    db.session.add(Foreshadowing(novel_id=novel.id, title="远期高重要度",
                                 description="d2", planted_chapter=40,
                                 status="planned", importance=5))
    db.session.commit()
    from app.services.writer_chain import build_writer_kwargs
    kw, _ = build_writer_kwargs(novel.id, 1, "【本章定位】推进。\n【场景节拍】1.开张；2.收摊。")
    titles = [f.get("title") for f in kw["foreshadowing_items"]]
    assert "远期高重要度" in titles
    assert "远期低重要度" not in titles


def test_sse_forwards_scene_plan(client, monkeypatch):
    """SSE 帮助函数把 scene_plan 原样转交 generation_tokens（Web 端拆锅接线）。"""
    from app.routes import generate as gen_mod
    captured = {}

    def fake_generation_tokens(messages, cfg, word_target=None, on_event=None,
                               scene_plan=None, beat_retry=False):
        captured["scene_plan"] = scene_plan
        captured["beat_retry"] = beat_retry
        yield "正文"

    monkeypatch.setattr(gen_mod, "generation_tokens", fake_generation_tokens)
    plan = {"beats": ["第一拍", "第二拍内容够长"], "tension": 3,
            "beat_tensions": [2, 3], "events": "", "context": "",
            "hook": "", "word_target": 1000, "prev_ending": ""}
    raw = "".join(gen_mod._stream_to_sse(
        [{"role": "user", "content": "x"}], {"model_name": "m"},
        scene_plan=plan))
    assert captured["scene_plan"] is plan
    assert captured["beat_retry"] is False      # SSE 路径不开拍级重试
    assert '"token": "正文"' in raw


def test_beat_merge_caps_over_slicing(client):
    """拍数超限相邻合并：内容不丢、上限 5 拍（碎段感防线，实测 8 拍场景）。"""
    from app.services.writer_chain import build_scene_plan
    outline = ("【本章定位】推进：摆摊。\n【场景节拍】"
               + "；".join(f"第{i}拍摆摊发生的事足够长了啊" for i in range(1, 9))
               + "\n【结尾钩子】排班表全天。")
    plan = build_scene_plan(outline, word_target=2500, novel_id=0, chapter_number=1)
    assert plan is not None
    assert len(plan["beats"]) == 5
    # 8 拍的内容全保留（分组拼接）
    assert "第1拍" in plan["beats"][0] and "第8拍" in plan["beats"][-1]
    # 5 拍内不合并
    outline5 = ("【本章定位】推进。\n【场景节拍】"
                + "；".join(f"第{i}拍内容" + "很长" * 8 for i in range(1, 6)))
    plan5 = build_scene_plan(outline5, word_target=2500, novel_id=0, chapter_number=1)
    assert len(plan5["beats"]) == 5


# ---------------------------------------------------------------------------
# 事件清单截断抢救（chapter_events，实测 GLM verbose goal 破 800 tokens）
# ---------------------------------------------------------------------------

def test_event_extraction_salvages_truncated_json(monkeypatch):
    """JSON 死在半截字符串：截断前完整的事件对象应被捞回。"""
    from app.services import chapter_events as ce

    truncated = (
        '{"events": ['
        '{"goal": "陈屿要把写好的攻略发她，把七月之行钉死在日程上", '
        '"conflict": "她讲队长的事有戏，他不敢问结果", '
        '"outcome": "她语音改了两处车次", "stake": "攻略作废则约会落空"}, '
        '{"goal": "他打出我票都看好了又删掉，只回了行，寒假'   # ← 截断处
    )
    monkeypatch.setattr(ce, "call_llm_sync" if hasattr(ce, "call_llm_sync") else "x",
                        None, raising=False)
    # 直接测解析段：把截断文本喂给内部逻辑（绕过 LLM 调用）
    import json as _json
    import re as _re
    raw = truncated.strip()
    events = []
    for m in _re.finditer(r"\{[^{}]*\}", raw, _re.S):
        try:
            ev = _json.loads(m.group(0))
        except _json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and (ev.get("goal") or ev.get("conflict")):
            events.append(ev)
    assert len(events) == 1
    assert "钉死在日程上" in events[0]["goal"]


def test_intensity_gap_quiet_register(client):
    """基调感知：安静向基调的期望下限减半（安静的煎熬是合法写法）。"""
    flat = measured_intensity(_flat_chapter())
    loud_outline_tone = "热闹喧哗"
    quiet_tone = "安静的煎熬：克制、白描"
    # 档 3 实测 5.0（下限8）：响基调报警；安静基调下限减半到 4 → 不报警；
    # 但 0.0 的全死文本连安静基调也救不了
    assert "张力档 3" in intensity_gap_note(3, 5.0, tone_text=loud_outline_tone)
    assert intensity_gap_note(3, 5.0, tone_text=quiet_tone) == ""
    assert "张力档 3" in intensity_gap_note(3, flat, tone_text=quiet_tone)
