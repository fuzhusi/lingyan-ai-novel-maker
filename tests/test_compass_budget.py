"""创作罗盘 + 上下文预算压缩 + @skill-id 按需启用测试。

路由级接线测试（test_generate_stream_wires_compass 等）的存在原因：
build_writer_prompt 单测传参正确不代表路由层真的把值接进去了——
writer 主链路曾因此漏接罗盘而全部测试照绿。
"""
from app import db
from app.models import Novel, Chapter, ChapterVersion, ChapterSummary
from app.services.prompt_builder import (
    build_writer_prompt, build_outline_prompt, build_rewrite_prompt,
    apply_context_budget,
)
from app.services.skill_system import parse_directive_skills, build_skill_prompt
from app.services.chapter_approval import (
    approve_chapter_version, EmptyChapterError,
)
import pytest


# ---------------------------------------------------------------------------
# 创作罗盘
# ---------------------------------------------------------------------------

def test_writer_prompt_compass(app):
    msgs = build_writer_prompt(
        novel_title="测试", author_intent="写一个复仇故事外壳下的救赎",
        current_focus="第二卷收尾")
    user = msgs[1]["content"]
    assert "创作罗盘" in user
    assert "复仇故事" in user
    assert "第二卷收尾" in user


def test_writer_prompt_no_compass(app):
    msgs = build_writer_prompt(novel_title="测试")
    assert "创作罗盘" not in msgs[1]["content"]


def test_outline_prompt_compass(app):
    msgs = build_outline_prompt(novel_title="测试", author_intent="全书承诺X")
    assert "创作罗盘" in msgs[1]["content"]
    assert "全书承诺X" in msgs[1]["content"]


def test_outline_prompt_fixed_format(app):
    """大纲固定格式：7 个字段名必须出现在 system prompt，硬性要求与人名约束在位。"""
    msgs = build_outline_prompt(
        novel_title="测试", characters=[{"name": "林昭"}])
    sys_prompt = msgs[0]["content"]
    for field in ("【本章定位】", "【核心事件】", "【出场人物】", "【场景节拍】",
                  "【情感基调】", "【伏笔操作】", "【结尾钩子】"):
        assert field in sys_prompt, f"缺少固定格式字段 {field}"
    # 出场人物与人物卡同名（infer_cast 自动勾选依赖人名精确匹配）
    assert "完全一致" in sys_prompt
    assert "背景提及" in sys_prompt
    # 三条硬性要求：字数上限 / 禁正文式描写 / 名单外角色不得进节拍
    assert "250" in sys_prompt
    assert "禁止出现对白" in sys_prompt
    assert "名单之外" in sys_prompt
    # 场景节拍施工语义（jarvis-write 式 beats）
    assert "施工" in sys_prompt
    # 条件化引用：冷启动（无角色卡/无前情）时指令不得悬空引用
    assert "若下方列出现有人物" in sys_prompt
    assert "若【前情提要】" in sys_prompt
    # 结尾用户指令指向固定格式
    assert "固定格式" in msgs[1]["content"]


def test_outline_prompt_world_settings_block(app):
    """世界观条目注入：节拍地点名须取自设定，防大纲自创平行世界地名。"""
    msgs = build_outline_prompt(
        novel_title="测试",
        world_settings=[{"category": "地理", "title": "临安城",
                         "content": "江南水乡大城"}])
    user = msgs[1]["content"]
    assert "世界观设定条目" in user
    assert "临安城" in user
    assert "不得自创" in msgs[0]["content"] or "取自" in user


def test_outline_prompt_db_template_override(app):
    """模板库 outline 类型记录会整体覆盖内置固定格式——行为须锁定为有意设计。"""
    from app.models import PromptTemplate
    t = PromptTemplate(
        name="自定义大纲提示词",
        template_type="outline",
        template_content="你是自定义大纲师，按你自己的风格写。")
    db.session.add(t)
    db.session.commit()
    try:
        msgs = build_outline_prompt(novel_title="模板覆盖测试", db=db)
        assert "自定义大纲师" in msgs[0]["content"]
        assert "【场景节拍】" not in msgs[0]["content"]  # 覆盖 = 固定格式整体让位
    finally:
        # session 级测试库跨用例共享，覆盖行必须自清理，否则污染后续测试
        db.session.delete(t)
        db.session.commit()


def test_writer_prompt_beats_instruction(app):
    """大纲含【场景节拍】时写手须收到逐拍施工指令；旧格式大纲不受影响。"""
    beats_outline = ("【本章定位】推进：主角北上\n"
                     "【场景节拍】1. 城门盘查，主角藏玉佩过关\n"
                     "【结尾钩子】身后有人认出了他")
    msgs = build_writer_prompt(novel_title="测试", outline=beats_outline)
    user = msgs[1]["content"]
    assert "节拍施工指令" in user
    assert "逐拍" in user

    plain_outline = "主角北上，途中遭遇伏击。"
    msgs2 = build_writer_prompt(novel_title="测试", outline=plain_outline)
    assert "节拍施工指令" not in msgs2[1]["content"]

    msgs3 = build_writer_prompt(novel_title="测试", outline="")
    assert "节拍施工指令" not in msgs3[1]["content"]


def test_rewrite_prompt_forbids_meta_commentary(app):
    """回归：改写模型曾在正文尾部附"改动说明：1.2.3."清单——prompt 须明令禁止。"""
    msgs = build_rewrite_prompt(
        original_content="x", critic_feedback="y",
        author_intent="承诺A", current_focus="重心B")
    sys_prompt = msgs[0]["content"]
    user_prompt = msgs[1]["content"]
    assert "改动说明" in sys_prompt and "不得出现" in sys_prompt
    assert "禁止附加改动说明" in user_prompt


def test_rewrite_prompt_compass(app):
    msgs = build_rewrite_prompt(
        original_content="x", critic_feedback="y",
        author_intent="承诺A", current_focus="重心B")
    assert "承诺A" in msgs[1]["content"]
    assert "重心B" in msgs[1]["content"]


def test_compass_db_roundtrip(app):
    n = Novel(title="罗盘测试", author_intent="意图X", current_focus="重心Y")
    db.session.add(n)
    db.session.commit()
    got = Novel.query.get(n.id)
    assert got.author_intent == "意图X"
    assert got.current_focus == "重心Y"
    db.session.delete(got)
    db.session.commit()


def test_generate_stream_wires_compass(app, client, monkeypatch):
    """路由级接线：generate_stream 必须把罗盘传进 writer prompt。

    回归锚：kw 曾漏掉 author_intent/current_focus 两键，导致主写作链路
    永远收不到罗盘，而 builder 层单测全部通过。
    """
    n = Novel(title="接线测试", author_intent="意图必须直达prompt",
              current_focus="重心必须直达prompt")
    db.session.add(n)
    db.session.commit()

    captured = {}

    def fake_stream(model=None, messages=None, **kw):
        if "messages" not in captured:  # 只记首轮（续写轮会重复调用）
            captured["messages"] = messages
        yield "文" * 2500  # 超过字数底线，避免触发续写轮

    # 生成流已抽到 writer_chain 公共层（P3 编排器共用），patch 点随之迁移
    monkeypatch.setattr("app.services.writer_chain.stream_llm_tokens", fake_stream)
    resp = client.post("/api/generate-stream", data={
        "novel_id": n.id, "chapter_number": 1,
        "novel_title": n.title, "chapter_title": "第一章",
        "outline": "【本章定位】推进：主角北上。【核心事件】1. 途经哨塔遗迹，发现旧年雪下的低语源头；2. 甩开尾随者。【场景节拍】1. 雪原夜行，罗盘失灵；2. 塔内残卷。【结尾钩子】低语喊出了他的名字。",
    })
    assert resp.status_code == 200
    # SSE 响应是惰性生成：测试客户端 post() 只拉第一帧（现为 stream_start
    # 进度帧）。必须读完响应体，generation_tokens 才会真正执行到 fake_stream。
    resp.get_data(as_text=True)
    user = captured["messages"][1]["content"]
    assert "创作罗盘" in user
    assert "意图必须直达prompt" in user
    assert "重心必须直达prompt" in user


# ---------------------------------------------------------------------------
# 上下文预算渐进压缩
# ---------------------------------------------------------------------------

def test_budget_no_shrink(app):
    kw = {"summaries": [{"chapter_number": 1, "summary": "s"}],
          "earlier_summaries": "e" * 100,
          "world_settings": [], "characters": [], "memory_context": ""}
    log = apply_context_budget(kw)
    assert log == ""
    assert kw["earlier_summaries"] == "e" * 100


def test_budget_shrinks_earlier_first(app):
    kw = {"summaries": [{"chapter_number": i, "summary": "x" * 3000} for i in range(1, 4)],
          "earlier_summaries": "y" * 3000,
          "world_settings": [], "characters": [], "memory_context": ""}
    log = apply_context_budget(kw, budget=8000)
    assert kw["earlier_summaries"] == ""
    assert len(kw["summaries"]) >= 1
    assert "远章" in log


def test_budget_never_touches_compass_ending(app):
    # 罗盘/boundary_context/prev_ending 不参与 _size 计量，也不会被收缩键触及
    kw = {"summaries": [{"chapter_number": 1, "summary": "x" * 9000}],
          "earlier_summaries": "y" * 5000,
          "world_settings": [{"category": "c", "title": "t", "content": "z" * 5000}],
          "characters": [{"name": "a", "personality": "p",
                          "appearance": "long" * 500, "background": "b" * 500,
                          "motivation": "m"}],
          "memory_context": "mm" * 3000,
          "boundary_context": "主角不知道幕后主使是谁" * 50,
          "prev_ending": "结尾永不压缩" * 100,
          "author_intent": "意图永不压缩"}
    apply_context_budget(kw, budget=5000)
    assert kw["prev_ending"] == "结尾永不压缩" * 100
    assert kw["author_intent"] == "意图永不压缩"
    assert kw["boundary_context"] == "主角不知道幕后主使是谁" * 50  # 一致性红线豁免压缩
    assert kw["characters"][0]["appearance"] == ""  # 次要字段被裁
    assert kw["characters"][0]["motivation"] == "m"  # 主要字段保留


def test_writer_prompt_boundary_section(app):
    """信息边界作为独立段落注入（不再混入 memory_context 被截半）。"""
    msgs = build_writer_prompt(novel_title="测试",
                               boundary_context="主角此时不知道幕后主使")
    user = msgs[1]["content"]
    assert "信息边界" in user
    assert "主角此时不知道幕后主使" in user


# ---------------------------------------------------------------------------
# @skill-id 按需启用
# ---------------------------------------------------------------------------

def test_parse_directive_skills(app):
    d, ids = parse_directive_skills("本章加强悬念 @chapter_hook @pacing_control 注意收束")
    assert ids == ["chapter_hook", "pacing_control"]
    assert d == "本章加强悬念 注意收束"


def test_parse_directive_skills_none(app):
    assert parse_directive_skills("普通指示") == ("普通指示", [])
    assert parse_directive_skills("") == ("", [])
    # @ 前无空白不误判（邮箱）
    d, ids = parse_directive_skills("联系 abc@def.com")
    assert ids == []


def test_parse_directive_skills_unknown_preserved(app):
    """未知 @词不吞：不对应任何已注册技能的 @handle 原样保留在指示中。"""
    d, ids = parse_directive_skills("参考 @someone 的观点，加强悬念 @chapter_hook")
    assert ids == ["chapter_hook"]
    assert "@someone" in d
    assert "@chapter_hook" not in d


def test_skill_prompt_extra(app):
    base = build_skill_prompt("write")
    ext = build_skill_prompt("write", extra_skills=["chapter_hook"])
    assert "章节钩子" in ext  # 附加后必然注入该技巧内容
    ghost = build_skill_prompt("write", extra_skills=["no_such_skill_xyz"])
    assert ghost == base  # 未知 id 静默跳过，不注入任何内容


def test_writer_prompt_directive_skill(app):
    msgs = build_writer_prompt(
        novel_title="测试", user_directive="加强悬念 @sensory_detail")
    # @id 从指示中剥离
    assert "@sensory_detail" not in msgs[1]["content"]
    assert "加强悬念" in msgs[1]["content"]


# ---------------------------------------------------------------------------
# 审批事务（Web / MCP / CLI 共用服务）
# ---------------------------------------------------------------------------

def _make_version(content):
    n = Novel(title="审批事务测试")
    db.session.add(n)
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=1, title="第一章")
    db.session.add(ch)
    db.session.commit()
    ver = ChapterVersion(chapter_id=ch.id, version_number=1, content=content, source="ai")
    db.session.add(ver)
    db.session.commit()
    return n, ch, ver


def test_approve_service_rejects_empty(app):
    n, ch, ver = _make_version("   ")
    with pytest.raises(EmptyChapterError):
        approve_chapter_version(ver, generate_summary=False)
    assert ver.approved is not True  # 拒绝时不落任何状态


def test_approve_service_guard_and_mark(app):
    n, ch, ver = _make_version("主角在雨夜回到了旧宅。")
    result = approve_chapter_version(ver, generate_summary=False)
    assert result == {"approved": True, "summary": ""}
    assert ver.approved is True


def test_approve_service_summary_fallback(app, monkeypatch):
    """LLM 摘要失败时截取正文开头 300 字兜底，前情提要链路不断。"""
    from app.services.llm import LLMError

    def boom(*a, **kw):
        raise LLMError("模拟 LLM 不可用")

    monkeypatch.setattr("app.services.chapter_approval.call_llm_sync", boom)
    n, ch, ver = _make_version("正" * 500)
    result = approve_chapter_version(ver, generate_summary=True)
    assert result["summary"].startswith("正")
    assert len(result["summary"]) <= 302  # 300 字正文 + "……"
    cs = ChapterSummary.query.filter_by(chapter_id=ch.id).first()
    assert cs and cs.summary == result["summary"]


def test_web_approve_empty_version_returns_400(client):
    n, ch, ver = _make_version("")
    resp = client.post("/api/approve", data={"version_id": ver.id})
    assert resp.status_code == 400
    assert resp.get_json().get("error")


def test_outline_stream_wires_compass(app, client, monkeypatch):
    """outline-stream 回归：路由曾因重构漏导 assemble_chapter_context 而 500
    （症状：写作页点「AI 生成本章」毫无反应），且无任何测试覆盖——本测试补位。"""
    n = Novel(title="大纲链测试", author_intent="大纲必须服务此承诺",
              current_focus="收束北境伏笔")
    db.session.add(n)
    db.session.commit()

    captured = {}

    def fake_tokens(messages, cfg, word_target=None, on_event=None):
        captured["messages"] = messages
        yield "大纲：主角进入北境。"

    monkeypatch.setattr("app.routes.generate.generation_tokens", fake_tokens)
    resp = client.post("/api/outline-stream", data={
        "novel_id": n.id, "chapter_number": 1,
        "novel_title": n.title, "chapter_title": "第一章",
    })
    assert resp.status_code == 200
    resp.get_data(as_text=True)  # 读完惰性 SSE 体，fake_tokens 才会执行（同上）
    user = captured["messages"][1]["content"]
    assert "创作罗盘" in user
    assert "大纲必须服务此承诺" in user
    # 路由层真的用上了固定格式大纲提示词（builder 单测绿但路由漏接的前车之鉴）
    sys = captured["messages"][0]["content"]
    assert "【场景节拍】" in sys
    assert "章节大纲固定格式" in sys
