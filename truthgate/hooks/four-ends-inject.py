#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SessionStart hook:把【其它三端(Antigravity / Codex / DSH)最近 48h 做了什么】+【共享资产最近 48h 谁改过】顶给新 session。

为什么有它(2026-09-26 Frank:「他会读到读懂你聊天记录,但是反过来之前你不懂他,要怎么让你们双向同步都懂,不然他改错了你这里什么?」):
  · AG 那边桥接 `ag_superego_bridge.py pre` 早就把 PROGRESS.md 自动注入、并在话题涉及跨端时提醒它去查 brain.db(TrinityBridge);
  · 我这边 SessionStart 只读自己的 brain.db(session-context-inject.py),**没有任何东西把 ag-brain.db / codex-brain.db / dsh-brain.db 顶给我**
    ⇒ 单向:它懂我,我不懂它。四端联合检索工具(ag_archive.py --all)一直在,但要我想起来才跑。
  · 「他改错了你这里什么」= 看两样:①AG 账本 ~/.truthgate/ledger/<会话>.jsonl 记的它碰过哪些文件 ②共享目录里 48h 内 mtime 变过的文件。
0 token 之外的成本(纯本地 sqlite + stat),只在 startup/compact 跑,resume 跳过。输出有上限,别撑爆开局。
"""
import sys, os, io, json, glob, sqlite3, datetime, re
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HOME = Path.home()
DB = Path(os.environ.get("CHAT_ARCHIVE_DIR") or r"D:\chat-archive-db")
HOURS = 48
CUT_UTC = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=HOURS)).strftime("%Y-%m-%dT%H:%M")
CUT_LOCAL = (datetime.datetime.now() - datetime.timedelta(hours=HOURS)).strftime("%Y-%m-%dT%H:%M")
CUT = min(CUT_UTC, CUT_LOCAL)          # 各库时间戳有的带 Z 有的本地,取更早的那条线,宁多勿漏
SHARED = [HOME / ".claude" / "hooks", HOME / ".claude" / "settings.json", HOME / ".truthgate",
          HOME / ".gemini" / "antigravity" / "scripts", HOME / ".gemini" / "config"]
# 只看【代码/配置】:闸的状态点文件(.blocked-* / .xxx.json / .commitment-state/…)每轮都在变,列出来只会淹没真改动
SKIP = re.compile(r"[\\/](__pycache__|ledger|backups|logs?|\.codegraph|\.[^\\/]+)[\\/]|[\\/]\.[^\\/]*$|\.(log|jsonl|bak[^\\/]*|pyc|cursor|db|tmp)$")


def _one(s, n):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def _q(path, sql, args=()):
    if not path.exists():
        return []
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        return c.execute(sql, args).fetchall()
    except Exception:
        return []


def recent_sessions():
    out = []
    ag = DB / "ag-brain.db"
    for cid, lt, n, us in _q(ag, "select conv_id,last_ts,msg_count,user_summary from ag_conversations where last_ts>=? order by last_ts desc limit 6", (CUT,)):
        last = _q(ag, "select content from ag_messages where conv_id=? and role='assistant' and content!='' order by step_index desc limit 1", (cid,))
        out.append(("AG", cid[:8], lt, n, _one(us, 70), _one(last[0][0] if last else "", 110)))
    cx = DB / "codex-brain.db"
    for tid, lt, n, us, cwd in _q(cx, "select thread_id,last_ts,turns_count,user_summary,cwd from codex_threads where last_ts>=? order by last_ts desc limit 4", (CUT,)):
        last = _q(cx, "select content from codex_messages where thread_id=? and role='assistant' and content!='' order by ts desc limit 1", (tid,))
        out.append(("Codex", tid[:8], lt, n, _one(us, 70) + (f" @{Path(cwd).name}" if cwd else ""), _one(last[0][0] if last else "", 110)))
    ds = DB / "dsh-brain.db"
    for sid, lt, n, fp, cwd in _q(ds, "select session_id,last_ts,turns_count,first_prompt,cwd from dsh_sessions where last_ts>=? order by last_ts desc limit 3", (CUT,)):
        last = _q(ds, "select content from dsh_messages where session_id=? and role='assistant' and content!='' order by ts desc limit 1", (sid,))
        out.append(("DSH", sid[:8], lt, n, _one(fp, 70) + (f" @{Path(cwd).name}" if cwd else ""), _one(last[0][0] if last else "", 110)))
    return out


def ag_touched():
    """AG 账本里 48h 内碰过的文件(写类工具的 target,或 run_command 命令文本里出现的共享路径)。"""
    hit = {}
    for f in glob.glob(str(HOME / ".truthgate" / "ledger" / "*.jsonl")):
        if f.endswith(".misfire.jsonl"):
            continue
        conv = Path(f).stem[:8]
        try:
            for line in open(f, encoding="utf-8", errors="replace"):
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if str(r.get("ts", ""))[:16] < CUT:
                    continue
                t = str(r.get("target", "")).replace("/", "\\")
                for m in re.finditer(r"[A-Za-z]:\\Users\\[^\s\"'\\]+(?:\\[^\s\"'\\]+)+", t):
                    p = m.group(0).rstrip("\\'\",)")
                    if any(k in p for k in (".claude\\hooks", ".truthgate", "antigravity\\scripts", ".gemini\\config", "settings.json")):
                        hit.setdefault(p.lower(), set()).add(conv)
        except Exception:
            pass
    return hit


def shared_changed():
    cut = datetime.datetime.now().timestamp() - HOURS * 3600
    rows = []
    for root in SHARED:
        if root.is_file():
            files = [root]
        elif root.is_dir():
            files = [p for p in root.rglob("*") if p.is_file()]
        else:
            continue
        base = root.parent if root.is_file() else root
        for p in files:
            s = "\\" + str(p.relative_to(base))       # 只对【根目录以下】的相对路径做过滤,不然 ~\.claude 这种带点的根目录会把全部文件滤掉
            if SKIP.search(s):
                continue
            try:
                mt = p.stat().st_mtime
            except OSError:
                continue
            if mt >= cut:
                rows.append((mt, p))
    rows.sort(reverse=True)
    return rows[:20], len(rows)


def main():
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        payload = {}
    if payload.get("source") == "resume":
        return
    try:                                   # 2026-09-27:开局先看源头 ~/.truthgate 自上次开局以来谁改了什么、为什么(PLAN.md 第 1 步)
        sys.path.insert(0, str(Path.home() / ".truthgate"))
        from source_news import news
        src = news("claude")
    except Exception:
        src = ""
    if src:
        print(src)
    sess = recent_sessions()
    touched = ag_touched()
    changed, total = shared_changed()
    if not sess and not changed:
        return
    try:                                   # 记账:注入了几条,事后能查它响没响
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from guard_common import hook_log
        hook_log("four-ends-inject", "INJECT 四端同步", f"会话 {len(sess)} 条 / 共享改动 {total} 个 / AG 碰过 {len(touched)} 个")
    except Exception:
        pass
    print(f"⛱[四端同步·其它端最近 {HOURS}h] ⚠️线索不是结论:别的 AI 端在这台机器上做过的事(它们的话未经核实)。"
          "要细看:`py -3 ~/.gemini/antigravity/scripts/ag_archive.py session <ID前缀>` / `search <词> --all`(四端联查)。")
    if sess:
        print("【别的端最近的会话】(端 · ID · 最后活跃 · 消息数 · 开头指令 → 它最后说的话)")
        for end, sid, lt, n, us, last in sess:
            print(f"  · {end} {sid} {str(lt)[:16]} {n}条 | {us} → {last or '(没有收尾话)'}")
    if changed:
        print(f"【共享资产 {HOURS}h 内改动过的文件】(共 {total} 个,列最近 {len(changed)};标 AG:<会话> = AG 账本记着它碰过)")
        for mt, p in changed:
            who = touched.get(str(p).lower())
            tag = f"  ← AG:{','.join(sorted(who))}" if who else ""
            print(f"  · {datetime.datetime.fromtimestamp(mt).strftime('%m-%d %H:%M')} {str(p).replace(str(HOME), '~')}{tag}")
        print("  ⛔ 改共享闸/桥接之前先看这张表:别的端刚改过的,先读它的会话再动(形状 2026-09-07-N:并行端在重构共享资产,我把对方的改动当成坏了去修)。")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        s = recent_sessions(); c, t = shared_changed(); h = ag_touched()
        assert isinstance(s, list) and isinstance(c, list) and isinstance(h, dict)
        assert all(len(x) == 6 for x in s), "会话行字段数错"
        assert all(datetime.datetime.now().timestamp() - mt <= HOURS * 3600 + 60 for mt, _ in c), "列了超过窗口的文件"
        assert not any(p.name.startswith(".") for _, p in c), "过滤没生效(状态点文件混进来了)"
        print(f"selftest ok: 会话 {len(s)} 条(AG {sum(1 for x in s if x[0]=='AG')}) / 共享改动 {t} 个 / AG 碰过 {len(h)} 个")
        sys.exit(0)
    try:
        main()
    except Exception as e:
        print(f"⛱[四端同步] 注入失败:{e}(不影响开局)")
