"""单源规矩（Frank 2026-09-27 定）：TruthGate 只在「在 ~/.truthgate 打开的对话」里改；副本一律不改，改源头。
Claude Code 在工具调用前用（hooks/single-source-gate.py），AG 在一轮收尾时按账本用（ag_superego_bridge.py）。

check(target, cwd) → None（放行）或一句拦截理由。只看事实：目标路径是什么、会话开在哪，不看措辞。
"""
import os

HOME = os.path.expanduser('~')
FWD_SIG = "__file__ = __import__('os').path.expanduser('~/.truthgate/"


def _n(p):
    return os.path.normpath(os.path.expanduser(str(p))).replace('\\', '/').lower()


TG = _n('~/.truthgate')
ALIASES = {_n('~/.claude/hooks'): TG + '/hooks', _n('~/.claude/superego-semantic'): TG + '/semantic'}
COPIES = [_n('~/.codex/hooks'), _n('~/.superego'), _n('~/Documents/antigravity/fearless-hertz/dist/superego/truthgate')]
RUNTIME = ('/ledger/', '/logs/', '/state/', '/__pycache__/')  # 进程自己写的运行数据，不归这条规矩管


def _under(p, root):
    return p == root or p.startswith(root + '/')


def check(target, cwd=''):
    if not target:
        return None
    t = _n(target)
    try:
        with open(os.path.expanduser(str(target)), encoding='utf-8-sig', errors='replace') as f:
            first = f.readline()
    except OSError:
        first = ''
    src = None
    if first.startswith(FWD_SIG):
        src = '~/.truthgate/' + first[len(FWD_SIG):].split("'")[0]
        return f'「{target}」是一行转接，真正的代码在 {src}。改那边（在 ~/.truthgate 打开的对话里）。'
    for c in COPIES:
        if _under(t, c):
            return f'「{target}」是 TruthGate 的旧副本（这一端还没接到源头），改了也不会同步。改 ~/.truthgate 里的同名文件。'
    alias = next((a for a in ALIASES if _under(t, a)), None)
    canon = (ALIASES[alias] + t[len(alias):]) if alias else t
    if not _under(canon, TG) or any(r in canon for r in RUNTIME):
        return None
    if not _under(_n(cwd or os.getcwd()), TG):
        return ('TruthGate 只在「在 ~/.truthgate 打开的对话」里改（Frank 2026-09-27 定）。'
                '这里要改的话，把要改什么、为什么写进 ~/.truthgate/PROGRESS.md 的待办，交给那个对话做。')
    if alias:
        return f'同一个文件，请用源头路径改：{canon.replace(TG, "~/.truthgate", 1)}（记账和各道闸的判断都认这个路径）。'
    return None


if __name__ == '__main__':
    import tempfile
    tg_cwd = os.path.expanduser('~/.truthgate')
    other = os.path.expanduser('~/airbnb')
    cases = [  # (目标, 会话目录, 该拦吗)
        ('~/.truthgate/hooks/critic-gate.py', tg_cwd, False),
        ('~/.truthgate/hooks/critic-gate.py', other, True),
        ('~/.claude/hooks/critic-gate.py', tg_cwd, True),        # 旧路径：请走源头路径
        ('~/.claude/hooks/config.py', tg_cwd, True),             # 转接文件
        ('~/.gemini/antigravity/scripts/config.py', tg_cwd, True),
        ('~/.gemini/antigravity/scripts/ag_archive.py', other, False),  # AG 自己的工具，不是闸零件
        ('~/.codex/hooks/critic-gate.py', tg_cwd, True),
        ('~/.truthgate/ledger/x.jsonl', other, False),           # 运行数据
        ('~/.truthgate/PROGRESS.md', other, True),
        ('D:/airbnb ai manager/server.js', other, False),
    ]
    bad = [(t, c) for t, c, want in cases if (check(t, c) is not None) != want]
    for t, c in bad:
        print('✗', t, '@', c, '→', check(t, c))
    print(f'{len(cases) - len(bad)}/{len(cases)} 对')
    raise SystemExit(1 if bad else 0)
