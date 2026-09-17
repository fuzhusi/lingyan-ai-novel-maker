"""人味分校准基建：把检测报告与外部朱雀回填记录落盘，供 LR 对齐。

零 LLM。每次 gate-check / 收敛可选择性调用 record_calibration_point。
样本格式对齐 docs/ai-tone-research.md §六 记录表。
"""
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_CALIB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "calibration")


def _ensure_dir():
    os.makedirs(_CALIB_DIR, exist_ok=True)
    return _CALIB_DIR


def record_calibration_point(source, text_hash, report, zhuque_rate=None,
                             pipeline="", note=""):
    """记录一个校准点（内部人味分 ↔ 外部朱雀 AI 率）。

    Args:
        source: 稿件来源标识（如 short#2 / chapter-12-v3）
        text_hash: 正文 md5 前 12 位（不存全文，保护用户稿件）
        report: analyze_ai_tone 返回的 dict
        zhuque_rate: 朱雀 AI 率（0-100），未测时 None
        pipeline: 处理管线描述
        note: 备注
    """
    _ensure_dir()
    path = os.path.join(_CALIB_DIR, "points.jsonl")
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "text_hash": text_hash,
        "human_score": report.get("human_score"),
        "mode": report.get("mode", "generate"),
        "passed": report.get("passed"),
        "stats": report.get("stats"),
        "risk_counts": {
            "high": sum(1 for c in report.get("checks", []) if c.get("risk") == "high"),
            "mid": sum(1 for c in report.get("checks", []) if c.get("risk") == "mid"),
        },
        "zhuque_ai_rate": zhuque_rate,
        "pipeline": pipeline,
        "note": note,
    }
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except OSError as e:
        logger.warning("校准点写入失败: %s", e)
        return False


def load_calibration_points(min_pairs=0):
    """读取校准点。min_pairs>0 时只返回同时有内部分数与朱雀率的样本。"""
    path = os.path.join(_CALIB_DIR, "points.jsonl")
    if not os.path.isfile(path):
        return []
    points = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                p = json.loads(line)
            except json.JSONDecodeError:
                continue
            if min_pairs and p.get("zhuque_ai_rate") is None:
                continue
            if p.get("human_score") is None:
                continue
            points.append(p)
    return points if min_pairs else points


def summary_stats():
    """校准数据概览（供 CLI/仪表盘）。"""
    all_p = load_calibration_points()
    paired = load_calibration_points(min_pairs=1)
    return {
        "total_points": len(all_p),
        "paired_with_zhuque": len(paired),
        "path": os.path.join(_CALIB_DIR, "points.jsonl"),
        "hint": "攒够 paired≥15 后可做人味分↔朱雀率的逻辑回归对齐",
    }
