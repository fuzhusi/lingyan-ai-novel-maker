# -*- coding: utf-8 -*-
"""02_characters.py —— 落地角色卡（6 字段）。

读 <content-dir>/characters.json：
    [
      {
        "name": "姓名",
        "personality": "性格",
        "speaking_style": "说话风格",
        "appearance": "外貌",
        "background": "背景",
        "motivation": "动机",
        "arc": "角色弧光"
      }
    ]

防重跑：本书 characters 表必须为空。
写完 state.characters = {姓名: ID}（供 06_relations.py 用姓名引用）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402

FIELDS = [("personality", "性格"), ("speaking_style", "说话风格"), ("appearance", "外貌"),
          ("background", "背景"), ("motivation", "动机"), ("arc", "角色弧光")]


def main():
    ap = L.content_parser("02 角色卡")
    args = ap.parse_args()
    L.set_dry_run(args.dry_run)
    L.banner("02 角色卡")

    nid = L.require_novel_id(args.content_dir)
    items = L.load_list(os.path.join(args.content_dir, "characters.json"), "characters.json")
    L.info("novel_id=%d，待落库角色 %d 张" % (nid, len(items)))

    names = [str(c.get("name", "")).strip() for c in items]
    if "" in names:
        raise SystemExit("有角色缺 name")
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise SystemExit("角色重名：%s（DB 层无唯一约束，重名会造成两种同名角色）" % "、".join(sorted(dup)))

    if not L.is_dry():
        L.assert_novel_empty(nid, "characters")

    mapping = {}
    warn_fields = []
    for i, c in enumerate(items, 1):
        name = str(c["name"]).strip()
        for key, zh in FIELDS:
            if not (c.get(key) or "").strip():
                warn_fields.append("%s 的「%s」为空" % (name, zh))
        r = L.run_write(["character", "create", "--novel", str(nid), "--name", name,
                         "--personality", c.get("personality", ""),
                         "--speaking-style", c.get("speaking_style", ""),
                         "--appearance", c.get("appearance", ""),
                         "--background", c.get("background", ""),
                         "--motivation", c.get("motivation", ""),
                         "--arc", c.get("arc", "")])
        cid = L.parse_new_id(r, "角色 %s" % name)
        if cid:
            mapping[name] = cid

    if L.is_dry():
        L.warn("dry-run：不写状态文件")
        return

    L.save_state(args.content_dir, {"characters": mapping})

    # 落库后回读核验（字段完整性 + 数量）
    rows = L.sql_rows("select name, personality, speaking_style, appearance, background,"
                      " motivation, arc_direction from characters where novel_id=?", (nid,))
    L.step("核验")
    L.ok("库中角色数 = %d（期望 %d）" % (len(rows), len(items)))
    if len(rows) != len(items):
        raise SystemExit("角色数量不符，请检查")
    if warn_fields:
        L.warn("字段为空 %d 处（不影响落库，但会削弱生成上下文质量）：" % len(warn_fields))
        for w in warn_fields:
            L.warn("  " + w)
    else:
        L.ok("6 字段全部非空")


if __name__ == "__main__":
    main()
