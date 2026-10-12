"""开局只看「对方从上次到现在新改了什么、提的问题还剩哪些」（PLAN.md 第 1 步第 4 项），再加开局核对（第 5 步）。
news('claude') / news('ag')：先列 alarms() 查出的接线故障（每次开局都列，直到修好），再列 ~/.truthgate 自该端上次开局以来的
新提交（谁、为什么、提交说明里的「问：」行）和还没提交的改动数；然后把「已看到」记到 state/seen-<端>.txt。没有新东西就返回空串，不占上下文。
"""
import collections, glob, json, os, re, subprocess, sys, time

TG = os.path.expanduser('~/.truthgate')
H = os.path.expanduser('~')
FWD = "__file__ = __import__('os').path.expanduser('~/.truthgate/"
AG_ONLY = {'ghost-browser-gate'}   # 保留拦截、hooks 里也有文件，但只在 AG 桥接里跑（查的是 AG 另起浏览器冒充他的）
NOT_PARTS = {'ag_watch.py', '__init__.py', '__main__.py'}   # AG 聊天存档守护 / 包标记，不是闸零件（第 1 步 unify-2026-09-27-switch.py 同样排除）


def _git(*a):
    try:
        return subprocess.run(['git', '-C', TG, *a], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5).stdout
    except Exception:
        return ''


def _jload(p):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _script(cmd):
    m = re.findall(r'([\w.-]+)\.(?:py|cjs|mjs|js|sh|ps1)\b', cmd)
    return m[-1] if m else ''


def _timeouts(since_h):
    """近 since_h 小时 TruthGate 闸的超时：Claude Code 会话记录里的 hook_cancelled(timedOut) + AG 桥接记的 ag-gate-timeouts.log。"""
    cut = time.time() - since_h * 3600
    cut_iso = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(cut))
    cnt = collections.Counter()
    tdir = os.environ.get('TG_TRANSCRIPTS') or os.path.join(H, '.claude', 'projects')
    for p in glob.glob(os.path.join(tdir, '*', '*.jsonl')):
        try:
            if os.path.getmtime(p) < cut:
                continue
            with open(p, 'rb') as f:
                b = f.read()
        except OSError:
            continue
        if b'"timedOut": true' not in b and b'"timedOut":true' not in b:
            continue
        for line in b.split(b'\n'):
            if b'hook_cancelled' not in line or b'timedOut' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            a = d.get('attachment') or {}
            cmd = a.get('command', '').replace('\\', '/')
            if a.get('timedOut') and d.get('timestamp', '') >= cut_iso and ('.claude/hooks/' in cmd or '.truthgate' in cmd):
                cnt[f"{_script(cmd)}（Claude {'调用工具前' if a.get('hookEvent') == 'PreToolUse' else a.get('hookEvent')}）"] += 1
    agl = os.environ.get('TG_AG_TIMEOUT_LOG') or os.path.join(TG, 'hooks', 'ag-gate-timeouts.log')
    try:
        with open(agl, encoding='utf-8', errors='replace') as f:
            for line in f:
                m = re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d).*?TIMEOUT ([\w.-]+)', line)
                if m and 'ag=zz' not in line and time.mktime(time.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')) >= cut:   # zz 开头 = 测试 / 测速用的假会话
                    cnt[f'{m.group(2)}（AG 收尾）'] += 1
    except OSError:
        pass
    return cnt


def alarms(since_h=24):
    """开局核对（PLAN 第 5 步）：两端是不是还在跑源头那一份、总调度在不在、闸有没有大量超时。一切正常返回空列表。
    9/25 总调度 hook_entry.py 从 Claude Code 接线里掉了、挂着 131 道各自独立的闸，两天没人发现 —— 这里每次开局都查一遍。"""
    out = []
    # ① 目录联接：断了 = Claude Code 跑的不是源头那一份
    for link, real in (('.claude/hooks', '.truthgate/hooks'), ('.claude/superego-semantic', '.truthgate/semantic')):
        if os.path.realpath(os.path.join(H, link)) != os.path.realpath(os.path.join(H, real)):
            out.append(f'~/{link} 没指向 ~/{real}（目录联接断了或被换成了副本）⇒ Claude Code 跑的不是源头那一份')
    # ② Claude Code 接线：每条命令指的脚本要在；保留拦截的闸要接着
    settings = os.environ.get('TG_CLAUDE_SETTINGS') or os.path.join(H, '.claude', 'settings.json')
    s = _jload(settings)
    if s is None:
        out.append(f'读不了 Claude Code 的接线 {settings}')
    else:
        wired, broken = set(), []
        for groups in (s.get('hooks') or {}).values():
            for g in groups:
                for h in g.get('hooks', []):
                    cmd = h.get('command', '')
                    if _script(cmd):
                        wired.add(_script(cmd))
                    for home, rest in re.findall(r'(\$HOME|~)(/[^"\s]+?\.(?:py|cjs|mjs|js|sh|ps1))\b', cmd):
                        if not os.path.isfile(H + rest):
                            broken.append('~' + rest)
        if broken:
            out.append(f'Claude Code 接线指向不存在的脚本：{"、".join(sorted(set(broken))[:6])} ⇒ 这几道一跑就报错、什么都不拦')
        obs = _jload(os.environ.get('SUPEREGO_OBSERVE_FILE') or os.path.join(H, '.claude', 'superego-observe.json')) or {}
        hooks_dir = os.path.join(TG, 'hooks')
        need = [g for g in obs.get('keep_blocking') or [] if g not in AG_ONLY
                and any(os.path.isfile(os.path.join(hooks_dir, g + e)) for e in ('.py', '.cjs', '.js'))]
        miss = [g for g in need if g not in wired]
        if miss:
            out.append(f'Claude Code 接线里少了 {len(miss)} 道保留拦截的闸：{"、".join(miss[:8])} ⇒ 它们现在什么都不拦')
    # ③ AG 接线：总调度（桥接）在「调模型前」「一轮结束」都要接着、指着源头那份
    ag_files = (os.environ.get('TG_AG_HOOKS') or os.pathsep.join([
        os.path.join(H, '.gemini', 'config', 'hooks.json'),
        os.path.join(H, '.gemini', 'config', 'plugins', 'superego-plugin', 'hooks.json')])).split(os.pathsep)
    have, stale = {'PreInvocation': False, 'Stop': False}, []
    times = {'PreInvocation': 0, 'Stop': 0}   # 同一时机桥接接了几次（2026-10-03：三组都开 ⇒ 每次收尾跑 3 遍、CPU 顶满、闸超时）
    for p in ag_files:
        for grp, spec in (_jload(p) or {}).items():
            if not isinstance(spec, dict) or not spec.get('enabled'):
                continue
            for ev in have:
                for h in spec.get(ev) or []:
                    cmd = h.get('command', '').replace('\\', '/')
                    if '.truthgate/ag_superego_bridge.py' in cmd:
                        have[ev] = True
                        times[ev] += 1
                    elif 'ag_superego_bridge.py' in cmd:
                        stale.append(f'{grp} {ev}')
    for ev, ok in have.items():
        if not ok:
            out.append(f'AG 端总调度（~/.truthgate/ag_superego_bridge.py）在「{"调模型前" if ev == "PreInvocation" else "一轮结束"}」没接着'
                       f' ⇒ AG 那边这个时机的闸全都不跑（查 ~/.gemini/config/hooks.json 和插件 superego-plugin 的 hooks.json）')
    if stale:
        out.append('AG 接线里有桥接指向的不是源头：' + '；'.join(stale))
    dup = [f'{"调模型前" if ev == "PreInvocation" else "一轮结束"} {n} 次' for ev, n in times.items() if n > 1]
    if dup:
        out.append('AG 桥接重复接线：' + '、'.join(dup) + ' ⇒ 每次都跑多遍、几十个 python 抢 CPU、闸反而超时；'
                   '只留 ~/.gemini/config/hooks.json 的 truthgate 组，其余组 enabled 改 false')
    # ④ AG scripts 里和源头同名的文件必须是一行转接（被旧副本盖掉 = AG 跑旧的）
    scripts = os.environ.get('TG_AG_SCRIPTS') or os.path.join(H, '.gemini', 'antigravity', 'scripts')
    bad = []
    for f in sorted(os.listdir(TG)):
        p = os.path.join(scripts, f)
        if f.endswith('.py') and f not in NOT_PARTS and os.path.isfile(p):
            try:
                with open(p, encoding='utf-8-sig', errors='replace') as fh:
                    if not fh.read(len(FWD)).startswith(FWD):
                        bad.append(f)
            except OSError:
                pass
    if bad:
        out.append(f'AG scripts 里 {len(bad)} 个和源头同名的文件不是一行转接：{"、".join(bad[:6])} ⇒ AG 跑的是旧副本')
    # ⑥ 一周误拦率（misfire_rate.py 每天后台算一次）：自动降级的、安全类误拦偏高只报不降的 —— 都要告诉 Frank
    obs_all = _jload(os.environ.get('SUPEREGO_OBSERVE_FILE') or os.path.join(H, '.claude', 'superego-observe.json')) or {}
    week_ago = time.strftime('%Y-%m-%d', time.localtime(time.time() - 7 * 86400))
    for g, note in (obs_all.get('_auto_demoted') or {}).items():
        if str(note)[:10] >= week_ago:
            out.append(f'{g} 已自动降成只记账：{note} ⇒ 告诉 Frank（要恢复：从 superego-observe.json 的 observe 里删掉它）')
    st = _jload(os.environ.get('TG_MF_STATE') or os.path.join(TG, 'state', 'misfire-rate.json')) or {}
    for x in st.get('decisions') or []:
        if x.get('action') == 'report':
            out.append(f"安全类 {x['gate']} 近 {st.get('days', 7)} 天误拦 {x['misfires']}/{x['blocks']}（> 1/5），只报不降 ⇒ 请 Frank 定")
    # ⑤ 闸超时：超时 = 那一次没检查、直接放行（调用工具前的闸超时 = 那次危险操作没人拦）
    hot = [(k, n) for k, n in _timeouts(since_h).most_common() if n >= 3]
    if hot:
        out.append(f'近 {since_h} 小时闸超时（超时 = 那一次没检查、直接放行）：' + '、'.join(f'{k} {n} 次' for k, n in hot[:8])
                   + ' ⇒ 把超时那次的输入原样重放、看卡在哪')
    return out


def _refresh_spec():
    """接线文件比 SPEC.md 新 ⇒ 后台重生成 SPEC.md（不等它、不挡开局）。"""
    spec = os.path.join(TG, 'SPEC.md')
    srcs = [os.path.join(H, '.claude', 'settings.json'), os.path.join(H, '.claude', 'superego-observe.json'),
            os.path.join(H, '.gemini', 'config', 'hooks.json'), os.path.join(H, '.gemini', 'config', 'plugins', 'superego-plugin', 'hooks.json')]
    try:
        if max(os.path.getmtime(p) for p in srcs if os.path.exists(p)) <= os.path.getmtime(spec):
            return
        flags = 0x00000008 | 0x08000000 if os.name == 'nt' else 0   # DETACHED_PROCESS | CREATE_NO_WINDOW
        subprocess.Popen([sys.executable, os.path.join(TG, 'spec_gen.py')], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags, cwd=TG)
    except Exception:
        pass


def _refresh_misfire():
    """一周误拦率每天后台算一次（misfire_rate.py；不等它、不挡开局）。几个会话同时开局只跑一个（锁 10 分钟过期）。"""
    st = os.path.join(TG, 'state', 'misfire-rate.json')
    lock = os.path.join(TG, 'state', 'misfire-rate.lock')
    try:
        if os.path.exists(st) and time.time() - os.path.getmtime(st) < 20 * 3600:
            return
        if os.path.exists(lock) and time.time() - os.path.getmtime(lock) < 600:
            return
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        with open(lock, 'w') as f:
            f.write(str(os.getpid()))
        flags = 0x00000008 | 0x08000000 if os.name == 'nt' else 0   # DETACHED_PROCESS | CREATE_NO_WINDOW
        subprocess.Popen([sys.executable, os.path.join(TG, 'misfire_rate.py')], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags, cwd=TG)
    except Exception:
        pass


def news(end, limit=8):
    try:
        bad = alarms()
    except Exception as e:
        bad = [f'开局核对自己出错了：{e!r}']
    _refresh_spec()
    _refresh_misfire()
    lines = ['🚨 ' + b for b in bad]
    head = _git('rev-parse', 'HEAD').strip()
    if not head:
        return '\n'.join(lines)
    seen_f = os.path.join(TG, 'state', f'seen-{end}.txt')
    try:
        last = open(seen_f, encoding='utf-8').read().strip()
    except OSError:
        last = ''
    if last != head:
        rng = [f'{last}..HEAD'] if last and _git('cat-file', '-t', last).strip() == 'commit' else ['-n', str(limit)]
        raw = _git('log', *rng, '--format=%x1e%h %ad%n%B', '--date=format:%m-%d %H:%M')
        commits = [c for c in raw.split('\x1e') if c.strip()]
        for c in commits[:limit]:
            head_line, _, body = c.partition('\n')
            subj = body.strip().split('\n', 1)[0]
            who = (re.search(r'^谁：\s*(.+)$', body, re.M) or [None, ''])[1]
            why = (re.search(r'^为什么：\s*(.+)$', body, re.M) or [None, ''])[1]
            lines.append(f'· {head_line} {subj[:70]}｜{who[:40]}｜{why[:80]}')
            lines += [f'   问：{q[:100]}' for q in re.findall(r'^问：\s*(.+)$', body, re.M)]
        if len(commits) > limit:
            lines.append(f'· …还有 {len(commits) - limit} 个更早的，`git -C ~/.truthgate log` 看全部')
    dirty = [l for l in _git('status', '--porcelain').splitlines() if l.strip()]
    if dirty:
        lines.append(f'· 还有 {len(dirty)} 个文件改了没提交（有人改完没记账；在 ~/.truthgate 会话里提交并写谁/为什么）')
    try:
        os.makedirs(os.path.dirname(seen_f), exist_ok=True)
        open(seen_f, 'w', encoding='utf-8').write(head)
    except OSError:
        pass
    if not lines:
        return ''
    title = '【TruthGate 开局核对：接线有问题，先修】' if bad else '【TruthGate 源头 ~/.truthgate：自你上次开局以来】'
    return title + '\n' + '\n'.join(lines)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--check']:   # 只跑开局核对，不动「已看到」记录
        print('\n'.join(alarms()) or '开局核对：两端接线正常，近 24 小时没有闸频繁超时')
    else:
        print(news(sys.argv[1] if len(sys.argv) > 1 else 'claude') or '（没有新变化）')
