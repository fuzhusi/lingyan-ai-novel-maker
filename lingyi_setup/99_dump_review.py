# -*- coding: utf-8 -*-
"""99_dump_review.py —— 只读导出知识库全文，供人工审查。

用法（仓库根目录）：
    .venv/Scripts/python.exe lingyi_setup/99_dump_review.py <novel_id>
    .venv/Scripts/python.exe lingyi_setup/99_dump_review.py <novel_id> --out-dir <目录>

输出：<id>_总览.md / <id>_角色卡全文.md / <id>_世界观全文.md / <id>_大纲树.md / <id>_伏笔表.md

只读保证：sqlite 以 mode=ro 打开，任何写入都会直接报错。
数据库跟随 DATABASE_PATH 环境变量（沙箱演练时自动指向副本库）。
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="只读导出某本书的知识库全文")
    ap.add_argument("novel_id", type=int)
    ap.add_argument("--out-dir", default=L.REVIEW_DIR)
    args = ap.parse_args()

    nid = args.novel_id
    outdir = args.out_dir
    os.makedirs(outdir, exist_ok=True)
    con = L._connect_ro()

    novel = con.execute("SELECT * FROM novels WHERE id=?", (nid,)).fetchone()
    if not novel:
        raise SystemExit("✗ 小说 %d 不存在（库：%s）" % (nid, L.DB))
    if L.IS_SANDBOX:
        print("[沙箱模式] 库 = %s" % L.DB)

    chars = con.execute("SELECT * FROM characters WHERE novel_id=? ORDER BY id", (nid,)).fetchall()
    worlds = con.execute("SELECT * FROM world_settings WHERE novel_id=? ORDER BY id", (nid,)).fetchall()
    nodes = con.execute("SELECT * FROM outline_nodes WHERE novel_id=? ORDER BY parent_id IS NOT NULL, sort_order, id", (nid,)).fetchall()
    fss = con.execute("SELECT * FROM foreshadowing WHERE novel_id=? ORDER BY id", (nid,)).fetchall()
    chapters = con.execute(
        "SELECT c.id, c.chapter_number, c.title, c.outline, c.outline_node_id,"
        " (SELECT COUNT(*) FROM chapter_versions v WHERE v.chapter_id=c.id) AS ver,"
        " (SELECT COUNT(*) FROM chapter_versions v WHERE v.chapter_id=c.id AND v.approved=1) AS appr"
        " FROM chapters c WHERE c.novel_id=? ORDER BY c.chapter_number", (nid,)).fetchall()

    title = novel["title"]
    lines = []

    def w(text=""):
        lines.append(text)

    def save(name):
        path = os.path.join(outdir, name)
        with io.open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print("  已导出: %s" % os.path.relpath(path, L.REPO_ROOT))

    # -------------------------------------------------------------- 完整性检查
    problems = []
    CFIELDS = [("personality", "性格"), ("speaking_style", "说话风格"), ("appearance", "外貌"),
               ("background", "背景"), ("motivation", "动机"), ("arc_direction", "弧光")]
    names = [c["name"] for c in chars]
    for dup, cnt in Counter(names).items():
        if cnt > 1:
            problems.append("角色重名 ×%d：%s" % (cnt, dup))
    for c in chars:
        for f, zh in CFIELDS:
            if not (c[f] or "").strip():
                problems.append("角色《%s》%s 为空" % (c["name"], zh))
    for dup, cnt in Counter(x["title"] for x in worlds).items():
        if cnt > 1:
            problems.append("世界观重名 ×%d：%s" % (cnt, dup))
    for x in worlds:
        if not (x["content"] or "").strip():
            problems.append("世界观《%s》正文为空" % x["title"])
        if not (x["category"] or "").strip():
            problems.append("世界观《%s》分类为空" % x["title"])

    node_ids = {n["id"] for n in nodes}
    for n in nodes:
        if n["parent_id"] and n["parent_id"] not in node_ids:
            problems.append("大纲节点 [%d]《%s》父节点 %d 不在本书" % (n["id"], n["title"], n["parent_id"]))
        if not (n["summary"] or "").strip():
            problems.append("大纲节点 [%d]《%s》摘要为空" % (n["id"], n["title"]))

    for ch in chapters:
        if not ch["outline_node_id"]:
            problems.append("第%s章《%s》未关联大纲节点（走了 chapter create 而非 outline create-chapter）"
                            % (ch["chapter_number"], ch["title"]))

    print("《%s》(novel %d)  角色 %d / 世界观 %d / 大纲 %d / 伏笔 %d / 章节 %d"
          % (title, nid, len(chars), len(worlds), len(nodes), len(fss), len(chapters)))
    if problems:
        print("完整性问题 %d 条：" % len(problems))
        for p in problems:
            print("  - %s" % p)
    else:
        print("完整性检查：无问题")
    print("大纲节点类型分布: %s" % dict(Counter(n["node_type"] for n in nodes)))
    print("世界观分类分布: %s" % dict(Counter(x["category"] for x in worlds)))
    print("伏笔状态分布: %s" % dict(Counter(f["status"] for f in fss)))

    # -------------------------------------------------------------- 总览
    w("# 《%s》总览（novel %d）\n" % (title, nid))
    w("- 类型：%s" % (novel["genre"] or "未设置"))
    w("- 简介：%s" % (novel["synopsis"] or "（空）"))
    w("- 世界观总纲：%s" % (novel["world_intro"] or "（空）"))
    ai = (novel["author_intent"] or "").strip()
    cf = (novel["current_focus"] or "").strip()
    w("- 创作罗盘 · 作者意图（%d 字）：%s" % (len(ai), ai or "（未设定）"))
    w("- 创作罗盘 · 当前重心（%d 字）：%s" % (len(cf), cf or "（未设定）"))
    w("")
    w("| 项目 | 数量 |")
    w("|---|---|")
    w("| 章节 | %d |" % len(chapters))
    w("| 角色 | %d |" % len(chars))
    w("| 世界观条目 | %d |" % len(worlds))
    w("| 大纲节点 | %d |" % len(nodes))
    w("| 伏笔 | %d |" % len(fss))
    w("")
    w("## 完整性问题（%d）\n" % len(problems))
    for p in problems:
        w("- %s" % p)
    if not problems:
        w("无。")
    save("%d_总览.md" % nid)

    # -------------------------------------------------------------- 角色卡
    lines = ["# 《%s》角色卡（%d 张）\n" % (title, len(chars))]
    for i, c in enumerate(chars, 1):
        w("\n## %d. %s（ID %d）\n" % (i, c["name"], c["id"]))
        for f, zh in CFIELDS:
            w("**%s**：%s\n" % (zh, c[f] or "（空）"))
    save("%d_角色卡全文.md" % nid)

    # -------------------------------------------------------------- 世界观
    lines = ["# 《%s》世界观（%d 条）\n" % (title, len(worlds))]
    cats = []
    for x in worlds:
        if x["category"] not in cats:
            cats.append(x["category"])
    for cat in cats:
        items = [x for x in worlds if x["category"] == cat]
        w("\n## 【%s】（%d 条）\n" % (cat, len(items)))
        for x in items:
            w("### %s（ID %d）\n" % (x["title"], x["id"]))
            w((x["content"] or "") + "\n")
    save("%d_世界观全文.md" % nid)

    # -------------------------------------------------------------- 大纲树
    by_parent = {}
    for n in nodes:
        by_parent.setdefault(n["parent_id"], []).append(n)
    ICO = {"volume": "[卷]", "chapter": "[章]", "scene": "[景]"}

    def walk(parent_id, depth):
        for n in sorted(by_parent.get(parent_id, []), key=lambda x: (x["sort_order"], x["id"])):
            w("%s- %s [%d] %s" % ("  " * depth, ICO.get(n["node_type"], "[?]"), n["id"], n["title"]))
            if (n["summary"] or "").strip():
                for line in n["summary"].strip().splitlines():
                    w("%s  %s" % ("  " * depth, line))
            walk(n["id"], depth + 1)

    lines = ["# 《%s》大纲树（%d 节点）\n" % (title, len(nodes))]
    walk(None, 0)
    save("%d_大纲树.md" % nid)

    # -------------------------------------------------------------- 伏笔表
    lines = ["# 《%s》伏笔（%d 条）\n" % (title, len(fss))]
    w("\n| ID | 标题 | 状态 | 重要度 | 埋设章 | 超时阈值 | 预期回收 |")
    w("|---|---|---|---|---|---|---|")
    for f in fss:
        w("| %d | %s | %s | %d | %s | %s | %s |"
          % (f["id"], f["title"], f["status"], f["importance"] or 0,
             f["planted_chapter"] or "-", f["timeout_threshold"] or "-",
             f["expected_resolve_chapter"] or "-"))
    for f in fss:
        w("\n## [%d] %s（%s）\n" % (f["id"], f["title"], f["status"]))
        w("**描述**：%s\n" % (f["description"] or "（空）"))
        if (f["notes"] or "").strip():
            w("**记注**：%s\n" % f["notes"])
    save("%d_伏笔表.md" % nid)

    con.close()


if __name__ == "__main__":
    main()
