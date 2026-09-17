# -*- coding: utf-8 -*-
"""test_generation.py —— 生产层冒烟测试：在沙箱里真跑一章「一键本章」。

⚠️ 本测试**会真实调用 LLM**（约 3-6 次），产生少量 API 费用。默认不开盲审，用 --blind 打开。

用法（仓库根目录）：
    .venv/Scripts/python.exe lingyi_setup/tests/test_generation.py
    .venv/Scripts/python.exe lingyi_setup/tests/test_generation.py --blind
    .venv/Scripts/python.exe lingyi_setup/tests/test_generation.py --chapter 2 --keep

它验证的是**管线是否通**（生成 → 门禁 → AI味收敛 → 落版本 → 零成本质检），
不是文笔质量——样本角色是假的，生成结果无文学意义。

安全：全程只写沙箱副本库（.tmp-test/lingyi_sandbox.db），真库只读。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.dirname(HERE)
REPO = os.path.dirname(SETUP)
PYEXE = os.path.join(REPO, ".venv", "Scripts", "python.exe")
CLI = os.path.join(REPO, "cli.py")
TMP_ROOT = os.path.join(REPO, ".tmp-test")
SANDBOX_REL = os.path.join(".tmp-test", "lingyi_sandbox.db")
SANDBOX_ABS = os.path.join(REPO, SANDBOX_REL)
CONTENT_DIR = os.path.join(TMP_ROOT, "content")

PASS, FAIL = [], []


def check(cond, label):
    (PASS if cond else FAIL).append(label)
    print("   %s %s" % ("✓" if cond else "✗", label))
    return bool(cond)


def run(args, env):
    t0 = time.time()
    r = subprocess.run([PYEXE] + args, cwd=REPO, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", type=int, default=1)
    ap.add_argument("--blind", action="store_true", help="额外跑一次双盲审（+2 次 LLM 调用）")
    ap.add_argument("--keep", action="store_true", help="保留沙箱与生成结果")
    ap.add_argument("--directive", default="本章仅用于验证生成管线连通，写得短一些即可。")
    args = ap.parse_args()

    print("=== 生产层冒烟测试（沙箱 + 真实 LLM）===")
    print("!! 本测试会真实调用 LLM，产生少量 API 费用。")

    env = {k: v for k, v in os.environ.items() if k != "DATABASE_PATH"}
    env["DATABASE_PATH"] = SANDBOX_REL
    env["PYTHONIOENCODING"] = "utf-8"

    # ---------------------------------------------------------------- 准备沙箱
    print("\n-- 准备沙箱（复用或新建）--")
    state_file = os.path.join(CONTENT_DIR, "_state.json")
    nid = None
    if os.path.exists(SANDBOX_ABS) and os.path.exists(state_file):
        with open(state_file, "r", encoding="utf-8") as f:
            nid = json.load(f).get("novel_id")
        print("   复用已有沙箱，novel_id=%s" % nid)
    if not nid:
        print("   沙箱不完整，先跑建库链…")
        r, dt = run(["lingyi_setup/tests/test_build_chain.py", "--keep"], env)
        if r.returncode != 0:
            print(r.stdout[-2000:], r.stderr[-800:])
            raise SystemExit("建库链准备失败")
        with open(state_file, "r", encoding="utf-8") as f:
            nid = json.load(f)["novel_id"]
        print("   沙箱就绪，novel_id=%s（%.1fs）" % (nid, dt))
    nid = int(nid)

    # ---------------------------------------------------------------- 管线
    print("\n-- 一键本章（生成 → 门禁 → 收敛 → 落版本）--")
    out_file = os.path.join(TMP_ROOT, "chapter_%d.md" % args.chapter)
    if os.path.exists(out_file):
        os.remove(out_file)
    r, dt = run(["cli.py", "chapter", "pipeline", "--novel", str(nid),
                 "--number", str(args.chapter), "--save",
                 "--directive", args.directive, "--out", out_file], env)
    print("   用时 %.1f 秒（rc=%d）" % (dt, r.returncode))
    print("   ---- CLI 输出 ----")
    for line in (r.stdout or "").strip().splitlines()[:40]:
        print("   | " + line)
    if r.stderr.strip():
        print("   [stderr] " + r.stderr.strip()[:500])

    o = r.stdout or ""
    gate_blocked = "门禁未通过" in o
    saved = bool(re.search(r"已保存版本 id=(\d+)", o))
    score_m = re.search(r"人味分:\s*(\S+)", o)
    score = score_m.group(1) if score_m else "?"

    check("[body]" in o or saved or gate_blocked, "流水线跑到正文阶段")
    check(score != "?", "输出了人味分（实际 %s）" % score)
    if gate_blocked:
        check(True, "终稿门禁未通过 → 流水线按设计停在人工闸门（下同，需人工处置）")
    else:
        check(saved, "已落 AI 版本（版本 id 见上）")

    # ---------------------------------------------------------------- 落盘核验
    print("\n-- 落盘核验（沙箱 SQL）--")
    import sqlite3
    con = sqlite3.connect("file:///%s?mode=ro" % SANDBOX_ABS.replace("\\", "/"), uri=True)
    ch = con.execute("select id, outline from chapters where novel_id=? and chapter_number=?",
                     (nid, args.chapter)).fetchone()
    check(bool(ch), "章节存在")
    n_ver = con.execute("select count(*) from chapter_versions where chapter_id=?", (ch[0],)).fetchone()[0]
    n_appr = con.execute("select count(*) from chapter_versions where chapter_id=? and approved=1",
                         (ch[0],)).fetchone()[0]
    word = con.execute("select length(content) from chapter_versions where chapter_id=?"
                       " order by version_number desc limit 1", (ch[0],)).fetchone()
    check(n_ver >= 1, "已产生版本记录（%d 个）" % n_ver)
    check(n_appr == 0, "版本未被自动审批（人工闸门有效）")
    check(bool(word and word[0] and word[0] > 300),
          "正文非空且成型（%s 字）" % (word[0] if word and word[0] else 0))
    con.close()

    check(os.path.exists(out_file) and os.path.getsize(out_file) > 200,
          "--out 写出了正文文件（%s 字节）"
          % (os.path.getsize(out_file) if os.path.exists(out_file) else 0))

    # ---------------------------------------------------------------- 零成本质检
    print("\n-- 零 LLM 成本质检 --")
    r2, dt2 = run(["cli.py", "audit", "run", "--novel", str(nid), "--number", str(args.chapter)], env)
    check(r2.returncode == 0 and "✗" not in r2.stdout, "audit run 通过（%.1fs）" % dt2)
    r3, dt3 = run(["cli.py", "tone", "check", "--novel", str(nid), "--number", str(args.chapter)], env)
    check(r3.returncode == 0 and "✗" not in r3.stdout, "tone check 通过（%.1fs）" % dt3)
    m = re.search(r"人味分[:：]\s*(\d+)", (r3.stdout or ""))
    if m:
        print("   tone check 人味分 = %s" % m.group(1))

    # ---------------------------------------------------------------- 困惑度雷达
    print("\n-- 困惑度雷达（需要厂商支持 logprobs，可选）--")
    r4, dt4 = run(["cli.py", "tone", "radar", "--novel", str(nid), "--number", str(args.chapter)], env)
    low = (r4.stdout or "")
    if "不可用" in low or "不支持" in low or "降级" in low:
        print("   · 厂商不支持 logprobs → 雷达自动降级为不可用（不影响主干）")
        check(True, "雷达按降级纪律处理（未崩）")
    else:
        check(r4.returncode == 0, "radar 跑通（%.1fs）" % dt4)

    # ---------------------------------------------------------------- 盲审
    if args.blind:
        print("\n-- 双盲审（阎浮 × 白骨，2 次 LLM 调用）--")
        r5, dt5 = run(["cli.py", "blind", "run", "--novel", str(nid), "--number", str(args.chapter)], env)
        print("   用时 %.1f 秒" % dt5)
        for line in (r5.stdout or "").strip().splitlines()[:30]:
            print("   | " + line)
        con = sqlite3.connect("file:///%s?mode=ro" % SANDBOX_ABS.replace("\\", "/"), uri=True)
        n_blind = con.execute("select count(*) from blind_reviews where novel_id=?", (nid,)).fetchone()[0]
        con.close()
        check(n_blind >= 1, "盲审结果已落库（%d 条）" % n_blind)
    else:
        print("\n-- 双盲审：未跑（加 --blind 打开）--")

    # ---------------------------------------------------------------- 真库
    print("\n-- 真库零改动 --")
    con = sqlite3.connect("file:///%s?mode=ro" % os.path.join(REPO, "data.db").replace("\\", "/"), uri=True)
    prod_books = con.execute("select count(*) from novels").fetchone()[0]
    prod_ver = con.execute("select count(*) from chapter_versions").fetchone()[0]
    con.close()
    check(prod_books == 3, "真库 books = 3（实际 %s）" % prod_books)
    print("   · 真库 chapter_versions = %s（供下次比对）" % prod_ver)

    print("\n=== 结果：通过 %d / 失败 %d ===" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  ✗ %s" % f)
    if not args.keep:
        print("（沙箱保留在 %s，便于人工查看；删除即删该文件）" % SANDBOX_REL)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
