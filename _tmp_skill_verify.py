# -*- coding: utf-8 -*-
"""验证：全链路技能注入。"""
import sys
sys.path.insert(0, ".")

from app import create_app
from app.models import db

app = create_app()
with app.app_context():
    db.create_all()

    from app.services.prompt_builder.writer import (
        build_writer_prompt, build_outline_prompt)
    from app.services.prompt_builder.review import build_rewrite_prompt
    from app.services.prompt_builder.keepers import build_editor_prompt
    from app.services.skill_system import build_skill_prompt

    MARK = "写作技巧 — 请在写作中运用以下技巧"

    # 1. 长篇章节生成
    msgs = build_writer_prompt(novel_title="测试", chapter_title="第一章")
    assert MARK in msgs[0]["content"], "writer 未注入技能"
    print("writer        ->", len(msgs[0]["content"]), "chars, 技能已注入")

    # 2. 大纲（应含静态技巧、不含协议包全文）
    msgs = build_outline_prompt(novel_title="测试", chapter_title="第一章")
    c = msgs[0]["content"]
    assert MARK in c, "outline 未注入技能"
    assert "遮蔽梯" not in c, "outline 不应注入协议包页面级笔法"
    print("outline       ->", len(c), "chars, 静态技巧已注入/协议包已跳过")

    # 3. 按评审改写
    msgs = build_rewrite_prompt(original_content="正文", critic_feedback="加强开头")
    assert MARK in msgs[0]["content"], "rewrite 未注入技能"
    print("rewrite       ->", len(msgs[0]["content"]), "chars, 技能已注入")

    # 4. Editor 润色（协议包走 polish 模块 = fingerprints + evaluation）
    msgs = build_editor_prompt(chapter_content="正文")
    c = msgs[0]["content"]
    assert MARK in c, "editor 未注入技能"
    print("editor(polish)->", len(c), "chars, 技能已注入")

    # 5. 激活江南作者技能后，write 应加载文件型完整协议
    from app.services.skill_system import set_active_skills, get_active_skills
    old = get_active_skills()
    try:
        set_active_skills(["jiangnan_fingerprint", "pacing_control"])
        p = build_skill_prompt("write")
        assert len(p) > 3000, f"文件型协议未生效({len(p)})"
        assert "core" in p.lower() or "指纹" in p
        print("jiangnan write->", len(p), "chars, 文件型完整协议已加载")

        po = build_skill_prompt("outline")
        assert "江南感" not in po and "节奏控制" in po
        print("jiangnan out  ->", len(po), "chars, 协议包正确跳过/静态保留")
    finally:
        set_active_skills(old)

    # 6. 异常兜底不再静默：模拟失败路径
    import app.services.prompt_builder.context as ctx
    orig = ctx.get_skill_prompt
    def boom(t): raise RuntimeError("boom")
    ctx.get_skill_prompt = boom
    try:
        msgs = build_writer_prompt(novel_title="x")  # 不应抛异常
        print("failure path  -> 优雅降级 OK")
    finally:
        ctx.get_skill_prompt = orig

    print("\n=== 全部通过 ===")
