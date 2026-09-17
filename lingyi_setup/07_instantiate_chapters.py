# -*- coding: utf-8 -*-
"""07_instantiate_chapters.py —— 把大纲里的 chapter 节点实例化成正文章节。

数据来源：<content-dir>/_state.json 里 04_outline.py 写下的 state.outline.nodes
（含每个节点的 ID、类型、路径）。本脚本按**落库顺序**过滤出 chapter 节点，
逐个调用 `outline create-chapter`。

⚠️ 坑 4：`outline create-chapter` 不校验节点类型，且章号 = 当前最大值 + 1。
   所以这里必须（a）只对 chapter 节点调用，（b）严格按叙事顺序调用。
   它同时会写 outline_node_id（章节↔大纲关联）并把 scene 子节点拼成「分幕指引」。
   —— 正文章节一律走这条路，不要用 `chapter create`（那条不写 outline_node_id）。

防重跑：本书 chapters 表必须为空。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402


def main():
    ap = L.content_parser("07 实例化章节")
    args = ap.parse_args()
    L.set_dry_run(args.dry_run)
    L.banner("07 大纲节点 → 正文章节")

    nid = L.require_novel_id(args.content_dir)
    state = L.load_state(args.content_dir)
    nodes = (state.get("outline") or {}).get("nodes")
    if not nodes:
        raise SystemExit("state 里没有大纲清单——先跑 04_outline.py")

    chapters = [n for n in nodes if n.get("type") == "chapter"]
    if not chapters:
        raise SystemExit("大纲里没有 chapter 类型节点，无事可做")
    L.info("novel_id=%d，将实例化 %d 章（按落库顺序）" % (nid, len(chapters)))

    if not L.is_dry():
        L.assert_novel_empty(nid, "chapters")

    if L.is_dry():
        for i, n in enumerate(chapters, 1):
            print("   [dry] 第%d章 ← 大纲节点 [%s] %s" % (i, n["id"], n["title"]))
        return

    for n in chapters:
        L.run_write(["outline", "create-chapter", "--novel", str(nid), "--id", str(n["id"])])

    # ---------------------------------------------------------------- 核验
    rows = L.sql_rows("select c.chapter_number, c.title, c.outline, c.outline_node_id,"
                      " c.user_directive,"
                      " (select count(*) from outline_nodes o where o.parent_id=c.outline_node_id"
                      "  and o.node_type='scene') as scenes"
                      " from chapters c where c.novel_id=? order by c.chapter_number", (nid,))
    L.step("核验")
    L.ok("库中章节 = %d（期望 %d）" % (len(rows), len(chapters)))
    if len(rows) != len(chapters):
        raise SystemExit("章节数量不符，请检查")

    problems = []
    for i, (row, node) in enumerate(zip(rows, chapters), 1):
        if row["chapter_number"] != i:
            problems.append("章号错位：第 %s 章（期望 %d）" % (row["chapter_number"], i))
        if (row["title"] or "").strip() != node["title"].strip():
            problems.append("标题错位：第 %d 章「%s」≠ 大纲「%s」" % (i, row["title"], node["title"]))
        if not row["outline_node_id"]:
            problems.append("第 %d 章未关联大纲节点" % i)
        if not (row["outline"] or "").strip():
            problems.append("第 %d 章大纲为空（生成时无本章指引）" % i)
    if problems:
        for p in problems[:12]:
            L.warn(p)
        raise SystemExit("实例化核验失败 %d 项——章号靠调用顺序累加，错位说明顺序不对" % len(problems))

    with_scenes = sum(1 for r in rows if r["scenes"])
    L.ok("章号 1..%d 连续、标题与大纲一一对应、outline_node_id 全部就位" % len(rows))
    L.info("其中 %d 章带 scene 子节点（已并入「分幕指引」）" % with_scenes)
    L.info("下一步：先跑 00_preflight.py --backup，再逐章生成")
    L.info("        cli.py chapter pipeline --novel %d --number 1 --dry-run" % nid)
    L.info("        cli.py chapter pipeline --novel %d --number 1 --save" % nid)


if __name__ == "__main__":
    main()
