"""上下文分层(档0/档1)测试:节点 prompt 的缓存友好排序 + 出场角色筛选。"""

import pytest

from app import create_app, db
from app.models import ShortStory
from app.routes.short_story.prompts import build_node_prompt, _select_character_sections


@pytest.fixture
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        max_story = db.session.query(db.func.max(ShortStory.id)).scalar() or 0
        yield app
        ShortStory.query.filter(ShortStory.id > max_story).delete(synchronize_session=False)
        db.session.commit()


def _make_story(**kwargs):
    defaults = dict(title="分层测试", mode="inspiration", word_target=6000,
                    plan_characters="### 主角（主角）\n- 性格：冷静\n\n### 反派（反派）\n- 性格：残暴")
    defaults.update(kwargs)
    st = ShortStory(**defaults)
    db.session.add(st)
    db.session.commit()
    return st


NODES = [
    {"id": 1, "act": "第一幕", "title": "雨夜初遇", "summary": "主角在雨夜遇到神秘人",
     "word_count": 1000, "status": "done", "entities": ["主角", "神秘人"]},
    {"id": 2, "act": "第一幕", "title": "反派登场", "summary": "反派现身威胁主角",
     "word_count": 1000, "status": "pending", "entities": ["主角", "反派"]},
]


class TestLayerOrdering:
    """档0:静态前缀在前,动态在尾;无逐节点状态标记。"""

    def test_no_status_markers(self, app_ctx):
        st = _make_story()
        msgs = build_node_prompt(st, NODES, current_idx=1, prev_text="前文内容。" * 100)
        full = msgs[0]["content"] + msgs[1]["content"]
        assert "✓已写" not in full and "★当前" not in full and "○待写" not in full

    def test_static_before_dynamic(self, app_ctx):
        st = _make_story()
        msgs = build_node_prompt(st, NODES, current_idx=1, prev_text="前文内容。" * 100)
        system, user = msgs[0]["content"], msgs[1]["content"]
        # 层2(大纲,静态)在 user;层4(前文/指令)在 user 尾部
        assert "完整剧情大纲" in user
        assert user.find("完整剧情大纲") < user.find("前文内容") < user.find("现在请写")
        # 当前节点信息在尾部指令里(不在大纲行做动态标注)
        assert "现在请写【节点2" in user
        # system 里没有大纲(大纲是篇级静态,但放 user 层2;system 只放全站静态)
        assert "完整剧情大纲" not in system

    def test_tone_instruction_in_user_tail(self, app_ctx):
        """tone_inst 每次调用都变——必须放 user 尾部而非 system(否则杀死缓存)。"""
        st = _make_story()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.services.ai_metric.build_tone_instructions",
                       lambda text: "【修正】避免跨段重复")
            msgs = build_node_prompt(st, NODES, current_idx=1, prev_text="前文内容。" * 100)
        system, user = msgs[0]["content"], msgs[1]["content"]
        assert "避免跨段重复" not in system
        assert "避免跨段重复" in user
        assert user.find("避免跨段重复") > user.find("前文内容")

    def test_cross_node_prefix_stable(self, app_ctx):
        """同篇相邻节点:system 与静态 user 前缀逐字一致(缓存命中前提)。"""
        st = _make_story()
        m1 = build_node_prompt(st, NODES, current_idx=0, prev_text="")
        m2 = build_node_prompt(st, NODES, current_idx=1, prev_text="前文。")
        assert m1[0]["content"] == m2[0]["content"], "system 必须逐字节一致"
        # user 的静态头(角色/场景/主题/概念/大纲,到前文或指令之前)一致
        def static_head(content):
            head = content.split("【前文内容")[0].split("现在请写")[0]
            return head.rstrip()  # 尾部 join 分隔符换行数不算内容差异
        assert static_head(m1[1]["content"]) == static_head(m2[1]["content"])


class TestCharacterSelector:
    """档1:出场角色筛选——首节常驻+按节点文本命中;无结构回退整块。"""

    def test_selects_by_node_text(self):
        ctx = "### 主角（主角）\n- 性格：冷静\n\n### 反派（反派）\n- 性格：残暴\n\n### 路人（配角）\n- 性格：模糊"
        text, names = _select_character_sections(ctx, "反派现身威胁")
        assert "主角" in text and "反派" in text
        assert "路人" not in text
        assert names == ["主角", "反派"]

    def test_first_section_always_included(self):
        ctx = "### 主角（主角）\n- 性格：冷静\n\n### 反派（反派）\n- 性格：残暴"
        text, names = _select_character_sections(ctx, "完全无关的内容")
        assert "主角" in text
        assert "反派" not in text

    def test_unstructured_blob_fallback(self):
        ctx = "主角:冷静,寡言,复仇者。"
        text, names = _select_character_sections(ctx, "任意")
        assert text == ctx
        assert names == []

    def test_union_selection_by_outline(self, app_ctx):
        """联合筛选:全书大纲(含 entities)命中的角色入选;全书未提及的不注入。
        集合对同篇所有节点一致 → 前缀稳定。"""
        blob = "### 主角（主角）\n- 性格：冷静\n\n### 反派（反派）\n- 性格：残暴\n\n### 工具人（配角）\n- 性格：模糊"
        st = _make_story(plan_characters=blob)
        nodes = [dict(n) for n in NODES]
        msgs = build_node_prompt(st, nodes, current_idx=1, prev_text="")
        user = msgs[1]["content"]
        assert "冷静" in user and "残暴" in user   # 大纲提到主角/反派 → 入选
        assert "模糊" not in user                  # 工具人全书未提及 → 不注入
