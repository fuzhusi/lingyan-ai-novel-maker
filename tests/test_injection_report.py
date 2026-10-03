"""注入观测层 + 知识库容器页回归（调研 v2 第 0 步 + 前端方案 B）。"""
from app import db
from app.models import Character, Foreshadowing, Novel, WorldSetting
from app.services.prompt_builder.writer import build_writer_prompt
from app.services.writer_chain import build_writer_kwargs


# ---------------------------------------------------------------------------
# 观测层：注入清单
# ---------------------------------------------------------------------------

def test_injection_report_dims_and_zero_prompt_change(client):
    """报告覆盖全部维度；且纯观测——prompt 内容不含报告痕迹。"""
    n = Novel(title="观测测试", genre="都市", synopsis="s", world_intro="w",
              author_intent="承诺A")
    db.session.add(n)
    db.session.commit()
    kw, novel = build_writer_kwargs(n.id, 1, "【本章定位】推进。\n【结尾钩子】有事发生。")
    report = kw.get("injection_report")
    assert report and report["dims"], "报告必须存在且有维度"
    dims = {d["dim"] for d in report["dims"]}
    # 关键维度登记（17 管道的代表集）
    for dim in ("boundary_context", "context_budget", "semantic_select",
                "style_fingerprint", "tone_instructions", "style_memo",
                "creator_preferences", "foreshadow_window"):
        assert dim in dims, f"缺维度 {dim}"
    assert "sizes" in report and report["total_chars"] > 0
    # 零行为变化：报告与报告字段值不出现在任何 prompt 消息里
    msgs = build_writer_prompt(**kw)
    blob = "".join(m.get("content") or "" for m in msgs)
    assert "injection_report" not in blob and "注入降级" not in blob


def test_injection_report_degradation_visible(client, monkeypatch):
    """注入管道降级时报告必须可见（静默失效变可见失效）。"""
    n = Novel(title="降级测试", genre="都市")
    db.session.add(n)
    db.session.commit()

    def boom(*a, **k):
        raise RuntimeError("模拟故障")

    monkeypatch.setattr(
        "app.services.causal_chain.get_chain_context", boom)
    kw, _ = build_writer_kwargs(n.id, 1, "【本章定位】推进。")
    report = kw["injection_report"]
    entry = next(d for d in report["dims"] if d["dim"] == "causal_chain")
    assert entry["status"] == "degraded" and "模拟故障" in entry["note"]
    assert "causal_chain" in report["degraded"]


def test_tail_recap_block(client):
    """尾部复述区：承诺/重心/钩子临近生成处再出现一次（≤200 字符）。"""
    msgs = build_writer_prompt(
        novel_title="t", outline="【本章定位】x\n【结尾钩子】排班表写着全天",
        author_intent="承诺内容很长很长很长，只需复述前 60 字也有效",
        current_focus="卷一收束", boundary_context="陈屿知道：某事实")
    user = msgs[1]["content"]
    assert "尾部复述" in user
    assert user.index("尾部复述") > user.index("信息边界与既定事实")   # 位于近尾部
    assert "承诺内容" in user and "排班表" in user


def test_summaries_moved_after_boundary(client):
    """近因效应修正：近章摘要必须出现在信息边界之后（贴尾部）。"""
    msgs = build_writer_prompt(
        novel_title="t", outline="x",
        summaries=[{"chapter_number": 3, "summary": "第三章摘要内容"}],
        boundary_context="陈屿知道：某事实")
    user = msgs[1]["content"]
    assert user.index("近章前情提要") > user.index("信息边界与既定事实")


# ---------------------------------------------------------------------------
# 知识库容器页
# ---------------------------------------------------------------------------

def test_knowledge_page_tabs_and_legacy_pages(client):
    n = Novel(title="前端测试", genre="都市")
    db.session.add(n)
    db.session.commit()
    db.session.add(Character(novel_id=n.id, name="陈屿", personality="沉默"))
    db.session.add(WorldSetting(novel_id=n.id, category="地理", title="常德",
                                content="沅水边的城市"))
    db.session.add(Foreshadowing(novel_id=n.id, title="旧怀表",
                                 description="封印", status="open"))
    db.session.commit()

    # 三个 Tab 各自渲染对应内容
    for tab, marker in (("characters", "陈屿"), ("world", "沅水边的城市"),
                        ("foreshadowing", "封印")):
        resp = client.get(f"/novel/{n.id}/knowledge?tab={tab}")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert marker in body and "知识库" in body
    # 非法 tab 回退默认
    assert client.get(f"/novel/{n.id}/knowledge?tab=bogus").status_code == 200
    # 旧页面路由仍然工作（深链兼容，未删除）
    assert client.get(f"/novel/{n.id}/characters").status_code == 200
    assert client.get(f"/novel/{n.id}/world-settings").status_code == 200
    assert client.get(f"/novel/{n.id}/foreshadowing").status_code == 200


def test_sse_emits_injection_report_frame(client, monkeypatch):
    """SSE 流首帧区透出 injection_report（Web 端可见）。"""
    from app.routes import generate as gen_mod
    import json as _json

    def fake_tokens(messages, cfg, word_target=None, on_event=None,
                    scene_plan=None):
        yield "正文"

    monkeypatch.setattr(gen_mod, "generation_tokens", fake_tokens)
    report = {"dims": [{"dim": "memory", "status": "ok", "note": ""}],
              "total_chars": 123, "degraded": []}
    raw = "".join(gen_mod._stream_to_sse(
        [{"role": "user", "content": "x"}], {"model_name": "m"},
        injection_report=report))
    frames = [_json.loads(line[6:]) for line in raw.split("\n")
              if line.startswith("data: ")]
    inj = [f["status"] for f in frames if "status" in f
           and f["status"].get("stage") == "injection_report"]
    assert inj and inj[0]["total_chars"] == 123


def test_runner_stages_and_version_record_carry_report(client, monkeypatch):
    """编排器路径：injection_report 进 stages，auto_save 写入 model_params_json。"""
    from app.routes.knowledge import characters as _  # noqa: F401  确保路由已导入
    from app.services import chapter_runner as runner

    n = Novel(title="编排观测", genre="都市", synopsis="s", world_intro="w")
    db.session.add(n)
    db.session.commit()
    from app.models import Chapter
    db.session.add(Chapter(novel_id=n.id, chapter_number=1,
                           outline="【本章定位】推进：首章建立人物与异常。\n"
                                   "【核心事件】1.开局事件；2.转折事件。\n"
                                   "【结尾钩子】门外传来敲门声。"))
    db.session.add(Character(novel_id=n.id, name="陈屿", personality="沉默寡言"))
    db.session.commit()

    body = "陈屿推开宿舍门，床上居然躺着个陌生人。" * 30   # >200 字
    monkeypatch.setattr(runner, "collect_full_text",
                        lambda messages, cfg, word_target=None,
                        scene_plan=None: body)
    monkeypatch.setattr("app.services.skill_gate.run_gate",
                        lambda text, active_skills=None: {"passed": True, "checks": []})
    monkeypatch.setattr("app.services.ai_metric.analyze_ai_tone",
                        lambda text, mode="generate": {"passed": True, "human_score": 95})
    monkeypatch.setattr(
        "app.services.web_novel_gate.analyze_web_novel",
        lambda text, outline="", event_count=None, is_first_chapter=False,
        protagonist_names=None: {"passed": True, "readability_score": 95,
                                 "checks": [], "hint": ""})

    result = runner.run_chapter_pipeline(n.id, 1, auto_save=True)
    assert "error" not in result
    stage = next(s for s in result["stages"] if s["stage"] == "injection_report")
    assert stage["dims"] and stage["total_chars"] > 0
    assert "characters" in stage["sizes"]

    from app.models import ChapterVersion
    ver = ChapterVersion.query.get(result["saved_version_id"])
    import json as _json
    saved = _json.loads(ver.model_params_json or "{}")
    assert saved["injection_report"]["dims"], "版本记录必须携带注入报告"


def test_injection_report_skip_status_explicit(client):
    """skip 状态显式断言：未配置的维度记 skipped 而非静默缺席。"""
    n = Novel(title="跳过测试", genre="都市")
    db.session.add(n)
    db.session.commit()
    kw, _ = build_writer_kwargs(n.id, 1, "【本章定位】推进。")
    report = kw["injection_report"]
    dims = {d["dim"]: d["status"] for d in report["dims"]}
    for dim in ("creator_preferences", "tone_instructions"):
        assert dim in dims, f"{dim} 必须显式登记（ok/skip/degrade 之一）"
        assert dims[dim] in ("ok", "skipped", "degraded")
    assert report["degraded_count"] == 0


def test_knowledge_forms_wellformed(client):
    """回归：next 隐藏域必须落在 form 标签闭合之后——
    曾经插入到未闭合标签中间，把 onsubmit/confirm 挤成页面可见文本
    （tojson 的 unicode 转义随之原样泄漏到确认框）。"""
    n = Novel(title="表单结构", genre="都市")
    db.session.add(n)
    db.session.commit()
    db.session.add(Character(novel_id=n.id, name="明尘", personality="p"))
    db.session.add(WorldSetting(novel_id=n.id, category="规则", title="规矩", content="c"))
    db.session.add(Foreshadowing(novel_id=n.id, title="怀表", description="d"))
    db.session.commit()
    broken_sig = '"\n<input type="hidden" name="next"'
    for tab in ("characters", "world", "foreshadowing"):
        body = client.get(f"/novel/{n.id}/knowledge?tab={tab}").get_data(as_text=True)
        assert broken_sig not in body, f"{tab} 存在断裂的 form 标签"
        assert body.count('name="next"') >= 1
