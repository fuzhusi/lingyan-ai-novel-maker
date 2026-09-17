# -*- coding: utf-8 -*-
"""test_build_chain.py —— 在沙箱 DB 副本上端到端演练建库链（01→07）。

用法（仓库根目录）：
    .venv/Scripts/python.exe lingyi_setup/tests/test_build_chain.py
    .venv/Scripts/python.exe lingyi_setup/tests/test_build_chain.py --keep

安全保证：真库 data.db **全程只读**——沙箱库是它的一份副本（SQLite backup API 复制），
所有写入都发生在副本上；结束时副本被删除（--keep 则保留供人工查看）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.dirname(HERE)
REPO = os.path.dirname(SETUP)
PYEXE = os.path.join(REPO, ".venv", "Scripts", "python.exe")
CLI = os.path.join(REPO, "cli.py")
PROD_DB = os.path.join(REPO, "data.db")
TMP_ROOT = os.path.join(REPO, ".tmp-test")
SANDBOX_REL = os.path.join(".tmp-test", "lingyi_sandbox.db")
SANDBOX_ABS = os.path.join(REPO, SANDBOX_REL)
SAMPLE = os.path.join(HERE, "sample_content")

PASS, FAIL = [], []


def check(cond, label):
    (PASS if cond else FAIL).append(label)
    print("   %s %s" % ("✓" if cond else "✗", label))
    return bool(cond)


def run_label(label, args, env, expect_fail=False):
    r = subprocess.run([PYEXE] + args, cwd=REPO, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (r.stdout or "").strip().splitlines()
    good = (r.returncode != 0) if expect_fail else (r.returncode == 0)
    print("   %s %s（rc=%d）" % ("✓" if good else "✗", label, r.returncode))
    if not good:
        print("     --- 输出尾部 ---")
        for line in tail[-15:]:
            print("     " + line)
        err = (r.stderr or "").strip().splitlines()
        for line in err[-8:]:
            print("     [stderr] " + line)
    return r


def prod_scalar(q, params=()):
    con = sqlite3.connect("file:///%s?mode=ro" % PROD_DB.replace("\\", "/"), uri=True)
    try:
        row = con.execute(q, params).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="保留沙箱库与导出目录")
    args = ap.parse_args()

    print("=== 建库链端到端演练（沙箱） ===")
    prod_before = prod_scalar("select count(*) from novels")
    print("   真库 books = %s（演练前后必须一致）" % prod_before)

    # ---------------------------------------------------------------- 沙箱库
    os.makedirs(os.path.dirname(SANDBOX_ABS), exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        p = SANDBOX_ABS + suffix
        if os.path.exists(p):
            os.remove(p)
    env_prod = {k: v for k, v in os.environ.items() if k != "DATABASE_PATH"}
    env_prod["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([PYEXE, CLI, "sys", "backup", "--output", SANDBOX_ABS],
                       cwd=REPO, env=env_prod, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if not check(r.returncode == 0 and os.path.exists(SANDBOX_ABS),
                 "沙箱库副本已创建（%s）" % SANDBOX_REL):
        print(r.stdout, r.stderr)
        return 1

    env = dict(env_prod)
    env["DATABASE_PATH"] = SANDBOX_REL          # 相对项目根，模拟人工用法
    os.environ["DATABASE_PATH"] = SANDBOX_REL   # 本进程内的 _lib 也要指向沙箱

    sys.path.insert(0, SETUP)
    import _lib as L  # noqa: E402
    check(L.IS_SANDBOX and os.path.abspath(L.DB) == os.path.abspath(SANDBOX_ABS),
          "_lib 正确识别沙箱库")

    # ---------------------------------------------------------------- 纯函数
    print("\n-- 伏笔状态机（纯函数）--")
    check(L.fs_path("open", "planned") == ["planned"], "open→planned 直连")
    check(L.fs_path("open", "resolved") == ["buried", "advancing", "reclaimable", "resolved"],
          "open→resolved 取最短合法路径（open→buried 合法，故绕开 planned）")
    check(L.fs_path("resolved", "open") is None, "resolved→open 判定为不可达（终态）")
    check(L.fs_path("open", "open") == [], "同状态为空路径")

    # ---------------------------------------------------------------- 内容目录
    # 注意：系统临时目录（%TEMP%）在沙箱下不可写，临时目录一律放工作区 .tmp-test/
    content = os.path.join(TMP_ROOT, "content")
    shutil.rmtree(content, ignore_errors=True)
    os.makedirs(content)
    for fn in os.listdir(SAMPLE):
        shutil.copy2(os.path.join(SAMPLE, fn), os.path.join(content, fn))
    print("\n-- 内容目录：%s --" % os.path.relpath(content, REPO))

    # ---------------------------------------------------------------- 建库链
    print("\n-- 建库链 01→07 --")
    steps = [
        ("01 建书", ["lingyi_setup/01_create_novel.py", "--content-dir", content]),
        ("02 角色卡", ["lingyi_setup/02_characters.py", "--content-dir", content]),
        ("03 世界观", ["lingyi_setup/03_world.py", "--content-dir", content]),
        ("04 大纲树", ["lingyi_setup/04_outline.py", "--content-dir", content]),
        ("05 伏笔", ["lingyi_setup/05_foreshadow.py", "--content-dir", content]),
        ("06 角色关系", ["lingyi_setup/06_relations.py", "--content-dir", content]),
        ("07 实例化章节", ["lingyi_setup/07_instantiate_chapters.py", "--content-dir", content]),
    ]
    for label, argv in steps:
        r = run_label(label, argv, env)
        check(r.returncode == 0, "%s 退出码 0" % label)

    # ---------------------------------------------------------------- 落库核验
    print("\n-- 落库核验（沙箱 SQL）--")
    nid = L.sql_scalar("select id from novels where title like '【样本】%' order by id desc limit 1")
    check(bool(nid), "样本书已建（novel id=%s）" % nid)
    if not nid:
        return finish(args, content)
    nid = int(nid)

    ai = L.sql_scalar("select author_intent from novels where id=?", (nid,)) or ""
    cf = L.sql_scalar("select current_focus from novels where id=?", (nid,)) or ""
    check(len(ai.strip()) > 0 and len(cf.strip()) > 0,
          "创作罗盘已落库（绕过 novel create 不写罗盘的坑）")

    n_char = L.sql_scalar("select count(*) from characters where novel_id=?", (nid,))
    check(n_char == 3, "角色 = 3（实际 %s）" % n_char)
    empty_char = L.sql_scalar(
        "select count(*) from characters where novel_id=? and (personality='' or speaking_style=''"
        " or appearance='' or background='' or motivation='' or arc_direction='')", (nid,))
    check(empty_char == 0, "角色 6 字段无空缺（实际空缺 %s）" % empty_char)

    n_world = L.sql_scalar("select count(*) from world_settings where novel_id=?", (nid,))
    check(n_world == 3, "世界观 = 3（实际 %s）" % n_world)

    n_node = L.sql_scalar("select count(*) from outline_nodes where novel_id=?", (nid,))
    check(n_node == 6, "大纲节点 = 6（1 卷 + 3 章 + 2 景，实际 %s）" % n_node)
    n_vol = L.sql_scalar("select count(*) from outline_nodes where novel_id=? and node_type='volume'", (nid,))
    check(n_vol == 1, "其中卷 = 1（实际 %s）" % n_vol)

    n_fs = L.sql_scalar("select count(*) from foreshadowing where novel_id=?", (nid,))
    check(n_fs == 2, "伏笔 = 2（实际 %s）" % n_fs)
    n_fs_planned = L.sql_scalar("select count(*) from foreshadowing where novel_id=? and status='planned'", (nid,))
    check(n_fs_planned == 2, "伏笔状态已推进到 planned（实际 %s；create 只能建出 open）" % n_fs_planned)
    fs_notes = L.sql_scalar("select count(*) from foreshadowing where novel_id=? and notes != ''", (nid,))
    check(fs_notes == 1, "伏笔 notes 已补（create 不读 --notes，实际有备注 %s 条）" % fs_notes)
    fs_thr = L.sql_scalar("select timeout_threshold from foreshadowing where novel_id=? and importance=8", (nid,))
    check(fs_thr == 20, "重要度 8 → 超时阈值自动 20 章（实际 %s）" % fs_thr)

    n_rel = L.sql_scalar("select count(*) from character_relations where novel_id=?", (nid,))
    check(n_rel == 2, "角色关系 = 2（实际 %s）" % n_rel)

    chs = L.sql_rows("select chapter_number, title, outline, outline_node_id from chapters"
                     " where novel_id=? order by chapter_number", (nid,))
    check(len(chs) == 3, "章节 = 3（实际 %s）" % len(chs))
    check([c["chapter_number"] for c in chs] == [1, 2, 3], "章号 1..3 连续且顺序正确")
    check(all(c["outline_node_id"] for c in chs), "每章都关联了大纲节点（outline_node_id 非空）")
    ch1 = chs[0]["outline"] if chs else ""
    check("分幕指引" in ch1 and "样本场景·灵堂" in ch1 and "样本场景·后巷" in ch1,
          "第1章大纲含 scene 子节点合并出的「分幕指引」")

    # ---------------------------------------------------------------- 防重跑
    print("\n-- 防重跑保险丝 --")
    r = run_label("重跑 01（应被拒）", ["lingyi_setup/01_create_novel.py", "--content-dir", content],
                  env, expect_fail=True)
    check(r.returncode != 0 and "防重跑" in (r.stdout + r.stderr), "同名书重跑被中止")
    r = run_label("重跑 02（应被拒）", ["lingyi_setup/02_characters.py", "--content-dir", content],
                  env, expect_fail=True)
    check(r.returncode != 0 and "防重跑" in (r.stdout + r.stderr), "角色表非空重跑被中止")

    print("\n-- dry-run --")
    r = run_label("02 --dry-run", ["lingyi_setup/02_characters.py", "--content-dir", content, "--dry-run"], env)
    check(r.returncode == 0 and "[dry]" in r.stdout, "dry-run 只打印不写库")

    # ---------------------------------------------------------------- 只读导出
    print("\n-- 只读导出 99_dump_review.py --")
    outdir = os.path.join(TMP_ROOT, "review_out")
    shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(outdir)
    r = run_label("导出", ["lingyi_setup/99_dump_review.py", str(nid), "--out-dir", outdir], env)
    check(r.returncode == 0, "导出退出码 0")
    expect = ["%d_总览.md" % nid, "%d_角色卡全文.md" % nid, "%d_世界观全文.md" % nid,
              "%d_大纲树.md" % nid, "%d_伏笔表.md" % nid]
    missing = [e for e in expect if not os.path.exists(os.path.join(outdir, e))]
    check(not missing, "5 份导出文件齐备（缺 %s）" % (missing or "无"))
    check("完整性检查：无问题" in r.stdout, "样本内容完整性检查无问题")

    # ---------------------------------------------------------------- 真库未动
    print("\n-- 真库零改动核验 --")
    check(prod_scalar("select count(*) from novels") == prod_before, "真库 books 数量未变")
    check(prod_scalar("select count(*) from novels where title like '【样本】%'") == 0,
          "真库里没有样本书")

    return finish(args, content, outdir)


def finish(args, content, outdir=None):
    print("\n=== 结果：通过 %d / 失败 %d ===" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  ✗ %s" % f)
    if args.keep:
        print("保留：沙箱库 %s" % SANDBOX_REL)
        print("保留内容目录：%s" % os.path.relpath(content, REPO))
        if outdir:
            print("保留导出目录：%s" % os.path.relpath(outdir, REPO))
    else:
        shutil.rmtree(content, ignore_errors=True)
        if outdir:
            shutil.rmtree(outdir, ignore_errors=True)
        for suffix in ("", "-wal", "-shm"):
            p = SANDBOX_ABS + suffix
            if os.path.exists(p):
                os.remove(p)
        print("已清理沙箱库与临时目录（--keep 可保留）")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
