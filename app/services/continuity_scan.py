"""跨章连续性扫描（调研 2026-10-03 转正）：钩子接住率与张力连续性的 LLM 批读。

origin: .tmp-writing/continuity_scan.py（跑数据找问题阶段验证过 26 对样本）。
定位：观测工具（advisory）。改道率 >50% 或断裂（连续性≤2）>20% 时在输出中报警。
"""
import json
import os

from app.models import Chapter
from app.config_utils import get_model_config
from app.services.llm import call_llm_auto

_SYSTEM = (
    "你是连载小说的连续性分析员。对每对【本章结尾】→【下一章开头】，输出 JSON：\n"
    '{"ending_type": "事件钩|情绪收|冲突结清|悬置", '
    '"ending_summary": "本章结尾时未决/刚发生的事，一句话", '
    '"catch": "接住|改道|无视", '
    '"catch_evidence": "下章开头承接它的具体证据或为什么判定无视", '
    '"tension_continuity": 1-5整数（1=完全断裂，5=无缝续接）}\n'
    "判定口径：事件钩=章尾发生外部事件/决定；冲突结清=本章矛盾当场了结且无新开；"
    "接住=下一章开头直接延续该事件或其后果；改道=提及但转向新事件；无视=完全不见。"
    "只输出一个 JSON 对象。"
)

_ALERT_REROUTE = 0.5
_ALERT_BREAK = 0.2


def scan_novel(novel_id, samples_limit=0):
    """扫描全书相邻章对。返回统计 dict；逐对结果写 data/calibration/。"""
    cfg = get_model_config(agent_type="summary")
    chapters = (Chapter.query.filter_by(novel_id=novel_id)
                .order_by(Chapter.chapter_number).all())
    by_num = {c.chapter_number: c for c in chapters}
    max_num = max(by_num) if by_num else 0

    out_path = os.path.join("data", "calibration",
                            f"continuity_novel{novel_id}.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    done = set()
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["from_chapter"])
                except (ValueError, KeyError):
                    continue

    pairs = []
    for num in range(1, max_num):
        if num in done:
            continue
        cur, nxt = by_num.get(num), by_num.get(num + 1)
        if not cur or not cur.versions:
            continue
        cur_tail = (cur.versions[-1].content or "")[-800:]
        if len(cur_tail) < 200:
            continue
        if nxt and nxt.versions:
            head, kind = (nxt.versions[-1].content or "")[:800], "正文"
        elif nxt:
            head, kind = (nxt.outline or "")[:800], "大纲"
        else:
            continue
        pairs.append((num, cur_tail, head, kind))
        if samples_limit and len(pairs) >= samples_limit:
            break

    stats = {}
    catches = {}
    conts = []
    with open(out_path, "a", encoding="utf-8") as f:
        for num, tail, head, kind in pairs:
            user = (f"【本章（第{num}章）结尾 800 字】\n{tail}\n\n"
                    f"【下一章开头（{kind}）】\n{head}\n\n请分析。")
            try:
                out = call_llm_auto(
                    model=cfg["model_name"],
                    messages=[{"role": "system", "content": _SYSTEM},
                              {"role": "user", "content": user}],
                    api_key=cfg.get("api_key", ""),
                    base_url=cfg.get("base_url", ""),
                    provider_type=cfg.get("provider_type", "deepseek"),
                    temperature=0.2, max_tokens=500,
                    timeout=cfg.get("timeout") or 300)
            except Exception as e:
                print(f"  章{num}→{num + 1} 调用失败，跳过: {str(e)[:80]}")
                continue
            raw = out.strip()
            try:
                parsed = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
            except (ValueError, Exception):
                print(f"  章{num}→{num + 1} 解析失败: {raw[:80]}")
                continue
            parsed["from_chapter"] = num
            parsed["next_kind"] = kind
            f.write(json.dumps(parsed, ensure_ascii=False) + "\n")
            f.flush()
            stats[parsed.get("ending_type")] = stats.get(parsed.get("ending_type"), 0) + 1
            catches[parsed.get("catch")] = catches.get(parsed.get("catch"), 0) + 1
            if isinstance(parsed.get("tension_continuity"), int):
                conts.append(parsed["tension_continuity"])
            print(f"  章{num}→{num + 1}: {parsed.get('ending_type')} / "
                  f"{parsed.get('catch')} / 连续性 {parsed.get('tension_continuity')}")

    total = sum(stats.values())
    reroute = catches.get("改道", 0)
    ignore = catches.get("无视", 0)
    summary = {"pairs": total, "ending_types": stats, "catches": catches,
               "continuity_avg": round(sum(conts) / len(conts), 2) if conts else None,
               "broken": sum(1 for c in conts if c <= 2),
               "alert": None}
    if total:
        if (reroute + ignore) / total > _ALERT_REROUTE:
            summary["alert"] = ("钩子改道/无视率超过 50%：下章开头对上章钩子的承接不足，"
                                "检查大纲生成是否缺上一章结尾上下文")
        broken_ratio = summary["broken"] / len(conts) if conts else 0
        if conts and broken_ratio > _ALERT_BREAK:
            summary["alert"] = (summary["alert"] or "") + \
                f" 张力断裂（≤2）占 {broken_ratio:.0%}"
    return summary
