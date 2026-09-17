"""删除单一真源 —— Web/MCP/CLI 共用的删书级联。

FK ON 后引用完整性由数据库兜底，按依赖顺序 **bulk 删除**：
盲审/抽取队列/向量索引/FTS → 章节（先于大纲节点，chapters.outline_node_id
有 FK 指向大纲节点）→ 知识库全家 → 本体。

性能注记：此前走 ORM 级联逐章删，每章触发版本/评审/记忆整集合懒加载，
且版本行携带整章正文——几百章的书删除要几十秒。改为按 id 集合批量
DELETE 后与数据量基本无关（只取 id 列，永不加载正文）。
"""
from app.models import (
    db, Novel, Chapter, ChapterVersion, ChapterSummary, ChapterMemory,
    CriticReview, Character, CharacterRelation, WorldSetting, OutlineNode,
    Foreshadowing, StoryState, StoryStateSnapshot, BlindReview,
    PendingExtraction, EntityEmbedding,
)


def delete_novel_full(novel_id):
    """删除小说及全部关联数据。返回 (ok, message)。"""
    novel = db.session.get(Novel, novel_id)
    if not novel:
        return False, f"小说 {novel_id} 不存在"
    title = novel.title

    # 1) 只取 id 列，绝不加载版本正文（整章文本是慢的根源）
    chapter_ids = [row[0] for row in
                   db.session.query(Chapter.id).filter_by(novel_id=novel_id)]
    version_ids = []
    if chapter_ids:
        version_ids = [row[0] for row in
                       db.session.query(ChapterVersion.id).filter(
                           ChapterVersion.chapter_id.in_(chapter_ids))]

    # 2) 无级联的外围引用
    if version_ids:
        BlindReview.query.filter(
            BlindReview.version_id.in_(version_ids)).delete(synchronize_session=False)
    PendingExtraction.query.filter_by(novel_id=novel_id).delete(synchronize_session=False)
    # 向量索引无 FK（rowid 复用会串书），删书必须同步清
    EntityEmbedding.query.filter_by(novel_id=novel_id).delete(synchronize_session=False)

    # 3) 章节产物：评审→版本→摘要/记忆→章节（先于大纲节点解 FK）
    if version_ids:
        CriticReview.query.filter(
            CriticReview.version_id.in_(version_ids)).delete(synchronize_session=False)
        ChapterVersion.query.filter(
            ChapterVersion.id.in_(version_ids)).delete(synchronize_session=False)
    if chapter_ids:
        ChapterSummary.query.filter(
            ChapterSummary.chapter_id.in_(chapter_ids)).delete(synchronize_session=False)
    ChapterMemory.query.filter_by(novel_id=novel_id).delete(synchronize_session=False)
    if chapter_ids:
        Chapter.query.filter(
            Chapter.id.in_(chapter_ids)).delete(synchronize_session=False)

    # 4) 知识库与状态（关系先于角色，character_relations 双 FK 指向 characters）
    CharacterRelation.query.filter_by(novel_id=novel_id).delete(synchronize_session=False)
    Character.query.filter_by(novel_id=novel_id).delete(synchronize_session=False)
    WorldSetting.query.filter_by(novel_id=novel_id).delete(synchronize_session=False)
    Foreshadowing.query.filter_by(novel_id=novel_id).delete(synchronize_session=False)
    OutlineNode.query.filter_by(novel_id=novel_id).delete(synchronize_session=False)
    StoryStateSnapshot.query.filter_by(novel_id=novel_id).delete(synchronize_session=False)
    StoryState.query.filter_by(novel_id=novel_id).delete(synchronize_session=False)

    # 5) 本体（其余 ORM cascade 关系由数据库 FK 兜底）
    db.session.delete(novel)
    db.session.commit()

    # 6) FTS 语义记忆索引——必须在主事务 commit 之后：
    #    它走独立连接，而 SQLite 单写者，主事务未提交时它要等满 busy_timeout
    #    （10 秒）才超时——这正是"删除特别慢"的根源；失败不阻断（孤儿可全量重建）
    try:
        from app.services.vector_memory import delete_novel_memory
        delete_novel_memory(novel_id)
    except Exception:
        pass
    return True, f"已删除小说「{title}」及所有关联数据"
