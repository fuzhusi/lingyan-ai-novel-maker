"""嵌入服务 —— 统一管理嵌入向量生成，使用项目已配的 LLM 厂商。

策略：
1. 逐个尝试已启用厂商的 POST /embeddings 端点（OpenAI 兼容协议）
2. 全部失败 → 字符频率向量降级（无语义但管线可跑通）
3. text_hash 缓存：内容不变不重嵌入（由调用方 EntityEmbedding 表管理）
"""
import hashlib
import logging
import math
import struct

logger = logging.getLogger(__name__)

# 每厂商尝试的模型名（按顺序）
_EMBED_MODEL_FALLBACKS = [
    "text-embedding-3-small",
    "embedding-2",
    "BAAI/bge-m3",
]


def _hash_text(text):
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def _pack_vector(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vector(blob):
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _char_freq(text, dim=256):
    vec = [0.0] * dim
    for ch in (text or "")[:5000]:
        vec[ord(ch) % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm > 0 else vec


def get_embedding(text):
    """获取文本嵌入向量（纯向量，不含模型信息）。"""
    vec, _ = _try_embed(text)
    return vec


def get_embedding_with_model(text):
    """获取嵌入向量 + 使用的模型标识。"""
    return _try_embed(text)


def _try_embed(text):
    """逐厂商尝试 embedding API。返回 (vector, model_label)。

    text 为空时返回 (char_freq_vec, "(empty)")。
    """
    text = (text or "").strip()
    if not text:
        return _char_freq(text), "(empty)"

    from app.models import LLMProvider
    from app.config_utils import get_model_config

    # 构建候选列表：summary agent 优先，然后逐个其他已启用厂商
    candidates = []
    cfg = get_model_config(agent_type="summary")
    if cfg and cfg.get("base_url") and cfg.get("api_key"):
        candidates.append(cfg)
    seen_urls = {cfg["base_url"] for c in candidates if c.get("base_url")}
    for p in LLMProvider.query.filter_by(enabled=True).all():
        if p.api_key and p.base_url and p.base_url not in seen_urls:
            candidates.append({"base_url": p.base_url, "api_key": p.api_key})
            seen_urls.add(p.base_url)

    errors = []
    for pcfg in candidates:
        for model_name in _EMBED_MODEL_FALLBACKS[:2]:
            try:
                vec = _call_embed_api(text, pcfg, model_name)
                if vec:
                    label = f"{pcfg['base_url']}/{model_name}"
                    return vec, label
            except Exception as e:
                errors.append(f"{pcfg.get('base_url', '?')}/{model_name}: {e}")

    logger.warning("所有厂商 embedding 调用失败，降级字符频率: %s",
                   errors[0] if errors else "无可用厂商")
    return _char_freq(text), "(all_failed)"


def _call_embed_api(text, pcfg, model_name):
    """单次 embedding API 调用。返回向量 list[float] 或抛异常。"""
    import httpx
    url = f"{pcfg['base_url'].rstrip('/')}/embeddings"
    resp = httpx.post(url,
                      json={"model": model_name, "input": text[:8000]},
                      headers={"Authorization": f"Bearer {pcfg['api_key']}",
                               "Content-Type": "application/json"},
                      timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    if "data" in data and isinstance(data["data"], list) and data["data"]:
        emb = data["data"][0].get("embedding", [])
        if emb:
            return emb
    raise ValueError(f"embedding API 返回空: {str(data)[:200]}")
