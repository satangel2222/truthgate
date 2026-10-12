"""按真实接线生成 SPEC.md（TruthGate 现在实际在做什么）。只读，不改任何接线。
用法：py -3 ~/.truthgate/spec_gen.py        # 重写 ~/.truthgate/SPEC.md
"""
import datetime as dt, glob, json, os, re, subprocess
_NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)   # 起子进程不弹黑窗
from pathlib import Path

H = Path.home()
TG = H / '.truthgate'
FWD = "__file__ = __import__('os').path.expanduser('~/.truthgate/"


def git(*a):
    return subprocess.run(['git', '-C', str(TG), *a], creationflags=_NOWIN, capture_output=True, text=True, encoding='utf-8', errors='replace').stdout.strip()


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception:
        return default


def is_junction(p):
    try:
        return p.is_dir() and p.resolve() != p.absolute()
    except OSError:
        return False


def count_fwd(d):
    n = 0
    for p in Path(d).glob('*.py'):
        try:
            n += p.read_text(encoding='utf-8', errors='replace').startswith(FWD)
        except OSError:
            pass
    return n


def gate_name(cmd):
    m = re.findall(r'([\w\-\.]+)\.(?:py|cjs|mjs|js|sh|ps1)', cmd)
    return m[-1] if m else '内联:' + re.sub(r'\s+', ' ', cmd)[:18]


out = []
w = out.append
now = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
w('# TruthGate 现在实际在做什么（SPEC.md）\n')
w(f'> 由 `py -3 ~/.truthgate/spec_gen.py` 按真实接线生成（{now}），别手改；接线一变就重跑。要什么看 `REQUIREMENTS.md`，怎么改看 `PLAN.md`，怎么来的看 `HISTORY.md`。\n')

# 一、源头与副本
w('## 一、源头与副本\n')
n_commits = git('rev-list', '--count', 'HEAD') or '0'
w(f'- **源头**：`~/.truthgate`（git，{n_commits} 个提交，最新 `{git("log", "-1", "--format=%h %s")[:90]}`）')
for link, real in (('.claude/hooks', '.truthgate/hooks'), ('.claude/superego-semantic', '.truthgate/semantic'), ('.codex/hooks', '.truthgate/hooks')):
    ok = is_junction(H / link) and (H / link).resolve() == (H / real).resolve()
    if ok or link != '.codex/hooks':
        w(f'- 目录联接 `~/{link}` → `~/{real}`：{"✔ 实测指向源头" if ok else "✘ 不是联接或指错了"}')
w(f'- 一行转接（运行时执行源头那份）：hooks {count_fwd(TG / "hooks")} 个 · semantic {count_fwd(TG / "semantic")} 个 · AG scripts {count_fwd(H / ".gemini/antigravity/scripts")} 个')
copies = [('~/.superego', H / '.superego', '旧安装目录'),
          ('公开仓库克隆 ~/Documents/antigravity/fearless-hertz/dist/superego', H / 'Documents/antigravity/fearless-hertz/dist/superego/truthgate', '推 GitHub 用'),
          ('~/.claude/dissat-classifier', H / '.claude/dissat-classifier', '语义服务目录，里面也有 blood_doctor.py')]
if not is_junction(H / '.codex/hooks'):
    copies.insert(0, ('~/.codex/hooks', H / '.codex/hooks', 'Codex 自己的接线在跑它'))
w('- **还没接到源头的旧副本**（改了不会同步；单源闸不让改）：' + '；'.join(
    f'{name}（{len(list(p.glob("*.py")))} 个 .py，{why}）' for name, p, why in copies if p.exists()))
w('')

# 二、Claude Code
s = jload(H / '.claude/settings.json', {}) or {}
obs = jload(H / '.claude/superego-observe.json', {}) or {}
observe = set(obs.get('observe') or [])
hooks = s.get('hooks', {})
w('## 二、Claude Code 接线（`~/.claude/settings.json`）\n')
w('- 共 ' + str(sum(len(g.get('hooks', [])) for gs in hooks.values() for g in gs)) + ' 道：' +
  ' / '.join(f'{ev} {sum(len(g.get("hooks", [])) for g in gs)}' for ev, gs in hooks.items()))
w(f'- 调用路径写的是 `$HOME/.claude/hooks/…`（联接 → 源头）：闸里有代码按「自己所在目录的上一级」找 `~/.claude` 下的东西，走联接路径才找得对。')
w(f'- 👁 = 只记账不拦（`~/.claude/superego-observe.json`，{len(observe)} 道，{obs.get("since", "")} 起）。其余照常拦。\n')
for ev, gs in hooks.items():
    names = []
    for g in gs:
        for h in g.get('hooks', []):
            n = gate_name(h.get('command', ''))
            names.append(('👁' if n in observe else '') + n)
    w(f'- **{ev}**：' + '、'.join(names))
w('')

# 三、AG
w('## 三、AG 接线\n')
for label, p in (('全局', H / '.gemini/config/hooks.json'), ('插件 superego-plugin', H / '.gemini/config/plugins/superego-plugin/hooks.json')):
    d = jload(p, {}) or {}
    for grp, spec in d.items():
        if not isinstance(spec, dict):
            continue
        evs = []
        for ev in spec:
            if not isinstance(spec.get(ev), list) or not spec[ev]:
                continue
            item = spec[ev][0]
            cmd = item.get("command", "")
            if not cmd and "hooks" in item and item["hooks"]:
                cmd = item["hooks"][0].get("command", "")
            evs.append(f'{ev}→`{cmd[-60:]}`')
        w(f'- {label} 组 `{grp}`（{"启用" if spec.get("enabled") else "停用"}）：' + '；'.join(evs))
mcp = (jload(H / '.gemini/config/mcp_config.json', {}) or {}).get('mcpServers', {})
w('- MCP：' + '；'.join(f'`{k}` → `{" ".join(v.get("args", []))[-60:] or v.get("command", "")}`' for k, v in mcp.items()))
bridge = (TG / 'ag_superego_bridge.py').read_text(encoding='utf-8', errors='replace')
built_in = sorted(set(re.findall(r'(?:violations(?:_pre)?\.append\(|violations_pre = \[)\("([\w\-]+)"', bridge)))  # 收尾前置的两道（账本、证据表）写的是 violations_pre = [(...)]
built_in = [('👁' if n in observe else '') + n for n in built_in]
hard = set(re.findall(r'"([\w\-]+)"', (re.search(r'hardcoded_gates = \{(.*?)\}', bridge, re.S) or [None, ''])[1]))
stop_py = {Path(gate_name(h.get('command', '')) + '.py').stem for g in hooks.get('Stop', []) for h in g.get('hooks', [])}
disk = {Path(p).stem for p in glob.glob(str(TG / 'hooks' / '*-gate.py')) + glob.glob(str(TG / 'hooks' / '*-guard.py'))}
dyn = sorted((stop_py | disk) - hard)
w(f'- 桥接收尾时跑：内置检查 {len(built_in)} 道（{"、".join(built_in)}）＋ 从 Claude 目录现找的 Stop 闸 {len(dyn)} 道（接线里的 + 文件名以 -gate / -guard 结尾的，去掉内置同名的）。')
w('- AG 端接线（2026-10-11 物理补齐）：PreInvocation（模型调用前体检）＋ PreToolUse（工具执行前硬阻断，guard-destructive/single-source-gate 等）＋ Stop（收尾深度多维审查）。\n')

# 四、Python 包、端口
w('## 四、Python 包与端口\n')
fnd = glob.glob(str(H / 'AppData/Local/Programs/Python/Python312/Lib/site-packages/__editable___truthgate_*_finder.py'))
m = re.search(r"'truthgate': '([^']+)'", Path(fnd[0]).read_text(encoding='utf-8')) if fnd else None
w(f'- `import truthgate`（Python 3.12）→ `{m.group(1).replace(chr(92) * 2, chr(92)) if m else "（没装）"}`')
try:
    ps = subprocess.run(['powershell', '-NoProfile', '-WindowStyle', 'Hidden', '-Command',
                         "Get-NetTCPConnection -LocalPort 17911 -State Listen -ErrorAction SilentlyContinue | "
                         "ForEach-Object { (Get-CimInstance Win32_Process -Filter \"ProcessId=$($_.OwningProcess)\").CommandLine }"],
                        creationflags=_NOWIN, capture_output=True, text=True, timeout=20).stdout.strip()
except Exception:
    ps = ''
if not ps:
    w('- 端口 17911：没人监听（语义服务按 Frank 9/25 下线令关着）')
elif 'dashboard.py' in ps:
    w('- 端口 17911：⚠️ 被 TruthGate 看板 `dashboard.py` 占着，**不是语义服务**（语义服务 9/25 按 Frank 下线令关着）。探 17911 判断「语义服务在不在」的代码会把看板当成语义服务。')
else:
    w(f'- 端口 17911：`{ps[-100:]}` 在监听')
w('')

# 五、考卷
w('## 五、考卷\n')
latest = sorted(glob.glob(str(TG / 'exam' / 'baseline-*.json')), key=os.path.getmtime)  # 按时间取最新（按名字排 unified 会排在 step2 后面）
if latest:
    r = jload(latest[-1], []) or []
    sb = [x for x in r if x.get('kind') == 'should_block' and x.get('got') != '跑不了']
    nb = [x for x in r if x.get('kind') == 'should_not_block']
    w(f'- 最近一次（`{Path(latest[-1]).name}`）：该拦的 {len(sb)} 题拦住 {sum(x["got"] == "拦" for x in sb)}；'
      f'不该拦的 {len(nb)} 题误拦 {sum(x["got"] == "拦" for x in nb)}；半对 {sum(x["kind"] == "half" for x in r)}；'
      f'跑不了 {sum(x.get("got") == "跑不了" for x in r)}。打分：`py -3 ~/.truthgate/exam/score_gates.py`（只记账的闸按它本来的结论算）')
(TG / 'SPEC.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
print(f'SPEC.md 已生成：{len(out)} 行')
