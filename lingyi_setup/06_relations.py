# -*- coding: utf-8 -*-
"""06_relations.py —— 落地角色关系（恋爱线的评分演化基础）。

读 <content-dir>/relations.json：
    [ { "char_a": "姓名A", "char_b": "姓名B",
        "type": "friend", "desc": "关系描述" } ]

角色用**姓名**引用（由 state.characters 解析成 ID），避免手抄 ID 出错。
后续可用 `relation event --id N --event ... --intensity x` 随剧情推进评分
（事件类型：battle_together / betrayal / life_saving / conflict / open_talk / public_humiliation）。

防重跑：本书 character_relations 表必须为空。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402


def main():
    ap = L.content_parser("06 角色关系")
    args = ap.parse_args()
    L.set_dry_run(args.dry_run)
    L.banner("06 角色关系")

    nid = L.require_novel_id(args.content_dir)
    items = L.load_list(os.path.join(args.content_dir, "relations.json"), "relations.json")

    state = L.load_state(args.content_dir)
    name2id = state.get("characters") or {}
    if not name2id and not L.is_dry():
        raise SystemExit("state 里没有角色 ID 映射——先跑 02_characters.py")

    # 不依赖 state 的兜底：直接从库里按姓名取
    def resolve(name):
        if name in name2id:
            return int(name2id[name])
        row = L.sql_scalar("select id from characters where novel_id=? and name=?", (nid, name))
        if not row:
            raise SystemExit("角色《%s》在本书里不存在（先落 02，或检查姓名）" % name)
        return int(row)

    if not L.is_dry():
        L.assert_novel_empty(nid, "character_relations")

    L.info("novel_id=%d，待落库关系 %d 条" % (nid, len(items)))
    for rel in items:
        a = str(rel.get("char_a", "")).strip()
        b = str(rel.get("char_b", "")).strip()
        if not a or not b:
            raise SystemExit("关系条目缺 char_a / char_b：%r" % rel)
        if a == b:
            raise SystemExit("关系两端是同一角色：%s" % a)
        L.info("%s ↔ %s（%s）" % (a, b, rel.get("type") or "ordinary"))
        if L.is_dry():
            print("   [dry] cli.py relation create --novel %d --char-a <%s> --char-b <%s> ..." % (nid, a, b))
            continue
        L.run_write(["relation", "create", "--novel", str(nid),
                     "--char-a", str(resolve(a)), "--char-b", str(resolve(b)),
                     "--type", rel.get("type", "ordinary"),
                     "--desc", rel.get("desc", "") or ""])

    if L.is_dry():
        return

    L.step("核验")
    L.run_cli(["relation", "list", "--novel", str(nid)])
    n = L.sql_scalar("select count(*) from character_relations where novel_id=?", (nid,))
    L.ok("库中关系 = %s（期望 %d）" % (n, len(items)))
    if int(n) != len(items):
        raise SystemExit("关系数量不符，请检查")


if __name__ == "__main__":
    main()
