"""LLM 厂商配置 API — 管理 API 厂商、拉取模型列表、勾选模型。"""
from flask import Blueprint, request, jsonify, render_template
from app.models import db
from app.models.llm_provider import LLMProvider, LLMModel
from app.services.llm import fetch_models_from_provider, test_provider_connection

llm_settings_bp = Blueprint("llm_settings", __name__)


# ---- 页面 ----

@llm_settings_bp.route("/settings/llm")
def llm_settings_page():
    """厂商模型配置页。"""
    providers = LLMProvider.query.order_by(LLMProvider.id).all()
    return render_template("settings_llm.html", providers=providers)


# ---- 厂商 CRUD ----

@llm_settings_bp.route("/settings/llm/provider/add", methods=["POST"])
def add_provider():
    """添加厂商。"""
    name = request.form.get("name", "").strip()
    provider_type = request.form.get("provider_type", "custom")
    base_url = request.form.get("base_url", "").strip()
    api_key = request.form.get("api_key", "").strip()

    if not name or not base_url:
        return jsonify({"error": "名称和 API 地址不能为空"}), 400

    p = LLMProvider(name=name, provider_type=provider_type, base_url=base_url, api_key=api_key)
    db.session.add(p)
    db.session.commit()
    return jsonify({"ok": True, "provider": p.to_dict(include_key=False)})


@llm_settings_bp.route("/settings/llm/provider/<int:pid>/update", methods=["POST"])
def update_provider(pid):
    """更新厂商信息。"""
    p = LLMProvider.query.get_or_404(pid)
    name = request.form.get("name", "").strip()
    base_url = request.form.get("base_url", "").strip()
    api_key = request.form.get("api_key")
    enabled = request.form.get("enabled")

    if name:
        p.name = name
    if base_url:
        p.base_url = base_url
    if api_key is not None:
        p.api_key = api_key
    if enabled is not None:
        p.enabled = enabled.lower() in ("true", "1", "on")
    db.session.commit()
    return jsonify({"ok": True, "provider": p.to_dict(include_key=False)})


@llm_settings_bp.route("/settings/llm/provider/<int:pid>/delete", methods=["POST"])
def delete_provider(pid):
    """删除厂商及其所有模型。"""
    p = LLMProvider.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    return jsonify({"ok": True})


# ---- 拉取模型 ----

@llm_settings_bp.route("/settings/llm/provider/<int:pid>/fetch-models", methods=["POST"])
def fetch_models(pid):
    """调用厂商 API 拉取可用模型列表，存入 LLMModel 表。"""
    p = LLMProvider.query.get_or_404(pid)
    try:
        models = fetch_models_from_provider(p.base_url, p.api_key, p.provider_type)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 400

    # 获取已有模型
    existing = {m.model_id: m for m in LLMModel.query.filter_by(provider_id=pid).all()}

    added = 0
    for m in models:
        mid = m["id"]
        if mid not in existing:
            db.session.add(LLMModel(
                provider_id=pid,
                model_id=mid,
                display_name=mid,
                enabled=False,
            ))
            added += 1

    db.session.commit()

    # 返回所有模型（含新增）
    all_models = LLMModel.query.filter_by(provider_id=pid).all()
    return jsonify({
        "ok": True,
        "added": added,
        "total": len(all_models),
        "models": [m.to_dict() for m in all_models],
    })


# ---- 测试连接 ----

@llm_settings_bp.route("/settings/llm/provider/<int:pid>/test", methods=["POST"])
def test_connection(pid):
    """测试厂商 API 连接。"""
    p = LLMProvider.query.get_or_404(pid)
    result = test_provider_connection(p.base_url, p.api_key, p.provider_type)
    return jsonify(result)


# ---- 勾选模型 ----

@llm_settings_bp.route("/settings/llm/model/<int:mid>/toggle", methods=["POST"])
def toggle_model(mid):
    """勾选/取消模型。"""
    m = LLMModel.query.get_or_404(mid)
    enabled = request.form.get("enabled")
    if enabled is not None:
        m.enabled = enabled.lower() in ("true", "1", "on")
    else:
        m.enabled = not m.enabled
    db.session.commit()
    return jsonify({"ok": True, "model": m.to_dict()})


@llm_settings_bp.route("/settings/llm/provider/<int:pid>/toggle-all", methods=["POST"])
def toggle_all_models(pid):
    """批量勾选/取消某厂商下所有模型。"""
    enabled = request.form.get("enabled", "true").lower() in ("true", "1", "on")
    LLMModel.query.filter_by(provider_id=pid).update({"enabled": enabled})
    db.session.commit()
    return jsonify({"ok": True})


# ---- 获取可用模型（供角色配置下拉用） ----

@llm_settings_bp.route("/settings/llm/available-models")
def available_models():
    """返回所有已启用厂商的已勾选模型，按厂商分组。"""
    from app.config_utils import get_available_models_for_agent
    return jsonify(get_available_models_for_agent())


# ---- 批量保存勾选状态 ----

@llm_settings_bp.route("/settings/llm/provider/<int:pid>/save-selection", methods=["POST"])
def save_selection(pid):
    """批量保存模型勾选状态。body: model_ids=1,2,3"""
    ids_str = request.form.get("model_ids", "")
    enabled_ids = set()
    if ids_str:
        try:
            enabled_ids = set(int(i) for i in ids_str.split(",") if i.strip())
        except ValueError:
            pass

    models = LLMModel.query.filter_by(provider_id=pid).all()
    for m in models:
        m.enabled = m.id in enabled_ids
    db.session.commit()

    return jsonify({"ok": True, "models": [m.to_dict() for m in models]})
