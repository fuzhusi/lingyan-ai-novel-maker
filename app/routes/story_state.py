"""Story State Engine — maintains full-book narrative state for long-form coherence.

Inspired by StoryForge's design: tracks main quest, subplots, conflicts,
arc phase (setup/development/climax/resolution), risk flags, and pacing.
"""
import json
from flask import Blueprint, request, jsonify
from app.models import db, StoryState, StoryStateSnapshot, Novel, Chapter, ChapterSummary, Foreshadowing

story_state_bp = Blueprint("story_state", __name__, url_prefix="/api")


def _serialize_state(state):
    if not state:
        return None
    return {
        "id": state.id,
        "novelId": state.novel_id,
        "mainQuest": state.main_quest,
        "mainQuestProgress": state.main_quest_progress,
        "activeSubplots": json.loads(state.active_subplots or "[]"),
        "activeConflicts": json.loads(state.active_conflicts or "[]"),
        "arcPhase": state.arc_phase,
        "arcIntensity": state.arc_intensity,
        "riskFlags": json.loads(state.risk_flags or "{}"),
        "excitementHistory": json.loads(state.excitement_history or "[]"),
        "lastExcitementChapter": state.last_excitement_chapter,
        "currentExcitementDensity": state.current_excitement_density,
        "recentPacing": json.loads(state.recent_pacing or "[]"),
        "currentChapter": state.current_chapter,
        "updatedAt": state.updated_at,
    }


def _detect_arc_phase(novel_id):
    """Auto-detect arc phase based on chapter progress and foreshadowing state."""
    total = Chapter.query.filter_by(novel_id=novel_id).count()
    if total == 0:
        return "setup", 1

    open_fs = Foreshadowing.query.filter_by(novel_id=novel_id).filter(
        Foreshadowing.status.in_(["open", "planned", "buried", "advancing", "reclaimable"])
    ).count()

    # Progress-based phase detection
    # We don't have target_words, so use foreshadow density as secondary signal
    if total < 5:
        phase = "setup"
        intensity = min(total + 1, 5)
    elif total < 15:
        phase = "development"
        intensity = 3 + min(total - 5, 5)
    elif open_fs > 5:
        # Many open foreshadows → still in climax
        phase = "climax"
        intensity = 7 + min(open_fs - 5, 3)
    elif total < 25:
        phase = "climax"
        intensity = 8
    else:
        phase = "resolution"
        intensity = max(10 - (total - 25), 3)

    return phase, min(intensity, 10)


def _detect_risks(novel_id, chapter_number):
    """Detect narrative risks in the current chapter."""
    risks = {}

    # Check foreshadowing timeouts
    foreshadows = Foreshadowing.query.filter_by(novel_id=novel_id).filter(
        Foreshadowing.status.in_(["buried", "advancing"])
    ).all()

    timeout_warnings = []
    for fs in foreshadows:
        if fs.planted_chapter and fs.timeout_threshold:
            age = chapter_number - fs.planted_chapter
            if age > fs.timeout_threshold:
                timeout_warnings.append({
                    "id": fs.id,
                    "title": fs.title or fs.description[:50],
                    "age": age,
                    "threshold": fs.timeout_threshold,
                    "importance": fs.importance,
                })

    if timeout_warnings:
        risks["foreshadow_timeout"] = timeout_warnings

    return risks


@story_state_bp.route("/novels/<int:novel_id>/story-state")
def get_story_state(novel_id):
    Novel.query.get_or_404(novel_id)
    state = StoryState.query.filter_by(novel_id=novel_id).first()
    if not state:
        # Auto-create with detected phase
        phase, intensity = _detect_arc_phase(novel_id)
        state = StoryState(novel_id=novel_id, arc_phase=phase, arc_intensity=intensity)
        db.session.add(state)
        db.session.commit()
    return jsonify(_serialize_state(state))


@story_state_bp.route("/novels/<int:novel_id>/story-state", methods=["PUT"])
def update_story_state(novel_id):
    Novel.query.get_or_404(novel_id)
    state = StoryState.query.filter_by(novel_id=novel_id).first()
    if not state:
        state = StoryState(novel_id=novel_id)
        db.session.add(state)

    data = request.get_json(silent=True) or {}

    if "mainQuest" in data:
        state.main_quest = data["mainQuest"]
    if "mainQuestProgress" in data:
        state.main_quest_progress = data["mainQuestProgress"]
    if "activeSubplots" in data:
        state.active_subplots = json.dumps(data["activeSubplots"], ensure_ascii=False)
    if "activeConflicts" in data:
        state.active_conflicts = json.dumps(data["activeConflicts"], ensure_ascii=False)
    if "arcPhase" in data:
        state.arc_phase = data["arcPhase"]
    if "arcIntensity" in data:
        state.arc_intensity = data["arcIntensity"]
    if "riskFlags" in data:
        state.risk_flags = json.dumps(data["riskFlags"], ensure_ascii=False)

    db.session.commit()
    return jsonify(_serialize_state(state))


@story_state_bp.route("/novels/<int:novel_id>/story-state/auto-detect")
def auto_detect_state(novel_id):
    """Auto-detect arc phase and risks based on current progress."""
    Novel.query.get_or_404(novel_id)
    phase, intensity = _detect_arc_phase(novel_id)

    # Get latest chapter number
    latest = Chapter.query.filter_by(novel_id=novel_id).order_by(
        Chapter.chapter_number.desc()).first()
    chapter_num = latest.chapter_number if latest else 0

    risks = _detect_risks(novel_id, chapter_num)

    # Count foreshadowing stats
    fs_stats = {}
    for status in ["open", "planned", "buried", "advancing", "reclaimable", "resolved", "abandoned"]:
        fs_stats[status] = Foreshadowing.query.filter_by(novel_id=novel_id, status=status).count()

    return jsonify({
        "arcPhase": phase,
        "arcIntensity": intensity,
        "risks": risks,
        "foreshadowStats": fs_stats,
        "totalChapters": chapter_num,
    })


@story_state_bp.route("/novels/<int:novel_id>/story-state/snapshot", methods=["POST"])
def create_snapshot(novel_id):
    """Save a snapshot of the current story state."""
    Novel.query.get_or_404(novel_id)
    state = StoryState.query.filter_by(novel_id=novel_id).first()
    if not state:
        return jsonify({"error": "No story state found"}), 404

    chapter_id = request.form.get("chapter_id", type=int)
    chapter_number = request.form.get("chapter_number", type=int, default=0)
    is_checkpoint = request.form.get("is_checkpoint", "").lower() == "true"

    snapshot = StoryStateSnapshot(
        novel_id=novel_id,
        chapter_id=chapter_id,
        chapter_number=chapter_number,
        state_json=json.dumps(_serialize_state(state), ensure_ascii=False),
        is_checkpoint=is_checkpoint,
    )
    db.session.add(snapshot)
    db.session.commit()

    return jsonify({"ok": True, "snapshotId": snapshot.id})


@story_state_bp.route("/novels/<int:novel_id>/story-state/snapshots")
def list_snapshots(novel_id):
    """List all state snapshots for a novel."""
    snapshots = StoryStateSnapshot.query.filter_by(novel_id=novel_id).order_by(
        StoryStateSnapshot.chapter_number.desc()).all()
    return jsonify([{
        "id": s.id,
        "chapterNumber": s.chapter_number,
        "chapterId": s.chapter_id,
        "isCheckpoint": s.is_checkpoint,
        "state": json.loads(s.state_json or "{}"),
        "createdAt": s.created_at,
    } for s in snapshots])


@story_state_bp.route("/novels/<int:novel_id>/story-state/rollback", methods=["POST"])
def rollback_state(novel_id):
    """Rollback story state to a snapshot."""
    snapshot_id = request.form.get("snapshot_id", type=int)
    if not snapshot_id:
        return jsonify({"error": "missing snapshot_id"}), 400

    # 归属校验：快照必须属于当前小说，防止跨书覆盖状态
    snapshot = StoryStateSnapshot.query.filter_by(id=snapshot_id, novel_id=novel_id).first_or_404()
    state_data = json.loads(snapshot.state_json or "{}")

    state = StoryState.query.filter_by(novel_id=novel_id).first()
    if not state:
        state = StoryState(novel_id=novel_id)
        db.session.add(state)

    state.main_quest = state_data.get("mainQuest", "")
    state.main_quest_progress = state_data.get("mainQuestProgress", "")
    state.active_subplots = json.dumps(state_data.get("activeSubplots", []), ensure_ascii=False)
    state.active_conflicts = json.dumps(state_data.get("activeConflicts", []), ensure_ascii=False)
    state.arc_phase = state_data.get("arcPhase", "setup")
    state.arc_intensity = state_data.get("arcIntensity", 3)
    state.risk_flags = json.dumps(state_data.get("riskFlags", {}), ensure_ascii=False)
    # 完整回滚：恢复快照中已序列化的引擎字段（此前只回滚 7 个主线字段，
    # 导致兴奋度/节奏/章节进度与主线状态时间线错位）
    if "excitementHistory" in state_data:
        state.excitement_history = json.dumps(state_data.get("excitementHistory", []), ensure_ascii=False)
    if "currentExcitementDensity" in state_data:
        state.current_excitement_density = state_data.get("currentExcitementDensity") or 0.0
    if "recentPacing" in state_data:
        state.recent_pacing = json.dumps(state_data.get("recentPacing", []), ensure_ascii=False)
    if "lastExcitementChapter" in state_data:
        state.last_excitement_chapter = state_data.get("lastExcitementChapter")
    if "currentChapter" in state_data:
        state.current_chapter = state_data.get("currentChapter") or 0

    db.session.commit()
    return jsonify({"ok": True, "state": _serialize_state(state)})
