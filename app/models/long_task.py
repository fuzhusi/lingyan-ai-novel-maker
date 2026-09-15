"""进程内长任务:任务表即队列(单用户单机,无需外部队列)。

长管线(拆书/整本复刻/批量改写)脱离 HTTP 请求生命周期:
后台线程执行,进度落库,前端轮询;进程重启时由启动恢复置为可重试的失败态。
"""
from app.models.base import db, now


class LongTask(db.Model):
    __tablename__ = "long_tasks"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(40), nullable=False)   # deconstruct / generate_long / rework_all
    ref_id = db.Column(db.Integer, nullable=True)     # 关联业务对象(如 plagiarize_tasks.id)
    status = db.Column(db.String(20), default="running")  # running / done / failed / cancelled
    cancel_requested = db.Column(db.Boolean, default=False)  # 协作式取消:执行循环分批检查
    progress = db.Column(db.Text, default="")         # 追加式进度日志(保留尾部)
    result = db.Column(db.Text, default="")           # 完成标记(如 [NOVEL_ID: n])
    error = db.Column(db.Text, default="")
    created_at = db.Column(db.String(20), default=now)
    updated_at = db.Column(db.String(20), default=now, onupdate=now)
