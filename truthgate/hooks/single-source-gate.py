#!/usr/bin/env python3
"""PreToolUse：单源闸（2026-09-27，PLAN.md 第 1 步「改副本当场拦并指回源头」）。
只看事实：这次工具调用要【写】哪个文件、会话开在哪。判据在 ~/.truthgate/single_source.py（AG 端收尾时用同一份）。
  · 写一行转接 / 旧副本（~/.codex/hooks、~/.superego、公开仓库克隆）→ 拦，指回源头
  · 写 ~/.truthgate（含指过来的 ~/.claude/hooks、~/.claude/superego-semantic），但会话不是在 ~/.truthgate 开的 → 拦
  · 在 ~/.truthgate 会话里走旧路径写 → 拦，请用源头路径（同一个文件，路径统一才好记账）
命令行只认明确的写入：> / >> / tee / sed -i / cp / mv / Set-Content / Add-Content / Out-File / Copy-Item / Move-Item 的目标。
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser('~/.truthgate'))
try:
    from single_source import check
except Exception:          # 判据文件坏了 ⇒ 放行（fail-open），别把所有写操作都拦死
    sys.exit(0)
try:
    from guard_common import hook_log
except Exception:
    def hook_log(*a, **k):
        pass

HOME = os.path.expanduser('~')
MARK = re.compile(r'\.truthgate|\.claude[\\/](hooks|superego-semantic)|\.codex[\\/]hooks|\.superego|fearless-hertz|antigravity[\\/]scripts', re.I)
TOK = r'''("?)([^\s"';|&<>]+)\1'''
WRITES = [
    re.compile(r'(?<![0-9&])>>?\s*' + TOK),
    re.compile(r'\btee\s+(?:-a\s+)?' + TOK),
    re.compile(r'\bsed\s+-i\S*\s+(?:\'[^\']*\'|"[^"]*"|\S+)\s+' + TOK),
    re.compile(r'\b(?:cp|mv|Copy-Item|Move-Item)\b[^;&|\n]*\s' + TOK + r'\s*(?:$|[;&|\n])', re.I),
    re.compile(r'\b(?:Set-Content|Add-Content|Out-File)\s+(?:-(?:Path|FilePath|LiteralPath)\s+)?' + TOK, re.I),
]


def targets(tool, ti):
    if tool in ('Edit', 'Write', 'MultiEdit'):
        return [ti.get('file_path', '')]
    if tool == 'NotebookEdit':
        return [ti.get('notebook_path', '')]
    if tool in ('Bash', 'PowerShell'):
        cmd = str(ti.get('command', '')).replace('$HOME', HOME).replace('$env:USERPROFILE', HOME)
        out = []
        for rx in WRITES:
            out += [m.group(2) for m in rx.finditer(cmd)]
        return [t for t in out if MARK.search(t)]
    return []


def main():
    try:
        d = json.loads(sys.stdin.read() or '{}')
    except Exception:
        return 0
    cwd = d.get('cwd') or os.getcwd()
    for t in targets(d.get('tool_name', ''), d.get('tool_input') or {}):
        why = check(t, cwd)
        if why:
            hook_log('single-source-gate', f"BLOCK {d.get('tool_name')} cwd={cwd}", t)
            print('⛔ 单源闸：' + why, file=sys.stderr)
            return 2
    return 0


def selftest():
    tg = os.path.expanduser('~/.truthgate')
    cases = [  # (工具, 输入, 会话目录, 该拦吗)
        ('Edit', {'file_path': tg + '/hooks/critic-gate.py'}, tg, False),
        ('Edit', {'file_path': tg + '/hooks/critic-gate.py'}, 'D:/airbnb ai manager', True),
        ('Write', {'file_path': HOME + '/.gemini/antigravity/scripts/config.py'}, tg, True),
        ('Bash', {'command': 'cat ~/.claude/hooks/critic-gate.py > /tmp/x.txt'}, tg, False),   # 只读旧路径，写的是别处
        ('Bash', {'command': 'echo x >> "$HOME/.claude/hooks/critic-gate.py"'}, tg, True),
        ('Bash', {'command': "sed -i 's/a/b/' ~/.codex/hooks/critic-gate.py"}, tg, True),
        ('Bash', {'command': 'cp a.py ~/.truthgate/hooks/a.py'}, 'D:/airbnb ai manager', True),
        ('Bash', {'command': 'python x.py 2>/dev/null'}, 'D:/airbnb ai manager', False),
        ('PowerShell', {'command': 'Set-Content -Path C:/Users/<username>/.truthgate/PROGRESS.md -Value x'}, 'D:/x', True),
        ('Read', {'file_path': tg + '/hooks/critic-gate.py'}, 'D:/x', False),
    ]
    bad = []
    for tool, ti, cwd, want in cases:
        got = any(check(t, cwd) for t in targets(tool, ti))
        if got != want:
            bad.append((tool, ti, cwd, got))
    for b in bad:
        print('✗', b)
    print(f'{len(cases) - len(bad)}/{len(cases)} 对')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(selftest() if '--selftest' in sys.argv else main())
