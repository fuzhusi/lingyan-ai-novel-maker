# -*- coding: utf-8 -*-
"""08_generate_chapter.py —— 带「写作纪律」的章节生成器（一键本章批量版）。

为什么要这个脚本：
  1. 中文长文本走 PowerShell 命令行容易踩编码坑，这里用 subprocess 直接传 argv（_lib 已验证）；
  2. 每章都要带上 `content/writing_directives.md` 里的通用纪律（双盲审暴露的 AI 手癖），
     否则放量时每章重犯；
  3. 坑 8：门禁失败时 CLI 只打印一行错误就 return，正文与 `--out` 全丢——本脚本会**明确标红**该情况。

用法：
    .venv/Scripts/python.exe lingyi_setup/08_generate_chapter.py --numbers 1,2,3
    .venv/Scripts/python.exe lingyi_setup/08_generate_chapter.py --from 1 --to 5 --force
    .venv/Scripts/python.exe lingyi_setup/08_generate_chapter.py --numbers 1 --no-directive --dry-run

默认行为：已有版本的章节**跳过**（防重复扣费），--force 强制重生成。
沙箱：设 DATABASE_PATH 即切沙箱库（_lib 自动识别并打横幅）。
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402

DEFAULT_OUT_DIR = os.path.join(L.REVIEW_DIR, "4_试写")


def load_directive(content_dir, enabled=True):
    """从 writing_directives.md 取正文纪律（去掉开头的用法说明，只留规则）。"""
    if not enabled:
        return ""
    path = os.path.join(content_dir, "writing_directives.md")
    if not os.path.exists(path):
        L.warn("找不到 %s，本次不带特别指示" % path)
        return ""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    idx = raw.find("## ")
    body = raw[idx:] if idx >= 0 else raw
    # 去掉 markdown 标记，只留可读规则（模型读 markdown 也没问题，这里只是瘦身）
    body = re.sub(r"^#{2,3}\s*", "", body, flags=re.M)
    return body.strip()


def parse_numbers(args):
    if args.numbers:
        return [int(x) for x in re.split(r"[,\s]+", args.numbers.strip()) if x]
    if args.from_ and args.to:
        return list(range(args.from_, args.to + 1))
    raise SystemExit("请给 --numbers 1,2,3 或 --from N --to M")


def already_has_version(nid, number):
    return bool(L.sql_scalar(
        "select count(*) from chapter_versions v join chapters c on c.id=v.chapter_id"
        " where c.novel_id=? and c.chapter_number=?", (nid, number)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--novel", type=int, help="小说 ID（缺省取 content/_state.json）")
    ap.add_argument("--numbers", help="章号列表，如 1,2,3")
    ap.add_argument("--from", dest="from_", type=int, help="起始章号")
    ap.add_argument("--to", type=int, help="结束章号")
    ap.add_argument("--content-dir", default=L.DEFAULT_CONTENT)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--force", action="store_true", help="已有版本也重新生成")
    ap.add_argument("--no-directive", action="store_true", help="不带写作纪律")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    L.banner("08 章节生成（带写作纪律）")
    nid = args.novel or L.require_novel_id(args.content_dir)
    numbers = parse_numbers(args)
    directive = load_directive(args.content_dir, enabled=not args.no_directive)

    L.info("novel_id=%d，章号 %s" % (nid, numbers))
    L.info("特别指示长度 = %d 字符（%s）"
           % (len(directive), "已关闭" if args.no_directive else "writing_directives.md"))

    if args.dry_run:
        for n in numbers:
            skip = already_has_version(nid, n) and not args.force
            print("   [dry] 第%d章 %s" % (n, "跳过（已有版本）" if skip else "生成"))
        print("   [dry] 命令：cli.py chapter pipeline --novel %d --number N --save --directive <%d 字符> --out ..."
              % (nid, len(directive)))
        return

    os.makedirs(args.out_dir, exist_ok=True)
    log_lines = []
    results = []

    for n in numbers:
        if already_has_version(nid, n) and not args.force:
            L.info("第 %d 章已有版本 —— 跳过（--force 可强制重生成）" % n)
            results.append((n, "skipped", None, 0))
            continue

        out_file = os.path.join(args.out_dir, "第%d章.md" % n)
        argv = ["chapter", "pipeline", "--novel", str(nid), "--number", str(n),
                "--save", "--out", out_file]
        if directive:
            argv += ["--directive", directive]

        L.step("生成第 %d 章" % n)
        t0 = time.time()
        r = L.run_cli(argv, check=False, echo=False)
        dt = time.time() - t0
        out = r.stdout or ""
        err = (r.stderr or "").strip()

        saved = re.search(r"已保存版本 id=(\d+)", out)
        score = re.search(r"人味分[:：]\s*(\S+)", out)
        gate_fail = "门禁未通过" in out
        hard_fail = "✗ 失败" in out

        if saved:
            L.ok("第 %d 章完成：版本 id=%s，人味分=%s，用时 %.0f 秒"
                 % (n, saved.group(1), score.group(1) if score else "?", dt))
            status = "ok"
        elif gate_fail or hard_fail:
            L.warn("第 %d 章**未落库**（坑 8：门禁失败会把正文整个丢掉），用时 %.0f 秒" % (n, dt))
            L.warn("   CLI 原话：%s" % (out.strip().splitlines()[-1] if out.strip() else "(无输出)"))
            L.warn("   对策：调 chapter converge / 走 Web 写作页取正文，或调纪律后重跑")
            status = "gate_failed"
        else:
            L.warn("第 %d 章结果不明确（未解析到保存标记），用时 %.0f 秒" % (n, dt))
            L.warn("   输出尾部：%s" % (" | ".join(out.strip().splitlines()[-3:]) or "(空)"))
            status = "unknown"

        stages = re.findall(r"\[([✓✗])\] (\S+)\s*(.*)", out)
        if stages:
            L.info("   阶段：" + " / ".join("%s%s%s" % (m[1], m[0], (" " + m[2].strip()) if m[2].strip() else "")
                                           for m in stages))
        if err:
            short = " ".join(line for line in err.splitlines() if "embedding" not in line)[:200]
            if short.strip():
                L.info("   stderr（已滤 embedding 噪声）：%s" % short.strip()[:200])

        log_lines.append("| 第%d章 | %s | %s | %s | %.0f 秒 |"
                         % (n, status, saved.group(1) if saved else "-",
                            score.group(1) if score else "-", dt))
        results.append((n, status, score.group(1) if score else None, dt))

    # ---------------------------------------------------------------- 汇总
    L.step("汇总")
    ok_n = sum(1 for r in results if r[1] == "ok")
    L.ok("成功落库 %d 章 / 共 %d 章" % (ok_n, len(results)))
    for n, status, score, dt in results:
        mark = {"ok": "✓", "skipped": "·", "gate_failed": "✗", "unknown": "?"}[status]
        L.info("   %s 第%d章 %s%s" % (mark, n, status,
                                    (" 人味分 " + score) if score else ""))

    if log_lines:
        log_path = os.path.join(args.out_dir, "_生成日志.md")
        header = "" if os.path.exists(log_path) else "# 章节生成日志\n\n| 章 | 状态 | 版本 id | 人味分 | 用时 |\n|---|---|---|---|---|\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(header)
            f.write("<!-- %s -->\n" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            f.write("\n".join(log_lines) + "\n")
        L.info("日志追加：%s" % log_path)

    return 1 if any(r[1] in ("gate_failed", "unknown") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
