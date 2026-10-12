"""交付自检（PLAN.md 第 3 步；REQUIREMENTS 第 3、4、11 条）。两端共用：Claude 收尾闸 anti-toy-test-gate / visual-proof-gate、AG 桥接收尾。

只看本轮做了什么，不看措辞：
  · 改了网页文件（html / css / 前端 js / vue / jsx / tsx…）⇒ 最后一次改完之后要有：
      真浏览器跑过（browser）、跑的时候监听了控制台报错（console）、截图并打开看过（shot）
  · 改了定义网络接口的代码（文件里写着路由）⇒ 最后一次改完之后要真发过一次请求（request）
anti-toy-test-gate 管 browser / console / request（「别拿玩具测试糊弄」），visual-proof-gate 管 shot（「眼见为实」）。
动作记录由 evidence_table.actions_from_claude / actions_from_ag 取（两端各一个）。
"""
import os
import re

FRONT = re.compile(r'\.(?:html?|css|scss|less|vue|jsx|tsx|svelte)$|(?:^|[\\/])(?:app|main|index|script)\.js$', re.I)
NOT_SHIPPED = re.compile(r'(?:^|[\\/])(?:tests?|__tests__|fixtures?|archive|node_modules|exam)[\\/]|(?:^|[\\/])test_[^\\/]*$|\.(?:test|spec)\.', re.I)
ROUTES = re.compile(r'@(?:app|router|bp|api)\.(?:get|post|put|patch|delete|route)\b|\b(?:app|router|server)\.(?:get|post|put|patch|delete)\(\s*[\'"`]/'
                    r'|\bexpress\(\)|\bFastAPI\(|\bFlask\(|\bhttp\.createServer\(|\bBaseHTTPRequestHandler\b|\bAPIRouter\(', re.I)
GEN_WEB = re.compile(r'\[脚本:写网页 ([^\]]+)\]')   # evidence_table._cmd_kind 标的：跑脚本 / 重定向生成了网页，算改了网页
SHOT_TOOL = re.compile(r'^\S*screenshot\S*', re.I)   # 浏览器工具自己截的图会直接给到我眼前（MCP 这类），算看过；脚本存成文件的要再 Read
NEED = {'browser': '真浏览器跑一遍', 'console': '跑的时候监听控制台报错（pageerror / console.error）',
        'shot': '截图并打开看过（Read 那张图）', 'request': '真发一次请求（curl / 浏览器）'}
OBSERVE_ITEMS = set()  # 2026-10-12 转正开拦: 改动路由代码收尾前必须真发一次请求   # 「改了接口要真发请求」是新规矩：先只记账一周（约 10-04），打靶合格从这里删掉即开拦
SKIP_ASK = re.compile(r'不用测|别测|不需要测|只测后端|不用看网页|不需要看网页|不用管前端|跳过\s*UI', re.I)


CODE = re.compile(r'\.(?:py|js|mjs|cjs|ts|go|rb|php|java|cs|rs)$', re.I)   # 只看代码文件：文档里写着路由（PROJECT-STRUCTURE.md）不算接口代码


def _defines_routes(path):
    try:
        return bool(CODE.search(path)) and os.path.getsize(path) < 2_000_000 and bool(ROUTES.search(open(path, encoding='utf-8', errors='replace').read()))
    except Exception:
        return False


def check(actions):
    """→ {'web': (最后改的网页文件, [缺的项]), 'api': (最后改的接口文件, [缺的项])}，没改就没有那一项。"""
    out = {}
    actions = [dict(a, kind='write', path=m.group(1)) if (m := GEN_WEB.search(a.get('text', ''))) else a for a in actions]
    wi = max((i for i, a in enumerate(actions) if a['kind'] == 'write' and FRONT.search(a.get('path', '')) and not NOT_SHIPPED.search(a['path'])), default=-1)
    if wi >= 0:
        after = actions[wi + 1:]
        miss = [k for k, ok in (('browser', any(a['kind'] == 'browser' for a in after)),
                                ('console', any(a['kind'] == 'browser' and ('[脚本:控制台]' in a['text'] or re.search(r'console', a['text'].split(' ')[0], re.I)) for a in after)),
                                ('shot', any(a['kind'] == 'image' or (a['kind'] == 'browser' and SHOT_TOOL.search(a['text'])) for a in after))) if not ok]
        out['web'] = (actions[wi]['path'], miss)
    ai = max((i for i, a in enumerate(actions) if a['kind'] == 'write' and a.get('path') and not FRONT.search(a['path'])
              and not NOT_SHIPPED.search(a['path']) and _defines_routes(a['path'])), default=-1)
    if ai >= 0:
        ok = any(a['kind'] in ('web', 'browser') for a in actions[ai + 1:])
        out['api'] = (actions[ai]['path'], [] if ok else ['request'])
    return out


def missing(actions, items):
    """只要某道闸管的那几项：→ [(改的文件, 缺的项)]。"""
    return [(path, [m for m in miss if m in items]) for path, miss in check(actions).values() if any(m in items for m in miss)]


def message(gate, gaps):
    lines = [f'{os.path.basename(p)}：还缺 ' + '、'.join(NEED[m] for m in miss) for p, miss in gaps]
    return (f'⛔ 交付自检（{gate}）：你这轮改了给人用的东西，改完之后没像用户那样走一遍。\n' + '\n'.join('  · ' + x for x in lines)
            + '\n只看本轮做了什么（改了哪个文件、之后跑没跑浏览器 / 截图 / 请求），不看你怎么说。'
              '这轮改的不是给人用的（测试夹具、没上线的草稿），或者用户说了不用测，一句话说明即可。')


def stop_main(gate, items, hook_log):
    """Claude Code 收尾闸的公共入口（anti-toy-test-gate、visual-proof-gate 共用）：读本轮 → 查缺项 → 拦 / 只记账。
    hook_log 由闸自己传进来（闸文件里 import 的那个），返回退出码。"""
    import json
    import sys
    from guard_common import load_transcript_tail, turn_start_index, self_blocked_this_turn, _text_of
    from evidence_table import actions_from_claude
    try:
        data = json.loads(sys.stdin.read() or '{}')
    except Exception:
        return 0
    if data.get('stop_hook_active') and self_blocked_this_turn(gate):
        return 0
    if not data.get('stop_hook_active'):
        self_blocked_this_turn(gate, turn_start=True)
    tp = data.get('transcript_path')
    if not tp or not os.path.exists(tp):
        return 0
    msgs = load_transcript_tail(tp)
    s = turn_start_index(msgs)
    if s >= 0 and SKIP_ASK.search(_text_of((msgs[s].get('message') or {}).get('content'))):
        return 0
    # 2026-10-05 改了没生效（判据在 stale_process.py，只看事实）：只在 anti-toy-test-gate 这一道里查一次，
    #   出任何错只丢它自己，不连累下面的网页 / 接口检查。
    if gate == 'anti-toy-test-gate':
        try:
            import stale_process
            sp = stale_process.verdict(msgs[s:] if s >= 0 else msgs)
        except Exception:
            sp = None
        if sp:
            hook_log(gate, 'BLOCK(stale-process)', sp[0])
            sys.stderr.write(sp[1] + '\n')
            return 2
    gaps = missing(actions_from_claude(msgs[s + 1:]), items)
    watch = [(p, [m for m in miss if m in OBSERVE_ITEMS]) for p, miss in gaps]
    gaps = [(p, [m for m in miss if m not in OBSERVE_ITEMS]) for p, miss in gaps]
    for p, miss in watch:
        if miss:
            hook_log(gate, 'WOULDBLOCK(' + ','.join(miss) + ')', p)
    gaps = [(p, miss) for p, miss in gaps if miss]
    if not gaps:
        return 0
    hook_log(gate, 'BLOCK(' + ','.join(m for _, miss in gaps for m in miss) + ')', gaps[0][0])
    sys.stderr.write(message(gate, gaps) + '\n')
    return 2


if __name__ == '__main__':
    import tempfile
    W = lambda p: {'kind': 'write', 'text': f'Edit {p}', 'path': p}
    A = lambda k, t: {'kind': k, 'text': t, 'path': ''}
    d = tempfile.mkdtemp()
    srv = os.path.join(d, 'server.js')
    open(srv, 'w', encoding='utf-8').write("const app = express();\napp.get('/api/self-cost', (q, r) => r.json({}))\n")
    lib = os.path.join(d, 'util.py')
    open(lib, 'w', encoding='utf-8').write('def f():\n    return 1\n')
    doc = os.path.join(d, 'PROJECT-STRUCTURE.md')
    open(doc, 'w', encoding='utf-8').write("server.js 里 app.get('/api/self-cost') 返回自用成本\n")
    from evidence_table import _cmd_kind
    brw = os.path.join(d, 'server.js')   # 上面那个 server.js 里没有浏览器驱动；再造一个提到 opencli 的
    scr = os.path.join(d, 'scrape.js')
    open(scr, 'w', encoding='utf-8').write("const { execSync } = require('child_process'); execSync('opencli browser open x')\n")
    assert _cmd_kind(f'git status {scr}')[0] == 'cmd', '只提到脚本不算跑（c017 那轮 git status / rg 被当成开浏览器）'
    assert _cmd_kind(f'node "{scr}"')[0] == 'browser', '真用解释器跑了驱动浏览器的脚本才算'
    assert _cmd_kind(f'py -3.12 -u {brw}')[0] == 'cmd'
    gen = os.path.join(d, 'build.py')
    open(gen, 'w', encoding='utf-8').write("OUT = os.path.join(R, '教科书.html')\nwith open(OUT, 'w', encoding='utf-8') as f:\n    f.write(x)\n")
    rd = os.path.join(d, 'read.py')
    open(rd, 'w', encoding='utf-8').write("src = open('tpl.html').read()\nprint(len(src))\n")
    k, t = _cmd_kind(f'python "{gen}"')
    assert '[脚本:写网页 教科书.html]' in t, 'cb9b2465：跑脚本生成网页要认成改了网页'
    assert '写网页' not in _cmd_kind(f'python "{rd}"')[1], '只读 html 不算生成'
    assert '[脚本:写网页 out.html]' in _cmd_kind('pandoc a.md > out.html')[1], '重定向生成网页'
    assert check([A(k, t), A('cmd', 'Bash ls')]) == {'web': ('教科书.html', ['browser', 'console', 'shot'])}
    here = os.path.abspath(__file__)
    assert '写网页' not in _cmd_kind(f'py -3 "{here}"')[1], '跑自检脚本（正文里有 .html 夹具）不算生成网页'
    assert '写网页' not in _cmd_kind(f'py -3 "{os.path.join(os.path.dirname(here), "test_visual_proof_gate.py")}"')[1], 'test_ 脚本不算'
    qa = A('browser', 'Bash python qa.py [脚本:浏览器] [脚本:控制台]')
    cases = [  # (说明, 动作, 期望 check 的结果)
        ('什么都没改 → 不查', [A('cmd', 'Bash ls')], {}),
        ('改了网页、没做任何事 → 三样都缺（0b8b629d 那种）', [W('D:/p/app.js'), A('cmd', 'Bash node --check app.js')], {'web': ('D:/p/app.js', ['browser', 'console', 'shot'])}),
        ('改网页之前跑过浏览器截过图、改完没再看 → 照样缺', [qa, A('image', 'Read D:/p/a.png'), W('D:/p/style.css')], {'web': ('D:/p/style.css', ['browser', 'console', 'shot'])}),
        ('改完跑了带控制台监听的浏览器、打开看了截图 → 齐', [W('D:/p/index.html'), qa, A('image', 'Read D:/p/shot.png')], {'web': ('D:/p/index.html', [])}),
        ('浏览器跑了但没听控制台、没看图 → 缺两样', [W('D:/p/index.html'), A('browser', 'Bash opencli browser open x')], {'web': ('D:/p/index.html', ['console', 'shot'])}),
        ('MCP 浏览器工具：截图直接到眼前、控制台工具 → 齐', [W('D:/p/a.vue'), A('browser', 'mcp__pw__browser_navigate http://x'),
                                                        A('browser', 'mcp__pw__browser_console_messages'), A('browser', 'mcp__pw__browser_take_screenshot')], {'web': ('D:/p/a.vue', [])}),
        ('改的是测试夹具 → 不查', [W('D:/p/tests/fixture.html')], {}),
        ('改了接口代码、没发请求 → 缺请求', [W(srv), A('cmd', 'Bash node --check server.js')], {'api': (srv, ['request'])}),
        ('改了接口代码、之后 curl 了 → 齐', [W(srv), A('web', 'Bash curl http://127.0.0.1:8899/api/self-cost')], {'api': (srv, [])}),
        ('改了普通代码（没有路由）→ 不查', [W(lib)], {}),
        ('改了文档、文档里写着路由 → 不查（c017 那轮的 PROJECT-STRUCTURE.md）', [W(doc)], {}),
    ]
    bad = 0
    for why, acts, want in cases:
        got = check(acts)
        ok = got == want
        bad += not ok
        print(('OK  ' if ok else 'FAIL') + f'  {why}' + ('' if ok else f' → {got}'))
    print(f'{len(cases) - bad}/{len(cases)} 对')
    raise SystemExit(1 if bad else 0)
