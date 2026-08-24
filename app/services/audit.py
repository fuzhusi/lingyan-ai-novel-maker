"""Multi-Dimensional Audit System — 17 quality dimensions across 6 audit agents.

Inspired by inkos's 33-dimension system. Runs parallel focused audits instead
of a single vague Critic, each checking a specific quality dimension.

Architecture:
    ┌─────────────────────────────────────────────────────┐
    │              Audit Runner (parallel)                 │
    ├──────────┬──────────┬──────────┬──────────┬─────────┤
    │Character │  Plot    │  World   │ Writing  │ Foreshadow│
    │  Agent   │  Agent   │  Agent   │  Agent   │  Agent   │
    │ 4 dims   │ 4 dims   │ 3 dims   │ 4 dims   │ 2 dims   │
    └──────────┴──────────┴──────────┴──────────┴─────────┘
                        │
                  Aggregator → score + issues + grade
"""
import json
import concurrent.futures
from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError


def _safe_score(value, default=5):
    """把 AI 返回的分数强制转为 float。

    模型可能输出 "8"（字符串）、null、true 等非法值——
    直接参与加权聚合会 TypeError 并炸掉整条审计链路。
    非法值回退中性分 default。
    """
    if isinstance(value, bool) or value is None:
        return default
    try:
        return max(0.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return default

# ---------------------------------------------------------------------------
# Dimension definitions
# ---------------------------------------------------------------------------

DIMENSIONS = {
    # Character (4)
    "personality_consistency": {
        "name": "性格一致性", "group": "character", "weight": 1.2,
        "desc": "角色的性格、价值观、行为模式是否与设定一致",
    },
    "behavior_plausibility": {
        "name": "行为合理性", "group": "character", "weight": 1.0,
        "desc": "角色在当前情境下的行为是否合理可信",
    },
    "dialogue_naturalness": {
        "name": "对话自然度", "group": "character", "weight": 1.0,
        "desc": "对话是否符合角色身份、性格，是否有人物区分度",
    },
    "growth_trajectory": {
        "name": "成长轨迹", "group": "character", "weight": 0.8,
        "desc": "角色发展是否符合预定的弧光方向",
    },
    # Plot (4)
    "logic_coherence": {
        "name": "逻辑连贯性", "group": "plot", "weight": 1.3,
        "desc": "情节逻辑是否自洽，有无矛盾或漏洞",
    },
    "pacing_control": {
        "name": "节奏把控", "group": "plot", "weight": 1.0,
        "desc": "叙事节奏是否合理，有无拖沓或过快",
    },
    "conflict_progression": {
        "name": "冲突推进", "group": "plot", "weight": 1.1,
        "desc": "冲突是否在推进，有无停滞或重复",
    },
    "suspense_management": {
        "name": "悬念管理", "group": "plot", "weight": 0.9,
        "desc": "悬念/钩子是否有效，读者是否有继续阅读的动力",
    },
    # World (3)
    "world_consistency": {
        "name": "世界观一致性", "group": "world", "weight": 1.2,
        "desc": "是否违反已确立的世界观规则、设定",
    },
    "power_balance": {
        "name": "战力/能力平衡", "group": "world", "weight": 1.0,
        "desc": "角色能力是否合理，有无突然飙升或崩坏",
    },
    "timeline_correctness": {
        "name": "时间线正确性", "group": "world", "weight": 0.9,
        "desc": "事件时间顺序是否正确，有无时间矛盾",
    },
    # Writing Quality (4)
    "prose_fluency": {
        "name": "文笔流畅度", "group": "writing", "weight": 1.0,
        "desc": "语言是否流畅自然，有无生硬或堆砌",
    },
    "sensory_richness": {
        "name": "感官描写", "group": "writing", "weight": 0.8,
        "desc": "是否有具体的视觉/听觉/触觉/嗅觉/味觉描写",
    },
    "ai_artifacts": {
        "name": "AI痕迹", "group": "writing", "weight": 1.5,
        "desc": "是否有明显的AI写作特征（套话、模式化、过度修饰）",
    },
    "info_density": {
        "name": "信息密度", "group": "writing", "weight": 0.8,
        "desc": "有效信息量是否充足，有无空洞废话",
    },
    # Foreshadowing (2)
    "foreshadow_progression": {
        "name": "伏笔推进", "group": "foreshadow", "weight": 1.0,
        "desc": "已埋伏笔是否有推进或暗示",
    },
    "foreshadow_resolution": {
        "name": "伏笔回收", "group": "foreshadow", "weight": 1.1,
        "desc": "到期伏笔是否被回收，回收是否自然",
    },
}

# Group dimensions by their audit agent group
GROUPS = {}
for dim_id, dim in DIMENSIONS.items():
    group = dim["group"]
    if group not in GROUPS:
        GROUPS[group] = []
    GROUPS[group].append((dim_id, dim))


# ---------------------------------------------------------------------------
# Audit prompt builders (one per agent group)
# ---------------------------------------------------------------------------

def _build_character_audit_prompt(chapter_content, characters, novel_title):
    dims = GROUPS["character"]
    dim_desc = "\n".join(f"- {d['name']}({d_id}): {d['desc']}" for d_id, d in dims)

    char_lines = []
    for c in (characters or []):
        parts = [f"姓名：{c.get('name', '')}"]
        for field, label in [("personality", "性格"), ("speaking_style", "说话风格"),
                             ("background", "背景"), ("motivation", "动机"),
                             ("arc_direction", "角色弧光")]:
            val = c.get(field, "")
            if val:
                parts.append(f"{label}：{val}")
        char_lines.append("\n".join(parts))

    system = (
        "你是一位角色一致性审计专家。检查小说章节中角色相关的质量问题。\n"
        "严格按JSON格式输出，不要输出其他内容。"
    )
    user = (
        f"小说：{novel_title}\n\n"
        f"【人物设定】\n" + "\n---\n".join(char_lines) + "\n\n"
        f"【章节正文】\n{chapter_content}\n\n"
        f"【检查维度】\n{dim_desc}\n\n"
        "输出格式：\n"
        '{"dimensions": {'
        '"personality_consistency": {"score": 0-10, "issues": ["..."], "suggestions": ["..."]}, '
        '"behavior_plausibility": {"score": 0-10, ...}, ...}, '
        '"summary": "一句话总结"}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _build_plot_audit_prompt(chapter_content, outline, chapter_number, summaries):
    dims = GROUPS["plot"]
    dim_desc = "\n".join(f"- {d['name']}({d_id}): {d['desc']}" for d_id, d in dims)

    prev = ""
    if summaries:
        prev = "【前情提要】\n" + "\n".join(
            f"第{s.get('chapter_number', '?')}章：{s.get('summary', '')}" for s in summaries[-5:]
        )

    system = (
        "你是一位剧情审计专家。检查小说章节的情节质量。\n"
        "严格按JSON格式输出，不要输出其他内容。"
    )
    user = (
        f"第{chapter_number}章\n\n"
        f"【本章大纲】\n{outline}\n\n"
        f"{prev}\n\n"
        f"【章节正文】\n{chapter_content}\n\n"
        f"【检查维度】\n{dim_desc}\n\n"
        "输出格式同上（dimensions + summary）"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _build_world_audit_prompt(chapter_content, world_settings, characters, novel_title):
    dims = GROUPS["world"]
    dim_desc = "\n".join(f"- {d['name']}({d_id}): {d['desc']}" for d_id, d in dims)

    ws_lines = []
    for ws in (world_settings or []):
        ws_lines.append(f"【{ws.get('category', '')} - {ws.get('title', '')}】\n{ws.get('content', '')}")

    system = (
        "你是一位世界观一致性审计专家。检查小说章节是否违反世界观规则。\n"
        "严格按JSON格式输出，不要输出其他内容。"
    )
    user = (
        f"小说：{novel_title}\n\n"
        f"【世界观设定】\n" + "\n\n".join(ws_lines) + "\n\n"
        f"【章节正文】\n{chapter_content}\n\n"
        f"【检查维度】\n{dim_desc}\n\n"
        "输出格式同上（dimensions + summary）"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _build_writing_audit_prompt(chapter_content):
    dims = GROUPS["writing"]
    dim_desc = "\n".join(f"- {d['name']}({d_id}): {d['desc']}" for d_id, d in dims)

    system = (
        "你是一位写作质量审计专家。检查小说章节的文字质量，特别关注AI写作痕迹。\n"
        "AI痕迹检查要点：\n"
        "- 是否有'仿佛''宛如''不禁'等高频AI词\n"
        "- 是否有'他知道/明白/意识到'开头的内心独白\n"
        "- 是否有'眼中闪过''嘴角微微上扬'等模式化描写\n"
        "- 句式是否单调（连续相同句式开头）\n"
        "- 对话是否加了不必要的修饰语（'他沉声道'）\n"
        "- 是否有过度解释（直接告诉读者角色感受而非展示）\n"
        "严格按JSON格式输出，不要输出其他内容。"
    )
    user = (
        f"【章节正文】\n{chapter_content}\n\n"
        f"【检查维度】\n{dim_desc}\n\n"
        "输出格式同上（dimensions + summary）"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _build_foreshadow_audit_prompt(chapter_content, foreshadowing_items, chapter_number):
    dims = GROUPS["foreshadow"]
    dim_desc = "\n".join(f"- {d['name']}({d_id}): {d['desc']}" for d_id, d in dims)

    fs_lines = []
    for f in (foreshadowing_items or []):
        age = chapter_number - f.get("planted_chapter", 0) if f.get("planted_chapter") else 0
        fs_lines.append(
            f"[ID:{f.get('id', '')}] {f.get('description', '')} "
            f"(状态:{f.get('status', 'open')}, 埋设:{f.get('planted_chapter', '?')}章, "
            f"已过:{age}章, 重要度:{f.get('importance', 5)})"
        )

    system = (
        "你是一位伏笔审计专家。检查小说章节中伏笔的推进和回收情况。\n"
        "严格按JSON格式输出，不要输出其他内容。"
    )
    user = (
        f"第{chapter_number}章\n\n"
        f"【活跃伏笔】\n" + "\n".join(fs_lines) + "\n\n"
        f"【章节正文】\n{chapter_content}\n\n"
        f"【检查维度】\n{dim_desc}\n\n"
        "输出格式同上（dimensions + summary）"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ---------------------------------------------------------------------------
# Audit Runner
# ---------------------------------------------------------------------------

def _call_ai(messages, cfg):
    """Non-streaming AI call, returns parsed JSON."""
    try:
        text = call_llm_sync(
            cfg["model_name"], messages,
            cfg["api_key"], cfg["base_url"],
            cfg.get("provider_type", "deepseek"),
            cfg["temperature"], cfg["max_tokens"],
        )
        # Try to extract JSON
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                elif line.startswith("```") and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)
        return json.loads(text)
    except LLMError as e:
        return {"dimensions": {}, "summary": f"审计失败: {e}", "error": str(e)}
    except Exception as e:
        return {"dimensions": {}, "summary": f"审计失败: {e}", "error": str(e)}


def _run_single_audit(group_name, messages, cfg):
    """Run a single audit agent and return its result."""
    result = _call_ai(messages, cfg)
    result["group"] = group_name
    return result


def run_full_audit(chapter_content, outline="", chapter_number=0,
                   characters=None, world_settings=None, summaries=None,
                   foreshadowing_items=None, novel_title="", cfg=None,
                   is_short_story=False):
    """Run all 6 audit agents in parallel and aggregate results.

    Args:
        is_short_story: If True, reduce weight for world-building dimensions
                        (short stories focus on emotion/character, not world-building)

    Returns:
        {
            "overall_score": 8.2,
            "grade": "B+",
            "dimensions": {
                "personality_consistency": {"score": 9, "issues": [], "suggestions": []},
                ...
            },
            "groups": {
                "character": {"score": 8.5, "summary": "..."},
                "plot": {"score": 7.8, "summary": "..."},
                ...
            },
            "issues": [...],  # All issues sorted by severity
            "summary": "..."
        }
    """
    if cfg is None:
        from app.config_utils import get_model_config
        cfg = get_model_config(agent_type="audit")

    # 短篇模式下降低世界观维度权重
    short_story_weight_factor = 0.2 if is_short_story else 1.0

    # Build prompts for each agent group
    agents = [
        ("character", _build_character_audit_prompt(chapter_content, characters, novel_title)),
        ("plot", _build_plot_audit_prompt(chapter_content, outline, chapter_number, summaries)),
        ("world", _build_world_audit_prompt(chapter_content, world_settings, characters, novel_title)),
        ("writing", _build_writing_audit_prompt(chapter_content)),
        ("foreshadow", _build_foreshadow_audit_prompt(chapter_content, foreshadowing_items, chapter_number)),
    ]

    # Run all agents in parallel
    raw_results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_run_single_audit, name, msgs, cfg): name
            for name, msgs in agents
        }
        for future in concurrent.futures.as_completed(futures):
            group_name = futures[future]
            try:
                raw_results[group_name] = future.result()
            except Exception as e:
                raw_results[group_name] = {"dimensions": {}, "summary": f"审计异常: {e}", "error": str(e)}

    # Aggregate results (defensive against malformed AI responses)
    all_dimensions = {}
    group_scores = {}
    all_issues = []

    for group_name, result in raw_results.items():
        dims = result.get("dimensions", {})
        # Handle AI returning list/bool/None instead of dict
        if not isinstance(dims, dict):
            dims = {}
        group_total = 0
        group_count = 0

        for dim_id, dim_def in DIMENSIONS.items():
            if dim_def["group"] != group_name:
                continue
            dim_result = dims.get(dim_id, {})
            # Handle bool/None/list responses from AI (graceful degradation)
            if not isinstance(dim_result, dict):
                dim_result = {}
            score = _safe_score(dim_result.get("score", 5))
            issues = dim_result.get("issues", [])
            suggestions = dim_result.get("suggestions", [])
            if not isinstance(issues, list):
                issues = []
            if not isinstance(suggestions, list):
                suggestions = []

            all_dimensions[dim_id] = {
                "score": score,
                "name": dim_def["name"],
                "group": group_name,
                "weight": dim_def["weight"],
                "issues": issues,
                "suggestions": suggestions,
            }

            group_total += score
            group_count += 1

            for issue in issues:
                all_issues.append({
                    "dimension": dim_id,
                    "dimension_name": dim_def["name"],
                    "group": group_name,
                    "issue": issue,
                    "severity": "high" if score <= 4 else "medium" if score <= 6 else "low",
                })

        group_avg = round(group_total / max(group_count, 1), 1)
        summary = result.get("summary", "") if isinstance(result, dict) else ""
        group_scores[group_name] = {
            "score": group_avg,
            "summary": summary if isinstance(summary, str) else "",
        }

    # Calculate weighted overall score
    # Short stories: reduce weight for world-building dimensions
    total_weighted = 0
    total_weight = 0
    for dim_id, dim_result in all_dimensions.items():
        w = dim_result["weight"]
        # 短篇模式下降低世界观维度权重
        if is_short_story and dim_result.get("group") == "world":
            w *= short_story_weight_factor
        total_weighted += dim_result["score"] * w
        total_weight += w

    overall_score = round(total_weighted / max(total_weight, 1), 1)

    # Assign grade
    if overall_score >= 9:
        grade = "S"
    elif overall_score >= 8:
        grade = "A"
    elif overall_score >= 7:
        grade = "B+"
    elif overall_score >= 6:
        grade = "B"
    elif overall_score >= 5:
        grade = "C"
    else:
        grade = "D"

    # Sort issues by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    all_issues.sort(key=lambda x: severity_order.get(x["severity"], 3))

    # Generate overall summary
    summaries = [f"{g}: {r.get('summary', '')}" for g, r in group_scores.items() if r.get("summary")]

    return {
        "overall_score": overall_score,
        "grade": grade,
        "dimensions": all_dimensions,
        "groups": group_scores,
        "issues": all_issues,
        "total_issues": len(all_issues),
        "high_issues": len([i for i in all_issues if i["severity"] == "high"]),
        "summary": " | ".join(summaries),
    }
