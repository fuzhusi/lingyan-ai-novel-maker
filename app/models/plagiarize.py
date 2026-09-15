"""拆书复刻模块模型：对标书整本拆解 → 待确认条目 → 采纳入库。

旧版 style/plot/rewrite（风格模仿/情节借鉴/三档洗稿）已由拆书复刻覆盖并下线，
旧任务数据保留但 Web/CLI 不再提供操作入口。
"""
import json

from app.models.base import db, now


class PlagiarizeTask(db.Model):
    """拆书任务"""
    __tablename__ = "plagiarize_tasks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), default="")       # 对标书名
    mode = db.Column(db.String(20), nullable=False, default="deconstruct")  # deconstruct / 旧值 style|plot|rewrite

    # 来源
    source_text = db.Column(db.Text, default="")       # 对标书全文
    source_filename = db.Column(db.String(200), default="")  # 上传的文件名
    source_type = db.Column(db.String(20), default="paste")  # paste / upload
    source_chapter_id = db.Column(db.Integer, nullable=True)  # 来源章节ID
    source_short_story_id = db.Column(db.Integer, nullable=True)  # 来源短篇ID

    # 目标（复刻落地）
    target_novel_id = db.Column(db.Integer, nullable=True)   # 目标小说ID（长篇）
    target_short_story_id = db.Column(db.Integer, nullable=True)  # 目标短篇ID

    # 拆书产物
    report_text = db.Column(db.Text, default="")        # 全案拆解报告（可读可编辑 Markdown）
    elements_json = db.Column(db.Text, default="[]")    # 六维拆解产物 JSON
    chapters_summary_json = db.Column(db.Text, default="[]")  # L1 逐章摘要压缩
    volumes_summary_json = db.Column(db.Text, default="[]")   # L2 卷级归并摘要
    modifications_text = db.Column(db.Text, default="")  # 微创新指令（题材/金手指/人物调整等）
    axes_text = db.Column(db.Text, default="")   # 差异轴（主角类型×冲突来源×情绪基调，批量改写时生成）

    # 旧字段兼容（旧 style/plot/rewrite 任务数据保留）
    rewrite_level = db.Column(db.String(10), default="medium")  # light/medium/heavy
    extra_instructions = db.Column(db.Text, default="")
    style_report = db.Column(db.Text, default="")
    result_content = db.Column(db.Text, default="")
    result_chapter_id = db.Column(db.Integer, nullable=True)

    # 状态
    status = db.Column(db.String(20), default="pending")  # pending/summarizing/deconstructing/done/failed
    error_message = db.Column(db.Text, default="")

    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)

    # 待确认条目（删除任务级联删除）
    items = db.relationship("DeconstructItem", back_populates="task",
                            cascade="all, delete-orphan", order_by="DeconstructItem.id")


class DeconstructItem(db.Model):
    """拆书待确认条目 —— 拆解产物先进队列，逐条人工核验/修改后采纳入库。

    错拆不污染知识库（与 PendingExtraction 抽取待确认队列同思路）。
    kind: character / world / outline
    status: pending / adopted / discarded
    """
    __tablename__ = "deconstruct_items"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("plagiarize_tasks.id"), nullable=False)
    kind = db.Column(db.String(20), nullable=False)  # character / world / outline
    title = db.Column(db.String(200), default="")
    content_json = db.Column(db.Text, default="{}")   # 拆解原稿（结构化字段）
    modified_content = db.Column(db.Text, default="")  # 用户修改稿（JSON）
    status = db.Column(db.String(20), default="pending")  # pending/adopted/discarded
    target_id = db.Column(db.Integer, nullable=True)  # 采纳后知识库实体 id
    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)

    task = db.relationship("PlagiarizeTask", back_populates="items")

    @property
    def content(self):
        """拆解原稿 dict（解析失败返回空 dict）。"""
        try:
            data = json.loads(self.content_json or "{}")
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    @property
    def display_data(self):
        """UI 展示用：用户修改稿优先，否则拆解原稿。"""
        if self.modified_content and self.modified_content.strip():
            try:
                data = json.loads(self.modified_content)
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, TypeError):
                pass
        return self.content
