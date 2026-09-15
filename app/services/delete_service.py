"""删除单一真源 —— Web/MCP/CLI 共用的删书级联。

FK ON 后引用完整性由数据库兜底:此处按正确顺序清理无 ORM 级联的外围引用
(盲审/抽取队列/FTS 索引),本体由 ORM 级联收掉(章节→版本→评审、知识库全家)。
"""
from app.models import db, Novel, BlindReview, PendingExtraction


def delete_novel_full(novel_id):
    """删除小说及全部关联数据。返回 (ok, message)。"""
    novel = db.session.get(Novel, novel_id)
    if not novel:
        return False, f"小说 {novel_id} 不存在"
    # 1) 无级联的外围引用
    version_ids = [v.id for ch in novel.chapters for v in ch.versions]
    if version_ids:
        BlindReview.query.filter(BlindReview.version_id.in_(version_ids)).delete(synchronize_session=False)
    PendingExtraction.query.filter_by(novel_id=novel.id).delete(synchronize_session=False)
    # 2) FTS 语义记忆索引
    try:
        from app.services.vector_memory import delete_novel_memory
        delete_novel_memory(novel.id)
    except Exception:
        pass  # 索引清理失败不阻断删除(孤儿索引可由全量重建修复)
    # 3) 本体:先删章节(大纲节点级联不做章节置空),再由 ORM 级联收其余
    for ch in list(novel.chapters):
        db.session.delete(ch)
    db.session.delete(novel)
    db.session.commit()
    return True, f"已删除小说「{novel.title}」及所有关联数据"
