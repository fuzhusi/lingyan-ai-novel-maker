"""资源库 —— 对标书原文作为一等公民存储,与拆书任务解耦。

资源库解决三个问题:
1. 原文独立存储:删拆书任务不丢原文;同一本书可多次拆书
2. 向量语义检索:分段嵌入后按语义相似度检索,替代全量注入
3. 成本控制:只把语义相关的片段注入写作包,不再全量塞入
"""
from app.models.base import db, now


class ResourceBook(db.Model):
    """资源库书籍(对标书原文)。"""
    __tablename__ = "resource_books"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(100), default="")
    source_type = db.Column(db.String(20), default="paste")  # paste/upload/txt_file
    content = db.Column(db.Text, default="")               # 全文
    total_chars = db.Column(db.Integer, default=0)
    chapter_count = db.Column(db.Integer, default=0)
    embedded = db.Column(db.Boolean, default=False)         # 向量是否已生成
    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)

    chunks = db.relationship("ResourceChunk", backref="book",
                             cascade="all, delete-orphan", order_by="ResourceChunk.chunk_index")


class ResourceChunk(db.Model):
    """资源的语义分段(章/块)+ 向量。检索的最小单元。"""
    __tablename__ = "resource_chunks"
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey("resource_books.id"), nullable=False)
    chunk_type = db.Column(db.String(20), default="chapter")  # chapter / volume / block
    chunk_index = db.Column(db.Integer, default=0)            # 在资源内的序号
    title = db.Column(db.String(200), default="")
    content = db.Column(db.Text, default="")                  # 分段原文
    embedding = db.Column(db.LargeBinary, nullable=True)      # float32 numpy 序列化
    text_hash = db.Column(db.String(64), default="")          # 内容哈希(变了才重嵌入)
    created_at = db.Column(db.String(20), default=now)
