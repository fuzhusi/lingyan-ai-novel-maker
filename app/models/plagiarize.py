"""抄袭/借鉴模块模型：风格模仿、情节借鉴、改写洗稿。"""
from app.models.base import db, now


class PlagiarizeTask(db.Model):
    """抄袭/借鉴任务"""
    __tablename__ = "plagiarize_tasks"
    
    id = db.Column(db.Integer, primary_key=True)
    mode = db.Column(db.String(20), nullable=False)  # "style" / "plot" / "rewrite"
    
    # 来源
    source_text = db.Column(db.Text, default="")       # 参考原文
    source_filename = db.Column(db.String(200), default="")  # 上传的文件名
    source_chapter_id = db.Column(db.Integer, nullable=True)  # 来源章节ID
    source_short_story_id = db.Column(db.Integer, nullable=True)  # 来源短篇ID
    
    # 目标
    target_novel_id = db.Column(db.Integer, nullable=True)   # 目标小说ID（长篇）
    target_short_story_id = db.Column(db.Integer, nullable=True)  # 目标短篇ID
    
    # 配置
    rewrite_level = db.Column(db.String(10), default="medium")  # light/medium/heavy
    extra_instructions = db.Column(db.Text, default="")
    
    # 风格分析报告
    style_report = db.Column(db.Text, default="")
    
    # 结果
    result_content = db.Column(db.Text, default="")  # 生成的内容
    result_chapter_id = db.Column(db.Integer, nullable=True)  # 生成的章节ID
    
    # 状态
    status = db.Column(db.String(20), default="pending")  # pending/generating/done/failed
    error_message = db.Column(db.Text, default="")
    
    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now)
