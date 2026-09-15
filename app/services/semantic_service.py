"""语义检索服务 —— 长篇知识库实体的嵌入生成、相似度检索与上下文精选。

三层注入策略（写第 N 章时）：
  层1 常驻（不走检索）：差异化红线 / must_payoff / 本章登场退场 / 前文结尾
  层2 语义精选（本服务）：角色卡 / 世界观 / 伏笔描述 → 按大纲语义选取 top-K
  层3 兜底：FTS5 关键词匹配（向量召回失败时）
"""
import hashlib
import logging
import math
import struct

from app.models import db
from app.models.entity_embedding import EntityEmbedding
from app.models import Character, WorldSetting, Foreshadowing, ChapterSummary

logger = logging.getLogger(__name__)

_DEFAULT_TOP_K = 5
_EMBED_DIM_FALLBACK = 256


def _hash(text):
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def _pack(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob):
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _embed_text(text):
    """统一走 embedding_service（逐厂商尝试 /embeddings 端点）。"""
    from app.services.embedding_service import get_embedding
    return get_embedding(text[:3000])


def _char_freq(text, dim=_EMBED_DIM_FALLBACK):
    vec = [0.0] * dim
    for ch in (text or "")[:3000]:
        vec[ord(ch) % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm > 0 else vec


# ---------------------------------------------------------------------------
# 实体文本提取（每个实体类型定义"用什么文本做嵌入"）
# ---------------------------------------------------------------------------

def _entity_text(entity_type, obj):
    """提取实体的语义表征文本。"""
    if entity_type == "character":
        parts = [obj.name or "", obj.personality or "", obj.background or "",
                 obj.motivation or "", obj.arc_direction or ""]
        return " ".join(p for p in parts if p)
    elif entity_type == "world":
        return f"{obj.title or ''} {obj.content or ''}"
    elif entity_type == "foreshadowing":
        return f"{obj.title or ''} {obj.description or ''}"
    elif entity_type == "chapter_summary":
        return obj.summary or ""
    return ""


def _get_entity(novel_id, entity_type, entity_id):
    if entity_type == "character":
        return db.session.get(Character, entity_id)
    elif entity_type == "world":
        return db.session.get(WorldSetting, entity_id)
    elif entity_type == "foreshadowing":
        return db.session.get(Foreshadowing, entity_id)
    elif entity_type == "chapter_summary":
        return db.session.get(ChapterSummary, entity_id)
    return None


# ---------------------------------------------------------------------------
# 嵌入生成
# ---------------------------------------------------------------------------

def embed_novel_entities(novel_id, force=False):
    """批量嵌入小说的所有角色/世界观/伏笔（幂等：text_hash 不变跳过）。"""
    embedded = 0
    entities = []

    for c in Character.query.filter_by(novel_id=novel_id).all():
        entities.append(("character", c.id, _entity_text("character", c)))
    for w in WorldSetting.query.filter_by(novel_id=novel_id).all():
        entities.append(("world", w.id, _entity_text("world", w)))
    for f in Foreshadowing.query.filter_by(novel_id=novel_id).all():
        entities.append(("foreshadowing", f.id, _entity_text("foreshadowing", f)))

    for etype, eid, text in entities:
        if not text.strip():
            continue
        th = _hash(text)
        existing = EntityEmbedding.query.filter_by(
            novel_id=novel_id, entity_type=etype, entity_id=eid).first()
        if existing and not force and existing.content_hash == th:
            continue
        vec = _embed_text(text)
        if existing:
            existing.embedding = _pack(vec)
            existing.content_hash = th
        else:
            db.session.add(EntityEmbedding(
                novel_id=novel_id, entity_type=etype, entity_id=eid,
                content_hash=th, embedding=_pack(vec)))
        embedded += 1
    db.session.commit()
    return embedded


# ---------------------------------------------------------------------------
# 语义检索
# ---------------------------------------------------------------------------

def search_relevant(novel_id, query_text, entity_types=None, top_k=_DEFAULT_TOP_K):
    """语义检索：query embed → 与指定类型实体算余弦 → top-K。

    返回 [{"entity_type", "entity_id", "score", "text_snippet"}]。
    """
    q_vec = _embed_text(query_text)
    if not q_vec or all(x == 0 for x in q_vec):
        return []
    embeddings = EntityEmbedding.query.filter_by(novel_id=novel_id)
    if entity_types:
        embeddings = embeddings.filter(EntityEmbedding.entity_type.in_(entity_types))
    scored = []
    for ee in embeddings.all():
        if not ee.embedding:
            continue
        e_vec = _unpack(ee.embedding)
        if len(e_vec) != len(q_vec):
            continue  # 维度不符（降级向量 vs API 向量混入）
        score = _cosine(q_vec, e_vec)
        if score > 0.05:  # 过滤噪声
            obj = _get_entity(novel_id, ee.entity_type, ee.entity_id)
            snippet = _entity_text(ee.entity_type, obj)[:200] if obj else ""
            scored.append({"entity_type": ee.entity_type, "entity_id": ee.entity_id,
                           "score": round(score, 4), "text_snippet": snippet})
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]


# ---------------------------------------------------------------------------
# 写作包精选（替代"全量塞→压缩"）
# ---------------------------------------------------------------------------

def select_relevant_entities(novel_id, chapter_outline, prev_ending="", top_k=5):
    """语义检索选出与本章相关的角色和世界观。

    返回 {"character_ids": [...], "world_ids": [...]}。可供
    assemble_chapter_context 的 character_ids 参数使用，实现精准注入。
    """
    query = " ".join(filter(None, [chapter_outline or "", prev_ending or ""]))
    if not query.strip():
        return {"character_ids": [], "world_ids": []}
    results = search_relevant(novel_id, query,
                              entity_types=("character", "world"), top_k=top_k)
    return {
        "character_ids": [r["entity_id"] for r in results if r["entity_type"] == "character"],
        "world_ids": [r["entity_id"] for r in results if r["entity_type"] == "world"],
    }
