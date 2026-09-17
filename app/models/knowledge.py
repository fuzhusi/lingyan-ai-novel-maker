"""知识库模型：角色、世界观、大纲、伏笔、角色关系。"""
from app.models.base import db, now


class Character(db.Model):
    __tablename__ = "characters"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    personality = db.Column(db.Text, default="")
    speaking_style = db.Column(db.Text, default="")
    appearance = db.Column(db.Text, default="")
    background = db.Column(db.Text, default="")
    motivation = db.Column(db.Text, default="")
    arc_direction = db.Column(db.Text, default="")
    status_json = db.Column(db.Text, default="{}")
    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)

    novel = db.relationship("Novel", backref=db.backref("characters", cascade="all, delete-orphan"))


class WorldSetting(db.Model):
    __tablename__ = "world_settings"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    category = db.Column(db.String(100), default="")
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, default="")
    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)

    novel = db.relationship("Novel", backref=db.backref("world_settings", cascade="all, delete-orphan"))


class OutlineNode(db.Model):
    __tablename__ = "outline_nodes"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("outline_nodes.id"), nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    node_type = db.Column(db.String(20), default="chapter")  # volume, chapter, scene
    title = db.Column(db.String(200), default="")
    summary = db.Column(db.Text, default="")
    created_at = db.Column(db.String(20), default=now)

    novel = db.relationship("Novel", backref=db.backref("outline_nodes", cascade="all, delete-orphan"))
    children = db.relationship("OutlineNode", backref=db.backref("parent", remote_side=[id]),
                               order_by="OutlineNode.sort_order")


class Foreshadowing(db.Model):
    __tablename__ = "foreshadowing"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    title = db.Column(db.String(200), default="")
    description = db.Column(db.Text, default="")
    planted_chapter = db.Column(db.Integer, nullable=True)
    resolve_chapter = db.Column(db.Integer, nullable=True)
    # State machine: planned → buried → advancing → reclaimable → resolved
    # Any state → abandoned
    status = db.Column(db.String(20), default="open")
    importance = db.Column(db.Integer, default=5)
    last_mentioned_chapter = db.Column(db.Integer, nullable=True)
    timeout_threshold = db.Column(db.Integer, default=15)
    notes = db.Column(db.Text, default="")
    # 拆书复刻的计划值（jarvis-write 双锚点：不可提前收 + 预期收）
    earliest_resolve_chapter = db.Column(db.Integer, nullable=True)  # 不可早于此章回收
    expected_resolve_chapter = db.Column(db.Integer, nullable=True)  # 预期回收章（计划值）
    source_event = db.Column(db.Text, default="")   # 拆解锚点原值（事件名，审计回溯）
    evidence = db.Column(db.Text, default="")       # 原书摘要引文（证据制）
    created_at = db.Column(db.String(20), default=now)

    novel = db.relationship("Novel", backref=db.backref("foreshadowing_items", cascade="all, delete-orphan"))


class PendingExtraction(db.Model):
    """抽取待确认队列（merge-assessment A4 / Agent 协同方案 P2）。

    自动抽取的事实先进队列，人工核验采纳后才写回真源——防止错抽污染
    一致性注入。kind: "truth"（时序真相）；后续 causal_chain 等接入复用。
    """
    __tablename__ = "pending_extractions"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    kind = db.Column(db.String(20), default="truth")
    payload_json = db.Column(db.Text, default="{}")
    chapter_number = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), default="pending")  # pending/adopted/discarded
    created_at = db.Column(db.String(20), default=now)

    novel = db.relationship("Novel", backref=db.backref("pending_extractions", cascade="all, delete-orphan"))


class CharacterRelation(db.Model):
    """Multi-dimensional character relationship with dynamic evolution."""
    __tablename__ = "character_relations"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    character_a_id = db.Column(db.Integer, db.ForeignKey("characters.id"), nullable=False)
    character_b_id = db.Column(db.Integer, db.ForeignKey("characters.id"), nullable=False)
    relation_type = db.Column(db.String(50), default="ordinary")
    description = db.Column(db.Text, default="")
    # Multi-dimensional scores (0-100)
    trust = db.Column(db.Integer, default=50)
    affection = db.Column(db.Integer, default=50)
    respect = db.Column(db.Integer, default=50)
    fear = db.Column(db.Integer, default=0)
    dependency = db.Column(db.Integer, default=50)
    status = db.Column(db.String(20), default="active")
    start_chapter = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)

    novel = db.relationship("Novel", backref=db.backref("character_relations", cascade="all, delete-orphan"))
    character_a = db.relationship("Character", foreign_keys=[character_a_id], backref="relations_as_a")
    character_b = db.relationship("Character", foreign_keys=[character_b_id], backref="relations_as_b")

    __table_args__ = (
        db.UniqueConstraint("character_a_id", "character_b_id", name="uq_char_relation"),
    )

    @property
    def overall_score(self):
        """Weighted relationship score."""
        return (self.trust * 0.3 + self.affection * 0.25 +
                self.respect * 0.2 + (100 - self.fear) * 0.15 +
                self.dependency * 0.1)

    @property
    def auto_relation_type(self):
        """Auto-detect relation type from scores."""
        if self.affection > 80 and self.trust > 70:
            return "恋人/挚友"
        if self.trust > 70 and self.respect > 60:
            return "好友"
        if self.fear > 70 and self.respect < 30:
            return "畏惧/仇恨"
        if self.dependency > 70 and self.trust > 60:
            return "依赖/师徒"
        if self.trust < 30 and self.affection < 30:
            return "敌对"
        return "普通"


class ReaderKnowledge(db.Model):
    """读者已知时间线（oh-story 双真相：作者真相 vs 读者已知）。

    与 info_boundary（角色视角「谁知道什么」）互补：
    本表追踪「已经向读者揭示」的设定/反转，供双盲审检查
    视角正确性（角色是否说出读者还不该知道的话；悬念是否被过早戳破）。
    """
    __tablename__ = "reader_knowledge"
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey("novels.id"), nullable=False)
    chapter_number = db.Column(db.Integer, nullable=False)  # 揭示章节
    kind = db.Column(db.String(20), default="reveal")  # setting / reveal / secret / character
    content = db.Column(db.Text, nullable=False)
    # public=读者已明确知道；foreshadowed=已暗示未明说；planted=作者埋了读者还不知道
    reader_state = db.Column(db.String(20), default="public")
    created_at = db.Column(db.String(20), default=now)

    novel = db.relationship("Novel", backref=db.backref("reader_knowledge", cascade="all, delete-orphan"))
