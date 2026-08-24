"""短篇评审路由：评审、获取评审、保存反馈、基于反馈重写。"""
import json
from flask import request, jsonify, Response, current_app
from app.models import db, ShortStory, ShortStoryVersion, ShortStoryReview
from app.config_utils import get_model_config
from app.services.text_cleaner import clean_ai_text
from app.services.deai_agent import deai_process
from app.services.prompt_builder import DEFAULT_WRITER_CONSTRAINTS
from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError
from app.routes.short_story import short_story_bp


@short_story_bp.route("/<int:story_id>/review", methods=["POST"])
def review_story(story_id):
    """Run critic review on current content (non-streaming, returns JSON)."""
    story = ShortStory.query.get_or_404(story_id)
    if not story.content:
        return jsonify({"error": "内容为空"}), 400

    cfg = get_model_config(agent_type="critic")

    system = (
        "你是一位资深文学评论编辑。对这篇短篇小说进行评审。\n"
        "请输出JSON格式的评审结果，不要输出其他内容，不要用markdown代码块包裹。\n"
        "评分标准：\n"
        "1. 文笔质量（语言流畅度、描写细腻度）\n"
        "2. 情节完整性（结构是否完整、节奏是否合理）\n"
        "3. 人物塑造（是否鲜活、有层次）\n"
        "4. 主题表达（是否有深度、是否打动人）\n"
        "5. AI痕迹（是否有明显的AI写作特征）\n"
        "6. 整体印象分\n"
    )
    user = (
        f"【标题】\n{story.title}\n\n"
        f"【体裁】\n{story.genre or '短篇'}\n\n"
        f"【小说正文】\n{story.content}\n\n"
        "请输出JSON格式评审结果：\n"
        '{"overall_score": 8.5, "overall_comment": "总评（150字以内，指出最突出优点与最需改进处）", '
        '"dimensions": [{"name": "文笔质量", "score": 8, "comment": "..."}, '
        '{"name": "情节完整性", "score": 7, "comment": "..."}, ...], '
        '"annotations": [{"quote": "正文原句", "issue": "问题", "suggestion": "修改建议"}, ...]}'
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    result = None
    try:
        text = call_llm_sync(
            model=cfg["model_name"], messages=messages,
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg.get("temperature", 0.3), max_tokens=cfg.get("max_tokens", 2048),
        )
        from app.routes.short_story.generate import _extract_json
        parsed = _extract_json(text)
        if isinstance(parsed, dict):
            result = parsed
    except LLMError as e:
        result = {"overall_score": None, "overall_comment": f"评审失败: {e}",
                  "dimensions": [], "annotations": []}
    except Exception as e:
        result = {"overall_score": None, "overall_comment": f"评审失败: {e}",
                  "dimensions": [], "annotations": []}
    if not result:
        result = {"overall_score": None, "overall_comment": "评审失败：AI 未返回有效的 JSON 结果",
                  "dimensions": [], "annotations": []}

    # Save review to latest version (auto-create if needed)
    versions = ShortStoryVersion.query.filter_by(story_id=story_id).order_by(
        ShortStoryVersion.version_number.desc()).all()
    if not versions and story.content:
        ver = ShortStoryVersion(
            story_id=story_id, version_number=1,
            content=story.content, source="ai",
        )
        db.session.add(ver)
        db.session.commit()
        versions = [ver]
    if versions:
        review = ShortStoryReview(
            version_id=versions[0].id,
            overall_score=result.get("overall_score"),
            dimension_scores_json=json.dumps(result.get("dimensions", []), ensure_ascii=False),
            annotations_json=json.dumps(result.get("annotations", []), ensure_ascii=False),
            overall_comment=result.get("overall_comment", ""),
            full_response=json.dumps(result, ensure_ascii=False),
        )
        db.session.add(review)
        db.session.commit()

    return jsonify(result)


@short_story_bp.route("/<int:story_id>/review/get")
def get_review(story_id):
    """Get the latest review for a short story."""
    story = ShortStory.query.get_or_404(story_id)
    versions = ShortStoryVersion.query.filter_by(story_id=story_id).order_by(
        ShortStoryVersion.version_number.desc()).all()
    if not versions:
        return jsonify(None)
    review = ShortStoryReview.query.filter_by(version_id=versions[0].id).order_by(
        ShortStoryReview.id.desc()).first()
    if not review:
        return jsonify(None)
    audit = None
    if review.audit_json:
        try:
            audit = json.loads(review.audit_json)
        except (json.JSONDecodeError, TypeError):
            audit = None
    return jsonify({
        "id": review.id,
        "overallScore": review.overall_score,
        "dimensions": json.loads(review.dimension_scores_json or "[]"),
        "annotations": json.loads(review.annotations_json or "[]"),
        "overallComment": review.overall_comment,
        "userFeedback": review.user_feedback or "",
        "audit": audit,
    })


@short_story_bp.route("/<int:story_id>/review/feedback", methods=["POST"])
def save_feedback(story_id):
    """Save user feedback on the latest review."""
    story = ShortStory.query.get_or_404(story_id)
    feedback = request.form.get("feedback", "")

    # Find or create version
    versions = ShortStoryVersion.query.filter_by(story_id=story_id).order_by(
        ShortStoryVersion.version_number.desc()).all()
    if not versions:
        # Auto-save current content as first version
        if story.content:
            ver = ShortStoryVersion(
                story_id=story_id, version_number=1,
                content=story.content, source="ai",
            )
            db.session.add(ver)
            db.session.commit()
            versions = [ver]
        else:
            return jsonify({"error": "内容为空"}), 400

    review = ShortStoryReview.query.filter_by(version_id=versions[0].id).order_by(
        ShortStoryReview.id.desc()).first()
    if not review:
        return jsonify({"error": "请先提交评审"}), 400
    review.user_feedback = feedback
    db.session.commit()
    return jsonify({"ok": True})


@short_story_bp.route("/<int:story_id>/rewrite-with-feedback", methods=["POST"])
def rewrite_with_feedback(story_id):
    """根据评审意见重写短篇。

    采用「多轮逐节点二次生成」策略：
    - 有节点结构（outline_nodes + 各节点独立正文）时，遍历每个已完成节点，
      用评审意见 + 前文 + 节点原内容孤立重写**该节点**，其余节点保持不变，
      逐节点二次生成，最终汇总为新的全文。
    - 无节点结构时回退到全文重写（多轮续写补足字数）。
    """
    story = ShortStory.query.get_or_404(story_id)

    # 收集评审意见（评审意见 + 用户补充）
    versions = ShortStoryVersion.query.filter_by(story_id=story_id).order_by(
        ShortStoryVersion.version_number.desc()).all()
    review = None
    if versions:
        review = ShortStoryReview.query.filter_by(version_id=versions[0].id).order_by(
            ShortStoryReview.id.desc()).first()

    critic_feedback = review.overall_comment if review else "请改进这篇小说"
    # 过滤掉失败的评审信息
    if critic_feedback and critic_feedback.startswith("评审失败"):
        critic_feedback = "请改进这篇小说"
    if review and review.user_feedback and review.user_feedback.strip():
        critic_feedback += "\n\n【用户补充意见】\n" + review.user_feedback.strip()

    original = story.content or ""
    cfg = get_model_config(agent_type="short_story")
    app = current_app._get_current_object()

    # 读取节点结构
    from app.routes.short_story.generate import load_outline_nodes
    nodes = load_outline_nodes(story)

    # 是否有可用的节点结构（已完成节点都有独立正文）
    done_nodes = [n for n in nodes if n.get("status") == "done" and n.get("content")]
    if done_nodes:
        return _rewrite_by_nodes(story, nodes, done_nodes, critic_feedback, cfg, app, story_id)

    # ============ 回退：无节点结构 → 全文重写（多轮续写补足字数） ============
    original_len = len(original)
    base_target = story.word_target or 3000
    word_target = max(original_len, min(base_target, original_len * 2 or base_target))
    round_cap = min(max(word_target * 2, 4096), 20000)
    max_rounds = 5

    system = (
        "你是一位专业的小说编辑。根据评审意见修改这篇短篇小说。\n"
        "解决指出的问题，保持原文的优点。输出修改后的完整小说正文。\n\n"
        f"【重要要求】\n"
        f"- 修改后的正文必须达到 {word_target} 字以上\n"
        f"- 原文有 {original_len} 字，修改后不得少于原文的 80%\n"
        f"- 通过丰富细节、扩展场景、深化对话来保持字数\n"
        f"- 不要删减情节，而是完善和扩展\n\n"
        + DEFAULT_WRITER_CONSTRAINTS
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": (
        f"【评审意见】\n{critic_feedback}\n\n【原文】\n{original}"
    )}]

    def generate():
        full_text = ""
        try:
            for token in stream_llm_tokens(
                model=cfg["model_name"], messages=messages,
                api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
                provider_type=cfg.get("provider_type", "deepseek"),
                temperature=cfg.get("temperature", 0.8), max_tokens=round_cap,
            ):
                full_text += token
                yield token
        except LLMError as e:
            yield f"\n[生成失败: {e}]"
            return

        round_num = 1
        while len(full_text) < word_target * 0.8 and round_num < max_rounds:
            round_num += 1
            remaining = word_target - len(full_text)
            yield "\n\n"
            continue_messages = [
                {"role": "system", "content": (
                    "你是一位专业的小说编辑。上一轮的重写还未达到目标字数，"
                    "请**继续刚才的重写**，从断点处自然延续情节与写法，"
                    "不要重复已写内容，不要输出任何说明。\n\n"
                    f"还需要写约 {remaining} 字。\n\n"
                    f"【评审意见（重写时持续参考）】\n{critic_feedback[:800]}"
                )},
                {"role": "user", "content": (
                    f"【已完成部分（最近内容）】\n{full_text[-4000:]}\n\n"
                    f"【目标】继续重写约 {remaining} 字，保持评审要求的改进方向，"
                    f"续写至故事自然结束。"
                )},
            ]
            try:
                for token in stream_llm_tokens(
                    model=cfg["model_name"], messages=continue_messages,
                    api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
                    provider_type=cfg.get("provider_type", "deepseek"),
                    temperature=cfg.get("temperature", 0.8),
                    max_tokens=min(remaining * 2, round_cap),
                ):
                    full_text += token
                    yield token
            except LLMError as e:
                yield f"\n[生成失败: {e}]"
                return

        if not full_text.strip():
            yield "\n[重写失败：未生成内容]"
            return
        full = deai_process(clean_ai_text(full_text))
        with app.app_context():
            s = db.session.get(ShortStory, story_id)
            if s:
                s.content = full
                _save_rewrite_version(story_id, full)
                db.session.commit()

    return Response(generate(), mimetype="text/plain")


def _save_rewrite_version(story_id, content):
    """保存重写结果为一个新的 rewrite 版本。"""
    max_ver = db.session.query(db.func.max(ShortStoryVersion.version_number)).filter_by(
        story_id=story_id).scalar()
    ver = ShortStoryVersion(
        story_id=story_id,
        version_number=(max_ver or 0) + 1,
        content=content,
        source="rewrite",
    )
    db.session.add(ver)


def _rewrite_by_nodes(story, nodes, done_nodes, critic_feedback, cfg, app, story_id):
    """多轮逐节点二次生成：遍历每个已完成节点，用评审意见孤立重写该节点。"""
    from app.routes.short_story.generate import _rebuild_content_from_nodes

    def generate():
        new_nodes = [dict(n) for n in nodes]  # 拷贝，重写时替换对应节点 content
        done_ids = {n["id"] for n in done_nodes}

        for idx, node in enumerate(nodes):
            if node.get("id") not in done_ids:
                continue  # 只重写已完成节点，未完成/无内容节点跳过
            # 流式标记（清洗标题，防止 = / 换行破坏前端解析）
            from app.routes.short_story.generate import _node_marker
            yield _node_marker(node)

            front = new_nodes[:idx]
            prev_text = "\n\n".join(
                n.get("content", "") for n in front if n.get("content"))
            original_node = node.get("content", "")
            node_len = len(original_node)
            # word_count 可能为 None/浮点串（旧数据/AI 输出），float() 容错
            target_len = max(node_len, int(float(node.get("word_count") or 1200) * 0.8))

            # 单节点重写提示词：评审意见 + 前文 + 节点原内容 + 节点大纲
            system = (
                "你是一位专业的小说编辑。根据评审意见，**只重写当前这一个节点**。\n\n"
                "【最高优先级】\n"
                "1. 只重写当前节点，不要修改或提前写其他节点的情节\n"
                "2. 解决评审中指出的、与本节点相关的问题；与本节点无关的问题不要动\n"
                "3. 与前后文保持衔接（承接前文结尾，为后续留好接口）\n"
                "4. 保持本节点的核心情节，只做完善、细化、修正，不要无故删改\n"
                "5. 直接输出重写后的节点正文（完整），不要输出节点编号或说明\n"
                f"6. 本节点重写后需约 {target_len} 字，不得少于原文的 80%\n\n"
                + DEFAULT_WRITER_CONSTRAINTS
            )
            user = (
                f"【评审意见】\n{critic_feedback[:800]}\n\n"
                + (f"【前文（上一节点结尾）】\n……{prev_text[-1500:]}\n\n" if prev_text else "")
                + f"【当前节点大纲】\n节点{node['id']}（{node.get('act', '')}）："
                  f"{node.get('title', '')} —— {node.get('summary', '')}\n\n"
                + f"【当前节点原文】\n{original_node}\n\n"
                + "请输出重写后的本节点完整正文："
            )
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

            node_text = ""
            node_tokens = min(max(node_len * 2, 1600), 14000)
            try:
                for token in stream_llm_tokens(
                    model=cfg["model_name"], messages=messages,
                    api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
                    provider_type=cfg.get("provider_type", "deepseek"),
                    temperature=cfg.get("temperature", 0.8), max_tokens=node_tokens,
                ):
                    node_text += token
                    yield token
            except LLMError as e:
                yield f"\n[节点{node['id']}重写失败: {e}]"
                continue

            if node_text.strip():
                node_text = deai_process(clean_ai_text(node_text))
                new_nodes[idx]["content"] = node_text
                new_nodes[idx]["status"] = "done"
            else:
                # 本节点生成空 → 保留原文，不破坏结构
                yield f"\n[节点{node['id']}重写失败，保留原内容]"
                new_nodes[idx]["content"] = original_node
                new_nodes[idx]["status"] = "done"

        # 汇总所有节点为新的全文
        full = _rebuild_content_from_nodes(new_nodes)
        with app.app_context():
            s = db.session.get(ShortStory, story_id)
            if s:
                s.content = full
                s.outline_nodes = json.dumps(new_nodes, ensure_ascii=False)
                # 存在 pending 缺口时保持可续写状态：
                # 此前无条件置 done，缺一节的残文会被当作完整作品入库/导出
                all_done = all(n.get("status") == "done" for n in new_nodes)
                s.status = "done" if all_done else "concept_ready"
                _save_rewrite_version(story_id, full)
                db.session.commit()

    return Response(generate(), mimetype="text/plain")
