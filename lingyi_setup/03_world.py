# -*- coding: utf-8 -*-
"""03_world.py —— 落地世界观条目。

读 <content-dir>/world.json：
    [ { "category": "灵异规则", "title": "标题", "content": "正文（300-600 字为宜）" } ]

分类建议（本书拟用，便于 Web 端聚合）：
    灵异规则 / 行业规矩与代价 / 法器与法事 / 地理与场所 / 行当与人情 / 时间线 / 民俗禁忌

防重跑：本书 world_settings 表必须为空。写完 state.world = {标题: ID}。
"""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402


def main():
    ap = L.content_parser("03 世界观")
    args = ap.parse_args()
    L.set_dry_run(args.dry_run)
    L.banner("03 世界观条目")

    nid = L.require_novel_id(args.content_dir)
    items = L.load_list(os.path.join(args.content_dir, "world.json"), "world.json")
    L.info("novel_id=%d，待落库条目 %d 条" % (nid, len(items)))

    titles = [str(x.get("title", "")).strip() for x in items]
    if "" in titles:
        raise SystemExit("有世界观条目缺 title")
    dup = {t for t in titles if titles.count(t) > 1}
    if dup:
        raise SystemExit("世界观重名：%s" % "、".join(sorted(dup)))
    bad_cat = [t for t, x in zip(titles, items) if not (x.get("category") or "").strip()]
    if bad_cat:
        raise SystemExit("以下条目缺 category（Web 端聚合依赖它）：%s" % "、".join(bad_cat))

    if not L.is_dry():
        L.assert_novel_empty(nid, "world_settings")

    mapping = {}
    short = []
    for x in items:
        title = str(x["title"]).strip()
        body = x.get("content", "") or ""
        if len(body) < 120:
            short.append("%s（%d 字）" % (title, len(body)))
        r = L.run_write(["world", "create", "--novel", str(nid),
                         "--category", x.get("category", ""),
                         "--title", title,
                         "--content", body])
        wid = L.parse_new_id(r, "世界观 %s" % title)
        if wid:
            mapping[title] = wid

    if L.is_dry():
        L.warn("dry-run：不写状态文件")
        return

    L.save_state(args.content_dir, {"world": mapping})

    rows = L.sql_rows("select category, title, content from world_settings where novel_id=?", (nid,))
    L.step("核验")
    L.ok("库中条目数 = %d（期望 %d）" % (len(rows), len(items)))
    if len(rows) != len(items):
        raise SystemExit("条目数量不符，请检查")
    L.info("分类分布：%s" % dict(Counter(r["category"] for r in rows)))
    if short:
        L.warn("以下条目偏短（<120 字），可能撑不起生成时的设定注入：")
        for s in short:
            L.warn("  " + s)


if __name__ == "__main__":
    main()
