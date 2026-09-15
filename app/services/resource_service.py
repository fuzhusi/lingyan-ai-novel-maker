"""资源库服务 —— 嵌入生成、语义检索、资源管理。

嵌入策略(按调研结论的轻量方案):
- 嵌入模型走已配的 LLM 厂商 embedding API(OpenAI/智谱等)
- 厂商不可用时降级为字符频率向量(零外部依赖,精度低但管线可跑通)
- 向量存 SQLite BLOB,暴力余弦(几千条毫秒级,不需要向量数据库)
- text_hash 缓存:内容不变不重嵌入
"""
import hashlib
import logging
import math
import re
import struct

from app.models import db
from app.models.resource import ResourceBook, ResourceChunk

logger = logging.getLogger(__name__)

# 语义分段大小(字符):太小上下文碎,太大检索粒度粗
CHUNK_SIZE = 2000
_CHUNK_OVERLAP = 100


# ---------------------------------------------------------------------------
# 嵌入(纯 Python:不需要 numpy,几千条暴力余弦毫秒级)
# ---------------------------------------------------------------------------

def _hash_text(text):
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def _pack(vec):
    """float list → bytes(存 SQLite BLOB)。"""
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob):
    """bytes → float list。"""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _get_embedding(text):
    """统一走 embedding_service（逐厂商尝试 /embeddings 端点）。"""
    from app.services.embedding_service import get_embedding
    return get_embedding(text)


def _char_freq_vector(text, dim=256):
    """字符频率向量(降级方案):中文按 Unicode 码位取模映射到固定维度。"""
    vec = [0.0] * dim
    for ch in (text or "")[:5000]:
        vec[ord(ch) % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm > 0 else vec


# ---------------------------------------------------------------------------
# 分段
# ---------------------------------------------------------------------------

_CHAPTER_RE = re.compile(
    r"^\s*(?:第\s*[0-9零一二三四五六七八九十百千万]+\s*[章节回卷](?:\s|$)|[Cc]hapter\s*\d+\s*[:：.]?)",
    re.M,
)


def _split_chunks(text):
    """把全文切成语义分段(章优先,无标记按 CHUNK_SIZE 定长)。"""
    text = (text or "").strip()
    if not text:
        return []
    matches = list(_CHAPTER_RE.finditer(text))
    if len(matches) >= 2:
        chunks = []
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.start():end].strip()
            if body:
                title = m.group(0).strip()
                # 大段(>CHUNK_SIZE×2)再切
                for j, sub_start in enumerate(range(0, len(body), CHUNK_SIZE)):
                    sub = body[sub_start:sub_start + CHUNK_SIZE]
                    if sub.strip():
                        chunks.append((f"{title}" + (f"(续{j})" if j else ""), sub.strip()))
        return chunks
    # 无章节标记:按 CHUNK_SIZE 定长分块
    return [(f"片段{i + 1}", text[i:i + CHUNK_SIZE])
            for i in range(0, len(text), CHUNK_SIZE) if text[i:i + CHUNK_SIZE].strip()]


# ---------------------------------------------------------------------------
# 资源入库(含嵌入)
# ---------------------------------------------------------------------------

def add_resource(title, content, author="", source_type="paste"):
    """入库一本书:存全文 + 切分段 + 逐段嵌入。返回 ResourceBook。"""
    book = ResourceBook(
        title=title or "未命名资源", author=author,
        source_type=source_type, content=content,
        total_chars=len(content or ""),
    )
    chunks = _split_chunks(content)
    book.chapter_count = len(chunks)
    db.session.add(book)
    db.session.flush()

    for idx, (ch_title, ch_body) in enumerate(chunks):
        th = _hash_text(ch_body)
        vec = _get_embedding(ch_body)
        db.session.add(ResourceChunk(
            resource_id=book.id, chunk_type="chapter", chunk_index=idx,
            title=ch_title[:200], content=ch_body,
            embedding=_pack(vec), text_hash=th,
        ))
    book.embedded = True
    db.session.commit()
    return book


def reembed_resource(resource_id):
    """重新嵌入(内容变了或降级向量要升级时调用)。"""
    book = db.session.get(ResourceBook, resource_id)
    if not book:
        return
    for chunk in book.chunks:
        th = _hash_text(chunk.content)
        if th == chunk.text_hash and chunk.embedding:
            continue
        vec = _get_embedding(chunk.content)
        chunk.embedding = _pack(vec)
        chunk.text_hash = th
    book.embedded = True
    db.session.commit()


# ---------------------------------------------------------------------------
# 语义检索
# ---------------------------------------------------------------------------

def semantic_search(query, novel_id=None, top_k=5):
    """语义检索:query embed → 与资源库所有分段算余弦 → top-K。

    novel_id 不为 None 时,只检索**已采纳进该小说的拆书任务**的来源资源
    (跨书检索留第二版)。
    返回 [{"title", "content", "score", "resource_title"}],score 越高越相关。
    """
    q_vec = _get_embedding(query)
    if not q_vec or all(x == 0 for x in q_vec):
        return []

    # 圈定资源范围
    if novel_id:
        from app.models import PlagiarizeTask
        task = PlagiarizeTask.query.filter_by(
            target_novel_id=novel_id, mode="deconstruct").order_by(
            PlagiarizeTask.id.desc()).first()
        if not task or not task.source_text:
            return []
        resource_ids = [rb.id for rb in ResourceBook.query.all()
                        if rb.content and rb.content.strip()[:100] == task.source_text.strip()[:100]]
        if not resource_ids:
            return []
        chunks = ResourceChunk.query.filter(ResourceChunk.resource_id.in_(resource_ids)).all()
    else:
        chunks = ResourceChunk.query.all()

    # 暴力余弦(几千条毫秒级)
    scored = []
    book_titles = {b.id: b.title for b in ResourceBook.query.all()}
    for chunk in chunks:
        if not chunk.embedding:
            continue
        c_vec = _unpack(chunk.embedding)
        score = _cosine(q_vec, c_vec)
        scored.append({
            "title": chunk.title or "",
            "content": (chunk.content or "")[:300],
            "score": round(score, 4),
            "resource_title": book_titles.get(chunk.resource_id, ""),
            "chunk_index": chunk.chunk_index,
        })
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]
