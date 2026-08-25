"""文风锚例（style anchor）测试：存储 / 开关 / prompt 格式化 / API。"""
from app import db
from app.models import Setting
from app.services.style_fingerprint import (
    save_anchor, load_anchor, anchor_enabled, set_anchor_enabled,
    format_anchor_for_prompt,
)

SAMPLE = (
    "路明非把作业本摊在桌上，发现今天的数学题长得像绕口令。"
    "他看了一眼窗外——操场上有人在打球，球弹起来的声音闷闷的，一下一下。"
) * 5  # >50 字，满足最短长度门槛


def teardown_function():
    Setting.query.filter(Setting.key.like("style_anchor%")).delete()
    db.session.commit()


def test_save_and_load_anchor(app):
    save_anchor(SAMPLE)
    assert load_anchor() == SAMPLE


def test_enabled_toggle(app):
    save_anchor(SAMPLE)
    set_anchor_enabled(True)
    assert anchor_enabled() is True
    set_anchor_enabled(False)
    assert anchor_enabled() is False


def test_format_block(app):
    save_anchor(SAMPLE)
    set_anchor_enabled(True)
    ctx = format_anchor_for_prompt()
    assert ctx.startswith("【文风锚例")
    assert SAMPLE[:20] in ctx
    assert "严禁复述" in ctx


def test_format_empty_when_disabled(app):
    save_anchor(SAMPLE)
    set_anchor_enabled(False)
    assert format_anchor_for_prompt() == ""


def test_format_empty_when_missing(app):
    set_anchor_enabled(True)
    assert format_anchor_for_prompt() == ""


def test_truncation_at_paragraph_boundary(app):
    paras = "\n\n".join("段落" + "字" * 400 for _ in range(8))
    save_anchor(paras)
    set_anchor_enabled(True)
    ctx = format_anchor_for_prompt()
    assert len(ctx) < 2400  # 截断上限（2000 字符 + 指令 + 省略号）
    assert "（节选）" in ctx


def test_api_get_save_toggle(client, app):
    r = client.post("/api/style-anchor", json={"text": SAMPLE})
    assert r.status_code == 200
    assert r.get_json()["len"] == len(SAMPLE)

    r = client.post("/api/style-anchor/toggle", json={"enabled": True})
    assert r.get_json()["enabled"] is True

    r = client.get("/api/style-anchor")
    data = r.get_json()
    assert data["text"] == SAMPLE
    assert data["enabled"] is True
