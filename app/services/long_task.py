"""进程内长任务执行器(P0-3):任务表即队列,不需要外部队列。

- 后台 daemon 线程消费生成器,进度追加落库,前端轮询
- 调用方先做业务守卫与原子认领(P0-6),再 start_long_task
- 进程重启:启动恢复(_recover_stale_states)把 running 置为可重试的失败态
"""
import re
import threading

from flask import current_app

from app.models import db
from app.models.long_task import LongTask

_MAX_PROGRESS_CHARS = 20000
_RESULT_MARKER = re.compile(r"\[NOVEL_ID: (\d+)\]")


def has_running(kind, ref_id):
    """同 kind+对象已有进行中任务则拒绝重复发起(双开标签页守卫)。"""
    return LongTask.query.filter_by(kind=kind, ref_id=ref_id, status="running").first() is not None


def _cancel_requested(task_id):
    """协作式取消检查:每次 flush 后用独立查询读取最新标志。"""
    return bool(db.session.query(LongTask.cancel_requested).filter_by(id=task_id).scalar())


def cancel_task(lt_id):
    """请求取消一个进行中的长任务(协作式:生成循环在最近的批次边界停止)。"""
    t = db.session.get(LongTask, lt_id)
    if not t:
        return False, "任务不存在"
    if t.status != "running":
        return False, "任务已结束，无需取消"
    t.cancel_requested = True
    db.session.commit()
    return True, "已请求取消，正在等待当前批次完成"


def start_long_task(kind, ref_id, gen_fn):
    """启动后台线程消费生成器。gen_fn: 零参 callable,返回 yield 进度文本的生成器。"""
    task = LongTask(kind=kind, ref_id=ref_id, status="running")
    db.session.add(task)
    db.session.commit()
    task_id = task.id
    app = current_app._get_current_object()

    def _run():
        with app.app_context():
            t = db.session.get(LongTask, task_id)
            gen = gen_fn()
            buf = []
            cancelled = False

            def flush():
                nonlocal buf
                if buf:
                    t.progress = ((t.progress or "") + "".join(buf))[-_MAX_PROGRESS_CHARS:]
                    db.session.commit()
                    buf = []

            try:
                for chunk in gen:
                    buf.append(chunk)
                    if len(buf) >= 10:
                        flush()
                        if _cancel_requested(task_id):
                            cancelled = True
                            break
                flush()
                if cancelled:
                    t.status = "cancelled"
                    db.session.commit()
                    gen.close()  # 触发生成器的中断清理(如拆书任务状态回写)
                    if kind == "deconstruct" and ref_id:
                        try:
                            from app.services.book_deconstruct import _set_status
                            _set_status(ref_id, "pending", "已取消（已完成的摘要保留，可重新拆书）")
                        except Exception:
                            pass
                    return
                t.status = "done"
                m = _RESULT_MARKER.search(t.progress or "")
                if m:
                    t.result = m.group(1)
                db.session.commit()
            except Exception as e:
                buf.append(f"[任务失败: {e}]")
                flush()
                t.status = "failed"
                t.error = str(e)[:500]
                db.session.commit()

    threading.Thread(target=_run, daemon=True, name=f"longtask-{kind}-{task_id}").start()
    return task


def task_progress(task_id):
    """轮询接口的数据源。返回 dict 或 None。"""
    t = db.session.get(LongTask, task_id)
    if not t:
        return None
    return {
        "id": t.id,
        "kind": t.kind,
        "status": t.status,
        "progress": t.progress or "",
        "result": t.result or "",
        "error": t.error or "",
    }
