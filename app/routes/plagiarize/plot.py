"""情节借鉴功能 — 提取参考文本情节骨架，套用到新设定。"""
from flask import request, Response, jsonify, current_app
from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError
from app.models import db, PlagiarizeTask
from app.config_utils import get_model_config
from app.services.text_cleaner import clean_ai_text
from app.services.deai_agent import deai_process
from app.routes.plagiarize import plagiarize_bp


PLOT_EXTRACT_PROMPT = """你是一位专业的故事结构分析师。请分析以下文本的情节结构，输出 JSON 格式的骨架。

分析维度：
1. 核心冲突：故事的主要矛盾是什么
2. 情节节点：按时间顺序列出关键事件（起因→发展→高潮→结局）
3. 人物弧光：主角从开始到结束的变化
4. 转折点：改变故事走向的关键时刻
5. 张力曲线：哪里最紧张、哪里最舒缓
6. 主题内核：故事想表达什么

输出格式：
```json
{
  "core_conflict": "...",
  "plot_points": [
    {"phase": "起因", "event": "...", "purpose": "..."},
    {"phase": "发展", "event": "...", "purpose": "..."},
    {"phase": "高潮", "event": "...", "purpose": "..."},
    {"phase": "结局", "event": "...", "purpose": "..."}
  ],
  "character_arc": {"start": "...", "end": "...", "change": "..."},
  "turning_points": [
    {"moment": "...", "impact": "..."}
  ],
  "tension_curve": [{"point": "...", "level": "high/medium/low"}],
  "theme": "...",
  "summary": "一句话概括这个故事的核心情节"
}
```"""


@plagiarize_bp.route("/<int:task_id>/extract-plot", methods=["POST"])
def extract_plot(task_id):
    """提取情节骨架（流式）"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    
    if not task.source_text:
        return Response("请先提供参考文本", mimetype="text/plain", status=400)
    
    task.status = "generating"
    db.session.commit()
    
    messages = [
        {"role": "system", "content": PLOT_EXTRACT_PROMPT},
        {"role": "user", "content": f"【参考文本】\n{task.source_text[:8000]}"},
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
                    t.style_report = full  # 复用 style_report 字段存储情节分析
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


PLOT_WRITE_PROMPT = """你是一位专业的小说作家。根据以下情节骨架，用全新的角色和设定重新创作这个故事。

【情节骨架】
{plot_skeleton}

【创作要求】
1. 保持情节骨架的核心结构（冲突、节点、转折、主题）
2. 使用全新的角色名字和性格
3. 使用全新的世界观和场景
4. 添加丰富的细节、对话、心理描写
5. 让故事读起来像原创，不是改编

直接输出小说正文，标题用一级标题格式，不要输出创作说明。"""


@plagiarize_bp.route("/<int:task_id>/generate-plot", methods=["POST"])
def generate_plot(task_id):
    """基于情节骨架生成新故事（流式）"""
    task = PlagiarizeTask.query.get_or_404(task_id)
    extra = request.form.get("extra_instructions", "")
    
    if not task.style_report:
        return Response("请先提取情节骨架", mimetype="text/plain", status=400)
    
    task.status = "generating"
    db.session.commit()
    
    system = PLOT_WRITE_PROMPT.format(plot_skeleton=task.style_report)
    
    if extra:
        system += f"\n\n【额外要求】\n{extra}"
    
    user_parts = ["请根据上述情节骨架创作一个全新的故事（约2000字）："]
    
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
                max_tokens=6144,
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
