"""删除级联回归（2026-09 审计 P0-4/P0-5）。

FK ON 后，带盲审/角色关系/拆书条目/向量索引的数据走批量删除
（Web delete-all、CLI delete-all、sys reset）必须全部成功且不留孤儿。
历史教训：三处各自手写级联、顺序漂移，遇 BlindReview.version_id、
character_relations 双 FK、deconstruct_items.task_id 即 IntegrityError。
"""
import argparse
import os
import sqlite3

import pytest

from app import db
from app.models import (
    Novel, Chapter, ChapterVersion, Character, CharacterRelation,
    OutlineNode, BlindReview, EntityEmbedding, PlagiarizeTask,
    DeconstructItem, ShortStory,
)


def _make_full_data():
    """一部带全量外围引用的小说 + 短篇盲审 + 拆书任务（旧顺序下必炸的配置）。"""
    n = Novel(title="级联回归书")
    db.session.add(n)
    db.session.commit()
    ch = Chapter(novel_id=n.id, chapter_number=1, title="第一章", outline="大纲")
    db.session.add(ch)
    db.session.commit()
    ver = ChapterVersion(chapter_id=ch.id, version_number=1,
                         content="正文内容，足够长。")
    db.session.add(ver)
    db.session.commit()
    c1 = Character(novel_id=n.id, name="甲")
    c2 = Character(novel_id=n.id, name="乙")
    db.session.add_all([c1, c2])
    db.session.commit()
    # 先清本 novel_id 的遗留向量行——早前测试删书留下的孤儿 embedding
    # 会在 rowid 复用后撞唯一索引（正是审计 P2-2 说的孤儿源）
    EntityEmbedding.query.filter_by(novel_id=n.id).delete(synchronize_session=False)
    db.session.add(CharacterRelation(
        novel_id=n.id, character_a_id=c1.id, character_b_id=c2.id, relation_type="rival"))
    db.session.add(OutlineNode(novel_id=n.id, node_type="chapter", title="节点一"))
    db.session.add(BlindReview(kind="chapter", version_id=ver.id, title="x",
                               word_count=9, editors_json="[]"))
    db.session.add(EntityEmbedding(novel_id=n.id, entity_type="character",
                                   entity_id=c1.id, content_hash="h"))
    task = PlagiarizeTask(title="对标", mode="deconstruct")
    db.session.add(task)
    db.session.commit()
    db.session.add(DeconstructItem(task_id=task.id, kind="character", title="角色卡"))
    db.session.add(ShortStory(title="短篇一", content="短篇正文"))
    db.session.commit()
    story = ShortStory.query.first()
    db.session.add(BlindReview(kind="story", story_id=story.id, title="s",
                               word_count=9, editors_json="[]"))
    db.session.commit()
    return n.id


def _orphan_report():
    """业务孤儿计数（删除后应全部为 0）。"""
    def count(model, **kw):
        return model.query.filter_by(**kw).count() if kw else model.query.count()
    return {
        "novels": count(Novel),
        "blind_reviews": count(BlindReview),
        "relations": count(CharacterRelation),
        "embeddings": count(EntityEmbedding),
        "deconstruct_items": count(DeconstructItem),
    }


def test_delete_service_with_full_references(app):
    """单书删除真源：带盲审/关系/向量索引/拆书任务引用时 FK 不炸、无孤儿。"""
    with app.app_context():
        nid = _make_full_data()
        story_br = BlindReview.query.filter_by(kind="story").count()
        from app.services.delete_service import delete_novel_full
        ok, _ = delete_novel_full(nid)
        assert ok
        # 本测试的书必须不存在；其他测试文件的存活小说不算孤儿
        assert db.session.get(Novel, nid) is None
        r = _orphan_report()
        # 章节盲审随书清掉；短篇盲审属于仍存在的 ShortStory，数量不变
        assert r["blind_reviews"] == story_br
        assert r["relations"] == 0
        assert r["embeddings"] == 0


def test_web_delete_all_with_full_references(app, client):
    with app.app_context():
        _make_full_data()
        _make_full_data()
        story_br = BlindReview.query.filter_by(kind="story").count()
    resp = client.post("/novel/delete-all", data={"confirm": "YES"})
    assert resp.status_code == 302
    with app.app_context():
        assert Novel.query.count() == 0  # delete-all 清掉全部小说（含其他测试的）
        r = _orphan_report()
        assert r["relations"] == 0 and r["embeddings"] == 0
        # 短篇盲审属于仍存在的 ShortStory，数量不变；章节盲审全部随书清掉
        assert r["blind_reviews"] == story_br
        assert BlindReview.query.filter_by(kind="chapter").count() == 0


def test_web_delete_all_requires_confirm(client):
    resp = client.post("/novel/delete-all", data={})
    assert resp.status_code == 400


def test_cli_delete_all_with_full_references(app):
    import cli as lingyan_cli
    with app.app_context():
        _make_full_data()
        story_br = BlindReview.query.filter_by(kind="story").count()
    lingyan_cli.cmd_novel(argparse.Namespace(action="delete-all", yes=True))
    with app.app_context():
        assert Novel.query.count() == 0
        r = _orphan_report()
        assert r["relations"] == 0 and r["blind_reviews"] == story_br


def test_cli_sys_reset_with_full_references(app):
    """sys reset：盲审(→short_stories/chapter_versions)与拆书条目(→tasks)须先清。
    注意：本测试清空全部业务数据，必须保持本文件内最后执行。"""
    import cli as lingyan_cli
    with app.app_context():
        _make_full_data()
    lingyan_cli.cmd_sys(argparse.Namespace(action="reset", yes=True, output=None))
    with app.app_context():
        assert Novel.query.count() == 0
        r = _orphan_report()
        assert r["blind_reviews"] == 0
        assert r["deconstruct_items"] == 0
        assert PlagiarizeTask.query.count() == 0
        assert ShortStory.query.count() == 0


def test_cli_outline_delete_unlinks_chapter(app):
    """CLI 删被章节引用的大纲节点：先解链再删（对齐 Web），FK 不炸、章节保留。"""
    import cli as lingyan_cli
    with app.app_context():
        n = Novel(title="解链测试书")
        db.session.add(n)
        db.session.commit()
        node = OutlineNode(novel_id=n.id, node_type="chapter", title="被引用节点")
        db.session.add(node)
        db.session.commit()
        ch = Chapter(novel_id=n.id, chapter_number=1, title="第一章",
                     outline_node_id=node.id)
        db.session.add(ch)
        db.session.commit()
        nid, num, node_id = n.id, ch.chapter_number, node.id

    lingyan_cli.cmd_outline(argparse.Namespace(
        action="delete", novel=nid, id=node_id, yes=True))

    with app.app_context():
        assert db.session.get(OutlineNode, node_id) is None
        ch = Chapter.query.filter_by(novel_id=nid, chapter_number=num).first()
        assert ch is not None
        assert ch.outline_node_id is None


def test_backup_and_restore_use_real_db_path(app, client):
    """DATABASE_PATH 现已显式落 config：backup 必须备份真实库而非 CWD 陈旧副本；
    restore 校验备份合法性后可回滚数据。"""
    import cli as lingyan_cli
    with app.app_context():
        n = Novel(title="备份恢复测试书")
        db.session.add(n)
        db.session.commit()
        nid = n.id
    backup_path = os.path.join(".tmp-test", "audit-backup-test.db")
    if os.path.exists(backup_path):
        os.remove(backup_path)
    lingyan_cli.cmd_sys(argparse.Namespace(
        action="backup", output=backup_path, yes=True))
    assert os.path.exists(backup_path)

    # 备份内容 = 真实库（含刚建的小说）
    check = sqlite3.connect(backup_path)
    titles = check.execute("SELECT title FROM novels WHERE id=?", (nid,)).fetchall()
    check.close()
    assert titles and titles[0][0] == "备份恢复测试书"

    # 删掉后再从备份恢复。恢复会移除库文件重建——先释放两个 app 的连接池，
    # 否则 Windows 下无法删除正被打开的文件（dispose 需要 app 上下文）
    with app.app_context():
        from app.services.delete_service import delete_novel_full
        delete_novel_full(nid)
    with app.app_context():
        app.extensions["sqlalchemy"].engine.dispose()
    with lingyan_cli.app.app_context():
        lingyan_cli.app.extensions["sqlalchemy"].engine.dispose()
    lingyan_cli.cmd_sys(argparse.Namespace(
        action="restore", output=backup_path, yes=True))
    check = sqlite3.connect(os.environ["DATABASE_PATH"])
    titles = check.execute("SELECT title FROM novels WHERE id=?", (nid,)).fetchall()
    check.close()
    assert titles and titles[0][0] == "备份恢复测试书"
    os.remove(backup_path)


def test_backup_refuses_overwrite(app):
    import cli as lingyan_cli
    existing = os.path.join(".tmp-test", "audit-backup-exists.db")
    open(existing, "w").close()
    lingyan_cli.cmd_sys(argparse.Namespace(action="backup", output=existing, yes=True))
    os.remove(existing)
