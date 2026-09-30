"""role_state 回归：角色状态回写 + 伏笔账本接线（审批流③b）。"""
import json

from app import db
from app.models import Character, Foreshadowing, Novel
from app.services.role_state import (
    apply_arc_updates, apply_foreshadow_touches, payoff_setup_note,
)


def _mk_novel(client, title="账本测试"):
    n = Novel(title=title, genre="都市")
    db.session.add(n)
    db.session.commit()
    return n


def test_apply_arc_updates_structured_and_history(client):
    n = _mk_novel(client)
    db.session.add(Character(novel_id=n.id, name="陈屿",
                             status_json=json.dumps({"plan": {"first_chapter": 1}})))
    db.session.commit()
    changes = {"陈屿": {
        "want_now": "让湘西之行按约发生",
        "fear_now": "被她的日程甩下",
        "change_stage": "第一次为两个人做计划",
        "relation_changes": [{"target": "苏晚", "relation": "他开始怕失去"}],
    }}
    updated = apply_arc_updates(n.id, 25, changes)
    assert updated == ["陈屿"]
    char = Character.query.filter_by(novel_id=n.id, name="陈屿").first()
    status = json.loads(char.status_json)
    assert status["plan"] == {"first_chapter": 1}          # 拆书 plan 键原样保留
    arc = status["arc_state"]
    assert arc["want_now"] == "让湘西之行按约发生"
    assert arc["relations"]["苏晚"] == "他开始怕失去"
    assert status["arc_history"][0]["chapter"] == 25
    # 二次回写：值未变则不再追加 history
    apply_arc_updates(n.id, 26, {"陈屿": {"want_now": "让湘西之行按约发生"}})
    status2 = json.loads(Character.query.filter_by(name="陈屿").first().status_json)
    assert len(status2["arc_history"]) == 1


def test_apply_arc_updates_legacy_string_and_missing_card(client):
    n = _mk_novel(client)
    db.session.add(Character(novel_id=n.id, name="苏晚"))
    db.session.commit()
    updated = apply_arc_updates(n.id, 3, {
        "苏晚": "当选实践队队长，目标感更强",     # 旧形态：纯描述
        "龙套甲": {"want_now": "不存在"},          # 无卡：静默跳过
    })
    assert updated == ["苏晚"]
    arc = json.loads(
        Character.query.filter_by(name="苏晚").first().status_json)["arc_state"]
    assert "队长" in arc["change_stage"]


def test_apply_foreshadow_touches_id_and_transitions(client):
    n = _mk_novel(client)
    fs1 = Foreshadowing(novel_id=n.id, title="湘西·大理之约",
                        planted_chapter=12, status="planned",
                        expected_resolve_chapter=40)
    fs2 = Foreshadowing(novel_id=n.id, title="一起迷路",
                        planted_chapter=20, status="open")
    db.session.add_all([fs1, fs2])
    db.session.commit()
    # id 对齐：planned → buried（首次提及）
    touched = apply_foreshadow_touches(n.id, 25, [
        {"description": "陈屿把攻略收进抽屉，湘西之约再次悬置",
         "foreshadow_id": fs1.id}])
    assert touched == [fs1.id]
    assert fs1.last_mentioned_chapter == 25
    assert fs1.status == "buried"
    # 标题包含匹配：buried → advancing（此前已被提及过）
    touched2 = apply_foreshadow_touches(n.id, 27, [
        {"description": "聊起湘西·大理之约，两人都沉默了"}])
    assert touched2 == [fs2.id] or touched2 == [fs1.id]
    target = Foreshadowing.query.get(touched2[0])
    assert target.last_mentioned_chapter == 27
    # resolved 不动
    fs3 = Foreshadowing(novel_id=n.id, title="已收的线", status="resolved")
    db.session.add(fs3)
    db.session.commit()
    assert apply_foreshadow_touches(n.id, 30, [
        {"description": "已收的线又被聊到", "foreshadow_id": fs3.id}]) == []


def test_payoff_setup_note_zero_echo(client):
    fs = Foreshadowing(title="无回响的线", planted_chapter=10,
                       last_mentioned_chapter=None)
    note = payoff_setup_note(fs, 30)
    assert "从未回响" in note and "第 10 章" in note
    fs_ok = Foreshadowing(title="有回响的线", planted_chapter=10,
                          last_mentioned_chapter=22)
    assert payoff_setup_note(fs_ok, 30) == ""
    fs_no_plant = Foreshadowing(title="没埋设", planted_chapter=None)
    assert payoff_setup_note(fs_no_plant, 5) == ""
