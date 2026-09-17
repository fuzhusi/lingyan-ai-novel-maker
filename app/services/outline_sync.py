"""大纲树节点 ↔ 写作章节 双向同步。

设计原则：大纲树是章节大纲的唯一事实源（single source of truth）。
- 「章」节点在大纲树创建时自动落一条 Chapter（章节列表即刻可见）；
- 章节创作页与大纲树任一侧编辑摘要，都同步回节点并刷新关联章节的快照；
- 生成时的大纲文本从节点实时组装（节点摘要 + 场景分幕指引），
  不再依赖创建时刻的静态拷贝。
"""
from app.models import db, Chapter, OutlineNode
from app.models.novel import outline_hash_of


def compose_node_outline(node: OutlineNode) -> str:
    """从节点实时组装大纲文本：节点摘要 + 子场景分幕指引。

    与 create-chapter 落库格式一致，生成 prompt 与大纲树显示同源。
    """
    if node is None:
        return ""
    parts = [(node.summary or "").strip()]
    scene_lines = []
    children = (OutlineNode.query.filter_by(parent_id=node.id)
                .order_by(OutlineNode.sort_order).all())
    for child in children:
        if child.node_type == "scene":
            scene_lines.append(f"【{child.title}】{child.summary or ''}")
    if scene_lines:
        parts.append("分幕指引：\n" + "\n".join(scene_lines))
    return "\n\n".join(p for p in parts if p)


def sync_chapter_from_node(chapter: Chapter, node: OutlineNode) -> Chapter:
    """把节点当前内容同步到关联章节（标题/大纲快照）。

    不动 outline_hash：大纲变了而正文还是旧大纲生成的，
    outline_stale() 应当如实报警，这正是指纹存在的意义。
    """
    chapter.title = node.title or chapter.title
    chapter.outline = compose_node_outline(node)
    return chapter


def ensure_chapter_for_node(node: OutlineNode) -> Chapter | None:
    """「章」节点缺关联章节时补建（幂等）；其他类型返回 None。"""
    if node.node_type != "chapter":
        return None
    existing = Chapter.query.filter_by(outline_node_id=node.id).first()
    if existing:
        return existing
    max_num = db.session.query(
        db.func.max(Chapter.chapter_number)
    ).filter_by(novel_id=node.novel_id).scalar()
    chapter = Chapter(
        novel_id=node.novel_id,
        chapter_number=(max_num or 0) + 1,
        title=node.title,
        outline=compose_node_outline(node),
        outline_node_id=node.id,
    )
    db.session.add(chapter)
    db.session.flush()
    return chapter


def refresh_node_outline_hash(chapter: Chapter) -> None:
    """章节大纲刚落定（生成/同步后）时刷新指纹，配合 outline_stale 使用。"""
    chapter.outline_hash = outline_hash_of(chapter.outline or "")
