"""写作链公共层（P3/P4）——generate_stream 与 chapter_runner 的单一实现。

写作包契约（WritingPacket，docs/agent-collaboration.md §3.1）：
    build_writer_kwargs() 是写作链唯一取料入口——上下文组装、预算压缩、
    文风锚例、罗盘、tone 指令、风格备忘录、偏好档案全部在此汇合，
    任何新增注入维度只改这一处，禁止调用方各自拼 prompt。
"""
import json
import logging
import re
import time

from app import db
from app.models import Novel, Setting
from app.config_utils import get_effective_config
from app.services.llm import stream_llm_tokens, LLMError
from app.services.prompt_builder import (
    assemble_chapter_context, apply_context_budget,
)
from app.services.tension_bus import (  # 张力总线：仅依赖 logging/re，无循环
    parse_scene_beats, parse_outline_field, chapter_tension, beat_tensions,
    tension_directive, temperature_for_level,
)

logger = logging.getLogger(__name__)

# 章节字数保障：目标约 2500 字，低于底线自动续写补足（对齐短篇的续写模式）
CHAPTER_WORD_TARGET = 2500
CHAPTER_WORD_FLOOR = 2000
CHAPTER_MAX_CONTINUE_ROUNDS = 3


def build_writer_kwargs(novel_id, chapter_number, outline,
                        user_directive="", character_ids=None):
    """组装写作包 kw（供 build_writer_prompt(**kw)）。

    Returns:
        (kw, novel)；novel_id/chapter_number 缺失时返回 ({}, None)。
    """
    if not (novel_id and chapter_number):
        return {}, None

    novel = Novel.query.get(novel_id)

    # 出场角色勾选（前端角色库勾选区）：逗号分隔的角色 id
    # None/缺省 = 全部角色（兼容旧流程与 MCP）；显式空串 = 不注入任何角色档案
    kw = {}
    ctx = assemble_chapter_context(novel_id, chapter_number, db,
                                   character_ids=character_ids)
    kw = {
        "characters": ctx["characters"],
        "world_settings": ctx["world_settings"],
        "summaries": ctx["summaries"],
        "earlier_summaries": ctx["earlier_summaries"],
        "prev_ending": ctx["prev_ending"],
        "foreshadowing_items": ctx["foreshadowing_items"],
        "synopsis": ctx["synopsis"],
        "world_intro": ctx["world_intro"],
        "genre": ctx["genre"],
        "outline_node_context": ctx["outline_node_context"],
        "next_chapter_brief": ctx.get("next_chapter_brief", ""),
        "author_intent": ctx["author_intent"],
        "current_focus": ctx["current_focus"],
    }

    # 伏笔窗口过滤（writer 侧）：只保留「本章能惦记或该还账」的伏笔——
    # 到期/逾期（expected ∈ [n-3, ∞) 的债务侧）或本章前后 3 章内到期；
    # 远期排程（如第 1 章看到第 41 章才收的线）对写正文是纯噪音，
    # 且与叙事计划块的 must_payoff 硬任务重复。无日期且非新埋的也让路。
    # 大纲生成不受影响（规划需要全量伏笔地图）。
    try:
        windowed = []
        for f in kw["foreshadowing_items"]:
            expected = f.get("expected_chapter")
            planted = f.get("planted_chapter")
            if expected is None:
                # 无排程日期：埋设点（planted）落在 [n-5, n+3] 才注入——
                # 本章/临近要埋的必须知道，刚埋不久的别忘；远期埋设
                # （拆书蓝图常见：planted 是未来章号）对写正文是噪音。
                # 高重要度（importance≥4）的无日期伏笔兜底保留：
                # 长线无排程伏笔恰是最易被踩穿的（code review P1）。
                if (planted is None
                        or (chapter_number - 5 <= planted <= chapter_number + 3)
                        or (f.get("importance") or 0) >= 4):
                    windowed.append(f)
                continue
            if expected <= chapter_number + 3:
                # 到期（==n）、逾期（<n，债务）或临近（≤n+3）
                windowed.append(f)
        dropped = len(kw["foreshadowing_items"]) - len(windowed)
        if dropped:
            logger.info("伏笔窗口过滤：保留 %d/%d 条（远期排程 %d 条不注入正文）",
                        len(windowed), len(kw["foreshadowing_items"]), dropped)
        kw["foreshadowing_items"] = windowed
    except Exception as exc:
        logger.warning("writer_chain 伏笔窗口过滤降级: %s", exc)

    # 出场角色默认按大纲【出场人物】过滤（确定性，零嵌入依赖）：
    # 语义选角色的兜底是"全量注入"，实体嵌入未建时会退回全部档案
    # （实测一书 7 份完整档案全进 prompt，本章只出场 3 人）。大纲名册
    # 是作者/大纲链路钦点的出场安排，作为缺省过滤源比"全部"更贴近
    # 本意；用户显式勾选（character_ids 非 None）时仍以勾选为准。
    if character_ids is None:
        try:
            roster_text = parse_outline_field(outline, "出场人物")
            if roster_text:
                names = [n.strip() for n in re.split(r"[、,，/]", roster_text)
                         if n.strip() and "龙套" not in n and "路人" not in n]
                if names:
                    matched = [c for c in kw["characters"]
                               if any(n in (c.get("name") or "") or (c.get("name") or "") in n
                                      for n in names)]
                    if matched and len(matched) < len(kw["characters"]):
                        logger.info("出场角色按大纲名册过滤：%d/%d 份档案注入",
                                    len(matched), len(kw["characters"]))
                        kw["characters"] = matched
        except Exception as exc:
            logger.warning("writer_chain 大纲名册过滤降级: %s", exc)

    # 出场角色硬约束（用户显式勾选时）：勾选语义不只是"注入谁的档案"，
    # 还要明确告诉模型"只许这些人登场"——否则未勾选角色会经由叙事计划
    # 排程点名、前章结尾、摘要/记忆检索等通道乱入正文。
    # None/缺省（MCP/旧流程）= 全部角色，不加约束。
    if character_ids is not None:
        allowed_names = [c.get("name", "") for c in ctx["characters"] if c.get("name")]
        if allowed_names:
            kw["cast_constraint"] = (
                "本章只允许以下角色登场并获得戏份：" + "、".join(allowed_names) + "。"
                "未列入的角色一律不得在本章出场、不得获得台词或推进其剧情；"
                "上一章结尾与前情提要中提及的其他人物仅作背景交代，"
                "不新增其出场与戏份。"
            )
        else:
            # ctx["characters"] 已按勾选过滤，不能当"无角色卡"的判据——
            # 查全书是否真的一张卡都没有（冷启动）
            from app.models import Character
            has_cards = (db.session.query(Character.id)
                         .filter_by(novel_id=novel_id).first() is not None)
            if not has_cards:
                # 冷启动：大纲的【出场人物】名册仍会点名角色，禁具名与名册
                # 正面矛盾；改按大纲处理，只禁大纲外新角色。
                kw["cast_constraint"] = (
                    "本书暂无人物档案：登场人物按本章大纲【出场人物】与节拍处理，"
                    "不得引入大纲之外的具名新角色。"
                )
            else:
                kw["cast_constraint"] = (
                    "本章未勾选任何角色档案：不要让任何具名角色登场或获得台词，"
                    "只写环境、氛围与叙事者视角的场景推进"
                    "（前文已确立人物至多作背景性提及，不新增戏份）。"
                )

    # Causal chain context from previous chapters
    try:
        from app.services.causal_chain import get_chain_context, format_chain_for_prompt
        chains = get_chain_context(novel_id, chapter_number)
        kw["causal_chain"] = format_chain_for_prompt(chains)
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

    # Vector memory context
    try:
        from app.services.vector_memory import build_context_for_chapter
        kw["memory_context"] = build_context_for_chapter(novel_id, chapter_number, outline)
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

    # 叙事计划块(拆书蓝图计划值):must_payoff 伏笔/禁埋令/本章登场退场角色。
    # 小块(~几百字),不参与预算压缩——排程任务是硬约束。
    # 登场/退场排程按出场白名单过滤：显式勾选时,拆书排程不能点名未勾选角色。
    try:
        from app.services.narrative_plan import build_plan_block
        allowed = None
        if character_ids is not None:
            allowed = [c.get("name") for c in ctx["characters"] if c.get("name")]
        kw["narrative_plan"] = build_plan_block(novel_id, chapter_number,
                                                allowed_names=allowed)
    except Exception as exc:
        logger.warning("writer_chain 计划块注入降级: %s", exc)

    # 本章事件清单（StoryWriter planning 层）：已有则注入，没有则从大纲现提
    try:
        from app.services.chapter_events import ensure_event_plan, format_events_block
        cfg_e = get_effective_config(novel, agent_type="outline")
        events = ensure_event_plan(novel_id, chapter_number, outline=outline, cfg=cfg_e)
        block = format_events_block(events)
        if block:
            kw["chapter_events"] = block
    except Exception as exc:
        logger.warning("writer_chain 事件清单注入降级: %s", exc)

    # 读者已知时间线（oh-story 双真相）：只注入本章之前已揭示的事实，
    # 帮助 writer 知道哪些不用重讲、哪些可作戏剧反讽
    try:
        from app.services.reader_knowledge import build_reader_context
        rk = build_reader_context(novel_id, before_chapter=chapter_number, limit=15)
        if rk:
            kw["reader_known"] = rk
    except Exception as exc:
        logger.warning("writer_chain 读者已知注入降级: %s", exc)

    # 跨章 Reflexion：最近几章的收敛失败/弃稿教训，主动避开
    try:
        from app.services.reflexion import collect_recent_lessons
        lessons = collect_recent_lessons(novel_id, chapter_number)
        if lessons:
            kw["reflexion_lessons"] = lessons
    except Exception as exc:
        logger.warning("writer_chain Reflexion 注入降级: %s", exc)

    # 语义检索(资源库):用本章大纲向量检索对标书相关片段,注入"原书写法参考"。
    # 只取 top-3、每条截 300 字(~900 字),不挤占主上下文预算。
    try:
        from app.services.resource_service import semantic_search
        hits = semantic_search(outline or "", novel_id=novel_id, top_k=3)
        if hits:
            ref_lines = [f"- {h['title']}（{h['resource_title']}）：{h['content'][:200]}"
                         for h in hits if h["score"] > 0.3]
            if ref_lines:
                kw["reference_passages"] = "\n".join(ref_lines)
    except Exception as exc:
        logger.warning("writer_chain 语义检索降级: %s", exc)

    # 语义选角色/设定(实体嵌入):用本章大纲+前文尾部检索相关实体,
    # 替代"全量注入→压缩"——只注入语义相关的 top-K 角色/世界观。
    # 保底：语义结果为空或过滤后为空时回退全量（不让检索失败变成零上下文）。
    # 用户显式勾选了出场角色（character_ids 非 None）时跳过角色侧剪枝——
    # 勾选是作者对本章人物的有意安排，不能被语义 top-K 静默裁掉。
    try:
        from app.services.semantic_service import select_relevant_entities
        # 检索 query 用【场景节拍】而非大纲整段：节拍是"地点+人物+动作"的
        # 实体密集短句，嵌入质量远高于叙事性长文（ANG 检索词生成思想的确定性版，
        # 零额外 LLM 调用）；无节拍的旧格式大纲回退全文
        m = re.search(r"【场景节拍】(.+?)(?=\n【|$)", outline or "", re.S)
        query_text = (m.group(1).strip() if m else (outline or ""))
        selected = select_relevant_entities(
            novel_id, query_text, (ctx.get("prev_ending") or "")[-500:], top_k=5)
        if selected["character_ids"] and character_ids is None:
            char_ids = set(selected["character_ids"])
            filtered_chars = [c for c in kw["characters"] if c.get("id") in char_ids]
            if filtered_chars:
                kw["characters"] = filtered_chars
        if selected["world_ids"]:
            world_ids = set(selected["world_ids"])
            filtered_world = [w for w in kw["world_settings"] if w.get("id") in world_ids]
            if filtered_world:
                kw["world_settings"] = filtered_world
    except Exception as exc:
        logger.warning("writer_chain 语义选角色降级(回退全量): %s", exc)

    # 信息边界 + 时序真相（一致性红线）：独立字段而非拼进 memory_context，
    boundary_parts = []
    try:
        from app.services.info_boundary import format_knowledge_boundaries
        boundary_ctx = format_knowledge_boundaries(novel_id, chapter_number)
        if boundary_ctx:
            boundary_parts.append(boundary_ctx)
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)
    try:
        from app.services.temporal_truth import format_truths_for_prompt
        truth_ctx = format_truths_for_prompt(novel_id, chapter_number)
        if truth_ctx:
            boundary_parts.append(truth_ctx)
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)
    if boundary_parts:
        kw["boundary_context"] = "\n\n".join(boundary_parts)

    # 上下文预算渐进压缩：必须在文风锚例注入之前执行（锚例豁免预算）
    try:
        shrink_log = apply_context_budget(kw)
        if shrink_log:
            logger.info("context budget shrink: %s", shrink_log)
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

    # Style fingerprint（注入顺序在预算压缩之后：风格上下文豁免预算）
    try:
        from app.services.style_fingerprint import (
            load_style, format_style_for_prompt, format_anchor_for_prompt)
        style = load_style()
        if style:
            style_ctx = format_style_for_prompt(style)
            if style_ctx:
                existing = kw.get("memory_context", "")
                kw["memory_context"] = (existing + "\n\n" + style_ctx).strip()
        anchor_ctx = format_anchor_for_prompt()
        if anchor_ctx:
            existing = kw.get("memory_context", "")
            kw["memory_context"] = (existing + "\n\n" + anchor_ctx).strip()
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

    # 行文指纹修正指令：基于近期章节正文的 AI 痕迹检测（降 AI 率闭环）
    try:
        from app.models import Chapter as ChapterModel
        from app.services.ai_metric import build_tone_instructions
        recent = (ChapterModel.query
                  .filter(ChapterModel.novel_id == novel_id,
                          ChapterModel.chapter_number < chapter_number)
                  .order_by(ChapterModel.chapter_number.desc())
                  .limit(2).all())
        # 正文在 ChapterVersion 上，Chapter 本身没有 content 字段（旧写法恒抛
        # AttributeError 被 except 吞掉，该注入长期静默失效）。取每章最新版本。
        sample_text = "\n\n".join(
            (ch.versions[-1].content or "") for ch in reversed(recent) if ch.versions)
        if len(sample_text.strip()) >= 500:
            tone_inst = build_tone_instructions(sample_text[-15000:])
            if tone_inst:
                kw["tone_instructions"] = tone_inst
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

    # P4 风格备忘录（B3）：审批时逐章累积的文体要点，注入最近 3 条
    try:
        memos = json.loads(novel.style_memo_json or "[]") if novel else []
        recent = [m.get("note", "") for m in (memos or [])[-3:]
                  if isinstance(m, dict) and m.get("note")]
        if recent:
            kw["style_memo"] = "\n".join(f"- {m}" for m in recent)
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

    # P4 创作偏好档案：结构化的文风/禁忌/受众长期约束
    try:
        pref = Setting.query.get("creator_preferences")
        if pref and (pref.value or "").strip():
            kw["creator_preferences"] = pref.value.strip()
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

    return kw, novel


def _round_tokens(messages, cfg, max_tokens, collected, on_event=None,
                  round_no=1):
    """单轮生成的原始 token 流（附带续写循环共用的收集器）。

    on_event: 可选回调，接收阶段事件 dict（轮次起止/首字延迟），供 SSE
    进度帧与编排器日志使用。回调异常一律吞掉，绝不影响生成主链路。
    """
    started = time.time()
    first_at = None

    def _emit(ev):
        if on_event is None:
            return
        try:
            on_event(ev)
        except Exception:
            pass

    _emit({"stage": "round_start", "round": round_no})
    try:
        for token in stream_llm_tokens(
            model=cfg["model_name"], messages=messages,
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg.get("temperature", 0.8),
            max_tokens=max_tokens,
            frequency_penalty=cfg.get("frequency_penalty"),
            presence_penalty=cfg.get("presence_penalty"),
            timeout=cfg.get("timeout", 300.0),
        ):
            if first_at is None:
                first_at = time.time()
                _emit({"stage": "first_token", "round": round_no,
                       "ttft_s": round(first_at - started, 1),
                       "model": cfg.get("model_name", ""),
                       "provider": cfg.get("provider_type", "")})
            collected.append(token)
            yield token
    finally:
        # chars 为全章累计（collected 跨轮共享），非本轮新增——前端按轮展示的是
        # 总字数曲线，语义如此；round_no 用于区分是哪一轮结束
        _emit({"stage": "round_end", "round": round_no,
               "chars": len("".join(collected)),
               "elapsed_s": round(time.time() - started, 1)})


# 拍数上限：超出则相邻合并（jarvis-write 场景卡纪律 3-5 场；实测大纲常把
# 场景内部的分号也写成"拍"，8 拍 × 300 字会产生碎段感与"每段都像结尾"）
_BEAT_MAX = 5


def _beat_context_block(kw):
    """拆锅模式下每拍必带的硬约束与身份块（整章 user 块的最小存活集）。

    整章路径这些块渲染在 user 消息里；拆锅若只带 system 会把它们全部丢掉
    （code review P0）：登场白名单、信息边界/时序真相红线、must_payoff
    排程、人物速写、创作罗盘必须在每一拍都在场——人物速写只保留
    性格/说话风格，档案全文留给整章路径。
    """
    parts = []
    try:
        from app.services.prompt_builder.context import build_compass_block
        compass = build_compass_block(kw.get("author_intent", ""),
                                      kw.get("current_focus", ""))
        if compass:
            parts.append(compass)
    except Exception as exc:
        logger.warning("beat_context 罗盘降级: %s", exc)
    if kw.get("cast_constraint"):
        parts.append(kw["cast_constraint"])
    chars = kw.get("characters") or []
    if chars:
        lines = []
        for c in chars:
            line = f"- {c.get('name', '')}：{(c.get('personality') or '')[:60]}"
            style = (c.get('speaking_style') or '')[:40]
            if style:
                line += f"｜{style}"
            m_deep = re.search(r"深层[:：]\s*([^;；\n]+)", c.get('motivation') or '')
            if m_deep:
                line += f"｜需求：{m_deep.group(1).strip()[:40]}"
            arc = c.get("arc_state") or {}
            arc_bits = "；".join(filter(None, [
                (arc.get("want_now") or "")[:30],
                (arc.get("change_stage") or "")[:30]]))
            if arc_bits:
                line += f"｜现态：{arc_bits}"
            lines.append(line)
        parts.append("【出场人物速写（性格｜说话风格｜现态）】\n" + "\n".join(lines))
    if kw.get("narrative_plan"):
        parts.append("【本章叙事计划（硬性任务）】\n" + kw["narrative_plan"])
    if kw.get("boundary_context"):
        parts.append("【信息边界与既定事实（一致性红线，必须遵守）】\n"
                     + kw["boundary_context"])
    if kw.get("tone_instructions"):
        parts.append(kw["tone_instructions"][:400])
    if kw.get("style_memo"):
        parts.append("【近期文体备忘】\n" + kw["style_memo"])
    return "\n\n".join(parts)


def _merge_beats(beats, limit=_BEAT_MAX):
    """拍数超限时相邻合并到 limit 拍（内容不丢，按顺序均匀分组）。"""
    if len(beats) <= limit:
        return beats
    n = len(beats)
    merged = []
    idx = 0
    for k in range(limit):
        take = (n - idx) // (limit - k)          # 剩余拍均匀分配到剩余槽位
        group = beats[idx:idx + take] or [beats[idx]]
        merged.append("；".join(group))
        idx += take
    return merged


def build_scene_plan(outline, kw=None, word_target=CHAPTER_WORD_TARGET,
                     novel_id=None, chapter_number=None):
    """从大纲【场景节拍】构建节拍级生成计划（None = 不拆锅，走整章路径）。

    机制来源（开源调研 2026-09-28）：
    - jarvis-write（藏山）「场景升格为生成单元」+「切分与写作分离」——灵砚的
      节拍已在细纲阶段（独立 LLM 调用）写好，本函数只做拆分与排程，
      不新增切分调用；少于 2 拍不拆（"换名字的整章一发"没有意义）。
    - 张力总线：章档由大纲定位+伏笔压力确定性推导，逐拍摊成不平曲线。

    每拍生成的 user 消息只带：事件清单 + 张力档 + 本拍 + 前拍结尾 + 章尾钩，
    比整章 prompt 小一个量级——拆锅是"减提示词"方向的（单次注意力更集中）。
    """
    try:
        beats = parse_scene_beats(outline)
        if len(beats) < 2:
            return None
        beats = _merge_beats(beats)
        level = chapter_tension(novel_id or 0, chapter_number or 0, outline)
        # 章级戏剧契约随拍下发：定位（本篇立场）与基调（温度基准）原属整章
        # 大纲字段，不随拍带走 writer 就只剩"事件清单"——写得出事，写不出调
        positioning = parse_outline_field(outline, "本章定位")
        tone = parse_outline_field(outline, "情感基调")
        plan = {
            "beats": beats,
            "tension": level,
            "beat_tensions": beat_tensions(level, beats),
            "events": (kw or {}).get("chapter_events", ""),
            "context": _beat_context_block(kw or {}),
            "positioning": positioning,
            "tone": tone,
            "hook": parse_outline_field(outline, "结尾钩子"),
            "word_target": int(word_target or CHAPTER_WORD_TARGET),
        }
        logger.info("节拍级生成计划：%d 拍，章张力档 %d，逐拍 %s",
                    len(beats), level, plan["beat_tensions"])
        return plan
    except Exception as exc:
        logger.warning("scene_plan 构建降级（回退整章生成）: %s", exc)
        return None


def _beat_user_message(plan, index, tail):
    """单拍的紧凑 user 消息（小于整章 prompt 一个量级）。"""
    beats = plan["beats"]
    n = len(beats)
    level = plan["beat_tensions"][index]
    parts = []
    if plan.get("context"):
        parts.append(plan["context"])
    if plan.get("events"):
        parts.append(plan["events"])
    # 章级契约压缩成两行，每拍在场（整章路径在 full outline 里，拆锅路径唯一入口）
    contract = "；".join(filter(None, [
        (f"【本章定位】{plan['positioning']}" if plan.get("positioning") else ""),
        (f"【情感基调】{plan['tone']}" if plan.get("tone") else ""),
    ]))
    if contract:
        parts.append(contract)
    parts.append(f"【本章张力档 {plan['tension']}/5 · 本拍力度 {level}/5】"
                 f"{tension_directive(level)}")
    if index == 0 and (tail or "").strip():
        # 首拍接上一章结尾，保章间衔接（tail 由调用方填 prev_ending）
        parts.append(f"【上一章结尾】\n{tail[-600:]}")
    elif tail:
        parts.append(f"【前文结尾（本拍直接接续）】\n{tail[-600:]}")
    parts.append(f"【本拍任务（第 {index + 1}/{n} 拍）】\n{beats[index]}")
    if index == n - 1 and plan.get("hook"):
        parts.append(f"【章尾钩（本拍收尾必须落在此）】\n{plan['hook']}")
    share = max(300, plan["word_target"] // n)
    parts.append(f"【字数】本拍约 {share} 字。只写本拍，不抢后面的拍。"
                 "直接输出正文，不要说明。")
    return "\n\n".join(parts)


def _beat_accepted(beat_text, prev_tail):
    """拍级验收（零 LLM 轻量版，对齐 jarvis-write accept_scene 的硬维度子集）。

    只查两条硬性：产出过短 / 与前文大段重复。情绪与目标命中留在章级
    门禁（ai_metric/web_novel_gate）统一判卷，避免双重判分。
    口径定标（书 1 实测正文）：拍预算 ≥300 字，100 字下限是"塌缩拍"；
    15 字 shingle / 40% 重叠率对齐拆书雷同检测的连续命中思路（低于
    15 字的短串在中文里碰撞率过高，40% 以上即"整段复读"级别）。
    Returns: (ok, reason)
    """
    if len(beat_text.strip()) < 100:
        return False, "本拍产出过短（<100 字）"
    if prev_tail:
        shingles = [beat_text[i:i + 15] for i in range(0, max(len(beat_text) - 14, 1), 15)]
        hits = sum(1 for s in shingles if s in prev_tail)
        if shingles and hits / len(shingles) > 0.4:
            return False, "本拍与前文大段重复"
    return True, ""


def generation_tokens(messages, cfg, word_target=None, on_event=None,
                      scene_plan=None, beat_retry=False):
    """完整正文生成的原始 token 流。

    两种模式：
    - scene_plan 为空：整章一次生成（原路径）；
    - scene_plan 提供时：按大纲场景节拍逐拍生成——每拍一次调用、
      独立紧凑 prompt、按拍张力档映射采样温度（高张力放开、低张力收紧），
      拍间以已写正文结尾衔接；全部拍完成后仍走字数保障续写轮。

    beat_retry: 拍级验收保险丝（编排器/非流式路径开启）——本拍产出过短
    或与前文大段重复时，丢弃初稿重写一次该拍。流式（SSE）路径不开启：
    已推送的 token 无法从流里收回，重试会造成用户可见的重复段。
    验收只查硬性两条（长度/重复），情绪与目标留给章级门禁判卷。

    on_event: 进度事件（见 _round_tokens）外加
        beat_start{beat,of,tension} / beat_end{beat,chars} /
        beat_retry{beat,reason}
    SSE 路由与编排器共用的单一实现；LLMError 原样抛出由调用方处置。
    """
    collected = []

    def _emit(ev):
        if on_event is None:
            return
        try:
            on_event(ev)
        except Exception:
            pass

    try:
        if scene_plan:
            beats = scene_plan["beats"]
            tensions = scene_plan["beat_tensions"]
            system_text = ""
            for m in messages:
                if m.get("role") == "system":
                    system_text = m.get("content") or ""
                    break
            # 首拍衔接上一章结尾（调用方经 scene_plan["prev_ending"] 传入）
            prev_tail = scene_plan.get("prev_ending", "")
            for i, beat in enumerate(beats):
                level = tensions[i]
                _emit({"stage": "beat_start", "beat": i + 1, "of": len(beats),
                       "tension": level})
                if i > 0:
                    yield "\n\n"
                cfg_b = dict(cfg)
                cfg_b["temperature"] = temperature_for_level(
                    cfg.get("temperature", 0.8), level)
                share = max(300, scene_plan.get("word_target", 0) // len(beats))
                share_tokens = min(share * 2, cfg.get("max_tokens", 4096))
                beat_user = _beat_user_message(scene_plan, i, prev_tail)
                mark = len(collected)
                reason = ""
                for attempt in range(2 if beat_retry else 1):
                    if attempt:
                        _emit({"stage": "beat_retry", "beat": i + 1,
                               "reason": reason})
                        del collected[mark:]
                        beat_msgs = [
                            {"role": "system", "content": (
                                system_text + "\n\n本拍初稿不合格（" + reason
                                + "）。重写本拍：直接推进剧情，禁止复述前文。")},
                            {"role": "user", "content": beat_user},
                        ]
                    else:
                        beat_msgs = [
                            {"role": "system", "content": system_text},
                            {"role": "user", "content": beat_user},
                        ]
                    if beat_retry:
                        buf = []
                        for tok in _round_tokens(beat_msgs, cfg_b, share_tokens,
                                                 collected, on_event=on_event,
                                                 round_no=i + 1):
                            buf.append(tok)
                        ok, reason = _beat_accepted("".join(buf), prev_tail)
                        if ok or attempt:
                            yield from buf
                            break
                    else:
                        yield from _round_tokens(beat_msgs, cfg_b, share_tokens,
                                                 collected, on_event=on_event,
                                                 round_no=i + 1)
                        break
                prev_tail = "".join(collected)[-600:]
                _emit({"stage": "beat_end", "beat": i + 1,
                       "chars": len("".join(collected))})
        else:
            yield from _round_tokens(messages, cfg, cfg.get("max_tokens", 4096),
                                     collected, on_event=on_event, round_no=1)
        # 字数保障：仅章节生成传入 word_target 时启用
        if word_target:
            rounds = 0
            while (len("".join(collected)) < CHAPTER_WORD_FLOOR
                   and rounds < CHAPTER_MAX_CONTINUE_ROUNDS):
                rounds += 1
                full = "".join(collected)
                remaining = word_target - len(full)
                _emit({"stage": "continue_start",
                       "round": rounds + 1,
                       "current_chars": len(full),
                       "floor": CHAPTER_WORD_FLOOR})
                yield "\n\n"
                # 续写轮戏剧纪律：禁止字数导向灌水；必须推进未完成的节拍/事件
                # （调研根因：弱指令补写是「梗概化正文」来源之一）
                last_tail = full[-2500:]
                continue_messages = [
                    {"role": "system", "content": (
                        "你正在续写一章网文。硬纪律：\n"
                        "1. 直接接续前文写下去，不重复、不总结、不输出说明文字。\n"
                        "2. 必须推进本章尚未完成的戏剧任务（目标/冲突/结果变化），"
                        "禁止用环境描写、文件操作、心理空转凑字数。\n"
                        "3. 对白要有算盘与信息差；禁止作者旁白解释悬念。\n"
                        "4. 若本章大纲含【场景节拍】/【结尾钩子】，续写须朝未完成的节拍与章尾钩推进。\n"
                        "5. 允许短段与跳切，禁止匀速流水账。"
                    )},
                    {"role": "user", "content": (
                        f"【本章已写内容（结尾部分）】\n{last_tail}\n\n"
                        + (f"【本章章尾钩（续写须落在此）】\n{scene_plan['hook']}\n\n"
                           if scene_plan and scene_plan.get("hook") else "")
                        + f"【要求】从上文断点继续，推进冲突或兑现本拍结果，"
                        f"朝章尾钩靠近。还需约 {max(remaining, 400)} 字有效剧情，"
                        f"写不出来就停在有意义的场面结果上，不要注水。"
                    )},
                ]
                yield from _round_tokens(continue_messages, cfg,
                                         min(remaining * 2, 16000), collected,
                                         on_event=on_event, round_no=rounds + 1)
    except LLMError:
        raise
    except Exception as e:
        logger.error("generation_tokens failed: %s", e)
        raise LLMError(f"LLM 调用失败: {e}") from e


def collect_full_text(messages, cfg, word_target=None, scene_plan=None,
                      beat_retry=True):
    """非流式消费生成流，返回完整正文（runner 用）。LLMError 向上抛。

    beat_retry 默认 True：编排器路径无流式回退顾虑，拍级验收保险丝常开。
    """
    parts = []
    for token in generation_tokens(messages, cfg, word_target=word_target,
                                   scene_plan=scene_plan, beat_retry=beat_retry):
        parts.append(token)
    return "".join(parts)
