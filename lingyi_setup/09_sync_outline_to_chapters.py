# -*- coding: utf-8 -*-
"""09_sync_outline_to_chapters.py —— 把 outline.json 的摘要同步到「大纲节点」与「正文章节」。

为什么需要它：
  `outline create-chapter` 是在**实例化那一刻**把大纲摘要复制进 `chapters.outline` 的。
  之后你再改 content/outline.json（改章纲、改钩子、改人物口径），库里的章节指引**不会自动跟着变**，
  生成时注入的仍是旧摘要——"我明明改了，怎么还是老样子"就是这么来的。

它做两件事（都按标题匹配，标题是章节与大纲节点的唯一对应）：
  1. 摘要变了的 outline 节点 → `outline update --id N --summary …`
  2. 摘要变了的章节 → `chapter update --novel N --number M --outline …`

用法：
    .venv/Scripts/python.exe lingyi_setup/09_sync_outline_to_chapters.py            # 预演（只报告差异）
    .venv/Scripts/python.exe lingyi_setup/09_sync_outline_to_chapters.py --apply    # 真正写入
    .venv/Scripts/python.exe lingyi_setup/09_sync_outline_to_chapters.py --apply --numbers 1,2,3
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402


def collect_chapters(tree, out):
    for node in tree:
        if (node.get("type") or "").lower() == "chapter":
            title = str(node.get("title", "")).strip()
            summary = (node.get("summary") or "").strip()
            out.append((title, summary))
        collect_chapters(node.get("children") or [], out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--novel", type=int)
    ap.add_argument("--content-dir", default=L.DEFAULT_CONTENT)
    ap.add_argument("--numbers", help="只同步这些章号，如 1,2,3")
    ap.add_argument("--apply", action="store_true", help="真正写入（缺省只预演）")
    args = ap.parse_args()

    L.banner("09 同步大纲摘要 → 节点与章节")
    nid = args.novel or L.require_novel_id(args.content_dir)
    tree = L.load_list(os.path.join(args.content_dir, "outline.json"), "outline.json")

    wanted = None
    if args.numbers:
        wanted = {int(x) for x in args.numbers.replace("，", ",").split(",") if x.strip()}

    items = []
    collect_chapters(tree, items)
    L.info("outline.json 里 chapter 节点 %d 个" % len(items))

    chapters = L.sql_rows("select chapter_number, title, outline from chapters"
                          " where novel_id=? order by chapter_number", (nid,))
    by_title = {r["title"].strip(): r for r in chapters}
    nodes = L.sql_rows("select id, title, summary from outline_nodes"
                       " where novel_id=? and node_type='chapter'", (nid,))
    node_by_title = {r["title"].strip(): r for r in nodes}

    ch_changes, node_changes, missing = [], [], []
    for idx, (title, summary) in enumerate(items, 1):
        if wanted and idx not in wanted:
            continue
        ch = by_title.get(title)
        nd = node_by_title.get(title)
        if not ch:
            missing.append("第 %d 章《%s》在库里找不到同名章节" % (idx, title))
            continue
        if (ch["outline"] or "").strip() != summary:
            ch_changes.append((ch["chapter_number"], title, len(ch["outline"] or ""), len(summary)))
        if nd and (nd["summary"] or "").strip() != summary:
            node_changes.append((nd["id"], title))
        elif not nd:
            missing.append("《%s》没有对应的大纲节点" % title)

    L.step("差异")
    if not ch_changes and not node_changes:
        L.ok("章节指引与大纲节点都已是最新，无需同步")
    for num, title, old_len, new_len in ch_changes:
        L.info("第 %d 章《%s》章节指引需更新（%d 字 → %d 字）" % (num, title, old_len, new_len))
    for nid_, title in node_changes:
        L.info("大纲节点 [%d]《%s》摘要需更新" % (nid_, title))
    for m in missing:
        L.warn(m)

    if not args.apply:
        L.warn("当前是预演（未写入）。加 --apply 才会真正更新。")
        return

    for nid_, title in node_changes:
        summary = next(s for t, s in items if t == title)
        L.run_write(["outline", "update", "--novel", str(nid), "--id", str(nid_),
                     "--summary", summary])
    for num, title, _, _ in ch_changes:
        summary = next(s for t, s in items if t == title)
        L.run_write(["chapter", "update", "--novel", str(nid), "--number", str(num),
                     "--outline", summary])

    L.step("复核")
    chapters = L.sql_rows("select chapter_number, title, outline from chapters"
                          " where novel_id=? order by chapter_number", (nid,))
    bad = []
    for idx, (title, summary) in enumerate(items, 1):
        if wanted and idx not in wanted:
            continue
        ch = by_title.get(title)
        cur = next((r["outline"] for r in chapters if r["chapter_number"] == ch["chapter_number"]), "")
        if (cur or "").strip() != summary:
            bad.append(idx)
    if bad:
        raise SystemExit("同步后仍不一致的章号：%s" % bad)
    L.ok("已同步：大纲节点 %d 个、章节指引 %d 个，复核一致"
         % (len(node_changes), len(ch_changes)))


if __name__ == "__main__":
    main()
