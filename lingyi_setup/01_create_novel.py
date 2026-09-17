# -*- coding: utf-8 -*-
"""01_create_novel.py —— 建书 + 补创作罗盘。

读 <content-dir>/novel.json：
    {
      "title": "书名",
      "genre": "民俗怪谈 · 都市灵异 · 情感成长",
      "synopsis": "一句话故事概括",
      "world_intro": "世界观总纲",
      "author_intent": "全书承诺，≤500 字（创作罗盘）",
      "current_focus": "阶段目标，≤300 字（创作罗盘）"
    }

⚠️ 坑 1：`novel create` 不接受 author_intent / current_focus（静默丢弃），
   所以本脚本建完书会立刻用 `novel update` 补罗盘——见 CLI建库要点.md。

防重跑：同名书已存在则中止。写完 state.novel_id。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402


def main():
    ap = L.content_parser("01 建书 + 创作罗盘")
    args = ap.parse_args()
    L.set_dry_run(args.dry_run)
    L.banner("01 建书 + 创作罗盘")

    novel = L.load_json(os.path.join(args.content_dir, "novel.json"))
    title = (novel.get("title") or "").strip()
    if not title:
        raise SystemExit("content/novel.json 缺 title")

    if not L.is_dry():
        L.assert_novel_absent(title)

    L.run_write(["novel", "create",
                 "--title", title,
                 "--genre", novel.get("genre", ""),
                 "--synopsis", novel.get("synopsis", ""),
                 "--world-intro", novel.get("world_intro", "")])

    if L.is_dry():
        L.warn("dry-run：后续依赖 novel_id 的步骤跳过")
        return

    nid = L.get_novel_id(title)
    L.ok("novel id = %d" % nid)

    # 坑 1：罗盘必须用 update 补（create 会静默丢弃）
    upd = ["novel", "update", "--id", str(nid)]
    has_compass = False
    if (novel.get("author_intent") or "").strip():
        upd += ["--author-intent", novel["author_intent"].strip()]
        has_compass = True
    if (novel.get("current_focus") or "").strip():
        upd += ["--current-focus", novel["current_focus"].strip()]
        has_compass = True
    if has_compass:
        L.run_write(upd)
    else:
        L.warn("novel.json 未提供 author_intent / current_focus，罗盘留空（可后续 compass set 补）")

    L.save_state(args.content_dir, {"novel_id": nid, "title": title})
    L.step("核验")
    L.run_cli(["novel", "info", "--id", str(nid)])
    L.run_cli(["compass", "show", "--novel", str(nid)])


if __name__ == "__main__":
    main()
