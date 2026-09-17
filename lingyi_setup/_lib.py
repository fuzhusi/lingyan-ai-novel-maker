# -*- coding: utf-8 -*-
"""lingyi_setup 建库脚本共用工具。

为什么用 Python 而不是 bash/PowerShell：
  - 宿主机是 Windows PowerShell 5.1（无 pwsh），它按 ANSI 读取无 BOM 的 .ps1，
    脚本里的中文会被误码成语法错误；bash 只有 WindowsApps 的 WSL 桩子。
  - Python 是本项目原生语言（uv 管理），UTF-8 无坑，subprocess 抓取已实测可用。

沙箱机制（重要）：
  设环境变量 DATABASE_PATH 指向另一个 .db 文件，cli.py 与全部导出/检查脚本都会
  切到那份库（app/config.py:14 支持）。用它可以在真库副本上端到端演练建库链，
  真库零风险。IS_SANDBOX 为真时所有输出会打上醒目横幅。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import deque

SETUP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SETUP_DIR)
PYEXE = os.path.join(REPO_ROOT, ".venv", "Scripts", "python.exe")
CLI = os.path.join(REPO_ROOT, "cli.py")
DEFAULT_DB = os.path.join(REPO_ROOT, "data.db")
DEFAULT_CONTENT = os.path.join(SETUP_DIR, "content")
REVIEW_DIR = os.path.join(SETUP_DIR, "review")

_env_db = (os.environ.get("DATABASE_PATH") or "").strip()
if _env_db:
    DB = _env_db if os.path.isabs(_env_db) else os.path.join(REPO_ROOT, _env_db)
    DB = os.path.abspath(DB)
else:
    DB = DEFAULT_DB
IS_SANDBOX = os.path.abspath(DB) != os.path.abspath(DEFAULT_DB)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

if not os.path.exists(PYEXE):
    raise SystemExit("找不到虚拟环境 Python：%s（先执行 uv sync）" % PYEXE)
if not os.path.exists(CLI):
    raise SystemExit("找不到 cli.py：%s" % CLI)

_DRY = False


# --------------------------------------------------------------------------- 输出
def step(msg):
    print("\n== %s" % msg)


def ok(msg):
    print("   ✓ %s" % msg)


def info(msg):
    print("   · %s" % msg)


def warn(msg):
    print("   ! %s" % msg)


def banner(title):
    if IS_SANDBOX:
        print("\n" + "#" * 68)
        print("# [沙箱模式] DATABASE_PATH=%s" % DB)
        print("# 真库 data.db 不会被改动。")
        print("#" * 68)
    else:
        print("\n" + "-" * 68)
        print("- [生产库] %s" % DB)
        print("-" * 68)
    print("=== %s ===" % title)


def set_dry_run(flag):
    global _DRY
    _DRY = bool(flag)
    if _DRY:
        warn("dry-run：只打印将要执行的 cli.py 调用，不写任何数据")


def is_dry():
    return _DRY


# --------------------------------------------------------------------------- 调 CLI
_NOISE = ("LegacyAPIWarning", "sqlalche.me", "Setting.query.get", "pref = Setting",
          "warnings.warn")


def _clean_err(text):
    keep = []
    for line in (text or "").splitlines():
        if any(n in line for n in _NOISE):
            continue
        if line.strip():
            keep.append(line)
    return "\n".join(keep)


def run_cli(args, check=True, echo=True):
    """调用 cli.py。check=True 时非 0 退出直接抛异常，避免"以为成功其实没写进去"。"""
    args = [str(a) for a in args]
    if not os.path.exists(DB):
        raise SystemExit("数据库不存在：%s" % DB)
    r = subprocess.run([PYEXE, CLI] + args, cwd=REPO_ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if echo:
        out = (r.stdout or "").rstrip()
        if out:
            print(out)
        err = _clean_err(r.stderr)
        if err:
            print("[stderr] %s" % err)
    if check and r.returncode != 0:
        raise SystemExit("cli.py %s 退出码 %s" % (" ".join(args), r.returncode))
    return r


def run_cli_expect_ok(args):
    """写操作专用：必须退出码 0 且输出里出现 ✓，否则视为失败。"""
    args = [str(a) for a in args]
    r = run_cli(args, check=True, echo=True)
    if "✓" not in (r.stdout or ""):
        raise SystemExit("cli.py %s 没有返回成功标记 ✓，已中止（输出见上）" % " ".join(args))
    return r


def run_write(args):
    """建库写操作的统一入口：dry-run 时只打印。"""
    if _DRY:
        print("   [dry] cli.py %s" % " ".join(str(a) for a in args))
        return None
    return run_cli_expect_ok(args)


def parse_new_id(result, label="对象"):
    """从 cli.py 的成功输出里解析新建对象的 ID，例如 '✓ 已创建角色: [12] 名字'。"""
    if result is None:
        return None
    m = re.search(r"\[(\d+)\]", result.stdout or "")
    if not m:
        raise SystemExit("无法从 cli 输出解析%s的 ID（输出见上）" % label)
    return int(m.group(1))


# --------------------------------------------------------------------------- 只读 SQL
def _connect_ro():
    uri = "file:///%s?mode=ro" % DB.replace("\\", "/")
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def sql_scalar(query, params=()):
    con = _connect_ro()
    try:
        row = con.execute(query, params).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def sql_rows(query, params=()):
    con = _connect_ro()
    try:
        return [dict(r) for r in con.execute(query, params).fetchall()]
    finally:
        con.close()


# --------------------------------------------------------------------------- 防重跑
def assert_novel_absent(title):
    n = sql_scalar("select count(*) from novels where title=?", (title,))
    if n:
        raise SystemExit("[防重跑] 已存在同名书《%s》，中止。同名字段无唯一约束，重复建会出两本。" % title)
    ok("书名《%s》未被占用" % title)


def assert_novel_empty(novel_id, table):
    n = sql_scalar("select count(*) from %s where novel_id=?" % table, (novel_id,))
    if n:
        raise SystemExit("[防重跑] novel %s 的 %s 已有 %s 条，中止。" % (novel_id, table, n))
    ok("%s 为空（novel %s）" % (table, novel_id))


def get_novel_id(title):
    nid = sql_scalar("select id from novels where title=? order by id limit 1", (title,))
    if not nid:
        raise SystemExit("找不到书《%s》" % title)
    return int(nid)


def get_novel(novel_id):
    rows = sql_rows("select * from novels where id=?", (novel_id,))
    if not rows:
        raise SystemExit("小说 %s 不存在" % novel_id)
    return rows[0]


# --------------------------------------------------------------------------- 内容与状态
def content_parser(title):
    ap = argparse.ArgumentParser(description=title)
    ap.add_argument("--content-dir", default=DEFAULT_CONTENT,
                    help="内容 JSON 目录（默认 lingyi_setup/content）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将执行的 cli.py 调用，不写数据")
    return ap


def load_json(path, required=True):
    if not os.path.exists(path):
        if required:
            raise SystemExit("缺少内容文件：%s" % path)
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_list(path, label):
    data = load_json(path)
    if not isinstance(data, list):
        raise SystemExit("%s 顶层必须是数组（当前是 %s）" % (label, type(data).__name__))
    if not data:
        raise SystemExit("%s 是空数组——先把内容填进去再落库。" % label)
    return data


def state_path(content_dir):
    return os.path.join(content_dir, "_state.json")


def load_state(content_dir):
    p = state_path(content_dir)
    if not os.path.exists(p):
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(content_dir, data):
    p = state_path(content_dir)
    old = load_state(content_dir)
    old.update(data)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False, indent=2)
    ok("状态已写入 %s" % os.path.relpath(p, REPO_ROOT))


def require_novel_id(content_dir):
    st = load_state(content_dir)
    if st.get("novel_id"):
        return int(st["novel_id"])
    novel = load_json(os.path.join(content_dir, "novel.json"), required=False)
    if novel and novel.get("title"):
        return get_novel_id(novel["title"])
    raise SystemExit("拿不到 novel_id：先跑 01_create_novel.py（或补 content/_state.json）")


# --------------------------------------------------------------------------- 伏笔状态机
# 出自 cli.py:885-897 的合法迁移表（单向，仅 advancing→buried 可回退）
FS_TRANSITIONS = {
    "open": ["planned", "buried"],
    "planned": ["buried", "abandoned"],
    "buried": ["advancing", "abandoned"],
    "advancing": ["reclaimable", "buried", "abandoned"],
    "reclaimable": ["resolved", "abandoned"],
    "resolved": [],
    "abandoned": [],
}


def fs_path(start, target):
    """BFS 最短合法迁移路径（不含起点，含终点）。不可达返回 None。"""
    if start == target:
        return []
    q = deque([(start, [])])
    seen = {start}
    while q:
        cur, path = q.popleft()
        for nxt in FS_TRANSITIONS.get(cur, []):
            if nxt in seen:
                continue
            np = path + [nxt]
            if nxt == target:
                return np
            seen.add(nxt)
            q.append((nxt, np))
    return None


def advance_foreshadow(fid, current, target):
    """按合法路径把伏笔推进到 target。cli.py 的 create 不接受 --status，必须单独推进。"""
    path = fs_path(current, target)
    if path is None:
        raise SystemExit("伏笔 [%s] 无法从 %s 迁移到 %s（合法目标：%s）"
                         % (fid, current, target, ", ".join(FS_TRANSITIONS.get(current, [])) or "无"))
    cur = current
    for nxt in path:
        run_write(["foreshadow", "status", "--id", str(fid), "--status", nxt])
        cur = nxt
    return cur
