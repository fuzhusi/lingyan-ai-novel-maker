"""注入观测层（调研 v2 第 0 步）：17 处知识注入管道的统一清单记录器。

背景：writer_chain 305 行历史注释记录过一次「except 吞 AttributeError 致
注入长期静默失效」的事故。本服务把每次 build_writer_kwargs 的全部注入
维度登记成清单——激活/降级/跳过、字符数、原因——透传到 SSE 进度帧与
章节版本 model_params_json，静默失效永久变可见失效。

红线：纯观测，不改变任何注入行为与 prompt 内容（验收含逐字节对比）。
"""
import json
import logging

logger = logging.getLogger(__name__)

# 参与字符统计的 kw 字段（装配后逐项量体积，零额外计算成本）
_MEASURED_KEYS = (
    "characters", "world_settings", "foreshadowing_items", "summaries",
    "earlier_summaries", "prev_ending", "memory_context", "boundary_context",
    "causal_chain", "narrative_plan", "chapter_events", "reader_known",
    "reflexion_lessons", "reference_passages", "tone_instructions",
    "style_memo", "creator_preferences", "cast_constraint",
)


class InjectionReport:
    """单次写作包构建的注入清单。"""

    def __init__(self):
        self.dims = []

    def ok(self, dim, note=""):
        self.dims.append({"dim": dim, "status": "ok", "note": str(note)[:80]})

    def skip(self, dim, note=""):
        self.dims.append({"dim": dim, "status": "skipped", "note": str(note)[:80]})

    def degrade(self, dim, reason):
        self.dims.append({"dim": dim, "status": "degraded",
                          "note": str(reason)[:120]})
        logger.warning("注入降级 [%s]: %s", dim, reason)

    def finalize(self, kw):
        """装配完成后量体积：已知字段逐项字符数 + 汇总。"""
        sizes = {}
        for key in _MEASURED_KEYS:
            val = kw.get(key)
            if val is None or val == "" or val == []:
                continue
            if isinstance(val, str):
                sizes[key] = len(val)
            else:
                try:
                    # 口径说明：JSON 序列化长度含键名与括号，比 prompt 渲染体积
                    # 偏高；与 apply_context_budget._size() 同口径，横向可比
                    sizes[key] = len(json.dumps(val, ensure_ascii=False))
                except (TypeError, ValueError):
                    sizes[key] = -1
        degraded = [d["dim"] for d in self.dims if d["status"] == "degraded"]
        return {
            "dims": self.dims,
            "sizes": sizes,
            "total_chars": sum(v for v in sizes.values() if v > 0),
            "degraded": degraded,
            "degraded_count": len(degraded),
        }


def empty_report():
    """无报告时的占位（调用方拿不到报告也不必判 None）。"""
    return {"dims": [], "sizes": {}, "total_chars": 0, "degraded": [],
            "degraded_count": 0}
