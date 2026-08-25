import json
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from app.models import db, Setting
from app.config_utils import (
    DEFAULTS, get_setting, get_model_config, get_effective_config,
    get_auto_default_model,
)

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

# Re-export for backward compatibility
__all__ = ["get_model_config", "get_effective_config", "settings_bp"]


# ---------------------------------------------------------------------------
# Agent 类型配置定义
# ---------------------------------------------------------------------------

# 所有支持的 Agent 类型及其元数据
AGENT_TYPES = {
    # 快速生成类 (V4 Flash)
    "writer":            {"name": "章节生成",     "group": "fast", "recommended_model": "deepseek-v4-flash"},
    "outline":           {"name": "大纲生成",     "group": "fast", "recommended_model": "deepseek-v4-flash"},
    "summary":           {"name": "摘要生成",     "group": "fast", "recommended_model": "deepseek-v4-flash"},
    "memory":            {"name": "章节记忆",     "group": "fast", "recommended_model": "deepseek-v4-flash"},
    "causal_chain":      {"name": "因果链",       "group": "fast", "recommended_model": "deepseek-v4-flash"},
    "temporal_truth":    {"name": "时序真理",     "group": "fast", "recommended_model": "deepseek-v4-flash"},
    "short_story":       {"name": "短篇生成",     "group": "fast", "recommended_model": "deepseek-v4-flash"},

    # 深度分析类 (V4 Pro)
    "critic":            {"name": "评审",         "group": "deep", "recommended_model": "deepseek-v4-pro"},
    "rewrite":           {"name": "改写",         "group": "deep", "recommended_model": "deepseek-v4-pro"},
    "character_check":   {"name": "角色检查",     "group": "deep", "recommended_model": "deepseek-v4-pro"},
    "lore_check":        {"name": "世界观检查",   "group": "deep", "recommended_model": "deepseek-v4-pro"},
    "foreshadow_check":  {"name": "伏笔检查",     "group": "deep", "recommended_model": "deepseek-v4-pro"},
    "editor":            {"name": "编辑润色",     "group": "deep", "recommended_model": "deepseek-v4-pro"},
    "audit":             {"name": "质量审计",     "group": "deep", "recommended_model": "deepseek-v4-pro"},
    "optimizer":         {"name": "全书优化",     "group": "deep", "recommended_model": "deepseek-v4-pro"},
    "style":             {"name": "风格分析",     "group": "deep", "recommended_model": "deepseek-v4-pro"},
}

# 推荐配置默认值
RECOMMENDED_DEFAULTS = {
    # 快速生成类
    "writer":         {"model_name": "deepseek-v4-flash", "temperature": "0.9",  "max_tokens": "4096"},
    "outline":        {"model_name": "deepseek-v4-flash", "temperature": "0.8",  "max_tokens": "2048"},
    "summary":        {"model_name": "deepseek-v4-flash", "temperature": "0.5",  "max_tokens": "1024"},
    "memory":         {"model_name": "deepseek-v4-flash", "temperature": "0.3",  "max_tokens": "2048"},
    "causal_chain":   {"model_name": "deepseek-v4-flash", "temperature": "0.3",  "max_tokens": "2048"},
    "temporal_truth": {"model_name": "deepseek-v4-flash", "temperature": "0.3",  "max_tokens": "1024"},
    "short_story":    {"model_name": "deepseek-v4-flash", "temperature": "0.9",  "max_tokens": "4096"},

    # 深度分析类
    "critic":           {"model_name": "deepseek-v4-pro", "temperature": "0.3", "max_tokens": "2048"},
    "rewrite":          {"model_name": "deepseek-v4-pro", "temperature": "0.7", "max_tokens": "4096"},
    "character_check":  {"model_name": "deepseek-v4-pro", "temperature": "0.3", "max_tokens": "2048"},
    "lore_check":       {"model_name": "deepseek-v4-pro", "temperature": "0.3", "max_tokens": "2048"},
    "foreshadow_check": {"model_name": "deepseek-v4-pro", "temperature": "0.3", "max_tokens": "2048"},
    "editor":           {"model_name": "deepseek-v4-pro", "temperature": "0.5", "max_tokens": "4096"},
    "audit":            {"model_name": "deepseek-v4-pro", "temperature": "0.3", "max_tokens": "2048"},
    "optimizer":        {"model_name": "deepseek-v4-pro", "temperature": "0.5", "max_tokens": "4096"},
    "style":            {"model_name": "deepseek-v4-pro", "temperature": "0.3", "max_tokens": "2048"},
}


def _save_setting(key, value):
    s = Setting.query.get(key)
    if s:
        s.value = value
    else:
        s = Setting(key=key, value=value)
        db.session.add(s)


@settings_bp.route("/")
def settings_page():
    config = get_model_config()
    # 获取每个 agent 类型的当前配置
    agent_configs = {}
    for agent_type in AGENT_TYPES:
        agent_configs[agent_type] = {
            "model_name": get_setting(f"model_name_{agent_type}", ""),
            "temperature": get_setting(f"temperature_{agent_type}", ""),
            "max_tokens": get_setting(f"max_tokens_{agent_type}", ""),
            "llm_model": get_setting(f"llm_model_{agent_type}", ""),
            "frequency_penalty": get_setting(f"frequency_penalty_{agent_type}", ""),
            "presence_penalty": get_setting(f"presence_penalty_{agent_type}", ""),
        }
    # 获取已勾选的可用模型（按厂商分组）
    from app.config_utils import get_available_models_for_agent
    available_models = get_available_models_for_agent()
    # 每个 Agent 的自动默认模型（未显式配置时使用）
    auto_models = {}
    for agent_type in AGENT_TYPES:
        auto = get_auto_default_model(agent_type)
        auto_models[agent_type] = auto["model_name"] if auto else ""
    return render_template("settings.html",
                          config=config,
                          defaults=DEFAULTS,
                          agent_types=AGENT_TYPES,
                          agent_configs=agent_configs,
                          available_models=available_models,
                          auto_models=auto_models,
                          recommended_defaults=RECOMMENDED_DEFAULTS)


@settings_bp.route("/save", methods=["POST"])
def save_settings():
    # 保存 temperature / max_tokens
    for key in ["temperature", "max_tokens"]:
        val = request.form.get(key, "")
        if val.strip():
            _save_setting(key, val.strip())
        elif request.form.get(f"_clear_{key}"):
            existing = Setting.query.get(key)
            if existing:
                db.session.delete(existing)
    db.session.commit()
    return redirect(url_for("settings.settings_page"))


@settings_bp.route("/save-agent", methods=["POST"])
def save_agent_settings():
    """保存按 agent 类型的模型配置。"""
    for agent_type in AGENT_TYPES:
        # 保存 llm_model（厂商模型选择，格式 "provider_id:model_id"）
        llm_key = f"llm_model_{agent_type}"
        llm_val = request.form.get(llm_key, "")
        if llm_val.strip():
            _save_setting(llm_key, llm_val.strip())
            # 从 llm_val 解析 model_id 存入 model_name（兼容旧逻辑）
            try:
                _, model_id = llm_val.split(":", 1)
                _save_setting(f"model_name_{agent_type}", model_id)
            except ValueError:
                pass
        else:
            # 留空表示使用全局配置
            for key in [llm_key, f"model_name_{agent_type}"]:
                existing = Setting.query.get(key)
                if existing:
                    db.session.delete(existing)

        # 保存 temperature / max_tokens / 采样惩罚（frequency_penalty / presence_penalty）
        for param in ["temperature", "max_tokens", "frequency_penalty", "presence_penalty"]:
            key = f"{param}_{agent_type}"
            val = request.form.get(key, "")
            if val.strip():
                _save_setting(key, val.strip())
            else:
                existing = Setting.query.get(key)
                if existing:
                    db.session.delete(existing)
    db.session.commit()
    return redirect(url_for("settings.settings_page"))


@settings_bp.route("/api/apply-recommended", methods=["POST"])
def apply_recommended():
    """一键应用推荐配置。"""
    for agent_type, defaults in RECOMMENDED_DEFAULTS.items():
        for param, val in defaults.items():
            key = f"{param}_{agent_type}"
            _save_setting(key, val)
    db.session.commit()
    return jsonify({"ok": True, "message": "已应用推荐配置"})


@settings_bp.route("/api/clear-agent", methods=["POST"])
def clear_agent_settings():
    """清除所有 agent 类型的自定义配置，恢复全局默认。"""
    for agent_type in AGENT_TYPES:
        for param in ["model_name", "llm_model", "temperature", "max_tokens",
                      "frequency_penalty", "presence_penalty"]:
            key = f"{param}_{agent_type}"
            existing = Setting.query.get(key)
            if existing:
                db.session.delete(existing)
    db.session.commit()
    return jsonify({"ok": True, "message": "已清除所有自定义配置"})


@settings_bp.route("/api/config")
def api_config():
    """返回当前生效配置。api_key 做掩码处理，绝不返回明文；
    同时给出厂商池状态供前端判断是否可生成。"""
    cfg = get_model_config()
    masked = dict(cfg)
    key = cfg.get("api_key") or ""
    if len(key) > 8:
        masked["api_key"] = key[:6] + "****"
    elif key:
        masked["api_key"] = key[:2] + "****"
    else:
        masked["api_key"] = ""
    masked["has_provider_config"] = get_auto_default_model() is not None
    return jsonify(masked)


@settings_bp.route("/api/novel-model-override", methods=["POST"])
def set_novel_model_override():
    """为特定小说设置 model_override (JSON 字符串)。

    Body: {"novel_id": int, "model_override": dict 或 ""}
    """
    data = request.get_json(silent=True) or {}
    novel_id = data.get("novel_id")
    override = data.get("model_override")

    if not novel_id:
        return jsonify({"ok": False, "error": "novel_id 必填"}), 400

    from app.models import Novel
    novel = Novel.query.get(novel_id)
    if not novel:
        return jsonify({"ok": False, "error": "小说不存在"}), 404

    if override == "" or override is None:
        # 清除覆盖
        novel.model_override = "{}"
    elif isinstance(override, dict):
        novel.model_override = json.dumps(override, ensure_ascii=False)
    else:
        return jsonify({"ok": False, "error": "model_override 必须是 dict 或空"}), 400

    db.session.commit()
    return jsonify({"ok": True, "novel_id": novel_id, "model_override": novel.model_override})