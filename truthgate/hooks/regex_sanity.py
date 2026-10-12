#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""判据过宽体检 —— 拿【绝不该被拦的正常输出】去打每道闸的正则,命中就是过宽嫌疑。

⛔ 先查现成(2026-07-29,按铁律):WebSearch「detect overly broad regex false positive test corpus」
   + `gh search repos "regex false positive detection corpus" / "regex linter overly broad"`
   → 前者只有通用 linter(Semgrep/pylint)和"正则效率 linter",后者 **0 结果**。
   没有"用正常语料反测判据是否过宽"的现成工具,且判据高度特化于本场景。⇒ **只能自建**。

⛔ 为什么必须有它(2026-07-29 一天之内我把判据写错 6 次,这是当天的头号形状):
   ① `SKIPPED` 放进 re.I 且无词边界 ⇒ 拦下 `12 passed, 1 skipped`(最常见的 pytest 输出)
   ② `test_.*guard` ⇒ 会误豁免用户项目里正常的 `test_auth_guard.py`
   ③ `hooks[/\\]` 要求后跟分隔符 ⇒ 漏掉最常见的 `cd .../hooks && python …`
   ④ 普查器只认大写 `BLOCK` ⇒ 把用 `DENY` 的闸判成纸老虎
   ⑤ 同上,漏小写 `block:` ⇒ 把今天刚拦过我的闸判成纸老虎
   ⑥ D 判据扫全文任意 except ⇒ 9 道报警、实际只有 3 道真有问题
   **每一次都是"看起来对、跑起来炸",而且每一次都要等到真数据打脸才发现。**
   ⇒ 把"拿常见正常输出试一次"这个动作**从自觉变成机器强制**。

用法:
    python regex_sanity.py            # 人看
    python regex_sanity.py --json     # 机器读(已挂进 superego-regress 收尾)
豁免:在正则那一行(或上一行)写 `# regex-sanity: ok <理由>`,该正则不参与体检。
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ── 绝不该触发任何拦截的【正常输出】语料 ──────────────────────────────────
# 每一条都是真实工具的典型成功输出;闸的判据打中这些 = 它会在日常工作里误伤。
CORPUS = [
    ("pytest 正常全过", "collected 12 items\n\n===== 12 passed in 1.20s ====="),
    ("pytest 带跳过", "===== 12 passed, 1 skipped in 2.31s ====="),
    ("pytest 明确零跳过", "===== 30 passed, 0 skipped, 0 failed in 4.1s ====="),
    ("npm test 成功", "> app@1.0.0 test\n> jest\n\nTests:  8 passed, 8 total\nTime: 2.4 s"),
    ("git status 干净", "On branch main\nnothing to commit, working tree clean"),
    ("git commit 成功", "[main 1a2b3c4] fix: 修好登录\n 2 files changed, 30 insertions(+)"),
    ("rsync 正常", "rsync: 2 skipped (up to date)\nsent 1.2K bytes  received 88 bytes"),
    ("pip 安装成功", "Successfully installed httpx-0.27.0 anyio-4.3.0"),
    ("docker 构建成功", "Successfully built 9f2a1b3c\nSuccessfully tagged app:latest"),
    ("curl 200", "HTTP/1.1 200 OK\nContent-Type: application/json\n\n{\"ok\":true}"),
    ("ffmpeg 正常收尾", "frame= 1200 fps= 60 q=28.0 Lsize=   4096kB\nvideo:3900kB muxing overhead 0.5%"),
    ("普通中文汇报", "改完了，我跑了一遍测试，结果都对，把凭证贴在上面了。"),
    ("普通中文提问", "这个功能大概什么时候能做完？要不要我先看看别的？"),
    ("文件列表", "total 48\n-rw-r--r-- 1 User 197121 1024 Jul 29 05:00 app.py"),
]

DECL = re.compile(r"^([A-Z][A-Z0-9_]{2,})\s*=\s*re\.compile\(", re.M)


def gate_sources():
    for p in sorted(glob.glob(os.path.join(HERE, "*.py"))):
        b = os.path.basename(p)
        if b.startswith("test_") or b in (os.path.basename(__file__), "regex_sanity.py"):
            continue
        yield b, p


def extract_regexes(path):
    """抠出模块级 `NAME = re.compile(...)`,连同它编译出来的对象。

    ⛔ 用 exec 整个模块会有副作用(闸会读 stdin / 退出),所以只 exec **这一条赋值语句**。
    ⛔⛔ 返回 `(检到的, 没检到的)` —— 第一版 eval 失败就 `continue`、**一个字都不吭**,
       外部 critic 2026-07-29 实测:全库 88 个模块级正则**只检了 57 个**,
       静默丢掉的 12 个恰恰是**最大最复杂的那批**(NAG / WALL_STRONG / WEAK_VERIFY /
       FILE_CLAIM / HEAVY / RESIDUE_LINE / DELIVERED …,因为它们引用了别的变量或跨行拼接),
       而它打印的是「✅ 干净」。**一把只量得到简单目标、却报『全都合格』的尺子 = 纸老虎。**
       现在:没检到的必须报出来,报表里写清覆盖率。
    """
    try:
        src = open(path, encoding="utf8", errors="replace").read()
    except Exception:
        return [], []
    # ⛔⛔ 用标准库 `ast` 解析,不再手写"从 re.compile( 起做括号配平"(critic 实测那套的两个硬伤):
    #    ① 括号配平**会切进字符串字面量** ⇒ RESIDUE_LINE / DELIVERED / WEAK_VERIFY 等 6 个 SyntaxError;
    #    ② 只 eval 单条语句 ⇒ 引用了前置变量的(`_FILE_OBJ` / `GAP` / `_WALL_STRONG`)全 NameError。
    #    ast 方案两个一起解决:按顺序 exec **所有模块级赋值**(不碰函数体、不触发闸的 main),
    #    前置变量就位;再用 `ast.get_source_segment` 拿到准确的源码片段。
    out, skipped = [], []
    try:
        import ast
        tree = ast.parse(src)
        ns = {"re": re, "os": os, "sys": sys, "json": json}
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            seg = ast.get_source_segment(src, node)
            if not seg:
                continue
            try:
                exec(seg, ns)          # 只跑模块级赋值:纯数据,不含 IO/退出
            except Exception:
                pass                    # 前置变量缺失不致命,下面按 regex 逐个记 skipped
            tgt = node.targets[0]
            if not isinstance(tgt, ast.Name) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", tgt.id):
                continue
            if not (isinstance(node.value, ast.Call)
                    and getattr(getattr(node.value, "func", None), "attr", "") == "compile"):
                continue
            ln0 = node.lineno - 1
            # 豁免只认紧邻上一行(见下方原因)
            if "regex-sanity: ok" in "\n".join(src.splitlines()[max(0, ln0 - 1): ln0 + 1]):
                continue
            rx = ns.get(tgt.id)
            if isinstance(rx, re.Pattern):
                out.append((tgt.id, rx, node.lineno))
            else:
                skipped.append((tgt.id, node.lineno, "exec 后拿不到编译好的 Pattern"))
        return out, skipped
    except SyntaxError as e:
        return [], [("<整个文件>", 0, f"文件本身语法错: {str(e)[:60]}")]
    except Exception:
        pass                            # ast 路径出意外 → 退回下面的老实现(fail-open,别整个哑掉)

    lines = src.splitlines()
    for m in DECL.finditer(src):
        name = m.group(1)
        start_line = src[:m.start()].count("\n")
        # ⛔ 豁免只认【紧邻上一行】—— 原来窗口是 `lines[decl-1 : decl+6]`,一条注释能顺带
        #    赦免它上方 6 行内的其它正则:外部 critic 2026-07-29 实测 **15 条注释实际赦免了
        #    19 个正则**(`time-sanity` 那条为 SENT_SPLIT 写的理由,顺带豁免了 DATE_RE 与 SHORT_RE,
        #    理由对它俩完全不适用)。后果和"故意滥用"一样:那些正则从没人真看过。
        window = "\n".join(lines[max(0, start_line - 1): start_line + 1])
        if "regex-sanity: ok" in window:
            continue
        # 从 re.compile( 起做括号配平,取出完整调用
        i = src.index("re.compile(", m.start()) + len("re.compile(")
        depth, j = 1, i
        while j < len(src) and depth:
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
            j += 1
        expr = "re.compile(" + src[i:j]
        try:
            rx = eval(expr, {"re": re, "__builtins__": {}})   # 只求值一个 re.compile 字面量
        except Exception as e:
            # ⛔ 绝不静默丢弃(见 docstring):丢掉的正是最复杂、最该被检的那批
            skipped.append((name, start_line + 1, f"{type(e).__name__}: {str(e)[:60]}"))
            continue
        out.append((name, rx, start_line + 1))
    return out, skipped


def audit(with_skipped=False):
    findings, skipped_all = [], []
    for gate, path in gate_sources():
        got, sk = extract_regexes(path)
        skipped_all += [(gate,) + t for t in sk]
        for name, rx, ln in got:
            hits = []
            for label, sample in CORPUS:
                try:
                    m = rx.search(sample)
                except Exception:
                    continue
                if m:
                    hits.append({"corpus": label, "matched": m.group(0)[:40]})
            if hits:
                findings.append({"gate": gate, "regex": name, "line": ln,
                                 "hit_count": len(hits), "hits": hits[:4]})
    return (findings, skipped_all) if with_skipped else findings


def main():
    f, skipped = audit(with_skipped=True)
    if "--json" in sys.argv:
        print(json.dumps({"findings": f,
                          "skipped": [{"gate": g, "regex": n, "line": ln, "why": w}
                                      for g, n, ln, w in skipped]},
                         ensure_ascii=False, indent=1))
        return 0
    # ⛔ 覆盖率必须先报:一把只量得到简单目标、却宣布"全都合格"的尺子 = 纸老虎
    #    (critic 实测第一版:88 个模块级正则只检了 57 个,静默丢掉的正是最复杂的那批)。
    if skipped:
        print(f"⚠️ 有 {len(skipped)} 个正则【没检到】(引用了别的变量/跨行拼接,eval 不出来)——"
              f"下面的结论**不覆盖它们**:")
        for g, n, ln, w in skipped[:12]:
            print(f"   · {g}:{ln} {n}  ({w})")
        print()
    if not f:
        print("✅ 判据过宽体检:检到的正则里,没有任何一个命中【正常输出】语料"
              + (f"(⚠️ 但另有 {len(skipped)} 个没检到,见上)" if skipped else ""))
        return 0
    print(f"⚠️ 判据过宽嫌疑 {len(f)} 处(命中了本不该被拦的正常输出):")
    for x in sorted(f, key=lambda y: -y["hit_count"]):
        print(f"\n  {x['gate']}:{x['line']}  {x['regex']}  命中 {x['hit_count']}/{len(CORPUS)} 条正常语料")
        for h in x["hits"]:
            print(f"      · 「{h['corpus']}」被匹配到: {h['matched']!r}")
    print("\n⛔ 这不等于一定是 bug —— 有些正则本来就该命中(如提取路径的)。"
          "\n   但每一条都必须【当场看一眼】:它会不会在日常工作里误伤?"
          "\n   确认无害就在那一行加注释 `# regex-sanity: ok <理由>` 豁免掉,别让它长期当噪音。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
