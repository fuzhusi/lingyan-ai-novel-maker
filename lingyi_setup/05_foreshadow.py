# -*- coding: utf-8 -*-
"""05_foreshadow.py —— 落地伏笔（含状态机推进）。

读 <content-dir>/foreshadow.json：
    [
      { "title": "标题", "description": "埋设点与回收意图",
        "importance": 8,              # 1-10，决定超时阈值(≥9→30章 / ≥7→20 / ≥4→15 / <4→10)
        "planted_chapter": 3,         # 埋设章（可省）
        "target_status": "planned",   # 建库阶段建议 planned；缺省 planned
        "notes": "排期备注（预期回收章等）" }
    ]

⚠️ 坑 3：`foreshadow create` 不接受 --status（新建恒为 open），必须再单独推进；
   状态机单向：open→planned|buried，planned→buried，buried→advancing，
   advancing→reclaimable|buried，reclaimable→resolved。跨级会被 cli 拒绝，
   本脚本用 BFS 走最短合法路径（_lib.fs_path）。
⚠️ 另一个坑：`foreshadow create` 也不读 --notes，notes 必须随后 update 补。

防重跑：本书 foreshadowing 表必须为空。写完 state.foreshadow = {标题: ID}。
"""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402


def main():
    ap = L.content_parser("05 伏笔")
    args = ap.parse_args()
    L.set_dry_run(args.dry_run)
    L.banner("05 伏笔")

    nid = L.require_novel_id(args.content_dir)
    items = L.load_list(os.path.join(args.content_dir, "foreshadow.json"), "foreshadow.json")
    L.info("novel_id=%d，待落库伏笔 %d 条" % (nid, len(items)))

    titles = [str(f.get("title", "")).strip() for f in items]
    if "" in titles:
        raise SystemExit("有伏笔缺 title")
    dup = {t for t in titles if titles.count(t) > 1}
    if dup:
        raise SystemExit("伏笔重名：%s" % "、".join(sorted(dup)))

    if not L.is_dry():
        L.assert_novel_empty(nid, "foreshadowing")

    mapping = {}
    for f in items:
        title = str(f["title"]).strip()
        imp = f.get("importance", 5)
        try:
            imp = int(imp)
        except (TypeError, ValueError):
            raise SystemExit("伏笔《%s》importance 不是整数：%r" % (title, imp))
        if not 1 <= imp <= 10:
            raise SystemExit("伏笔《%s》importance 需在 1~10" % title)

        argv = ["foreshadow", "create", "--novel", str(nid), "--title", title,
                "--description", f.get("description", "") or "",
                "--importance", str(imp)]
        if f.get("planted_chapter"):
            argv += ["--planted", str(int(f["planted_chapter"]))]
        if f.get("timeout_threshold"):
            argv += ["--threshold", str(int(f["timeout_threshold"]))]
        r = L.run_write(argv)
        fid = L.parse_new_id(r, "伏笔 %s" % title)

        if fid is None:      # dry-run
            continue

        target = (f.get("target_status") or "planned").strip()
        if target not in L.FS_TRANSITIONS:
            raise SystemExit("伏笔《%s》target_status 非法：%s（合法：%s）"
                             % (title, target, "/".join(L.FS_TRANSITIONS)))
        path = L.fs_path("open", target)
        if path is None:
            raise SystemExit("伏笔《%s》无法从 open 到达 %s" % (title, target))
        L.info("《%s》状态推进：open → %s" % (title, " → ".join(path) if path else "（保持 open）"))
        L.advance_foreshadow(fid, "open", target)

        if (f.get("notes") or "").strip():
            L.run_write(["foreshadow", "update", "--id", str(fid), "--notes", f["notes"].strip()])

        mapping[title] = fid

    if L.is_dry():
        L.warn("dry-run：不写状态文件")
        return

    L.save_state(args.content_dir, {"foreshadow": mapping})

    rows = L.sql_rows("select id, title, status, importance, planted_chapter, timeout_threshold,"
                      " notes from foreshadowing where novel_id=? order by id", (nid,))
    L.step("核验")
    L.ok("库中伏笔 = %d（期望 %d）" % (len(rows), len(items)))
    if len(rows) != len(items):
        raise SystemExit("伏笔数量不符，请检查")
    L.info("状态分布：%s" % dict(Counter(r["status"] for r in rows)))
    for r in rows:
        L.info("[%s] %s | %s | 重要度%s | 埋设章%s | 阈值%s"
               % (r["id"], r["title"], r["status"], r["importance"],
                  r["planted_chapter"] or "-", r["timeout_threshold"] or "-"))


if __name__ == "__main__":
    main()
