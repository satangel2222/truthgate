#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shell-writes-code-gate —— 拦「用 shell 的 heredoc / sed -i 去写或改【代码文件】」。

⛔ 来历（2026-08-19，同一个坑一天之内发作 3 次，Frank：
   「转义层今天已经暴露了坏了那么多次，模拟不去找根因修复固化，没必要吗？」）：

   ① `cat > check_frames.py <<'PYEOF' … PYEOF`
      → bash 报 `unexpected EOF while looking for matching "` —— 内容里的引号让 shell 提前断句。
   ② `sed -i 's/bad = judge(checklist(s, plates.get(hit, …)), ans)/X/' check_frames.py`
      → **把一整行有效代码替换成了字母 X**，文件当场坏掉，我还先去怀疑别的原因。
   ③ heredoc 里写 `'…分五行：\\n'` → 落盘变成【真换行】而不是转义序列
      → `SyntaxError: unterminated string literal`。

   **根因**：Bash 工具里的命令要穿过【工具层 + shell】两层转义，
   而代码文件里天然全是引号、反斜杠、`\\n`、中文 —— 每一层都可能吃掉或改写它们。
   Write / Edit 工具是**直接落盘，零层转义**。

⛔ 先查现成（2026-08-19）→ 判定 **自建**：
   本机 60+ 个 hook 里没有一个在管这件事。最近的同族是 `pipe-truncation-guard.py`
   （也是 PreToolUse:Bash 的用法闸），但它管的是「长跑进程输出接 head/tail」，功能不重叠。

⛔ 判据（客观、纯语法，不需要理解语义）：
   ① heredoc 重定向到代码文件　② `sed -i` 作用于代码文件　③ echo/printf 重定向到代码文件

✅ 不拦（Bash 的正当用法，别误伤）：
   · 重定向到 .log / .txt / .json / .md / .csv（落盘输出 —— pipe-truncation-guard 还要求这么做）
   · 只读：cat / sed -n / grep / head（不带 -i、不重定向到代码文件）
   · `python - <<'PY'` 把脚本喂给 stdin 执行（不落盘成代码文件，坏了也只是这次跑失败）
   · git / npm 等命令里恰好出现代码文件名

⛔ 2026-10-04 第⑤条（Frank「授权这里修复」）：把【临时目录里的代码文件】复制 / 移动进【工具目录】，
   而那边还没有这个文件 ⇒ 等于新建工具，按 prior-art-gate 同一条事实判据查（最近 3 轮有没有查过本机以外）。
   来历：我先把 show_on_desktop.py 写在临时目录（prior-art-gate 对临时目录免检），再 Copy-Item 进
   ~/.gemini/antigravity/scripts —— prior-art-gate 只挂在 Write 上，看不见复制。判据在 six_universes.py。

自测：python shell-writes-code-gate.py --self-test
"""
import json
import os
import re
import sys

# ⛔ 记账：guard_common 在被 import 时安装 stdout 监听 + 退出码钩子，
#    **不 import 它 = 这道闸的每一次拦截都不会进 hook-stats**
#    （2026-08-19 实测：我当天新建的四道闸全漏记，superego-metrics 会报 0 次）。
#    整段 try/except：它只是观测器，绝不允许它弄坏闸本身。
try:
    sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
    import guard_common  # noqa: F401  只为触发记账副作用
except Exception:
    pass


# ⛔ 2026-09-07:末尾的 `\b` 原来只加在【部分】使用点上(HEREDOC/SED_I/ECHO 各自补了一个),
#    `HD_CODE_PATH` 那条没补 ⇒ **`settings.json` 里的 `.js` 被当成 JavaScript 文件**
#    ⇒ 凡是"改 settings.json 的脚本"一律误伤(当场连拦我两次)。收进 CODE_EXT 自己,
#    使用点那几个多一个 `\b` 无害,少一个就出这种事。
CODE_EXT = r'\.(py|js|mjs|cjs|ts|tsx|jsx|rb|go|rs|java|c|cc|cpp|h|hpp|sh|ps1|php|lua)\b'

HEREDOC = re.compile(r'>\s*[^\s;|&]*' + CODE_EXT + r'\b[^\n]*<<', re.I)
SED_I = re.compile(r'\bsed\b[^|;&\n]*\s-i\b[^|;&\n]*' + CODE_EXT + r'\b', re.I)
ECHO = re.compile(r'\b(echo|printf)\b[^|;&\n]*>>?\s*[^\s;|&]*' + CODE_EXT + r'\b', re.I)

MSG = """⛔ shell 写代码闸：你正要用 shell 去写/改一个【代码文件】。

命中：{what}

⛔ 2026-08-19 这一个坑一天发作 3 次，每次都把文件写坏：
  ① `cat > x.py <<'EOF'` → 内容里的引号让 bash 提前断句，报 unexpected EOF
  ② `sed -i 's/…/X/'`    → **把一整行有效代码替换成了字母 X**
  ③ heredoc 里的 \\n      → 落盘变成真换行 → SyntaxError

根因：Bash 命令要穿过【工具层 + shell】两层转义，而代码文件里全是引号、
反斜杠、\\n、中文 —— 每层都可能吃掉或改写它们。Write/Edit 是零层转义。

✅ 改用零转义的路子：
  · 新建整个文件   → **Write 工具**
  · 改其中一段     → **Edit 工具**（old_string/new_string，精确、失败会报错而不是悄悄写坏）
  · 非要用脚本改   → 用 **Write** 把改写逻辑写成 scratchpad 里的一个 .py（零转义），
                     脚本里**先 ast.parse(s) 验语法、再 open(p,'w') 落盘**，然后 `py 那个脚本` 执行。
                     ⛔ 别把这段逻辑塞进 `python - <<'PY'`:heredoc 体内写代码文件会被本闸第④条拦
                     （2026-09-18 实录:提示原来推荐的正是 heredoc,照做就被拦,合法路径为空）。

(重定向到 .log/.txt/.json/.md 不受此限，那是正当的输出落盘。)"""


HD_START = re.compile(r"<<-?\s*'?\"?([A-Za-z_][A-Za-z0-9_]*)'?\"?")


def strip_heredoc_bodies(cmd):
    """把 heredoc 的【正文】剥掉，只留下真正的命令行。

    ⛔ 2026-08-19 本闸上线后第一次拦人就误伤了自己：我用正当的 `python - <<'PY'`
       往 lessons.md 追加教训，而**教训正文里引用了那条翻车命令**
       `cat > check_frames.py <<'PYEOF'` —— 正则扫到了 heredoc 的内容，把它当成命令拦了。
       ⇒ heredoc body 是**数据**，不是命令。判据只能看命令行本身。
    """
    out, lines, i = [], cmd.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        out.append(ln)
        m = HD_START.search(ln)
        if m:
            tag = m.group(1)
            i += 1
            while i < len(lines) and lines[i].strip() != tag:
                i += 1          # 丢掉 body
        i += 1
    return '\n'.join(out)


QUOTED = re.compile(r"""'[^']{25,}'|"[^"]{25,}\"""", re.S)


def strip_long_quoted(cmd):
    """把【长引号串】的内容挖空 —— 它们是参数值/文本，不是命令。

    ⛔ 2026-08-19 本闸第二次误伤：我跑外部审查时在 `--claim "…sed -i 改 .py…"`
       里【描述】这个闸的行为，"sed -i 改 .py" 这几个字被当成真命令拦了。
       ⇒ 引号里的东西是数据。只挖 >=25 字符的长串，短引号（路径、's/a/b/'）保留，
         这样 `sed -i 's/a/b/' x.py` 仍然拦得住。

    ⚠️ 已知边界（2026-08-19 外部审查 second-opinion 指出，诚实登记不假装没有）：
       **短引号（<25 字符）里的模式仍会被匹配**，例如 `echo "cat > x.py <<'EOF'"`
       这种【描述】会被误拦。这是有意的取舍 —— 挖掉短引号就会漏掉
       `sed -i 's/a/b/' x.py` 这种真命令。误拦时改用 Write/Edit 即可，代价远小于放过静默损坏。
    """
    return QUOTED.sub("''", cmd)


# ⛔ 2026-08-26 补的第四条判据 —— 前三条有个共同盲区,而我今天从头到尾都在钻它。
#    实测:`sed -i` 和 `cat > x.py` 拦得住,但下面这种【一次没拦过】(记账 215 次全放行):
#        py -3.12 - <<'PY'
#        p = 'test_foo.py'
#        io.open(p, 'w').write(...)        ← 真的在改代码文件
#        PY
#    根因:`strip_heredoc_bodies` 为了防误伤(上线首次就把 lessons 里【引用】的翻车命令当成命令拦了)
#    主动把 body 剥掉 ⇒ 体内真正在写文件的动作也一并看不见。它的自测里只有「heredoc 只读」,
#    没有一条测「heredoc 体内写文件」。⇒ 剥 body 做前三条检查【保留】,再【单独扫 body】补这条。
# ⛔ 为什么用【组合判据】而不是匹配 open('xxx.py','w'):我今天的写法路径是变量(p='...py' 再 open(p,'w')),
#    字面量正则一个都抓不到。⇒ 判据 = body 里【同时】出现「写模式的文件调用」和「代码文件后缀的字符串」。
HD_WRITE_CALL = re.compile(
    # ⛔ 2026-09-07:原来是 `open\([^)\n]*` —— `[^)]` 跨不过嵌套括号 ⇒
    #    `open(os.path.join(d, n), "w")` 这种**一次都没被拦过**(写代码文件的常见写法)。
    #    改成不含换行、≤120 字符的非贪婪,并要求模式串后面紧跟 `,` 或 `)` 才算数。
    r"""open\([^\n]{0,120}?['"][wa]\+?b?['"]\s*[,)]"""   # open(..., 'w') / 'a' / 'wb'
    r"""|\.write_text\("""                      # pathlib
    r"""|writeFileSync\("""                     # node
    r"""|\.writeFile\(""",
    re.I)
HD_CODE_PATH = re.compile(r"""['"][^'"\n]*""" + CODE_EXT + r"""['"]""", re.I)


def heredoc_bodies(cmd):
    """把 heredoc 的【正文】抽出来(strip_heredoc_bodies 的反面)。"""
    out, lines, i = [], cmd.splitlines(), 0
    while i < len(lines):
        m = HD_START.search(lines[i])
        i += 1
        if not m:
            continue
        tag, buf = m.group(1), []
        while i < len(lines) and lines[i].strip() != tag:
            buf.append(lines[i])
            i += 1
        if buf:
            out.append('\n'.join(buf))
    return out


# ⛔ 2026-09-07 修误伤:上面那条「body 里同时出现 写调用 + .py 字符串」的判据【太松】——
#    它不看写的是【哪个】文件。实录(当场连拦我两次,都是错的):
#        P = os.path.expanduser("~/.claude/settings.json")   ← 写的是 json
#        ...
#        if "lint-fatal-guard.py" in h.get("command", ""):   ← 只是【提到】一个 .py 名字
#        io.open(P, "w", encoding="utf-8").write(...)
#    ⇒ 判成"你在写 .py",拦掉。**改 settings.json 的脚本几乎必然要提到闸的 .py 文件名**,
#      所以这不是偶发,是这类活【每次都会】被误伤。
#    ⇒ 现在先解析写调用的【目标】:字面量直接看后缀;变量就回头找它的赋值行。
#      认定目标是非代码文件(json/md/txt/log/yaml…)⇒ 这次写调用放行。
#      **解析不出来时仍走老判据(宁可多拦)** —— 只收窄"我能证明它写的不是代码"的那部分。
NONCODE_EXT = re.compile(r"""\.(?:json|jsonl|md|txt|log|csv|ya?ml|toml|ini|cfg|html?)\b""", re.I)


def _extract_target(body, w):
    """从一处写调用里抠出【它写的是谁】。抠不出来返回 None(= 交给兜底,宁可多拦)。"""
    s = w.group(0)
    m = re.match(r"""(?:io\.)?open\(\s*([^,\n]+?)\s*,""", s, re.I)
    if m:
        return m.group(1)
    m = re.match(r"""(?:fs\.)?writeFileSync\(\s*([^,\n)]+)""", s, re.I)
    if m:
        return m.group(1)
    if ".write_text(" in s or ".writeFile(" in s:
        j = w.start()                          # 点号前面那个标识符
        k = j
        while k > 0 and (body[k - 1].isalnum() or body[k - 1] in "_."):
            k -= 1
        # ⛔ `Path("x.js").write_text(t)` —— 点号前是 `)`,抠不出标识符 ⇒ 返回 None 走兜底。
        #   我第一版在这里直接放行了,当场把一条真拦截改成漏拦(测试抓到)。
        return body[k:j] or None
    return None


def _target_is_code(body, tok):
    """这个写调用的目标是不是代码文件。True=是 / False=确定不是 / None=看不出来。"""
    tok = (tok or '').strip().strip('()')
    if not tok:
        return None
    if tok[0] in '\'"':                                   # 字面量:直接看它自己
        return bool(re.search(CODE_EXT, tok, re.I))
    if not re.match(r'^[A-Za-z_][\w.]*$', tok):           # 表达式(拼接/函数调用)→ 看不出来
        return None
    for ln in body.splitlines():                          # 变量:回头找赋值行
        if re.match(r'\s*%s\s*=' % re.escape(tok), ln):
            if re.search(CODE_EXT, ln, re.I):
                return True
            if NONCODE_EXT.search(ln):
                return False
    return None


def check_heredoc_writes(cmd):
    """heredoc 体内在写【代码文件】⇒ 命中。返回描述或 None。"""
    for b in heredoc_bodies(cmd or ''):
        p = HD_CODE_PATH.search(b)
        if not p:
            continue
        loose = None
        for w in HD_WRITE_CALL.finditer(b):
            verdict = _target_is_code(b, _extract_target(b, w))
            if verdict is True:                            # 确定在写代码文件
                return ('heredoc 里的脚本在写代码文件\n  → %s ... %s'
                        % (w.group(0)[:40], p.group(0)[:60]))
            if verdict is None:                            # 看不出来 → 留着当兜底
                loose = loose or w
        if loose is not None:                              # 解析不出目标 ⇒ 宁可多拦(老判据)
            return ('heredoc 里的脚本在写代码文件\n  → %s ... %s'
                    % (loose.group(0)[:40], p.group(0)[:60]))
    return None


def check(cmd):
    """返回命中的写法描述；没命中返回 None。"""
    if not cmd:
        return None
    hd = check_heredoc_writes(cmd)          # ← 先查 body(前三条看不见的那半)
    if hd:
        return hd
    cmd = strip_long_quoted(strip_heredoc_bodies(cmd))
    for rx, name in ((HEREDOC, 'heredoc 重定向到代码文件'),
                     (SED_I, 'sed -i 改代码文件'),
                     (ECHO, 'echo/printf 重定向到代码文件')):
        m = rx.search(cmd)
        if m:
            return '%s\n  → %s' % (name, m.group(0)[:120])
    return None


# ───────────── 第⑤条：临时目录 → 工具目录的复制（2026-10-04）─────────────
# 外审 2026-10-04：只认【命令位置】上的 cp / mv（行首或 ; & | 之后）——
#   `git commit -m "todo mv /tmp/a.py ~/.claude/bin/a.py"`、`echo "cp …"` 只是提到，不是在复制。
# 这一条只管最常见的写法；robocopy / cat > / 相对路径 / 先放桌面再搬 这些量不全的走法，
#   由 search-breadth-gate 收尾时按文件系统兜底（工具目录里这一轮多了什么新脚本）。
COPY_CMD = re.compile(r'(?:^|[;&|\n])\s*(?:cp|mv|copy|move|Copy-Item|Move-Item|cpi|mi)\b([^;&|\n]*)', re.I)
COPY_TOK = re.compile(r'"([^"]+)"|\'([^\']+)\'|([^\s"\';&|]+)')
VAR_DEF = re.compile(r'\$?([A-Za-z_]\w*)\s*=\s*(?:"([^"\n]+)"|\'([^\'\n]+)\'|([^\s;&|"\']+))')
MIN_TOOL_LINES = 40       # 和 prior-art-gate 的 MIN_LINES 同一个数


def _expand(tok, env):
    for k, v in env.items():
        tok = re.sub(r'\$\{?%s\}?(?![\w])' % re.escape(k), lambda m: v, tok)
    return tok.replace('$HOME', os.path.expanduser('~')).replace('$env:USERPROFILE', os.path.expanduser('~'))


def copies_into_tools(cmd):
    """命令里「临时目录的代码文件 → 工具目录」的复制 / 移动。返回 [(源, 目标文件)]。"""
    try:
        sys.path.insert(0, os.path.expanduser('~/.truthgate'))
        import six_universes as su
    except Exception:
        return []
    cmd = re.sub(r'[\\`]\r?\n', ' ', strip_heredoc_bodies(cmd or ''))      # 续行拼回一行
    env = {m.group(1): (m.group(2) or m.group(3) or m.group(4)) for m in VAR_DEF.finditer(cmd)}
    for _ in range(3):                                    # $s 里又用了 $env:TEMP 这类一层套一层
        env = {k: _expand(v, {a: b for a, b in env.items() if a != k}) for k, v in env.items()}
    out = []
    for m in COPY_CMD.finditer(cmd):
        toks = [_expand(a or b or c, env) for a, b, c in COPY_TOK.findall(m.group(1))]
        toks = [t for t in toks if not t.startswith('-')]
        srcs = [t for t in toks if su.TEMP_SRC.search(t) and re.search(CODE_EXT + r'$', t, re.I)]
        dsts = [t for t in toks if t not in srcs and su.is_tool_dest(t.rstrip('\\/') + '/')]
        for s in srcs:
            for d in dsts:
                target = d if re.search(CODE_EXT + r'$', d, re.I) else d.rstrip('\\/') + '/' + re.split(r'[\\/]', s)[-1]
                out.append((s, target))
    return out


def check_copy_into_tools(cmd, transcript_path):
    """第⑤条。返回拦截理由或 None。目标已存在（更新现有工具）/ 源文件不到 40 行 ⇒ 不管。"""
    pairs = copies_into_tools(cmd)
    if not pairs:
        return None
    try:
        import six_universes as su
        from guard_common import load_transcript_tail
        msgs = load_transcript_tail(transcript_path) if transcript_path else []
    except Exception:
        return None
    for src, dst in pairs:
        # 外审：/c/Users/…、%USERPROFILE%、${HOME} 这些写法 Windows 的 Python 直接判不出存在 ⇒ 先换算
        if os.path.exists(su.local_path(dst)):
            continue
        try:
            with open(su.local_path(src), encoding='utf-8', errors='replace') as f:
                if sum(1 for ln in f if ln.strip()) < MIN_TOOL_LINES:
                    continue
        except OSError:
            pass                                          # 读不到源文件 ⇒ 按够长算（宁可多查一次）
        why = su.tool_dest_verdict(dst, msgs)
        if why:
            return why + '\n（命中：把临时目录里的 %s 复制进工具目录 —— 和直接新建是一回事。）' % re.split(r'[\\/]', src)[-1]
    return None


# 前 3 条 = 2026-08-19 真实翻车的命令（postmortem-to-guard 要求用真实错误数据做回归）
SELF_TESTS = [
    ("cat > check_frames.py <<'PYEOF'\nprint(1)\nPYEOF", True),
    ("sed -i 's/bad = judge(checklist(s, plates), ans)/X/' check_frames.py", True),
    ("cat > /d/manju/novel/gen.py <<'EOF'\nx=1\nEOF", True),
    ('echo "import os" > tool.py', True),
    ('printf "%s" "x=1" >> helper.js', True),
    ("cat >> src/app.ts <<'TS'\nconst a=1\nTS", True),
    ('python check_frames.py EP001 > run.log 2>&1', False),
    ("python - <<'PY'\nimport io\nprint(1)\nPY", False),
    ('cat check_frames.py', False),
    ('sed -n "1,50p" check_frames.py', False),
    ('grep -n "def " check_frames.py > out.txt', False),
    ('git commit -m "fix check_frames.py"', False),
    ('cat > notes.md <<EOF\nhello\nEOF', False),
    ('sed -i "s/a/b/" config.json', False),
    ('npm run build > build.log 2>&1', False),
    # ⛔ 本闸上线后第一次拦人就误伤的那条：正当的 python - <<'PY'，
    #    但 heredoc **正文里引用了**翻车命令。body 是数据不是命令，不该拦。
    ("python - <<'PY'\ns = '''教训：cat > check_frames.py <<PYEOF 会崩'''\n"
     "open('lessons.md','a').write(s)\nPY", False),
    # 正文里出现 sed -i 也一样不该拦
    ("python - <<'PY'\nprint(\"别再用 sed -i 's/a/b/' tool.py\")\nPY", False),
    # ⛔ 第二次误伤：把闸的行为写进 --claim 参数里【描述】它，不是执行它
    ('py second-opinion.py --claim "会拦下 heredoc 写 .py / sed -i 改 .py / '
     'echo 重定向到 .py，但不拦 .log" --file gate.py', False),
    ('git commit -m "新闸拦 cat > x.py <<EOF 这种写法，改用 Write 工具"', False),
]


def self_test():
    bad = 0
    for cmd, want in SELF_TESTS:
        got = check(cmd) is not None
        if got != want:
            bad += 1
        print('%s 应拦=%-5s 实拦=%-5s | %s'
              % ('OK ' if got == want else 'XX ', want, got,
                 cmd.replace('\n', ' / ')[:74]))
    print('\n%d/%d 通过' % (len(SELF_TESTS) - bad, len(SELF_TESTS)))
    return (1 if bad else 0) or self_test_copy()


def self_test_copy():
    """第⑤条的自测：真写临时文件 + 假会话记录，走 check_copy_into_tools。"""
    import tempfile
    d = tempfile.mkdtemp(prefix='swcg_')
    scratch = os.path.join(d, 'scratchpad')
    os.makedirs(scratch)
    big = os.path.join(scratch, 'show_on_desktop.py')
    small = os.path.join(scratch, 'tiny.py')
    with open(big, 'w', encoding='utf-8') as f:
        f.write('\n'.join('x%d = %d' % (i, i) for i in range(60)))
    with open(small, 'w', encoding='utf-8') as f:
        f.write('x = 1\n')
    home = os.path.expanduser('~')
    AGS = home + '\\.gemini\\antigravity\\scripts\\'
    new = AGS + '__swcg_probe_not_exist__.py'
    exists = AGS + 'ag_archive.py'

    def tp(tools):
        p = os.path.join(d, 't%d.jsonl' % len(os.listdir(d)))
        rows = [{'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '修一下'}]}}]
        rows += [{'type': 'assistant', 'message': {'role': 'assistant', 'content': [
            {'type': 'tool_use', 'id': 't', 'name': n, 'input': i}]}} for n, i in tools]
        with open(p, 'w', encoding='utf-8') as f:
            f.write('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')
        return p

    GREP = ('Grep', {'pattern': 'desktop'})
    WEB = ('Bash', {'command': 'py -3 ~/.claude/web.py search "antigravity exebox hidden desktop"'})
    # 2026-10-04 真实那条命令的形状：PowerShell，源路径藏在变量里
    real = '$s="%s"\nCopy-Item "$s\\show_on_desktop.py" "%s" -Force' % (scratch, new)
    cases = [
        ('★10-04 真实形状：变量里的临时目录 → AG 脚本目录，零检索', real, [], True),
        ('★只在本机 grep 过', real, [GREP], True),
        ('✅用 web.py 上网搜过', real, [WEB], False),
        ('★bash cp 进 ~/.claude/bin（目标写目录）', 'cp "%s" ~/.claude/bin/' % big.replace('\\', '/'), [], False if os.path.exists(home + '/.claude/bin/show_on_desktop.py') else True),
        ('✅目标已存在 = 更新现有工具', 'Copy-Item "%s" "%s" -Force' % (big, exists), [], False),
        ('✅源文件不到 40 行', 'Copy-Item "%s" "%s"' % (small, AGS + '__swcg_tiny__.py'), [], False),
        ('✅复制到项目目录不算', 'cp "%s" "D:/airbnb ai manager/scripts/x.py"' % big.replace('\\', '/'), [], False),
        ('✅源不在临时目录（工具目录之间同步）', 'cp ~/.claude/skills/a/x.py ~/.gemini/config/skills/a/', [], False),
        ('✅复制的不是代码文件', 'cp "%s" ~/.claude/bin/' % os.path.join(scratch, 'notes.md').replace('\\', '/'), [], False),
        # ── 外审 2026-10-04 ──
        ('★变量用单引号', "$s='%s'\nCopy-Item \"$s\\show_on_desktop.py\" \"%s\"" % (scratch, new), [], True),
        ('★bash 变量不带引号', 's=%s\ncp "$s/show_on_desktop.py" "%s"' % (scratch.replace('\\', '/'), new.replace('\\', '/')), [], True),
        ('★续行', 'cp "%s" \\\n  "%s"' % (big.replace('\\', '/'), new.replace('\\', '/')), [], True),
        ('✅提交说明里只是提到 mv', 'git commit -m "todo mv /tmp/a.py ~/.claude/bin/a.py"', [], False),
        ('✅echo 里只是提到 cp', 'echo "todo: cp /tmp/a.py ~/.claude/bin/a.py"', [], False),
        ('✅目标已存在（/c/Users/… 写法）', 'cp "%s" "%s"' % (big.replace('\\', '/'), '/c' + exists.replace('\\', '/')[2:]), [], False),
        ('✅目标已存在（%USERPROFILE% 写法）', 'Copy-Item "%s" "%%USERPROFILE%%\\.gemini\\antigravity\\scripts\\ag_archive.py"' % big, [], False),
    ]
    bad = 0
    for name, cmd, tools, want in cases:
        got = check_copy_into_tools(cmd, tp(tools)) is not None
        bad += got != want
        print('%s 应拦=%-5s 实拦=%-5s | %s' % ('OK ' if got == want else 'XX ', want, got, name))
    # 读不到会话记录 ⇒ 判不了 ⇒ 放行（外审：原来这里是拦，而且该轮内怎么搜都解不开）
    for name, tpath in (('✅没有会话记录路径', None), ('✅会话记录不存在', os.path.join(d, 'nope.jsonl'))):
        got = check_copy_into_tools(real, tpath) is not None
        bad += got
        print('%s 应拦=False 实拦=%-5s | %s' % ('OK ' if not got else 'XX ', got, name))
    print('\n第⑤条 %d/%d 通过' % (len(cases) + 2 - bad, len(cases) + 2))
    return 1 if bad else 0


def main():
    if '--self-test' in sys.argv:
        return self_test()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get('tool_name') not in ('Bash', 'PowerShell'):
        return 0
    cmd = (data.get('tool_input') or {}).get('command', '')
    hit = check(cmd)
    if hit:
        print(MSG.format(what=hit), file=sys.stderr)
        return 2
    try:
        why = check_copy_into_tools(cmd, data.get('transcript_path'))
    except Exception:          # 第⑤条出错只丢它自己，别连累前四条
        why = None
    if why:
        print(why, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
