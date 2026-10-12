#!/usr/bin/env python3
"""PostToolUse:改完 .py 立刻用 ruff 查【致命静态错】,只报不改。

2026-07-28 建。病根:我今天【同一天两次】写下 `io.open(...)` 而目标文件根本没有
`import io` → NameError → 被 `except Exception` 吞掉 → **功能静默失效、测试还是绿的**
(doctor.py 的归属查询、session-context-inject 的失败警报,两次都是这样)。
fail-open 本意是安全,代价是它把我的 bug 藏起来 —— 所以要在【写完的那一刻】就抓。

先查现成(2026-07-28):本机 ruff/pyflakes/flake8/pylint **一个都没装** → 装了 ruff 0.16.0
(Rust 单二进制、启动 <50ms、免费);现成 hook `TMYuan/ruff-claude-hook` **★3、7 个月未更新、
且会自动 format**(会改动 Superego 里精心对齐的中文注释)⇒ **复用 ruff 本体、胶水自建、绝不 format**。
选的规则:F821 未定义名(今天两次的病根)/F822 __all__ 里的幽灵名/E9 语法与缩进错。
⛔ nudge 档:只注提醒,绝不阻塞、绝不自动改代码。
回归:`test_lint_fatal_guard.py`。
"""
import sys, os, ast, json, shutil, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from guard_common import hook_log, trig
except Exception:
    def hook_log(*a, **k): pass
    def trig(s, n=120): return (s or "")[:n]

RULES = "F821,F822,E9"


def io_open_text(fp):
    return open(fp, encoding="utf-8", errors="ignore").read()


def check_arity(src, fp):
    """同文件内定义的函数,被调用时【位置参数个数】对不对。纯 AST,毫秒级。

    ⛔ 2026-07-28 补:今天最狠的那个死闸就是这类 —— 我写 `_log(msg, ctx)`,而那两个文件的
       `_log` **只收 1 个参数** ⇒ TypeError → 被紧挨着的 `except: pass` 吃掉 ⇒
       **拦截 JSON 永远发不出去、日志照常打 allow(...)**,46 套测试全绿盖着它。
       这类错 ruff 抓不到(它不做调用图);pylint 的 E1121 抓得到,但**单文件 8.6 秒**,
       对每次 Edit 都跑的 hook 是灾难(会拖卡机器)⇒ 借它的判据、自己用 AST 实现。

    保守到底(宁可漏报,绝不误报):
      · 只看 `名字(...)` 形式的直接调用,属性调用(`obj.f()`)一概不看 —— 静态判不出 self/类;
      · 同名函数被定义多次(典型:try/except 里的 fail-open 降级桩)一律跳过 —— 用哪个静态定不了;
      · 调用里出现 `*args`/`**kwargs` 展开、或函数自己带 `*args`/`**kwargs` 的,跳过;
      · 解析失败静默返回空(语法错另有 E9 管)。
    """
    try:
        tree = ast.parse(src)
    except Exception:
        return []
    defs, dup = {}, set()
    # ⛔ 2026-07-29 外部 critic 抓到的【野外 100% 误报】:它独立扫 396 个 .py,命中 7 次、7 次全错。
    #   根因两个:
    #   ① **关键字专用参数(kwonly)**:`def f(a, *, verbose=False)` 里的裸 `*` 不是 vararg,
    #      上一版的保守闸放它进来了;而 given 把打给 kwonly 的关键字也算进【位置参数】⇒ 必然虚高。
    #      真实受害者:`offer_dependency_install(*, feature, ...)` 被判"传 4 个但定义 0 个"。
    #   ② **名字被重新绑定**(`f = functools.partial(f,1)` / 局部 `send = fn`)⇒ 调用的根本不是那个函数。
    #   每次 Edit 都跑的 nudge 一旦狼来了,整道闸就废了 —— 所以宁可再保守一层。
    rebound = {n.id for n in ast.walk(tree)
               if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if n.name in defs:
                dup.add(n.name)
                continue
            a = n.args
            if a.vararg or a.kwarg:
                dup.add(n.name)              # 变长参数 → 不判
                continue
            pos_names = [x.arg for x in getattr(a, "posonlyargs", [])] + [x.arg for x in a.args]
            kwok = {x.arg for x in a.args}   # 只有这些能被关键字顶到【位置槽】
            defs[n.name] = (len(pos_names) - len(a.defaults), len(pos_names), kwok)
    bad = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)):
            continue
        name = n.func.id
        if name in dup or name not in defs or name in rebound:
            continue                          # 被重新绑定过 → 静态定不了调的是谁
        if any(isinstance(x, ast.Starred) for x in n.args) or any(k.arg is None for k in n.keywords):
            continue                          # 有展开 → 静态数不准
        lo, hi, kwok = defs[name]
        if any(k.arg not in kwok for k in n.keywords):
            continue                          # 关键字打到 kwonly / 未知名 → 不判
        given = len(n.args) + len(n.keywords)
        if given < lo or given > hi:
            bad.append(f"{os.path.basename(fp)}:{n.lineno}: 调用 {name}() 传了 {given} 个参数,"
                       f"但它定义为 {lo}~{hi} 个 → 运行时 TypeError"
                       f"(而 TypeError 常被 except 吞掉 ⇒ 功能静默失效、测试还绿)")
    return bad


def scan(fp):
    """返回致命错文本('' = 干净)。两半各自独立 try —— 一半挂了不能把另一半也带走。

    ⛔ 2026-07-29 外部 critic 抓到两处实害,都源于"两件事塞进一个 try":
      ① **ruff 抛异常/超时时,arity 结果被一起吞掉** —— 而 arity 是纯 AST、毫秒级、零依赖,
         它的失败面和 ruff 完全不相关,不该共享。实测:ruff 超时 → 整个 scan 返回 ''。
      ② **ruff 会无声死亡**:调的是 `sys.executable -m ruff`,绑死在"谁在跑这个 hook"。
         实测 `C:\\Python314\\python.exe` 有 ruff、`py -3.12` 没有 ⇒ 换个解释器 F821 检查
         静默归零、**日志一行都不落**。这正是本闸自己诞生要治的病。⇒ 拿不到 ruff 必须留尸体。
    """
    if not fp.endswith(".py") or not os.path.exists(fp):
        return ""
    parts = []
    # ── 半一:ruff(外部依赖,可能不在当前解释器里)
    # ⛔⛔ 2026-09-05 根因加固(Frank 授权彻查 superego):本文件第 98 行早就预言了
    #   「调 `sys.executable -m ruff` = 绑死在谁在跑这个 hook,换个解释器就静默归零」——
    #   而 2026-09-04 换盘重装后 ruff 根本没被装回来,这道闸【整个失效】,
    #   26 条回归里 4 条红(连语法错 E9、未定义变量 F821 都放过)。
    #   同一天它没抓到的真 bug:`search-breadth-gate` 里 `hit` 未定义 ⇒ 那道闸 fail-open
    #   放行一切 ⇒ 我零检索通道下断言时无人拦。**抓错的工具坏了,错就没人抓。**
    #   ⇒ 不再只问当前解释器:按顺序找【第一个真有 ruff 的运行方式】。
    #   ⛔ 只放宽"去哪找 ruff",绝不放宽"发现问题要不要报"。
    def _ruff_argv():
        cands = [[sys.executable, "-m", "ruff"]]
        exe = shutil.which("ruff")                       # PATH 里的独立二进制(最快)
        if exe:
            cands.insert(0, [exe])
        for py in ("py",):                               # Windows 启动器:显式点名 3.12
            if shutil.which(py):
                cands.append([py, "-3.12", "-m", "ruff"])
        return cands

    ran = False
    for argv in _ruff_argv():
        try:
            r = subprocess.run(argv + ["check", "--select", RULES,
                                       "--output-format", "concise", "--no-cache", fp],
                               capture_output=True, text=True, timeout=20)
        except Exception:
            continue
        if "No module named" in (r.stderr or ""):
            continue                                     # 这条路没有 ruff,换下一条
        ran = True
        out = (r.stdout or "").strip()
        if out and not out.startswith("All checks passed"):
            parts.append("[ruff 静态错]\n" + out)
        break

    try:
        if not ran:
            hook_log("lint-fatal", "DEGRADED: 所有候选解释器都没有 ruff,F821 检查这轮没跑",
                     trig(sys.executable, 120))       # 死也要留尸体,别静默归零
        else:
            out = (r.stdout or "").strip()
            if out and not out.startswith("All checks passed"):
                parts.append("[ruff 静态错]\n" + out)
    except Exception as e:
        try:
            hook_log("lint-fatal", f"DEGRADED: ruff 跑不起来({type(e).__name__}),F821 检查这轮没跑", "")
        except Exception:
            pass
    # ── 半二:arity(纯 AST,零依赖) —— 独立 try,ruff 挂了它照样跑
    try:
        arity = check_arity(io_open_text(fp), fp)
        if arity:
            parts.append("[参数个数错 → 运行时 TypeError]\n" + "\n".join(arity))
    except Exception:
        pass
    return "\n".join(parts)


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
        # ⛔⛔ 2026-09-07 判效果不判手法(Frank 当场点破):
        #   原来只在 tool_name ∈ (Edit, Write, NotebookEdit) 时查,
        #   而我**大量用 Bash 跑脚本改 .py**(避转义坑,是 shell-writes-code-gate 教的)
        #   ⇒ 那条路写出来的 .py **一次都没被 ruff 查过**。
        #   今晚它报过的几个 F821 全来自 Write/Edit 那条路,另一条全黑。
        #   ⛔ 这道闸治的就是"被 except 吞掉的静默失效",而它自己在最常用那条路上静默失效。
        #   ⇒ 工具路径照旧(精准零成本);其它路径扫最近变过的 .py(实测 0.026~0.048 秒)。
        tn = data.get("tool_name")
        targets = []
        if tn in ("Edit", "Write", "NotebookEdit"):
            fp0 = str((data.get("tool_input") or {}).get("file_path") or "")
            if fp0:
                targets = [fp0]
        elif tn in ("Bash", "PowerShell", "Task", "Agent"):
            # ⛔ 只在【可能写文件的工具】上扫 —— 上一版无条件扫,导致
            #   「非文件工具→静默」「空 payload→静默」两条回归变红,那两条红得对:
            #   Read/Grep/空 payload 压根不可能写文件,见谁都扫就是新的噪音源,
            #   而噪音会让我学会无视这道闸(它自己的病历里写着这条)。
            try:
                from guard_common import recently_changed
                targets = recently_changed(within=90, exts=(".py",), limit=5)
            except Exception:
                targets = []
        if not targets:
            return
        fp, bad = "", ""
        for _t in targets[:5]:
            _b = scan(_t)
            if _b:
                fp, bad = _t, _b
                break
        if not bad:
            return
        hook_log("lint-fatal", f"NUDGE {os.path.basename(fp)}", trig(bad.replace("\n", " | "), 160))
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"🐛 {os.path.basename(fp)} 里有【致命静态错】(只报不改):\n{bad}\n"
                "⛔ 这两类错的共同点:**几乎总是被 `except Exception` 吞掉** ⇒ 功能静默失效、回归还是绿的。\n"
                "  · `F821 未定义名` = 用了没 import 的模块/变量。2026-07-28 同一天栽两次"
                "(doctor 的归属查询、开局失败警报),都是从别处抄了写法、没核目标文件的 import。\n"
                "  · `参数个数错` = 调用时传的个数和定义对不上 → 运行时 TypeError。"
                "同日最狠的死闸就是这类:`_log(msg, ctx)` 而 `_log` 只收 1 个 ⇒ 拦截 JSON 永远发不出去、"
                "日志照常打 allow(...)、46 套测试全绿盖着它。\n"
                "现在就修,别等它被 except 藏起来。"
            ),
        }}, ensure_ascii=False))
    except Exception:
        pass          # fail-open


if __name__ == "__main__":
    main()
