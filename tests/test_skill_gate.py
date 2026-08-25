# -*- coding: utf-8 -*-
"""技能质量门禁（skill_gate）测试。"""
from app.services.skill_gate import run_gate

DEFAULT5 = ["rhythm_breaking", "sensory_concrete", "imperfection",
            "dialogue_humanize", "deai_structure"]


class TestGateClean:
    def test_clean_text_passes(self):
        text = ("他把碗端起来，又放下。饭粒粘在筷子尖上，半天没夹起来。\n\n"
                "巷口只剩烧烤摊翻铁签子的声音。一下，又一下。")
        rep = run_gate(text, active_skills=DEFAULT5)
        assert rep["passed"] is True
        assert all(c["passed"] for c in rep["checks"])

    def test_inactive_skill_not_checked(self):
        rep = run_gate("她愤怒地说道。", active_skills=[])
        assert rep["passed"] is True
        assert rep["checks"] == []


class TestGateViolations:
    def test_dialogue_modifier_detected(self):
        rep = run_gate("\u201c你竟然敢骗我！\u201d她愤怒地说道。",
                       active_skills=["dialogue_realism"])
        check = next(c for c in rep["checks"] if c["skill"] == "dialogue_realism")
        assert not check["passed"]
        assert check["violations"]

    def test_ending_uplift_detected(self):
        body = "他走出门，把烟掐了。" * 40
        text = body + "这一刻，他终于明白了父亲沉默背后的良苦用心，眼眶不禁湿润了。"
        rep = run_gate(text, active_skills=["imperfection"])
        check = next(c for c in rep["checks"] if c["skill"] == "imperfection")
        assert not check["passed"]

    def test_parallel_triad_detected(self):
        text = "山上的石头有的像猴子，有的像大象，有的像仙人，姿态万千。"
        rep = run_gate(text, active_skills=["rhythm_breaking"])
        check = next(c for c in rep["checks"] if c["skill"] == "rhythm_breaking")
        assert not check["passed"]

    def test_template_structure_detected(self):
        text = "首先，他去了邮局寄信。其次，他在菜市场买了菜。最后，他回了家。"
        rep = run_gate(text, active_skills=["deai_structure"])
        check = next(c for c in rep["checks"] if c["skill"] == "deai_structure")
        assert not check["passed"]

    def test_tell_emotion_detected(self):
        rep = run_gate("她非常伤心，眼泪流了下来。她很紧张地攥着衣角。",
                       active_skills=["show_dont_tell"])
        check = next(c for c in rep["checks"] if c["skill"] == "show_dont_tell")
        assert not check["passed"]
        assert len(check["violations"]) >= 2

    def test_abstract_sensory_detected(self):
        rep = run_gate("房间里有一股难闻的气味，周围十分安静。",
                       active_skills=["sensory_concrete"])
        check = next(c for c in rep["checks"] if c["skill"] == "sensory_concrete")
        assert not check["passed"]

    def test_plain_quiet_also_detected(self):
        """「周围很安静」这类最高频写法也要能抓到。"""
        rep = run_gate("屋里很安静，只听得见钟摆声。",
                       active_skills=["sensory_concrete"])
        check = next(c for c in rep["checks"] if c["skill"] == "sensory_concrete")
        assert not check["passed"]

    def test_possessive_fragment_style_not_flagged(self):
        """「他的手。他的刀。他的命。」是合法碎句修辞，不算排比违规。"""
        text = "他的手。他的刀。他的命。全都留在了那座山上。"
        rep = run_gate(text, active_skills=["rhythm_breaking"])
        check = next(c for c in rep["checks"] if c["skill"] == "rhythm_breaking")
        assert check["passed"]


class TestGateAPI:
    def test_gate_endpoint(self, client):
        resp = client.post("/api/skills/gate-check",
                           json={"text": "\u201c哼。\u201d他冷冷道。"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "passed" in data and "checks" in data

    def test_gate_endpoint_requires_text(self, client):
        resp = client.post("/api/skills/gate-check", json={})
        assert resp.status_code == 400
