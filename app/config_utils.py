"""配置解析工具 - 供 routes 和 services 共同使用。

从 Setting 表读取全局 / Per-Agent / Per-Novel 配置，
避免 services 反向导入 routes.settings 造成的循环依赖。

模型配置解析优先级（高 -> 低）：
1. llm_model_{agent_type}   Per-Agent 指定厂商模型（"provider_id:model_id"）
2. 自动默认                 首个已启用厂商的已勾选模型（按 Agent 分组智能选择）
3. Setting 表全局键         api_key / base_url / model_name（遗留，仅 CLI 可写）
4. .env 环境变量            DEFAULTS

自动默认规则：
- 快速生成类 Agent（writer/outline/...）优先匹配快速模型（flash/lite/mini/...）
- 深度分析类 Agent（critic/audit/...）优先匹配深度模型（pro/max/plus/...）
- 无关键词匹配时用该厂商第一个已勾选模型
- 存在自动默认时忽略裸 model_name_{agent} 覆盖（裸模型名搭配错误 api_key 只会 401）
"""
import json
import os
from app.models import Setting

DEFAULTS = {
    "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
    "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    "model_name": os.getenv("MODEL_NAME", "deepseek-v4-pro"),
    "temperature": "0.8",
    "max_tokens": "4096",
}

# 请求级别缓存，避免同一请求内重复查询 LLMProvider 表
# 键格式："{pid}:{mid}" -> 厂商配置 dict | None；"__auto__:{agent}" -> 自动默认 dict | None
_provider_cache = {}

# Agent 分组：fast=快速生成类，deep=深度分析类（与 routes/settings.py AGENT_TYPES 保持同步）
AGENT_GROUPS = {
    "writer": "fast", "outline": "fast", "summary": "fast", "memory": "fast",
    "causal_chain": "fast", "temporal_truth": "fast", "short_story": "fast",
    "critic": "deep", "rewrite": "deep", "character_check": "deep",
    "lore_check": "deep", "foreshadow_check": "deep", "editor": "deep",
    "audit": "deep", "optimizer": "deep", "style": "deep",
}

# 模型选择关键词（匹配 model_id，不区分大小写）
FAST_MODEL_KEYWORDS = ("flash", "lite", "mini", "fast", "turbo", "instant", "air", "haiku", "speed")
PRO_MODEL_KEYWORDS = ("pro", "max", "plus", "premium", "opus", "thinking", "reasoner")


def _reset_provider_cache():
    """请求结束时清空缓存（由 app.teardown_appcontext 调用）。"""
    _provider_cache.clear()


def get_setting(key, fallback=""):
    s = Setting.query.get(key)
    if s and s.value and s.value.strip():
        return s.value
    return fallback


def _safe_float(val, default):
    """安全转 float，失败返回 default。"""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val, default):
    """安全转 int，失败返回 default。"""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _resolve_llm_model(key_value):
    """解析 "provider_id:model_id" 为厂商配置 dict；无效/未启用返回 None（带缓存）。

    模型被取消勾选后返回 None（调用方自动回退默认，而非报错）。

    Returns:
        {"api_key", "base_url", "model_name", "provider_type"} 或 None
    """
    try:
        pid, mid = key_value.split(":", 1)
        pid = int(pid)
    except (ValueError, TypeError, AttributeError):
        return None

    cache_key = f"{pid}:{mid}"
    if cache_key in _provider_cache:
        cached = _provider_cache[cache_key]
        return dict(cached) if cached else None

    from app.models.llm_provider import LLMProvider, LLMModel
    cfg = None
    provider = LLMProvider.query.get(pid)
    if provider and provider.enabled and provider.api_key:
        # 校验模型仍被勾选
        model = LLMModel.query.filter_by(provider_id=pid, model_id=mid, enabled=True).first()
        if model:
            cfg = {
                "api_key": provider.api_key,
                "base_url": provider.base_url,
                "model_name": mid,
                "provider_type": provider.provider_type,
            }
    _provider_cache[cache_key] = dict(cfg) if cfg else None
    return cfg


def get_auto_default_model(agent_type=None):
    """从已启用厂商中自动选择默认模型。

    选择逻辑：
    - 取 id 最小（最早添加）的已启用、有 api_key、有已勾选模型的厂商
    - 按 Agent 分组优先匹配关键词：fast 组匹配快速模型，deep 组匹配深度模型
    - 无匹配时用该厂商第一个已勾选模型

    Returns:
        {"api_key", "base_url", "model_name", "provider_type"} 或 None
    """
    cache_key = f"__auto__:{agent_type or ''}"
    if cache_key in _provider_cache:
        cached = _provider_cache[cache_key]
        return dict(cached) if cached else None

    from app.models.llm_provider import LLMProvider, LLMModel
    result = None
    providers = LLMProvider.query.filter_by(enabled=True).order_by(LLMProvider.id).all()
    for p in providers:
        if not p.api_key:
            continue
        models = LLMModel.query.filter_by(provider_id=p.id, enabled=True).order_by(LLMModel.id).all()
        if not models:
            continue

        group = AGENT_GROUPS.get(agent_type)
        chosen = None
        if group == "fast":
            chosen = next(
                (m for m in models if any(k in (m.model_id or "").lower() for k in FAST_MODEL_KEYWORDS)),
                None,
            )
        elif group == "deep":
            chosen = next(
                (m for m in models if any(k in (m.model_id or "").lower() for k in PRO_MODEL_KEYWORDS)),
                None,
            )
        if chosen is None:
            chosen = models[0]

        result = {
            "api_key": p.api_key,
            "base_url": p.base_url,
            "model_name": chosen.model_id,
            "provider_type": p.provider_type,
        }
        break

    _provider_cache[cache_key] = dict(result) if result else None
    return result


def _explicit_agent_cfg(agent_type, base):
    """收集 Agent 级显式配置（仅实际设置的键）。

    - llm_model_{agent}: 厂商模型（api_key/base_url/model_name/provider_type）
    - temperature_/max_tokens_: 参数覆盖
    - model_name_{agent}: 裸模型名，仅在无自动默认时生效（避免与厂商 key 错配）
    """
    cfg = {}
    temp_override = get_setting(f"temperature_{agent_type}", "")
    if temp_override:
        cfg["temperature"] = _safe_float(temp_override, base["temperature"])
    tokens_override = get_setting(f"max_tokens_{agent_type}", "")
    if tokens_override:
        cfg["max_tokens"] = _safe_int(tokens_override, base["max_tokens"])
    provider_cfg = _resolve_llm_model(get_setting(f"llm_model_{agent_type}", ""))
    if provider_cfg:
        cfg.update(provider_cfg)
    elif not get_auto_default_model(agent_type):
        model_override = get_setting(f"model_name_{agent_type}", "")
        if model_override:
            cfg["model_name"] = model_override
    return cfg


def get_model_config(agent_type=None):
    """Return the current effective model config as a dict.

    Args:
        agent_type: 可选，按 Agent 类型覆盖配置

    Returns:
        配置字典: api_key, base_url, model_name, temperature, max_tokens, provider_type
    """
    base = {
        "api_key": get_setting("api_key", DEFAULTS["api_key"]),
        "base_url": get_setting("base_url", DEFAULTS["base_url"]),
        "model_name": get_setting("model_name", DEFAULTS["model_name"]),
        "temperature": _safe_float(get_setting("temperature", DEFAULTS["temperature"]), 0.8),
        "max_tokens": _safe_int(get_setting("max_tokens", DEFAULTS["max_tokens"]), 4096),
        "provider_type": get_setting("provider_type", "deepseek"),
    }

    # 自动默认：已启用厂商的已勾选模型
    auto = get_auto_default_model(agent_type)
    if auto:
        base.update(auto)

    # Agent 级显式配置（最高优先级）
    if agent_type:
        base.update(_explicit_agent_cfg(agent_type, base))

    return base


def get_effective_config(novel=None, agent_type=None):
    """Get model config with optional per-novel and per-agent overrides.

    优先级: agent_type 显式配置 > novel.model_override > 自动默认 > 全局配置

    Agent 层只覆盖实际显式配置的键，避免 Agent 无配置时
    把 novel.model_override 的 api_key/base_url 冲掉。
    """
    # 第一层：全局配置 + 自动默认
    base = get_model_config(agent_type=None)
    # 第二层：novel.model_override
    if novel and novel.model_override:
        try:
            overrides = json.loads(novel.model_override)
            for k, v in overrides.items():
                if v and str(v).strip():
                    base[k] = v
        except json.JSONDecodeError:
            pass
    # 第三层（最高优先级）：agent_type 显式配置的键
    if agent_type:
        base.update(_explicit_agent_cfg(agent_type, base))
    return base


def get_available_models_for_agent():
    """获取所有已启用厂商的已勾选模型，按厂商分组。

    Returns:
        [{"provider_id": 1, "provider_name": "DeepSeek", "provider_type": "deepseek",
          "models": [{"model_id": "v4-pro", "display_name": "V4 Pro", "key": "1:deepseek-v4-pro"}]}]
    """
    from app.models.llm_provider import LLMProvider, LLMModel
    providers = LLMProvider.query.filter_by(enabled=True).all()
    result = []
    for p in providers:
        models = LLMModel.query.filter_by(provider_id=p.id, enabled=True).all()
        if models:
            result.append({
                "provider_id": p.id,
                "provider_name": p.name,
                "provider_type": p.provider_type,
                "models": [
                    {"model_id": m.model_id, "display_name": m.display_name or m.model_id,
                     "key": f"{p.id}:{m.model_id}"}
                    for m in models
                ],
            })
    return result
