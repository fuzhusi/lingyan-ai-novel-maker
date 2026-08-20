"""改写洗稿功能 — 同义替换、句式变换、结构重组。"""
from flask import request, Response, jsonify, current_app
from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError
from app.models import db, PlagiarizeTask
from app.config_utils import get_model_config
from app.services.text_cleaner import clean_ai_text
from app.services.deai_agent import deai_process
from app.routes.plagiarize import plagiarize_bp


REWRITE_PROMPTS = {
    "light": """你是一位专业的文本改写专家。请对以下文本进行【轻度改写】。

改写规则：
1. 保留原文的段落结构和情节走向
2. 替换同义词（但保留专有名词和术语）
3. 变换句式（主动↔被动、长句↔短句）
4. 调整语序，但不改变原意
5. 保持原文的风格和语气

目标：让文本看起来是"不同作者写的同一个故事"，而不是"同一个作者的复制粘贴"。""",
    
    "medium": """你是一位专业的文本改写专家。请对以下文本进行【中度改写】。

改写规则：
1. 重组段落顺序（在不影响情节连贯性的前提下）
2. 改变叙事视角（如第三人称→第一人称，或调整聚焦角色）
3. 增删细节描写（添加新的感官细节，删除部分描写）
4. 变换对话风格（调整语气、增删对话）
5. 保持核心情节和冲突不变

目标：让文本看起来是"基于同一个故事大纲的不同作品"。""",
    
    "heavy": """你是一位专业的文本改写专家。请对以下文本进行【重度改写】。

改写规则：
1. 只保留核心情节骨架（冲突→发展→高潮→结局）
2. 完全重写所有场景和描写
3. 更换所有角色名字（如果有的话）
4. 改变故事的氛围和风格基调
5. 添加全新的细节和支线
6. 保持主题内核不变

目标：让文本看起来是"灵感来源于原文的全新原创作品"。""",
}


@plagiarize_bp.route("/<int:task_id>/rewrite", methods=["POST"])
def rewrite_text(task_id):
    """改写文本（流式）"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    level = request.form.get("level", task.rewrite_level or "medium")
    extra = request.form.get("extra_instructions", "")
    
    if not task.source_text:
        return Response("请先提供原文", mimetype="text/plain", status=400)
    
    task.rewrite_level = level
    task.status = "generating"
    db.session.commit()
    
    system = REWRITE_PROMPTS.get(level, REWRITE_PROMPTS["medium"])
    
    if extra:
        system += f"\n\n【额外要求】\n{extra}"
    
    system += "\n\n直接输出改写后的完整文本，不要输出改写说明或对比。"
    
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"【原文】\n{task.source_text}"},
    ]
    
    cfg = get_model_config(agent_type="rewrite")
    app = current_app._get_current_object()
    word_target = len(task.source_text)
    
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
                max_tokens=max(word_target * 2, 4096),
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
            yield f"\n[改写失败: {e}]"
            with app.app_context():
                t = db.session.get(PlagiarizeTask, task_id)
                if t:
                    t.status = "failed"
                    t.error_message = str(e)
                    db.session.commit()
        except Exception as e:
            yield f"\n[改写失败: {e}]"
            with app.app_context():
                t = db.session.get(PlagiarizeTask, task_id)
                if t:
                    t.status = "failed"
                    t.error_message = str(e)
                    db.session.commit()
    
    return Response(generate(), mimetype="text/plain")
