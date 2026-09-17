"""CLI 大纲固定格式辅助（chapter outline-template + 手写大纲软校验）。

Web 端有「插入大纲模板」按钮，CLI 手写大纲的入口此前没有任何格式辅助——
AI 生成走共享提示词已内置固定格式，手写路径由本组测试锁定。
"""
import argparse


from app import db
from app.models import Novel, Chapter
from app.services.outline_template import (
    OUTLINE_FIELDS, OUTLINE_TEMPLATE, check_outline_format,
)
import cli as lingyan_cli


FORMATTED_OUTLINE = (
    "【本章定位】推进：主角夜探账房\n"
    "【核心事件】1. 主角偷出账册，被巡夜发现\n"
    "【出场人物】林晚照、沈青梧\n"
    "【场景节拍】1. 林晚照翻墙入院，惊动账房夜值\n"
    "【情感基调】紧张→惊疑\n"
    "【伏笔操作】埋设：账册缺页\n"
    "【结尾钩子】暗处有人认出了她"
)


def test_check_outline_format():
    ok, missing = check_outline_format(FORMATTED_OUTLINE)
    assert ok and missing == []

    ok2, missing2 = check_outline_format("主角北上，途中遭遇伏击。")
    assert not ok2 and len(missing2) == 7

    # 空大纲不检查（合规）
    ok3, missing3 = check_outline_format("")
    assert ok3 and missing3 == []


def test_template_matches_writer_prompt_fields(app):
    """模板字段与 AI 生成提示词的字段一致（同一契约，两边不可漂移）。"""
    from app.services.prompt_builder import build_outline_prompt
    msgs = build_outline_prompt(novel_title="一致性检查")
    sys_prompt = msgs[0]["content"]
    for field in OUTLINE_FIELDS:
        assert field in OUTLINE_TEMPLATE
        assert field in sys_prompt, f"提示词缺少固定格式字段 {field}"


def test_outline_template_command(app, capsys):
    lingyan_cli.cmd_chapter(argparse.Namespace(
        action="outline-template", novel=None))
    out = capsys.readouterr().out
    for field in OUTLINE_FIELDS:
        assert field in out
    assert "自动勾选" in out or "节拍" in out


def test_create_warns_on_freeform_outline(app, capsys):
    with app.app_context():
        n = Novel(title="CLI格式书")
        db.session.add(n)
        db.session.commit()
        nid = n.id

    lingyan_cli.cmd_chapter(argparse.Namespace(
        action="create", novel=nid, number=1, title="第一章",
        outline="主角北上，途中遭遇伏击。", directive="", yes=True))
    out = capsys.readouterr().out
    assert "⚠ 大纲未遵循 7 字段固定格式" in out
    assert "outline-template" in out

    with app.app_context():
        ch = Chapter.query.filter_by(novel_id=nid, chapter_number=1).first()
        assert ch is not None
        assert ch.outline == "主角北上，途中遭遇伏击。"  # 警告不阻断保存


def test_create_silent_on_formatted_outline(app, capsys):
    with app.app_context():
        n = Novel(title="CLI合规书")
        db.session.add(n)
        db.session.commit()
        nid = n.id

    lingyan_cli.cmd_chapter(argparse.Namespace(
        action="create", novel=nid, number=1, title="第一章",
        outline=FORMATTED_OUTLINE, directive="", yes=True))
    out = capsys.readouterr().out
    assert "⚠" not in out


def test_update_warns_on_freeform_outline(app, capsys):
    with app.app_context():
        n = Novel(title="CLI更新书")
        db.session.add(n)
        db.session.commit()
        ch = Chapter(novel_id=n.id, chapter_number=1, title="第一章",
                     outline=FORMATTED_OUTLINE)
        db.session.add(ch)
        db.session.commit()
        nid, num = n.id, 1

    lingyan_cli.cmd_chapter(argparse.Namespace(
        action="update", novel=nid, number=num,
        outline="这章写主角变强。", title=None, directive=None, yes=True))
    out = capsys.readouterr().out
    assert "⚠ 大纲未遵循 7 字段固定格式" in out

    with app.app_context():
        ch = Chapter.query.filter_by(novel_id=nid, chapter_number=num).first()
        assert ch.outline == "这章写主角变强。"
