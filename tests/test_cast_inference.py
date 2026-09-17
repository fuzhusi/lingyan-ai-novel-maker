"""出场角色推断（大纲文本 ↔ 人物卡名字匹配）测试。"""
from app import db
from app.models import Character, Novel, Chapter
from app.services.cast_inference import infer_cast


def _setup(app_ctx):
    n = Novel(title="推断测试书")
    db.session.add(n)
    db.session.commit()
    c1 = Character(novel_id=n.id, name="林晚照")
    c2 = Character(novel_id=n.id, name="沈青梧")
    c3 = Character(novel_id=n.id, name="")  # 空名角色跳过
    db.session.add_all([c1, c2, c3])
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=1, title="第一章",
                 outline="林晚照推门而入，与掌柜争执。沈青梧在暗处观察，林晚照并未察觉。")
    db.session.add(ch)
    db.session.commit()
    return n, {"林晚照": c1, "沈青梧": c2}, ch


def test_infer_cast_matches_and_sorts(app):
    with app.app_context():
        n, chars, _ = _setup(app)
        matched = infer_cast(n.id, "林晚照推门而入，沈青梧在暗处观察，林晚照并未察觉。")
        names = [m["name"] for m in matched]
        assert names == ["林晚照", "沈青梧"]  # 命中 2 次 > 1 次，降序
        assert matched[0]["hits"] == 2


def test_infer_cast_empty_text(app):
    with app.app_context():
        n, _, _ = _setup(app)
        assert infer_cast(n.id, "") == []
        assert infer_cast(n.id, "   ") == []


def test_infer_cast_skips_blank_names(app):
    with app.app_context():
        n, _, _ = _setup(app)
        # 空名角色即使正文里有任何字也不会匹配出条目
        assert all(m["name"] for m in infer_cast(n.id, "任意文本"))


def test_infer_cast_excludes_background_mentions(app):
    """固定格式契约：【出场人物】里带（背景提及）的名字不点亮勾选——
    否则 cast_constraint 白名单会反向给背景角色发登场许可。"""
    with app.app_context():
        n, chars, _ = _setup(app)
        outline = ("【本章定位】推进：主角夜探账房\n"
                   f"【出场人物】林晚照、沈青梧（背景提及）\n"
                   "【场景节拍】1. 林晚照翻墙入院，惊动账房夜值\n"
                   "【结尾钩子】暗处沈青梧的目光一直跟着她")
        matched = infer_cast(n.id, outline)
        names = [m["name"] for m in matched]
        assert "林晚照" in names
        assert "沈青梧" not in names  # 虽在节拍里被提及，但名册标注了背景提及

        # 兼容半角括号写法
        outline2 = "【出场人物】沈青梧(背景提及)、林晚照"
        matched2 = infer_cast(n.id, outline2)
        assert [m["name"] for m in matched2] == ["林晚照"]


def test_infer_cast_endpoint(app, client):
    with app.app_context():
        n, chars, ch = _setup(app)
        nid, cnum = n.id, 1
        id_wan, id_wu = chars["林晚照"].id, chars["沈青梧"].id
    resp = client.get(f"/novel/{nid}/api/infer-cast?chapter_number={cnum}")
    data = resp.get_json()
    assert data["ok"] is True
    ids = [m["id"] for m in data["matched"]]
    assert id_wan in ids and id_wu in ids
    assert data["outline_empty"] is False


def test_infer_cast_endpoint_unknown_chapter(app, client):
    with app.app_context():
        n, _, _ = _setup(app)
        nid = n.id
    resp = client.get(f"/novel/{nid}/api/infer-cast?chapter_number=999")
    data = resp.get_json()
    assert data["ok"] is True
    assert data["matched"] == [] and data["outline_empty"] is True
