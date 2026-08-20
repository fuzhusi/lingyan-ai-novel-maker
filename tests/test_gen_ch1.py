"""一次性脚本：CLI 触发第一章生成（非流式，复用项目内的 prompt + deai + save_version）"""
import json
import httpx
from app import create_app
from app.models import db, Novel, Chapter, ChapterVersion
from app.routes.settings import get_effective_config
from app.routes.generate import _stream_to_sse
from app.services.prompt_builder import (
    build_writer_prompt, assemble_chapter_context,
)
from app.routes.chapter import save_version
from flask import request
from werkzeug.datastructures import ImmutableMultiDict


def main():
    app = create_app()
    with app.app_context():
        novel_id = 4
        chapter_number = 1
        user_directive = (
            "风格参考：江南（龙族作者）。散文底色，留白多用，短句为主。\n"
            "主角邱于：22岁师范大学退学青年，戴老式黑框眼镜，说话停顿、回避形容词。"
            "夜里失眠、被动、对多数事情保持旁观式的安静。\n"
            "场景：凌晨两点半，邱于在槐安巷尾推开那扇木门。铜铃响了一声，店里没人，"
            "桌上小本子翻开着，最后一页是沈雾的字迹'交给你了'。\n"
            "重点氛围：不要解释世界观、不要抒情铺陈、不要用'仿佛/宛如/不禁'这类 AI 禁用词。"
            "靠动作和细节推进，给读者留白。第一章停在'他坐在那把本应该由别人坐的椅子上，"
            "台灯暖黄，门外巷子还黑着'这一行附近。"
        )

        novel = Novel.query.get(novel_id)
        chapter = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first()
        if not chapter:
            print("ERROR: 章节不存在")
            return

        # 1) 装配上下文（角色/世界观/伏笔/记忆/信息边界/时序/风格/技巧）
        ctx = assemble_chapter_context(novel_id, chapter_number, db)
        kw = {
            "characters": ctx["characters"],
            "world_settings": ctx["world_settings"],
            "summaries": ctx["summaries"],
            "foreshadowing_items": ctx["foreshadowing_items"],
            "synopsis": ctx["synopsis"],
            "world_intro": ctx["world_intro"],
            "outline_node_context": ctx["outline_node_context"],
        }
        # 因果链
        try:
            from app.services.causal_chain import get_chain_context, format_chain_for_prompt
            kw["causal_chain"] = format_chain_for_prompt(get_chain_context(novel_id, chapter_number))
        except Exception as e:
            print(f"[跳过] 因果链: {e}")
        # 向量记忆
        try:
            from app.services.vector_memory import build_context_for_chapter
            kw["memory_context"] = build_context_for_chapter(novel_id, chapter_number, chapter.outline or "")
        except Exception as e:
            print(f"[跳过] 向量记忆: {e}")
        # 信息边界
        try:
            from app.services.info_boundary import format_knowledge_boundaries
            boundary_ctx = format_knowledge_boundaries(novel_id, chapter_number)
            if boundary_ctx:
                kw["memory_context"] = (kw.get("memory_context", "") + "\n\n" + boundary_ctx).strip()
        except Exception as e:
            print(f"[跳过] 信息边界: {e}")
        # 时序真理
        try:
            from app.services.temporal_truth import format_truths_for_prompt
            truth_ctx = format_truths_for_prompt(novel_id, chapter_number)
            if truth_ctx:
                kw["memory_context"] = (kw.get("memory_context", "") + "\n\n" + truth_ctx).strip()
        except Exception as e:
            print(f"[跳过] 时序真理: {e}")

        # 2) 拼提示词
        messages = build_writer_prompt(
            novel_title=novel.title,
            chapter_title=chapter.title,
            outline=chapter.outline or "",
            user_directive=user_directive,
            db=db,
            **kw,
        )

        # 3) 取 writer 配置
        cfg = get_effective_config(novel, agent_type="writer")
        print(f"[模型] {cfg['model_name']} | temp={cfg['temperature']} | max_tokens={cfg['max_tokens']}")

        # 4) 非流式调用 API（避免流式解析）
        try:
            with httpx.Client(
                timeout=httpx.Timeout(300.0, connect=10.0),
                verify=False,
            ) as client:
                resp = client.post(
                    f"{cfg['base_url']}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {cfg['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": cfg["model_name"],
                        "messages": messages,
                        "stream": False,
                        "temperature": cfg["temperature"],
                        "max_tokens": cfg["max_tokens"],
                    },
                )
        except Exception as e:
            print(f"ERROR: API 请求失败: {e}")
            return

        if resp.status_code != 200:
            print(f"ERROR: HTTP {resp.status_code} | {resp.text[:500]}")
            return

        result = resp.json()
        content = result["choices"][0]["message"]["content"]
        usage = result.get("usage", {})
        print(f"[用量] prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')} total={usage.get('total_tokens')}")
        print(f"[生成字数] {len(content)}")

        # 5) 模拟 save_version 流程：clean + deai + 入库
        from app.services.text_cleaner import clean_ai_text
        from app.services.deai_agent import deai_process

        cleaned = clean_ai_text(content)
        deai = deai_process(cleaned)
        print(f"[De-AI 后] {len(deai)} 字")

        max_ver = db.session.query(db.func.max(ChapterVersion.version_number)).filter_by(chapter_id=chapter.id).scalar()
        version_number = (max_ver or 0) + 1

        # 序列化 messages 作为 prompt_used 记录
        prompt_used = json.dumps(messages, ensure_ascii=False)
        model_params = json.dumps({
            "model": cfg["model_name"],
            "temperature": cfg["temperature"],
            "max_tokens": cfg["max_tokens"],
        })

        version = ChapterVersion(
            chapter_id=chapter.id,
            version_number=version_number,
            content=deai,
            source="ai",
            prompt_used=prompt_used,
            model_params_json=model_params,
        )
        db.session.add(version)
        db.session.commit()
        print(f"✓ 已保存版本 v{version_number} (id={version.id})，共 {len(deai)} 字")

        # 6) 预览前 600 字
        print("\n--- 预览 ---")
        print(deai[:600])
        print("--- 完 ---\n")


if __name__ == "__main__":
    main()