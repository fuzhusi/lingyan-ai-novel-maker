"""风格模仿功能 — 分析参考文本风格，生成风格相似的新内容。"""
from flask import request, Response, jsonify, current_app
from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError
from app.models import db, PlagiarizeTask
from app.config_utils import get_model_config
from app.services.text_cleaner import clean_ai_text
from app.services.deai_agent import deai_process
from app.routes.plagiarize import plagiarize_bp


STYLE_ANALYSIS_PROMPT = """你是一位专业的文学风格分析师。请分析以下文本的写作风格，输出 JSON 格式的分析报告。

分析维度：
1. 句式特征：句子长度分布、句式结构偏好（长短句比例、是否喜欢排比等）
2. 用词风格：词汇偏好（书面/口语、文雅/直白）、高频词、特殊表达
3. 叙事视角：第几人称、视角切换频率
4. 节奏特点：段落长度、信息密度、张弛节奏
5. 对话风格：对话比例、对话修饰方式、潜台词运用
6. 描写偏好：侧重哪些感官、描写密度、抽象vs具象比例
7. 情感表达：直接vs间接、内敛vs外放、常用情感意象
8. 独特标记：该作者/文本最具辨识度的写作特征

输出格式：
```json
{
  "sentence_features": {"avg_length": 15, "style": "...", "examples": ["..."]},
  "vocabulary": {"tone": "...", "high_frequency": ["..."], "unique_phrases": ["..."]},
  "narrative": {"pov": "...", "distance": "..."},
  "rhythm": {"paragraph_avg": 4, "density": "...", "pacing": "..."},
  "dialogue": {"ratio": 0.3, "style": "...", "subtext": "..."},
  "description": {"senses": ["..."], "density": "...", "abstract_ratio": 0.3},
  "emotion": {"style": "...", "imagery": ["..."]},
  "signature": ["特征1", "特征2", "特征3"],
  "summary": "一句话概括该文本的风格特点"
}
```"""


@plagiarize_bp.route("/<int:task_id>/analyze-style", methods=["POST"])
def analyze_style(task_id):
    """分析参考文本风格（流式）"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    
    if not task.source_text:
        return Response("请先提供参考文本", mimetype="text/plain", status=400)
    
    task.status = "generating"
    db.session.commit()
    
    messages = [
        {"role": "system", "content": STYLE_ANALYSIS_PROMPT},
        {"role": "user", "content": f"【参考文本】\n{task.source_text[:5000]}"},
    ]
    
    cfg = get_model_config(agent_type="audit")
    app = current_app._get_current_object()
    
    def generate():
        collected = []
        try:
            for text in stream_llm_tokens(
                model=cfg["model_name"],
                messages=messages,
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                provider_type=cfg.get("provider_type", "deepseek"),
                temperature=cfg["temperature"],
                max_tokens=cfg["max_tokens"],
            ):
                if text:
                    collected.append(text)
                    yield text
            full = "".join(collected)
            with app.app_context():
                t = db.session.get(PlagiarizeTask, task_id)
                if t:
                    t.style_report = full
                    t.status = "done"
                    db.session.commit()
        except LLMError as e:
            yield f"\n[分析失败: {e}]"
            with app.app_context():
                t = db.session.get(PlagiarizeTask, task_id)
                if t:
                    t.status = "failed"
                    t.error_message = str(e)
                    db.session.commit()
        except Exception as e:
            yield f"\n[分析失败: {e}]"
            with app.app_context():
                t = db.session.get(PlagiarizeTask, task_id)
                if t:
                    t.status = "failed"
                    t.error_message = str(e)
                    db.session.commit()
    
    return Response(generate(), mimetype="text/plain")


STYLE_WRITE_PROMPT = """你是一位专业的风格模仿写手。根据以下风格分析报告，用该风格创作新内容。

【风格分析报告】
{style_report}

【写作要求】
1. 严格遵循风格报告中的句式、用词、节奏特征
2. 保持原文的叙事视角和情感表达方式
3. 体现原文的独特标记（signature）
4. 创作新内容，不要复制原文

直接输出小说正文，不要输出创作说明。"""


@plagiarize_bp.route("/<int:task_id>/generate-style", methods=["POST"])
def generate_style(task_id):
    """基于风格分析生成新内容（流式）"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    extra = request.form.get("extra_instructions", "")
    
    if not task.style_report:
        return Response("请先进行风格分析", mimetype="text/plain", status=400)
    
    task.status = "generating"
    db.session.commit()
    
    system = STYLE_WRITE_PROMPT.format(style_report=task.style_report)
    
    if extra:
        system += f"\n\n【额外要求】\n{extra}"
    
    user_parts = []
    if task.source_text:
        user_parts.append(f"【参考文本片段】\n{task.source_text[:2000]}")
    user_parts.append("请用上述风格创作一段新内容（约1000字）：")
    
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]
    
    cfg = get_model_config(agent_type="writer")
    app = current_app._get_current_object()
    
    def generate():
        collected = []
        try:
            for text in stream_llm_tokens(
                model=cfg["model_name"],
                messages=messages,
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                provider_type=cfg.get("provider_type", "deepseek"),
                temperature=cfg["temperature"],
                max_tokens=4096,
            ):
                if text:
                    collected.append(text)
                    yield text
            full = deai_process(clean_ai_text("".join(collected)))
            with app.app_context():
                t = db.session.get(PlagiarizeTask, task_id)
                if t:
                    t.result_content = full
                    t.status = "done"
                    db.session.commit()
        except LLMError as e:
            yield f"\n[生成失败: {e}]"
            with app.app_context():
                t = db.session.get(PlagiarizeTask, task_id)
                if t:
                    t.status = "failed"
                    t.error_message = str(e)
                    db.session.commit()
        except Exception as e:
            yield f"\n[生成失败: {e}]"
            with app.app_context():
                t = db.session.get(PlagiarizeTask, task_id)
                if t:
                    t.status = "failed"
                    t.error_message = str(e)
                    db.session.commit()
    
    return Response(generate(), mimetype="text/plain")


@plagiarize_bp.route("/<int:task_id>/save-as-skill", methods=["POST"])
def save_as_skill(task_id):
    """将风格分析保存为自定义技能"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    skill_name = request.form.get("skill_name", "").strip()
    
    if not task.style_report or not skill_name:
        return jsonify({"error": "缺少风格报告或技能名称"}), 400
    
    try:
        import json as json_mod
        from app.services.skill_system import save_custom_skill
        
        # 从风格报告中提取关键特征作为 prompt
        report = json_mod.loads(task.style_report) if task.style_report.startswith('{') else {}
        signature = report.get("signature", [])
        summary = report.get("summary", "")
        
        prompt = f"""风格模仿技巧 — {skill_name}

风格特点：{summary}

关键特征：
{chr(10).join(f'- {s}' for s in signature)}

写作时请模仿以下风格：
- 句式：{report.get('sentence_features', {}).get('style', '自然流畅')}
- 用词：{report.get('vocabulary', {}).get('tone', '适中')}
- 节奏：{report.get('rhythm', {}).get('pacing', '张弛有度')}
- 对话：{report.get('dialogue', {}).get('style', '自然真实')}
- 描写：{report.get('description', {}).get('density', '适度')}"""
        
        save_custom_skill(skill_name, {
            "name": skill_name,
            "description": f"从参考文本提取的风格特征 - {summary[:50]}",
            "prompt": prompt,
            "constraints": "",
        })
        
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
