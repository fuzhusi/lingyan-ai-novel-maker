"""知识激活回归（调研 v2 第 1 步）：policy 四模式 + writer_chain 集成。"""

from app import db
from app.models import Chapter, Character, Novel, WorldSetting
from app.services.knowledge_activation import (
    default_policy_for, gather_recent_text, keywords_hit,
    parse_policy, split_modes, dedupe_by_id,
)
from app.services.writer_chain import build_writer_kwargs


def _mk_book(client, title="激活测试"):
    n = Novel(title=title, genre="都市", synopsis="s", world_intro="w")
    db.session.add(n)
    db.session.commit()
    return n


def _mk_chapter_with_text(novel_id, number, text):
    from app.services.chapter_approval import create_version_record
    ch = Chapter(novel_id=novel_id, chapter_number=number,
                 outline="【本章定位】x")
    db.session.add(ch)
    db.session.flush()
    create_version_record(novel_id, number, text, source="human")
    db.session.commit()
    return ch


# ---------------------------------------------------------------------------
# 单元：parse/hit/split/默认策略
# ---------------------------------------------------------------------------

def test_parse_policy_defaults_and_validation():
    assert parse_policy(None) == {"mode": "auto", "keys": []}
    assert parse_policy("{}")["mode"] == "auto"
    assert parse_policy('{"mode": "bogus"}')["mode"] == "auto"     # 非法回退
    p = parse_policy('{"mode": "keywords", "keys": ["怀表", "x"]}')
    assert p["mode"] == "keywords" and p["keys"] == ["怀表", "x"]


def test_keywords_hit_and_min_length():
    text = "他把旧怀表攥在手心，转身就走。"
    assert keywords_hit(parse_policy('{"keys": ["怀表"]}'), "旧怀表", text)
    assert not keywords_hit(parse_policy('{"keys": ["表"]}'), "", text)  # 单字过滤
    # 标题即主键：title 命中也算（SillyTavern 同语义）
    assert keywords_hit(parse_policy('{"keys": ["戒指"]}'), "旧怀表", text)
    # 完全无命中
    assert not keywords_hit(parse_policy('{"keys": ["戒指"]}'), "祖传玉佩", text)
    assert not keywords_hit(parse_policy('{"keys": ["怀表"]}'), "旧怀表", "")


def test_split_modes_and_dedupe():
    items = [{"id": 1}, {"id": 2}, {"id": 3}]
    buckets = split_modes(items, lambda i: {"mode": {1: "auto", 2: "always",
                                                     3: "off"}.get(i["id"], "auto")})
    assert buckets["auto"] == [{"id": 1}]
    assert buckets["always"] == [{"id": 2}]
    assert buckets["off"] == [{"id": 3}]
    assert dedupe_by_id([{"id": 1}, {"id": 1}, {"id": 2}]) == [{"id": 1}, {"id": 2}]


def test_default_policy_for_deconstruct():
    p = parse_policy(default_policy_for("玄学佬"))
    assert p["mode"] == "keywords" and p["keys"] == ["玄学佬"]


def test_gather_recent_text_two_chapters(client):
    n = _mk_book(client)
    _mk_chapter_with_text(n.id, 1, "第一章正文提到旧怀表。")
    _mk_chapter_with_text(n.id, 2, "第二章正文提到供桌上阁楼。")
    text = gather_recent_text(n.id, 3)
    assert "旧怀表" in text and "供桌" in text
    # 第 2 章生成时只看到第 1 章
    assert "旧怀表" in gather_recent_text(n.id, 2)
    assert "供桌" not in gather_recent_text(n.id, 2)


# ---------------------------------------------------------------------------
# 集成：writer_chain 四模式行为
# ---------------------------------------------------------------------------

OUTLINE = ("【本章定位】推进：日常与冲突。\n"
           "【出场人物】陈屿\n"
           "【场景节拍】1.陈屿在宿舍收到陌生短信；2.他和苏晚在操场对峙。\n"
           "【结尾钩子】短信署名是个从未见过的名字。")


def _mk_kb(client, policies):
    n = _mk_book(client)
    _mk_chapter_with_text(n.id, 1, "第一章提到旧怀表与供桌。")
    for name, policy in policies.items():
        db.session.add(Character(novel_id=n.id, name=name, personality="p",
                                 injection_policy=policy))
    db.session.commit()
    return n


def test_policy_off_excludes_and_auto_uses_roster(client):
    n = _mk_kb(client, {"陈屿": "{}",                     # auto → 名册命中
                        "马千军": '{"mode": "off"}'})      # off → 剔除
    kw, _ = build_writer_kwargs(n.id, 2, OUTLINE)
    names = [c["name"] for c in kw["characters"]]
    assert "陈屿" in names            # auto：名册命中保留
    assert "马千军" not in names       # off：剔除


def test_policy_always_survives_roster(client):
    n = _mk_kb(client, {"陈屿": "{}",
                        "江屹": '{"mode": "always"}'})     # 不在名册但常驻
    kw, _ = build_writer_kwargs(n.id, 2, OUTLINE)
    names = [c["name"] for c in kw["characters"]]
    assert "陈屿" in names            # auto：名册命中
    assert "江屹" in names             # always：免疫名册剪枝


def test_policy_keywords_matches_recent_text(client):
    n = _mk_kb(client, {"陈屿": "{}",
                        "苏晚": '{"mode": "keywords", "keys": ["供桌"]}'})
    # 近两章正文含「供桌」→ keywords 命中（尽管不在名册）
    kw, _ = build_writer_kwargs(n.id, 2, OUTLINE)
    names = [c["name"] for c in kw["characters"]]
    assert "苏晚" in names


def test_policy_world_always_and_off(client):
    n = _mk_kb(client, {})
    db.session.add(WorldSetting(
        novel_id=n.id, category="规则", title="端公规矩",
        content="孝布不能带进别人家",
        injection_policy='{"mode": "always"}'))
    db.session.add(WorldSetting(
        novel_id=n.id, category="设定", title="废弃设定",
        content="已作废的旧设定",
        injection_policy='{"mode": "off"}'))
    db.session.commit()
    kw, _ = build_writer_kwargs(n.id, 2, OUTLINE)
    titles = [w["title"] for w in kw["world_settings"]]
    assert "端公规矩" in titles
    assert "废弃设定" not in titles


# ---------------------------------------------------------------------------
# 评审修复回归（code review + 验收团队发现）
# ---------------------------------------------------------------------------

def test_policy_keywords_miss_excluded(client):
    """P0 回归：角色 keywords 未命中近章正文 → 不注入（原实现恒等 always）。"""
    n = _mk_kb(client, {"陈屿": "{}",
                        "未触发者": '{"mode": "keywords", "keys": ["不存在的锚词"]}'})
    kw, _ = build_writer_kwargs(n.id, 2, OUTLINE)
    names = [c["name"] for c in kw["characters"]]
    assert "陈屿" in names
    assert "未触发者" not in names


def test_explicit_check_overrides_off(client):
    """用户显式勾选优先于持久 off 策略（避免 cast_constraint 自相矛盾）。"""
    n = _mk_kb(client, {"陈屿": '{"mode": "off"}'})
    off_char = Character.query.filter_by(novel_id=n.id, name="陈屿").first()
    kw, _ = build_writer_kwargs(n.id, 2, OUTLINE, character_ids=[off_char.id])
    names = [c["name"] for c in kw["characters"]]
    assert "陈屿" in names   # 勾选赢：off 不剔除显式勾选
    # 且 cast_constraint 宣告其可登场（不出现无档案矛盾）
    assert "只允许以下角色登场" in kw.get("cast_constraint", "")


def test_default_policy_single_char_title_falls_back_auto():
    """单字标题回退 auto（keywords_hit 过滤单字，keywords 会永不命中）。"""
    p = parse_policy(default_policy_for("妖"))
    assert p["mode"] == "auto"
    p2 = parse_policy(default_policy_for("玄学佬"))
    assert p2["mode"] == "keywords"


def test_gather_recent_text_tolerates_outline_only_chapter(client):
    """紧邻章只有大纲无正文：窗口跳过它取再前一章的正文。"""
    n = _mk_book(client)
    _mk_chapter_with_text(n.id, 1, "第一章正文含锚点词黑桃。")
    db.session.add(Chapter(novel_id=n.id, chapter_number=2,
                           outline="只有大纲没有正文"))
    db.session.commit()
    text = gather_recent_text(n.id, 3)
    assert "黑桃" in text
