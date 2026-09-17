# -*- coding: utf-8 -*-
"""04_outline.py —— 落地大纲树（卷 → 章 → 场景）。

读 <content-dir>/outline.json（嵌套结构，children 顺序即叙事顺序）：
    [
      { "title": "第一卷：…", "type": "volume", "summary": "…",
        "children": [
          { "title": "第1章 …", "type": "chapter", "summary": "…",
            "children": [ { "title": "场景名", "type": "scene", "summary": "…" } ] }
        ] }
    ]

要点（出自 CLI建库要点.md）：
  - sort_order 由 cli.py 按 (novel, parent) 自增 → **调用顺序即叙事顺序**，必须按序落库。
  - 本脚本只建大纲节点，不建正文章节；实例化交给 07_instantiate_chapters.py。

防重跑：本书 outline_nodes 表必须为空。写完 state.outline = {"nodes": [...]}（含 ID 清单）。
"""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402

VALID_TYPES = ("volume", "chapter", "scene")


def main():
    ap = L.content_parser("04 大纲树")
    args = ap.parse_args()
    L.set_dry_run(args.dry_run)
    L.banner("04 大纲树")

    nid = L.require_novel_id(args.content_dir)
    tree = L.load_list(os.path.join(args.content_dir, "outline.json"), "outline.json")

    if not L.is_dry():
        L.assert_novel_empty(nid, "outline_nodes")

    manifest = []

    def walk(nodes, parent_id, path):
        for node in nodes:
            title = str(node.get("title", "")).strip()
            ntype = (node.get("type") or "chapter").strip()
            summary = node.get("summary", "") or ""
            if not title:
                raise SystemExit("大纲节点缺 title（路径 %s）" % path)
            if ntype not in VALID_TYPES:
                raise SystemExit("节点《%s》type 非法：%s（合法：%s）" % (title, ntype, "/".join(VALID_TYPES)))
            here = "%s/%s" % (path, title)
            argv = ["outline", "create", "--novel", str(nid), "--title", title,
                    "--type", ntype, "--summary", summary]
            if parent_id:
                argv += ["--parent", str(parent_id)]
            r = L.run_write(argv)
            new_id = L.parse_new_id(r, "大纲节点 %s" % title)
            manifest.append({"path": here, "id": new_id, "type": ntype, "title": title,
                             "parent_id": parent_id, "summary_len": len(summary)})
            children = node.get("children") or []
            if children:
                if new_id is None:
                    raise SystemExit("dry-run 下无法继续下钻子节点（《%s》），请先去掉 --dry-run" % title)
                walk(children, new_id, here)

    walk(tree, None, "")

    if L.is_dry():
        L.warn("dry-run：不写状态文件")
        return

    L.save_state(args.content_dir, {"outline": {"nodes": manifest}})

    rows = L.sql_rows("select id, parent_id, sort_order, node_type, title, summary"
                      " from outline_nodes where novel_id=? order by id", (nid,))
    L.step("核验")
    L.ok("库中大纲节点 = %d（期望 %d）" % (len(rows), len(manifest)))
    if len(rows) != len(manifest):
        raise SystemExit("节点数量不符，请检查")
    L.info("类型分布：%s" % dict(Counter(r["node_type"] for r in rows)))

    # 父子归属校验（防跨书/断链）
    ids = {r["id"] for r in rows}
    broken = [r["title"] for r in rows if r["parent_id"] and r["parent_id"] not in ids]
    if broken:
        raise SystemExit("以下节点父节点不在本书：%s" % "、".join(broken))

    empty_summary = [r["title"] for r in rows if not (r["summary"] or "").strip()]
    if empty_summary:
        L.warn("摘要为空 %d 个：%s" % (len(empty_summary), "、".join(empty_summary[:8])))
    chapters = [m for m in manifest if m["type"] == "chapter"]
    L.info("其中 chapter 类型节点 %d 个 → 由 07 实例化成章节" % len(chapters))
    if not chapters:
        L.warn("没有任何 chapter 类型节点，07 会无事可做")


if __name__ == "__main__":
    main()
