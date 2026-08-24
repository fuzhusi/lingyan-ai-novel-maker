"""Character Relations — multi-dimensional relationship tracking with dynamic evolution."""
import json
from flask import Blueprint, request, jsonify
from app.models import db, CharacterRelation, Character, Novel

relations_bp = Blueprint("relations", __name__, url_prefix="/api")


def _serialize_relation(r):
    return {
        "id": r.id,
        "novelId": r.novel_id,
        "characterAId": r.character_a_id,
        "characterBId": r.character_b_id,
        "characterAName": r.character_a.name if r.character_a else "",
        "characterBName": r.character_b.name if r.character_b else "",
        "relationType": r.relation_type,
        "description": r.description,
        "trust": r.trust,
        "affection": r.affection,
        "respect": r.respect,
        "fear": r.fear,
        "dependency": r.dependency,
        "overallScore": r.overall_score,
        "autoRelationType": r.auto_relation_type,
        "status": r.status,
        "startChapter": r.start_chapter,
        "createdAt": r.created_at,
        "updatedAt": r.updated_at,
    }


VALID_RELATION_TYPES = [
    "family", "love", "friend", "enemy", "mentor", "rival", "ally", "ordinary"
]

RELATION_EVENTS = {
    "battle_together": {"trust": (5, 15), "respect": (3, 10)},
    "betrayal": {"trust": (-40, -20), "affection": (-30, -10)},
    "life_saving": {"trust": (15, 25), "affection": (10, 20)},
    "conflict": {"trust": (-15, -5), "respect": (-10, -3)},
    "open_talk": {"trust": (5, 10), "affection": (3, 8)},
    "public_humiliation": {"respect": (-25, -15), "fear": (5, 10)},
}


@relations_bp.route("/novels/<int:novel_id>/relations")
def list_relations(novel_id):
    Novel.query.get_or_404(novel_id)
    relations = CharacterRelation.query.filter_by(novel_id=novel_id).all()
    return jsonify([_serialize_relation(r) for r in relations])


@relations_bp.route("/novels/<int:novel_id>/relations", methods=["POST"])
def create_relation(novel_id):
    Novel.query.get_or_404(novel_id)
    data = request.get_json(silent=True) or {}

    char_a_id = data.get("characterAId")
    char_b_id = data.get("characterBId")
    if not char_a_id or not char_b_id:
        return jsonify({"error": "characterAId and characterBId required"}), 400
    if char_a_id == char_b_id:
        return jsonify({"error": "Cannot create relation with self"}), 400

    # 双向校验：两个角色都必须存在且属于本小说。
    # 此前不校验，可把 A 书角色与 B 书角色连成关系，污染双方上下文注入
    char_a = Character.query.filter_by(id=char_a_id, novel_id=novel_id).first()
    char_b = Character.query.filter_by(id=char_b_id, novel_id=novel_id).first()
    if not char_a or not char_b:
        return jsonify({"error": "角色不存在或不属于该小说"}), 400

    # Check for existing relation
    existing = CharacterRelation.query.filter(
        ((CharacterRelation.character_a_id == char_a_id) & (CharacterRelation.character_b_id == char_b_id)) |
        ((CharacterRelation.character_a_id == char_b_id) & (CharacterRelation.character_b_id == char_a_id))
    ).first()
    if existing:
        return jsonify({"error": "Relation already exists", "existingId": existing.id}), 409

    relation = CharacterRelation(
        novel_id=novel_id,
        character_a_id=char_a_id,
        character_b_id=char_b_id,
        relation_type=data.get("relationType", "ordinary"),
        description=data.get("description", ""),
        trust=data.get("trust", 50),
        affection=data.get("affection", 50),
        respect=data.get("respect", 50),
        fear=data.get("fear", 0),
        dependency=data.get("dependency", 50),
        start_chapter=data.get("startChapter"),
    )
    db.session.add(relation)
    db.session.commit()
    return jsonify(_serialize_relation(relation))


@relations_bp.route("/relations/<int:relation_id>")
def get_relation(relation_id):
    r = CharacterRelation.query.get_or_404(relation_id)
    return jsonify(_serialize_relation(r))


@relations_bp.route("/relations/<int:relation_id>", methods=["PUT"])
def update_relation(relation_id):
    r = CharacterRelation.query.get_or_404(relation_id)
    data = request.get_json(silent=True) or {}

    for field in ["relation_type", "description", "status"]:
        camel = field.replace("_", "").replace("type", "Type")
        # Map camelCase keys
        key_map = {
            "relationType": "relation_type",
            "description": "description",
            "status": "status",
        }
        for camel_key, db_key in key_map.items():
            if camel_key in data:
                setattr(r, db_key, data[camel_key])

    for dim in ["trust", "affection", "respect", "fear", "dependency"]:
        if dim in data:
            try:
                val = max(0, min(100, int(data[dim])))
            except (TypeError, ValueError):
                # AI 生成的关系事件可能传浮点串/None，直接 int() 会 500
                try:
                    val = max(0, min(100, int(float(data[dim]))))
                except (TypeError, ValueError):
                    return jsonify({"error": f"{dim} 必须是数字"}), 400
            setattr(r, dim, val)

    if "startChapter" in data:
        r.start_chapter = data["startChapter"]

    db.session.commit()
    return jsonify(_serialize_relation(r))


@relations_bp.route("/relations/<int:relation_id>", methods=["DELETE"])
def delete_relation(relation_id):
    r = CharacterRelation.query.get_or_404(relation_id)
    db.session.delete(r)
    db.session.commit()
    return jsonify({"ok": True})


@relations_bp.route("/relations/<int:relation_id>/event", methods=["POST"])
def apply_event(relation_id):
    """Apply a relationship event (e.g. battle_together, betrayal) to auto-adjust scores."""
    r = CharacterRelation.query.get_or_404(relation_id)
    data = request.get_json(silent=True) or {}
    event_type = data.get("eventType", "")
    intensity = data.get("intensity", 1.0)  # 0.5 ~ 2.0

    if event_type not in RELATION_EVENTS:
        return jsonify({"error": f"Unknown event type: {event_type}", "validTypes": list(RELATION_EVENTS.keys())}), 400

    changes = RELATION_EVENTS[event_type]
    applied = {}
    for dim, (low, high) in changes.items():
        import random
        base = random.randint(low, high)
        final = int(base * intensity)
        current = getattr(r, dim)
        new_val = max(0, min(100, current + final))
        setattr(r, dim, new_val)
        applied[dim] = {"before": current, "after": new_val, "change": new_val - current}

    # Auto-detect relation type change
    old_type = r.relation_type
    new_auto_type = r.auto_relation_type

    db.session.commit()

    return jsonify({
        "ok": True,
        "changes": applied,
        "overallScore": r.overall_score,
        "autoRelationType": new_auto_type,
        "previousType": old_type,
    })


@relations_bp.route("/novels/<int:novel_id>/relations/graph")
def relation_graph(novel_id):
    """Return graph data for visualization: nodes (characters) + edges (relations)."""
    Novel.query.get_or_404(novel_id)
    characters = Character.query.filter_by(novel_id=novel_id).all()
    relations = CharacterRelation.query.filter_by(novel_id=novel_id).all()

    nodes = [{"id": c.id, "name": c.name} for c in characters]
    edges = [{
        "id": r.id,
        "source": r.character_a_id,
        "target": r.character_b_id,
        "type": r.relation_type,
        "autoType": r.auto_relation_type,
        "score": r.overall_score,
        "trust": r.trust,
        "affection": r.affection,
        "respect": r.respect,
        "fear": r.fear,
        "dependency": r.dependency,
    } for r in relations]

    return jsonify({"nodes": nodes, "edges": edges})
