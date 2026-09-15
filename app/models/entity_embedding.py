"""实体嵌入 —— 长篇知识库的语义检索索引层。

解决"全量注入→预算压缩"的选择策略问题：写第 N 章时不再全量塞 20 个角色 +
30 条世界观，而是用本章大纲 embed 后按余弦相似度选取最相关的 top-K。

设计要点：
- 统一表：novel_id + entity_type + entity_id 唯一定位一个实体的向量
- text_hash 缓存：内容不变不重嵌入
- 暴力余弦（几千条毫秒级，不需要向量数据库）
- 嵌入降级：LLM embedding API 不可用时用字符频率向量（管线可跑通）
"""
from app.models.base import db, now


class EntityEmbedding(db.Model):
    __tablename__ = "entity_embeddings"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, nullable=False, index=True)
    entity_type = db.Column(db.String(30), nullable=False)  # character/world/foreshadowing/outline_node/chapter_summary
    entity_id = db.Column(db.Integer, nullable=False)
    content_hash = db.Column(db.String(64), default="")
    embedding = db.Column(db.LargeBinary, nullable=True)    # float32 list 序列化
    created_at = db.Column(db.String(20), default=now)

    __table_args__ = (
        db.Index("ix_entity_embeddings_lookup",
                 "novel_id", "entity_type", "entity_id", unique=True),
    )
