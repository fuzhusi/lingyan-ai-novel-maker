from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from app.models import db, PromptTemplate
from app.services.prompt_builder import DEFAULT_WRITER_CONSTRAINTS

templates_bp = Blueprint("templates_lib", __name__, url_prefix="/prompt-templates")


@templates_bp.route("/")
def list_templates():
    templates = PromptTemplate.query.order_by(PromptTemplate.template_type, PromptTemplate.name).all()

    # 检查每种类型是否有自定义模板
    template_types = ["writer", "critic", "summary", "outline", "rewrite",
                      "character_check", "lore_check", "foreshadow_check", "editor"]
    active_types = {}
    for t_type in template_types:
        has_custom = PromptTemplate.query.filter_by(template_type=t_type).first() is not None
        active_types[t_type] = has_custom

    return render_template("prompt_templates.html",
                          templates=templates,
                          default_constraints=DEFAULT_WRITER_CONSTRAINTS,
                          active_types=active_types)


@templates_bp.route("/create", methods=["POST"])
def create_template():
    t = PromptTemplate(
        name=request.form.get("name", "").strip(),
        template_type=request.form.get("template_type", "writer"),
        template_content=request.form.get("template_content", ""),
        constraints=request.form.get("constraints", ""),
        variable_help=request.form.get("variable_help", ""),
    )
    db.session.add(t)
    db.session.commit()
    return redirect(url_for("templates_lib.list_templates"))


@templates_bp.route("/<int:tid>/edit", methods=["POST"])
def edit_template(tid):
    t = PromptTemplate.query.get_or_404(tid)
    for field in ["name", "template_type", "template_content", "constraints", "variable_help"]:
        val = request.form.get(field)
        if val is not None:
            setattr(t, field, val)
    db.session.commit()
    return redirect(url_for("templates_lib.list_templates"))


@templates_bp.route("/<int:tid>/delete", methods=["POST"])
def delete_template(tid):
    PromptTemplate.query.get_or_404(tid)
    PromptTemplate.query.filter_by(id=tid).delete()
    db.session.commit()
    return redirect(url_for("templates_lib.list_templates"))


@templates_bp.route("/api/list")
def api_list():
    templates = PromptTemplate.query.order_by(PromptTemplate.template_type, PromptTemplate.name).all()
    return jsonify([
        {
            "id": t.id,
            "name": t.name,
            "template_type": t.template_type,
            "template_content": t.template_content,
            "constraints": t.constraints or "",
            "variable_help": t.variable_help,
        }
        for t in templates
    ])


@templates_bp.route("/api/<int:tid>")
def api_get(tid):
    t = PromptTemplate.query.get_or_404(tid)
    return jsonify({
        "id": t.id,
        "name": t.name,
        "template_type": t.template_type,
        "template_content": t.template_content,
        "constraints": t.constraints or "",
        "variable_help": t.variable_help,
    })
