# -*- coding: utf-8 -*-
"""改了没生效：这一轮动过一个【正在运行的程序】读的文件，而那个程序比文件还旧 ⇒ 它跑的还是旧的。只看事实，不看措辞。

来历（2026-10-05，tempchat 会话）：我撤掉 DSH 模型清单里两张过期月卡（改了 cordis.patch.yml），DSH 只在启动时读它，
我没重启就交付，还写了一句「DSH 要重启才生效」。Frank：「没生效=没交付完成，我铁律和 truthgate 没用吗？」
CLAUDE.md 里早有这条铁律（「改了长驻进程的代码 = 改了一份没人加载的文件」「收尾四步」），但没有任何一道闸查它：
交付自检只管「改了网页要开浏览器」「改了接口要发请求」。

判据（三样都是事实）：
  ① 文件：本轮工具调用里出现过它的路径（命令、脚本正文都算），它现在存在，修改时间在本轮之内；
  ② 进程：现在还在跑，启动时间早于这个文件的修改时间；
  ③ 关系（任一）：A 进程的命令行里写着这个文件（node server.js / python bot.py 这类）；
                  B 文件是配置类（yml/json/toml/ini…），路径里有一段目录名和程序名对得上
                    （…\\dsh-desktop\\…\\cordis.patch.yml ↔ DSH Desktop.exe）。
重启之后进程比文件新 ⇒ 自然放行。有的程序会自己重新读配置：那就在回复里写一行说明，这条每轮只拦一次。

量不到的（登记）：文件是别的东西代改的、路径从没在本轮动作里出现过；配置和程序名对不上的（放在别处的配置）；
开机服务 / 计划任务拉起的、当前用户读不到命令行的进程。
自检：py -3 stale_process.py
"""
import json
import os
import re
import time

CONFIG_EXT = (".yml", ".yaml", ".json", ".toml", ".ini", ".conf", ".cfg", ".env")
CODE_EXT = (".py", ".js", ".mjs", ".cjs", ".ts")
_EXT = r"(?:ya?ml|json|toml|ini|conf|cfg|env|py|js|mjs|cjs|ts)"
_HEAD = r"(?:[A-Za-z]:[\\/]|~[\\/]|/[a-zA-Z]/|%[A-Za-z]+%[\\/]|\$env:[A-Za-z]+[\\/]|\$\{?HOME\}?[\\/])"
PATH_QUOTED = re.compile(r"[\"'](" + _HEAD + r"[^\"'\n<>|]{1,240}?\." + _EXT + r")[\"']")
PATH_BARE = re.compile(r"(?<![\w\"'])(" + _HEAD + r"[^\s\"'<>|;,)]{1,240}?\." + _EXT + r")(?![\w.])")
# 这些地方的文件不是「被长驻进程读的东西」：临时目录、闸自己、版本库内部、依赖包
SKIP_PATH = re.compile(r"[\\/](?:Temp|tmp|scratchpad|node_modules|\.git|__pycache__|\.truthgate|backups?)[\\/]|[\\/]\.claude[\\/]", re.I)
# 这些程序名太泛，目录名对上也不说明问题（~/.claude 下的文件 ↔ claude.exe；…\\Code\\… ↔ Code.exe）
GENERIC = {"claude", "code", "node", "python", "pythonw", "py", "bash", "sh", "powershell", "pwsh", "git", "explorer",
           "chrome", "msedge", "opera", "firefox", "cmd", "conhost", "java", "docker", "system", "svchost", "electron"}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _local(p):
    try:
        from six_universes import local_path
        return local_path(p)
    except Exception:
        return os.path.normpath(os.path.expanduser(str(p)))


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def mentioned_paths(msgs):
    """本轮所有工具调用的参数里（命令、脚本正文、文件路径）出现过的、像配置 / 代码文件的路径。"""
    out = []
    for m in msgs or []:
        if m.get("type") != "assistant":
            continue
        c = (m.get("message") or {}).get("content") or []
        for b in c if isinstance(c, list) else []:
            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                continue
            for s in _strings(b.get("input") or {}):
                for rx in (PATH_QUOTED, PATH_BARE):
                    for g in rx.findall(s):
                        p = _local(g)
                        if p not in out:
                            out.append(p)
    return out


def turn_epoch(msgs):
    from datetime import datetime
    for m in msgs or []:
        ts = m.get("timestamp")
        if ts:
            try:
                return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
            except Exception:
                return None
    return None


def changed_files(msgs, since, skip=SKIP_PATH):
    """本轮动作里提到过、现在存在、修改时间在本轮之内的文件 → [(路径, 修改时间)]。skip=None 只给自检用。"""
    out = []
    for p in mentioned_paths(msgs):
        if skip is not None and skip.search(p):
            continue
        try:
            mt = os.stat(p).st_mtime
        except OSError:
            continue
        if mt >= since:
            out.append((p, mt))
    return out


# 只有这些「跑脚本的」程序才值得去读命令行（关系 A）。读命令行很慢：2026-10-05 实测机器满载时
# 485 个进程全读一遍要 18 秒，收尾闸等不起 ⇒ 名字和启动时间一次取完（快），命令行只对这几种、且比文件旧的才读。
INTERPRETERS = {"node", "python", "pythonw", "py", "deno", "bun", "pwsh", "powershell", "java", "ruby", "php", "pm2"}
SCAN_BUDGET = 2.5


def _processes(wanted, older_than=None):
    """[(pid, 名字, '', 命令行, 启动时间)]，只含名字在 wanted 里的进程（wanted = 归一化后的程序名集合）。
    名字用系统的 tasklist 一次取完（实测满载时 1.5 秒；psutil 逐个取名字 3 秒、再取启动时间 9 秒），
    启动时间 / 命令行只对名字对得上的那几个查；超时就收手。"""
    import csv
    import io as _io
    import subprocess
    import psutil
    t0 = time.time()
    me = set()
    try:
        p = psutil.Process()
        me = {p.pid} | {a.pid for a in p.parents()}
    except Exception:
        pass
    try:
        raw = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=8,
                             creationflags=0x08000000 if os.name == "nt" else 0).stdout
    except Exception:
        return []
    out = []
    for row in csv.reader(_io.StringIO(raw)):
        if len(row) < 2 or not row[1].isdigit():
            continue
        name, pid = row[0], int(row[1])
        stem = _norm(os.path.splitext(name)[0])
        if stem not in wanted or pid in me or time.time() - t0 > SCAN_BUDGET + 2:
            continue
        try:
            pr = psutil.Process(pid)
            born = pr.create_time()
            if older_than is not None and born >= older_than:
                continue
            cmd = " ".join(pr.cmdline()) if stem in INTERPRETERS else ""
        except Exception:
            continue
        out.append((pid, name, "", cmd, born))
    return out


def stale(files, procs=None):
    """→ [(文件, 程序名, pid, 关系)]：程序在跑、比文件旧、而且读它。"""
    if not files:
        return []
    if procs is None:
        wanted = set(INTERPRETERS)
        for path, _ in files:
            if os.path.splitext(path.lower())[1] in CONFIG_EXT:
                wanted |= {c for c in (_norm(x) for x in re.split(r"[\\/]", path)[:-1]) if len(c) >= 4 and c not in GENERIC}
        procs = _processes(wanted, max(mt for _, mt in files))
    hits = []
    for path, mt in files:
        low = path.lower().replace("\\", "/")
        ext = os.path.splitext(low)[1]
        comps = {_norm(c) for c in re.split(r"[\\/]", path)[:-1]}
        for pid, name, exe, cmd, born in procs:
            if born >= mt - 2:
                continue
            stem = _norm(os.path.splitext(name)[0])
            if low in cmd.lower().replace("\\", "/"):
                hits.append((path, name, pid, "它的命令行里写着这个文件"))
                break
            if ext in CONFIG_EXT and len(stem) >= 4 and stem not in GENERIC and stem in comps:
                hits.append((path, name, pid, "这是它的配置目录里的文件"))
                break
    return hits


def verdict(msgs):
    """收尾判决。msgs = 本轮消息（从本轮第一条真人消息起）。返回 None 或 (日志串, 拦截理由)。"""
    since = turn_epoch(msgs)
    if since is None:
        return None
    files = changed_files(msgs, since)
    if not files:
        return None
    hits = stale(files)
    if not hits:
        return None
    lines = ["  · %s ← %s（pid %s）还是改之前启动的；%s" % (os.path.basename(p), n, pid, why) for p, n, pid, why in hits[:4]]
    return ("%s<-%s" % (os.path.basename(hits[0][0]), hits[0][1]), (
        "⛔ 交付自检·改了没生效：这一轮改过的文件，读它的程序还是改之前启动的那一个 —— 它跑的还是旧的。\n" + "\n".join(lines) +
        "\nFrank 2026-10-05：「没生效=没交付完成」。收尾四步是：改了 → 进程重载了 → 新的真的生效了 → 旧的清掉了；你停在了第一步。\n"
        "重启一个停了能再起的程序不用等他授权（CLAUDE.md「不可逆是后果的属性」第 4 条）：先看一眼它有没有正在跑的任务，"
        "然后重启，再用它的界面 / 接口核对新的真的生效了。\n"
        "这个程序会自己重新读配置、不用重启：回复里写一行「<程序> 会自动重读 <文件>」，这条每轮只拦一次。"))


def ag_msgs(tool_calls, window=3600):
    """把 AG 的工具调用包成 verdict 认的形状。
    ponytail: AG 的对话记录不带每条的时间 ⇒ 「本轮之内改过」用「最近 window 秒内改过」代替；
    AG 一轮跑超过一小时会漏，真漏了再把本轮起点从它的记录里取出来。"""
    import json
    from datetime import datetime, timezone

    def unpack(x):                       # AG 的参数常是一段 JSON 文本，路径在里面带转义 ⇒ 先解开
        if isinstance(x, str) and x.lstrip()[:1] in "{[":
            try:
                return unpack(json.loads(x))
            except Exception:
                return x
        if isinstance(x, dict):
            return {k: unpack(v) for k, v in x.items()}
        if isinstance(x, list):
            return [unpack(v) for v in x]
        return x
    ts = datetime.fromtimestamp(time.time() - window, timezone.utc).isoformat()
    return [{"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "tool_use", "input": {"calls": unpack(tool_calls)}}]}}]


def verdict_ag(tool_calls, window=3600):
    """AG 端收尾判决：同一条事实检查，输入换成 AG 的工具调用清单。"""
    return verdict(ag_msgs(tool_calls, window))


if __name__ == "__main__":
    import json
    import sys
    import tempfile
    sys.stdout.reconfigure(encoding="utf-8")
    bad = []

    def ok(name, cond):
        print(("✓ " if cond else "✗ ") + name)
        cond or bad.append(name)

    now = time.time()
    d = tempfile.mkdtemp(prefix="sp_")
    app = os.path.join(d, "x", "AppData", "Roaming", "dsh-desktop", "harness")
    os.makedirs(app)
    cfgp = os.path.join(app, "cordis.patch.yml")
    open(cfgp, "w").write("a: 1\n")
    srv = os.path.join(d, "x", "proj", "server.js")
    os.makedirs(os.path.dirname(srv))
    open(srv, "w").write("x\n")
    OLD, NEW = now - 3600, now + 60
    DSH = (111, "DSH Desktop.exe", "C:\\P\\DSH Desktop\\DSH Desktop.exe", '"C:\\P\\DSH Desktop\\DSH Desktop.exe" --updated', OLD)
    NODE = (222, "node.exe", "C:\\n\\node.exe", 'node "%s"' % srv, OLD)
    ok("10-05 真实形状：改了 DSH 的配置、DSH 是改之前起的 ⇒ 认出", stale([(cfgp, now)], [DSH]) and stale([(cfgp, now)], [DSH])[0][1] == "DSH Desktop.exe")
    ok("DSH 重启过（比文件新）⇒ 放", not stale([(cfgp, now)], [DSH[:4] + (NEW,)]))
    ok("改了 server.js、node server.js 还是旧的 ⇒ 认出", stale([(srv, now)], [NODE]))
    ok("node 跑的是别的文件 ⇒ 放", not stale([(srv, now)], [(223, "node.exe", "", "node other.js", OLD)]))
    ok("~\\.claude 下的配置 ↔ claude.exe（名字太泛）⇒ 放", not stale([(os.path.join(d, "x", "claude", "settings.json"), now)], [(1, "claude.exe", "", "claude.exe", OLD)]))
    ok("…\\Code\\User\\settings.json ↔ Code.exe ⇒ 放", not stale([(os.path.join(d, "Code", "User", "settings.json"), now)], [(1, "Code.exe", "", "Code.exe", OLD)]))
    ok("代码文件只靠目录名对上 ⇒ 不算（要命令行里写着它）", not stale([(os.path.join(app, "plugin.js"), now)], [DSH]))
    ok("没有改过的文件 ⇒ 放", not stale([], [DSH]))
    U = {"type": "user", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 30)), "message": {"content": "撤掉"}}

    def T(name, inp):
        return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}
    script = 'CFG = os.path.expanduser("%s")\nopen(CFG, "w")' % cfgp.replace("\\", "/")
    ok("路径只出现在 Write 的脚本正文里 ⇒ 仍能认出这个文件", cfgp in [os.path.normpath(p) for p in mentioned_paths([U, T("Write", {"file_path": "C:/Temp/x.py", "content": script})])])
    ok("路径带空格、在命令的引号里 ⇒ 认出", any("my app" in p for p in mentioned_paths([T("PowerShell", {"command": 'Copy-Item a "C:\\Users\\x\\my app\\conf.yml"'})])))
    BC = [U, T("Bash", {"command": 'py x.py "%s"' % cfgp.replace("\\", "/")})]     # 自检的文件建在临时目录 ⇒ 这两条关掉目录排除
    ok("改过的文件：修改时间在本轮之内才算", changed_files(BC, now - 30, skip=None) and not changed_files(BC, now + 600, skip=None))
    ok("临时目录里的文件默认不算", not changed_files(BC, now - 30))
    ok("临时目录 / 闸自己 / ~/.claude 下的文件不算", not changed_files([T("Edit", {"file_path": os.path.expanduser("~/.claude/settings.json")}),
                                                                    T("Edit", {"file_path": os.path.expanduser("~/.truthgate/config.json")})], 0))
    AGTC = [{"function": {"name": "run_command", "arguments": json.dumps({"CommandLine": 'py fix.py "%s"' % cfgp})}}]
    ok("AG 的工具调用（参数是一段 JSON 字符串、反斜杠成对）⇒ 仍能认出这个文件",
       cfgp in [os.path.normpath(p) for p in mentioned_paths(ag_msgs(AGTC))] and changed_files(ag_msgs(AGTC), turn_epoch(ag_msgs(AGTC)), skip=None))
    ok("AG：一小时前改的文件不算本轮", not changed_files(ag_msgs(AGTC, window=-600), turn_epoch(ag_msgs(AGTC, window=-600)), skip=None))
    t0 = time.time()
    n = len(_processes(set(INTERPRETERS) | {"dshdesktop", "antigravity"}, now))
    el = time.time() - t0
    ok("查本机进程在 5 秒内（对上名字的 %d 个，%.2f 秒）" % (n, el), el < 5)
    print("全过" if not bad else "失败 %d 项" % len(bad))
    sys.exit(1 if bad else 0)
