"""短篇 AI 生成路由：灵感发散、创作、直接生成、润色、分段生成。"""
import json
import re
from flask import request, Response, jsonify, current_app
from app.models import db, ShortStory
from app.config_utils import get_model_config
from app.services.text_cleaner import clean_ai_text
from app.services.deai_agent import deai_process
from app.services.llm import stream_llm_tokens, call_llm_sync, LLMError
from app.routes.short_story.prompts import (
    _build_expander_prompt, _build_writer_from_concept_prompt,
    _build_setting_prompt, _build_careful_prompt, SECTION_PROMPTS,
    DEFAULT_WRITER_CONSTRAINTS, _get_genre_instruction,
    build_skill_prompt, get_template_prompt, build_node_prompt,
    _build_character_prompt, _build_theme_prompt,
)
from app.routes.short_story import short_story_bp


def _bank_constraints(story):
    """约束词库装配（short_story 场景，按体裁）；停用/异常返回 None 走兜底常量。"""
    try:
        from app.services.constraint_bank import get_constraints_text
        return get_constraints_text("short_story", genre=story.genre)
    except Exception:
        return None


def _anchor():
    """文风锚例上下文；未启用/未保存时返回空串。"""
    try:
        from app.services.style_fingerprint import format_anchor_for_prompt
        return format_anchor_for_prompt()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 剧情大纲节点解析
# ---------------------------------------------------------------------------

NODE_LINE_RE = re.compile(
    r"节点\s*(\d+)\s*[（(]\s*([^，,]+?)\s*，\s*约\s*(\d+)\s*字\s*[)）]\s*[:：]\s*(.+)"
)


def parse_outline_nodes(concept_text, word_target=None):
    """从构思文本中解析出剧情节点列表。

    节点行格式（由发散 Agent 产出）：
        节点1（第一幕·开端，约1200字）：标题 —— 描述

    Returns:
        list[dict]: [{id, act, title, summary, word_count, status}]，解析失败返回 []
    """
    if not concept_text:
        return []
    nodes = []
    for m in NODE_LINE_RE.finditer(concept_text):
        node_id = int(m.group(1))
        act = m.group(2).strip()
        raw_title = m.group(4).strip()
        # 「标题 —— 描述」两段式：拆出 summary。
        # 此前整体吞进 title，导致节点大纲描述永久丢失、后续提示词退化
        title, summary = raw_title, ""
        for sep in ("——", "──"):
            if sep in raw_title:
                title, _, summary = raw_title.partition(sep)
                title = title.strip()
                summary = summary.strip()
                break
        try:
            wc = int(float(m.group(3)))
        except (TypeError, ValueError):
            wc = 1200
        # 钳制字数：AI 可能输出超大值导致 token 触顶后正文必然不足却照样标 done
        wc = min(max(wc, 300), 3000)
        nodes.append({
            "id": node_id,
            "act": act,
            "title": title,
            "summary": summary,
            "word_count": wc,
            "status": "pending",
        })
    # 校验节点 id 连续
    if nodes:
        ids = [n["id"] for n in nodes]
        if ids != list(range(1, len(nodes) + 1)):
            return []
    return nodes


def _node_marker(node):
    """生成 ===NODE:id:title=== 进度标记。

    标题中的 = 和换行会破坏前端解析正则，统一替换为下划线。
    """
    safe_title = re.sub(r"[=\r\n]+", "_", str(node.get("title", "")))
    return f"\n\n===NODE:{node['id']}:{safe_title}===\n\n"


def load_outline_nodes(story):
    """从 story.outline_nodes 读取节点列表，损坏或为空时返回 []。"""
    try:
        nodes = json.loads(story.outline_nodes or "[]")
        if isinstance(nodes, list) and nodes and all("id" in n for n in nodes):
            return nodes
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _extract_json(raw):
    """从 AI 返回文本中提取 JSON 对象（容错 markdown 代码块和前后杂质）。"""
    if not raw:
        return None
    text = raw.strip()
    # 去掉 markdown 代码块包裹
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _parse_expander_output(raw):
    """解析大纲 Agent 的输出，返回 (concept_str, nodes_list)。

    concept_str 为「核心概念」一句话；nodes_list 为规范化节点列表。
    JSON 解析失败返回 (None, [])。
    """
    data = _extract_json(raw)
    if not data:
        return None, []
    concept = data.get("concept", "") or ""
    raw_nodes = data.get("nodes", []) or []
    valid_nodes = []
    for n in raw_nodes:
        if not isinstance(n, dict):
            continue
        node = {
            "id": int(n.get("id", 0)),
            "act": str(n.get("act", "正文")),
            "title": str(n.get("title", "")),
            "summary": str(n.get("summary", "")),
            "word_count": int(n.get("word_count", 1000)),
            "status": "pending",
        }
        if node["id"] > 0 and node["title"]:
            valid_nodes.append(node)
    # id 连续性校验
    if valid_nodes:
        ids = [n["id"] for n in valid_nodes]
        if ids != list(range(1, len(valid_nodes) + 1)):
            valid_nodes = []
    if not valid_nodes:
        return None, []
    return concept, valid_nodes


def _format_concept(concept_str, nodes):
    """把「核心概念 + 节点列表」格式化为可读文本。

    存到 story.concept 供前端展示与编辑；节点行格式与 parse_outline_nodes
    正则兼容，编辑后可通过 save_concept 重新解析。
    """
    lines = [f"【核心概念】\n{concept_str}", "", "【剧情大纲】"]
    for n in nodes:
        lines.append(
            f"节点{n['id']}（{n['act']}，约{n['word_count']}字）：{n['title']} —— {n.get('summary', '')}"
        )
    return "\n".join(lines)


def save_outline_nodes(story, nodes):
    """持久化节点列表到 story.outline_nodes。"""
    story.outline_nodes = json.dumps(nodes, ensure_ascii=False)
    db.session.commit()


def _stream_ai_tokens(cfg, messages, max_tokens):
    """流式 AI 请求，逐段 yield 文本片段。委托给 llm.stream_llm_tokens。
    错误时抛出 LLMError（调用方应捕获，不持久化错误文本）。"""
    yield from stream_llm_tokens(
        model=cfg["model_name"],
        messages=messages,
        api_key=cfg.get("api_key", ""),
        base_url=cfg.get("base_url", ""),
        provider_type=cfg.get("provider_type", "deepseek"),
        temperature=cfg.get("temperature", 0.8),
        max_tokens=max_tokens,
        frequency_penalty=cfg.get("frequency_penalty"),
        presence_penalty=cfg.get("presence_penalty"),
    )


def _call_ai_sync_wrapper(messages, cfg):
    """非流式 AI 请求。委托给 llm.call_llm_sync。
    错误时抛出 LLMError（调用方应捕获，不持久化错误文本）。"""
    return call_llm_sync(
        model=cfg["model_name"],
        messages=messages,
        api_key=cfg.get("api_key", ""),
        base_url=cfg.get("base_url", ""),
        provider_type=cfg.get("provider_type", "deepseek"),
        temperature=cfg.get("temperature", 0.8),
        max_tokens=cfg.get("max_tokens", 4096),
        frequency_penalty=cfg.get("frequency_penalty"),
        presence_penalty=cfg.get("presence_penalty"),
    )


def _rebuild_content_from_nodes(nodes):
    """按顺序拼接所有已完成节点的独立正文，得到全文。"""
    return "\n\n".join(
        n["content"] for n in nodes
        if n.get("status") == "done" and n.get("content")
    )


def _nodes_have_content(nodes):
    """所有已完成节点是否都存有独立正文（旧数据可能没有）。"""
    done = [n for n in nodes if n.get("status") == "done"]
    return bool(done) and all(n.get("content") for n in done)


# ---------------------------------------------------------------------------
# 灵感模式：双Agent协作
# ---------------------------------------------------------------------------

@short_story_bp.route("/<int:story_id>/expand", methods=["POST"])
def expand_inspiration(story_id):
    """大纲生成 Agent — 一次调用产出 JSON 剧情大纲（非流式）。

    流程：灵感 → 一次 AI 调用 → 解析 JSON → 存「核心概念 + 大纲」到 concept，
    存节点列表到 outline_nodes。内容生成阶段再逐节点一轮一轮写正文。
    """
    story = ShortStory.query.get_or_404(story_id)
    if not (story.inspiration or story.theme or story.character_desc or story.scene_desc):
        return jsonify({"error": "请先填写灵感、主题或角色/场景设定"}), 400
    prev_status = story.status
    story.status = "expanding"
    db.session.commit()

    messages = _build_expander_prompt(story)
    cfg = get_model_config(agent_type="short_story")
    # 大纲是一次性 JSON 产出，节点多时（如 2 万字 ≈ 19 节点）默认 max_tokens
    # 会被撑爆截断成残缺 JSON，前端就只能显示一坨裸 JSON。这里给足输出空间。
    cfg = dict(cfg)
    cfg["max_tokens"] = max(cfg.get("max_tokens", 4096), 8192)
    cfg["temperature"] = 0.7  # 大纲策划要稳定，不必沿用写作的 0.9

    try:
        raw = _call_ai_sync_wrapper(messages, cfg)
    except LLMError as e:
        story.status = prev_status
        db.session.commit()
        return jsonify({"error": f"AI 调用失败: {e}"}), 502
    concept_str, nodes = _parse_expander_output(raw)

    if nodes:
        story.concept = _format_concept(concept_str, nodes)
        story.outline_nodes = json.dumps(nodes, ensure_ascii=False)
        story.status = "concept_ready"
    else:
        # 兜底：JSON 解析失败（通常是输出被 max_tokens 截断成残缺 JSON）
        # 不把裸 JSON 当构思存——那对用户毫无意义；给明确提示引导重试
        fallback = parse_outline_nodes(raw or "", story.word_target)
        story.outline_nodes = json.dumps(fallback, ensure_ascii=False) if fallback else "[]"
        story.concept = (
            "⚠️ 大纲生成不完整（AI 输出被截断），未能解析出有效节点。\n"
            "请点「重新生成大纲」再试一次；若反复出现，可在设置里换用更大上下文的模型。"
        ) if not fallback else _format_concept("（部分节点）", fallback)
        story.status = "concept_ready"

    # 大纲已重置为全新 pending 节点：旧全文与新节点失配，必须清空。
    # 否则「继续生成」会把旧全文当上下文前文，新节点 append 后整篇重复
    story.content = ""
    db.session.commit()

    return jsonify({
        "ok": True,
        "concept": story.concept,
        "nodes": nodes if nodes else parse_outline_nodes(story.concept, story.word_target),
    })


# ---------------------------------------------------------------------------
# 分阶段策划：角色设计 / 场景构建 / 主题定调（非流式，可编辑确认）
# ---------------------------------------------------------------------------

def _plan_stage(story_id, build_prompt_fn, field_name, prev_status):
    """通用策划阶段处理：非流式 AI 调用 → 存储纯文本产出 → 返回 JSON。

    Args:
        story_id: 故事 ID
        build_prompt_fn: 提示词构建函数 (story) -> messages
        field_name: 存储字段名 ("plan_characters" / "plan_setting" / "plan_theme")
        prev_status: 失败时回退的状态
    """
    story = ShortStory.query.get_or_404(story_id)
    if not (story.inspiration or story.theme or story.character_desc or story.scene_desc):
        return jsonify({"error": "请先填写灵感、主题或角色/场景设定"}), 400

    messages = build_prompt_fn(story)
    cfg = get_model_config(agent_type="short_story")

    try:
        raw = _call_ai_sync_wrapper(messages, cfg)
    except LLMError as e:
        return jsonify({"error": f"AI 调用失败: {e}"}), 502

    text = (raw or "").strip()
    if not text:
        return jsonify({"error": "AI 未返回有效内容"}), 502

    setattr(story, field_name, text)
    db.session.commit()

    return jsonify({"ok": True, field_name: text})


@short_story_bp.route("/<int:story_id>/plan-characters", methods=["POST"])
def plan_characters(story_id):
    """阶段1：角色设计 — AI 产出角色档案（纯文本）。"""
    return _plan_stage(story_id, _build_character_prompt, "plan_characters", "draft")


@short_story_bp.route("/<int:story_id>/plan-theme", methods=["POST"])
def plan_theme(story_id):
    """阶段3：主题定调 — AI 提炼主题与叙事风格，使用全部前序策划作为上下文。"""
    story = ShortStory.query.get_or_404(story_id)
    if not story.concept:
        return jsonify({"error": "请先生成剧情大纲"}), 400
    return _plan_stage(story_id, _build_theme_prompt, "plan_theme", "concept_ready")


@short_story_bp.route("/<int:story_id>/write-from-concept", methods=["POST"])
def write_from_concept(story_id):
    """Agent 2: 创作Agent — 根据构思逐节点写出完整短篇（流式，每节点一轮）。

    流程：发散产出的「剧情大纲节点列表」驱动，一次请求顺序生成所有未完成节点；
    每完成一个节点持久化一次（支持中途暂停后从断点恢复）；
    全部完成统一做 deai 处理。
    """
    story = ShortStory.query.get_or_404(story_id)

    if not story.concept:
        return Response("构思为空，请先进行灵感发散", mimetype="text/plain", status=400)

    reset = request.form.get("reset") == "1"
    if reset:
        story.content = ""
        nodes = load_outline_nodes(story) or parse_outline_nodes(story.concept, story.word_target)
        for n in nodes:
            n["status"] = "pending"
            n.pop("content", None)  # 清除节点正文，从头生成
        story.outline_nodes = json.dumps(nodes, ensure_ascii=False) if nodes else "[]"
        db.session.commit()
    else:
        nodes = load_outline_nodes(story) or parse_outline_nodes(story.concept, story.word_target)
        if nodes and not story.outline_nodes:
            story.outline_nodes = json.dumps(nodes, ensure_ascii=False)
        db.session.commit()

    prev_status = story.status if story.status not in ("generating", "expanding") else "concept_ready"
    story.status = "generating"
    db.session.commit()

    cfg = get_model_config(agent_type="short_story")
    app = current_app._get_current_object()
    word_target = story.word_target or 10000
    # 生成前捕获为纯文本：流式响应阶段请求 session 已销毁，
    # generator 内再访问过期 ORM 实例属性会抛 DetachedInstanceError
    concept = story.concept or ""

    def _single_round(messages, max_tokens):
        """单轮生成，流式返回文本片段（委托模块级实现）。"""
        return _stream_ai_tokens(cfg, messages, max_tokens)

    def generate():
        # 有节点 → 逐节点多轮生成
        with app.app_context():
            s = db.session.get(ShortStory, story_id)
            node_list = load_outline_nodes(s) if s else []

        if node_list:
            # 前文 = 已完成节点正文拼接（旧数据无节点正文时回退 story.content）
            with app.app_context():
                s = db.session.get(ShortStory, story_id)
                if _nodes_have_content(node_list):
                    all_text = _rebuild_content_from_nodes(node_list)
                else:
                    all_text = (s.content or "") if s else ""

            # 从第一个未完成节点开始
            for idx, node in enumerate(node_list):
                if node.get("status") == "done":
                    continue
                # 节点分隔标记（不进入正文，前端据此更新进度）
                yield _node_marker(node)
                sep = "\n\n" if all_text else ""
                if sep:
                    yield sep
                node_text = ""
                try:
                    with app.app_context():
                        s = db.session.get(ShortStory, story_id)
                        messages = build_node_prompt(s, node_list, idx, all_text)
                    # word_count 可能为 None/浮点串（旧数据/AI 输出），float() 容错
                    node_tokens = min(int(float(node.get("word_count") or 1200)) * 2, 12000)
                    for token in _stream_ai_tokens(cfg, messages, node_tokens):
                        node_text += token
                        yield token
                except Exception as e:
                    yield f"\n[节点{node['id']}生成失败: {e}]"
                    node_text = ""

                if not node_text.strip():
                    continue  # 本节点失败保持 pending，暂停/重试时续写

                # 每完成一个节点：独立存储节点正文（先去AI处理）+ 持久化状态与全文
                node_text = deai_process(clean_ai_text(node_text))
                all_text += sep + node_text
                with app.app_context():
                    s = db.session.get(ShortStory, story_id)
                    if s:
                        node["content"] = node_text
                        node["status"] = "done"
                        s.outline_nodes = json.dumps(node_list, ensure_ascii=False)
                        s.content = all_text
                        db.session.commit()

            # 收尾：全部节点完成才置 done；有失败/未完成节点回退 concept_ready，
            # 保持可从断点续写（避免空内容 + "已完成"的死状态）
            with app.app_context():
                s = db.session.get(ShortStory, story_id)
                if s:
                    s.content = all_text
                    pending = [n for n in node_list if n.get("status") != "done"]
                    s.status = "concept_ready" if pending else "done"
                    db.session.commit()
            return

        # ============ 兼容旧数据：无节点 → 单轮全篇 + 续写 ============
        with app.app_context():
            s = db.session.get(ShortStory, story_id)
            first_messages = _build_writer_from_concept_prompt(s)
            all_text = ""

        round_tokens = min(word_target * 2, 16000)
        try:
            for token in _single_round(first_messages, round_tokens):
                all_text += token
                yield token
        except LLMError as e:
            # 状态回滚：否则 status 永久卡在 "generating"（列表页永远显示生成中）
            with app.app_context():
                s = db.session.get(ShortStory, story_id)
                if s:
                    s.status = prev_status
                    db.session.commit()
            yield f"\n[生成失败: {e}]"
            return

        max_rounds = 5
        round_num = 1
        while len(all_text) < word_target * 0.8 and round_num < max_rounds:
            round_num += 1
            remaining = word_target - len(all_text)
            yield "\n\n"
            continue_messages = [
                {"role": "system", "content": (
                    "你是一位才华横溢的短篇小说作家。请继续创作这篇小说。\n\n"
                    "【严格约束 — 最高优先级】\n"
                    "1. 必须严格按照下面提供的「原始构思」推进情节，不得擅自添加构思中没有的新势力、新角色、新冲突线\n"
                    "2. 构思中列出的每个情节点都必须写到，不得跳过\n"
                    "3. 直接接续前文写下去，不要重复已有内容，不要输出任何说明\n"
                    f"4. 还需要写约 {remaining} 字\n\n"
                    f"【原始构思 — 必须严格遵守】\n{concept}"
                    + _anchor()
                )},
                {"role": "user", "content": (
                    f"【前文内容（最近部分）】\n{all_text[-4000:]}\n\n"
                    f"【目标】继续写约 {remaining} 字。请检查构思中还有哪些情节点未写到，"
                    f"按构思顺序继续推进，直到故事自然结束。"
                )},
            ]
            try:
                for token in _single_round(continue_messages, min(remaining * 2, 16000)):
                    all_text += token
                    yield token
            except LLMError as e:
                yield f"\n[生成失败: {e}]"
                return

        if len(all_text) < word_target * 0.6:
            yield "\n\n"
            remaining = word_target - len(all_text)
            final_messages = [
                {"role": "system", "content": (
                    "你是一位才华横溢的短篇小说作家。这篇小说即将完结。\n"
                    "请根据原始构思，为故事写一个完整的结尾，收束所有线索。\n\n"
                    f"【原始构思】\n{concept}\n\n"
                    "不要添加构思之外的新情节，专注于收尾。"
                    + _anchor()
                )},
                {"role": "user", "content": (
                    f"【前文内容】\n{all_text[-3000:]}\n\n"
                    f"请为这个故事写一个有力的结尾。"
                )},
            ]
            try:
                for token in _single_round(final_messages, min(remaining * 2, 16000)):
                    all_text += token
                    yield token
            except LLMError as e:
                yield f"\n[生成失败: {e}]"
                return

        with app.app_context():
            s = db.session.get(ShortStory, story_id)
            if s:
                s.content = deai_process(clean_ai_text(all_text))
                s.status = "done"
                db.session.commit()

    return Response(generate(), mimetype="text/plain")


# ---------------------------------------------------------------------------
# 节点级操作：单节点重写
# ---------------------------------------------------------------------------

@short_story_bp.route("/<int:story_id>/node/<int:node_id>/rewrite", methods=["POST"])
def rewrite_node(story_id, node_id):
    """单节点重写：只重新生成指定节点，其余节点正文保持不变（流式）。

    要求：指定节点之前的所有已完成节点都存有独立正文（否则无法定位前文）。
    """
    story = ShortStory.query.get_or_404(story_id)
    nodes = load_outline_nodes(story)
    if not nodes:
        return Response("该短篇没有节点大纲，无法单节点重写", mimetype="text/plain", status=400)
    idx = next((i for i, n in enumerate(nodes) if n["id"] == node_id), None)
    if idx is None:
        return Response(f"节点 {node_id} 不存在", mimetype="text/plain", status=404)
    prev_done = [n for n in nodes[:idx] if n.get("status") == "done"]
    if prev_done and not all(n.get("content") for n in prev_done):
        return Response("前置节点缺少独立正文（旧数据或手动编辑过全文），请先「重新创作」以启用单节点重写",
                        mimetype="text/plain", status=400)

    prev_text = "\n\n".join(n["content"] for n in prev_done)
    cfg = get_model_config(agent_type="short_story")
    app = current_app._get_current_object()

    def generate():
        yield _node_marker(nodes[idx])
        node_text = ""
        with app.app_context():
            s = db.session.get(ShortStory, story_id)
            messages = build_node_prompt(s, nodes, idx, prev_text)
        # word_count 可能为 None/浮点串（旧数据/AI 输出），float() 容错
        # （与主生成路径 L358 保持一致；此前 int(None) 会在流中途崩溃）
        node_tokens = min(int(float(nodes[idx].get("word_count") or 1200)) * 2, 12000)
        try:
            for token in _stream_ai_tokens(cfg, messages, node_tokens):
                node_text += token
                yield token
        except LLMError as e:
            # 本路由不修改 story.status，无需回滚
            yield f"\n[生成失败: {e}]"
            return
        if not node_text.strip():
            yield "\n[重写失败：未生成内容]"
            return
        node_text = deai_process(clean_ai_text(node_text))
        with app.app_context():
            s = db.session.get(ShortStory, story_id)
            if s:
                nodes[idx]["content"] = node_text
                nodes[idx]["status"] = "done"
                s.outline_nodes = json.dumps(nodes, ensure_ascii=False)
                # 重建全文：其它节点正文保持不变 + 本次重写结果
                s.content = _rebuild_content_from_nodes(nodes)
                # 只有全部节点完成才能标记 done；
                # 之后仍有 pending 节点时保持可续写状态，防止残文被当完整作品
                all_done = all(n.get("status") == "done" for n in nodes)
                s.status = "done" if all_done else "concept_ready"
                db.session.commit()

    return Response(generate(), mimetype="text/plain")


# ---------------------------------------------------------------------------
# 局部编辑：续写 / 扩写选中 / 局部重写
# ---------------------------------------------------------------------------

@short_story_bp.route("/<int:story_id>/continue", methods=["POST"])
def continue_story(story_id):
    """续写：从当前结尾继续往下写（流式）。节点模式下并入最后一个节点正文。"""
    story = ShortStory.query.get_or_404(story_id)
    if not story.content:
        return Response("内容为空，无法续写", mimetype="text/plain", status=400)
    words = request.form.get("words", type=int) or 800

    cfg = get_model_config(agent_type="short_story")
    app = current_app._get_current_object()
    nodes = load_outline_nodes(story)
    concept = story.concept or story.inspiration or story.theme or ""

    system = (
        "你是一位才华横溢的短篇小说作家。请续写这篇小说。\n\n"
        "【要求】\n"
        "1. 直接接续前文写下去，不要重复已有内容，不要输出任何说明\n"
        "2. 情节与原设定保持一致，不得引入突兀的新人物、新势力、新冲突线\n"
        f"3. 续写约 {words} 字，写到一个自然的停顿处即可\n\n"
        + (_bank_constraints(story) or DEFAULT_WRITER_CONSTRAINTS)
        + _anchor()
    )
    user = (
        f"【原设定】\n{concept[:600]}\n\n"
        f"【前文结尾】\n……{story.content[-3000:]}\n\n"
        f"请从上文断点处继续写约 {words} 字："
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def generate():
        yield "\n\n"
        new_text = ""
        try:
            for token in _stream_ai_tokens(cfg, messages, min(words * 2, 8000)):
                new_text += token
                yield token
        except LLMError as e:
            # 本路由不修改 story.status，无需回滚
            yield f"\n[生成失败: {e}]"
            return
        if not new_text.strip():
            yield "[续写失败：未生成内容]"
            return
        new_text = deai_process(clean_ai_text(new_text))
        with app.app_context():
            s = db.session.get(ShortStory, story_id)
            if s:
                cur_nodes = load_outline_nodes(s)
                merged = False
                if cur_nodes:
                    # 并入最近一个有正文的节点（而非仅当末节点 done 才并入）：
                    # 断点暂停后末节点必为 pending，若走 else 分支追加到全文，
                    # 恢复生成时 rebuild 会把这段续写整体覆盖丢失
                    last_done = next((n for n in reversed(cur_nodes) if n.get("content")), None)
                    if last_done is not None:
                        last_done["content"] = last_done["content"] + "\n\n" + new_text
                        s.outline_nodes = json.dumps(cur_nodes, ensure_ascii=False)
                        s.content = _rebuild_content_from_nodes(cur_nodes)
                        merged = True
                if not merged:
                    s.content = (s.content or "") + "\n\n" + new_text
                db.session.commit()

    return Response(generate(), mimetype="text/plain")


@short_story_bp.route("/<int:story_id>/expand-selection", methods=["POST"])
def expand_selection(story_id):
    """扩写选中文本（流式）。输出为扩写后的完整段落，由前端替换编辑器中的选段。"""
    story = ShortStory.query.get_or_404(story_id)
    text = request.form.get("text", "").strip()
    before = request.form.get("before", "")[-500:]
    add_words = request.form.get("words", type=int) or 500
    if not text:
        return Response("未选中要扩写的文本", mimetype="text/plain", status=400)

    cfg = get_model_config(agent_type="short_story")
    system = (
        "你是一位才华横溢的短篇小说作家。请扩写指定的文本片段。\n\n"
        "【要求】\n"
        "1. 保留原片段的情节、人物、因果关系，只做加法：补充细节、感官描写、动作、心理\n"
        f"2. 在原有内容基础上增加约 {add_words} 字\n"
        "3. 输出扩写后的**完整段落**（含原有内容），不要输出任何说明或前后缀\n\n"
        + (_bank_constraints(story) or DEFAULT_WRITER_CONSTRAINTS)
        + _anchor()
    )
    user = (
        (f"【前文（供衔接参考）】\n……{before}\n\n" if before else "")
        + f"【待扩写片段】\n{text}\n\n"
        + f"请输出扩写后的完整段落："
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def generate():
        try:
            for token in _stream_ai_tokens(cfg, messages, min((len(text) + add_words) * 2, 8000)):
                yield token
        except LLMError as e:
            # 本路由不修改 story.status，无需回滚
            yield f"\n[生成失败: {e}]"
            return

    return Response(generate(), mimetype="text/plain")


@short_story_bp.route("/<int:story_id>/rewrite-selection", methods=["POST"])
def rewrite_selection(story_id):
    """按指令局部重写选中文本（流式）。输出为重写后的段落，由前端替换选段。"""
    story = ShortStory.query.get_or_404(story_id)
    text = request.form.get("text", "").strip()
    instruction = request.form.get("instruction", "").strip()
    before = request.form.get("before", "")[-500:]
    if not text:
        return Response("未选中要重写的文本", mimetype="text/plain", status=400)
    if not instruction:
        return Response("请提供重写指令（例如：改成第一人称、更口语化）", mimetype="text/plain", status=400)

    cfg = get_model_config(agent_type="short_story")
    system = (
        "你是一位专业的小说编辑。请按指令重写指定的文本片段。\n\n"
        "【要求】\n"
        "1. 严格按指令修改，未涉及的部分尽量保持原样\n"
        "2. 与前后文的情节、人称、时态保持一致\n"
        "3. 只输出重写后的片段，不要输出任何说明\n\n"
        + (_bank_constraints(story) or DEFAULT_WRITER_CONSTRAINTS)
        + _anchor()
    )
    user = (
        (f"【前文（供衔接参考）】\n……{before}\n\n" if before else "")
        + f"【重写指令】\n{instruction}\n\n"
        + f"【待重写片段】\n{text}\n\n"
        + "请输出重写后的片段："
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def generate():
        try:
            for token in _stream_ai_tokens(cfg, messages, min(len(text) * 3 + 2000, 8000)):
                yield token
        except LLMError as e:
            # 本路由不修改 story.status，无需回滚
            yield f"\n[生成失败: {e}]"
            return

    return Response(generate(), mimetype="text/plain")


# ---------------------------------------------------------------------------
# 设定模式 & 细心模式：直接生成
# ---------------------------------------------------------------------------

@short_story_bp.route("/<int:story_id>/generate", methods=["POST"])
def generate_story(story_id):
    """直接生成短篇（设定模式/细心模式）"""
    story = ShortStory.query.get_or_404(story_id)
    prev_status = story.status
    story.status = "generating"
    db.session.commit()

    if story.mode == "setting":
        messages = _build_setting_prompt(story)
    else:  # careful
        messages = _build_careful_prompt(story)

    cfg = get_model_config(agent_type="short_story")
    app = current_app._get_current_object()
    word_target = story.word_target or 10000

    def generate():
        full_text = ""
        try:
            for token in _stream_ai_tokens(cfg, messages, min(word_target * 2, 16000)):
                full_text += token
                yield token
        except LLMError as e:
            yield f"\n[生成失败: {e}]"
            # 失败时回退状态，避免永远卡在"生成中"
            with app.app_context():
                s = db.session.get(ShortStory, story_id)
                if s and s.status == "generating":
                    s.status = prev_status
                    db.session.commit()
            return
        with app.app_context():
            s = db.session.get(ShortStory, story_id)
            if s:
                s.content = deai_process(clean_ai_text(full_text))
                s.status = "done"
                db.session.commit()

    return Response(generate(), mimetype="text/plain")


# ---------------------------------------------------------------------------
# 润色（通用）
# ---------------------------------------------------------------------------

@short_story_bp.route("/<int:story_id>/rewrite", methods=["POST"])
def rewrite_story(story_id):
    """润色/修改短篇"""
    story = ShortStory.query.get_or_404(story_id)
    instruction = request.form.get("instruction", "请改进这篇小说")

    system = (
        "你是一位专业的小说编辑。根据用户的要求，修改和完善这篇短篇小说。\n"
        "输出修改后的完整小说正文，不要输出其他说明。"
    )
    system += _anchor()
    user = (
        f"【修改要求】\n{instruction}\n\n"
        f"【原文】\n{story.content}"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    cfg = get_model_config(agent_type="short_story")
    app = current_app._get_current_object()
    word_target = len(story.content) if story.content else 5000

    def generate():
        full_text = ""
        try:
            for token in _stream_ai_tokens(cfg, messages, min(word_target * 2, 16000)):
                full_text += token
                yield token
        except LLMError as e:
            # 本路由不修改 story.status，无需回滚
            yield f"\n[生成失败: {e}]"
            return
        with app.app_context():
            s = db.session.get(ShortStory, story_id)
            if s:
                s.content = deai_process(clean_ai_text(full_text))
                db.session.commit()

    return Response(generate(), mimetype="text/plain")


# ---------------------------------------------------------------------------
# 分段生成
# ---------------------------------------------------------------------------

@short_story_bp.route("/<int:story_id>/generate-section", methods=["POST"])
def generate_section(story_id):
    """分段生成 — 为长故事分段创作"""
    story = ShortStory.query.get_or_404(story_id)
    section_type = request.form.get("section_type", "opening")
    previous_content = request.form.get("previous_content", "")

    section = SECTION_PROMPTS.get(section_type)
    if not section:
        return jsonify({"error": f"未知段落类型: {section_type}"}), 400

    prev_status = story.status
    story.status = "generating"
    db.session.commit()

    # Build context
    context_parts = []
    if story.title:
        context_parts.append(f"【标题】{story.title}")
    if story.genre:
        context_parts.append(f"【体裁】{story.genre}")
    if story.tone:
        context_parts.append(f"【情感基调】{story.tone}")
    if story.inspiration:
        context_parts.append(f"【灵感】{story.inspiration}")
    if story.concept:
        context_parts.append(f"【构思】{story.concept}")
    if story.character_desc:
        context_parts.append(f"【角色】{story.character_desc}")
    if story.scene_desc:
        context_parts.append(f"【场景】{story.scene_desc}")

    context_str = "\n\n".join(context_parts)

    word_per_section = {
        "opening": int(story.word_target * 0.25),
        "development": int(story.word_target * 0.40),
        "climax": int(story.word_target * 0.20),
        "ending": int(story.word_target * 0.15),
    }
    target_words = word_per_section.get(section_type, 500)

    system = (
        f"你是一位才华横溢的短篇小说作家。{section['instruction']}\n\n"
        f"目标字数：约 {target_words} 字\n"
        f"直接输出小说正文，不要输出创作说明。\n\n"
        + (_bank_constraints(story) or DEFAULT_WRITER_CONSTRAINTS)
    )

    # Add skill context
    skill_ctx = build_skill_prompt()
    if skill_ctx:
        system += "\n\n" + skill_ctx

    system += _anchor()

    user_parts = [context_str]
    if previous_content:
        user_parts.append(f"【前文内容】\n{previous_content}")
    user_parts.append(f"\n请开始写{section['name']}：")

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]

    cfg = get_model_config(agent_type="short_story")
    app = current_app._get_current_object()

    def generate():
        full_text = ""
        try:
            for token in _stream_ai_tokens(cfg, messages, min(target_words * 2, 16000)):
                full_text += token
                yield token
        except LLMError as e:
            yield f"\n[生成失败: {e}]"
            # 失败时回退状态，避免永远卡在"生成中"
            with app.app_context():
                s = db.session.get(ShortStory, story_id)
                if s and s.status == "generating":
                    s.status = prev_status
                    db.session.commit()
            return
        full = deai_process(clean_ai_text(full_text))
        with app.app_context():
            s = db.session.get(ShortStory, story_id)
            if s:
                if previous_content:
                    s.content = previous_content + "\n\n" + full
                else:
                    s.content = full
                s.status = "done"
                db.session.commit()

    return Response(generate(), mimetype="text/plain")
