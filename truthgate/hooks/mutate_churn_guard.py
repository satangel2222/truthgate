#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""churn-guard 故障注入 —— 把 bug 逐个放回去,要求测试【真的变红】。

⛔ 为什么必须有(2026-08-25 我一天内五次量错尺子,其中一次靠外部审查才发现
   33 条故障注入没有一条真正执行过被测代码):**只跑绿永远发现不了摆设的断言**。
⛔ 每条注入后面标了它对应哪个真实事故形状。
⛔ 带对照组(control):等价改写,预期【仍绿】—— 没有对照组的故障注入是半套,
   全红也可能只是因为尺子在量"代码长什么样"而不是"它干了什么"。
"""
import os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "churn-guard.py")
TEST = os.path.join(HERE, "test_churn_guard.py")
PY = sys.executable

FAULTS = [
    # (名字, from, to, control?)
    ("判据恒假:总次数阈值调到天文数字(闸永不开火)",
     'CHURN_FILE = int(os.environ.get("CHURN_FILE", "20"))',
     'CHURN_FILE = int(os.environ.get("CHURN_FILE", "999999"))', False),
    ("判据恒假:同段阈值调到天文数字",
     'CHURN_SPOT = int(os.environ.get("CHURN_SPOT", "4"))',
     'CHURN_SPOT = int(os.environ.get("CHURN_SPOT", "999999"))', False),
    ("指纹不剥注释(同一段认不出来 —— 回归当场抓到过的真 bug)",
     '    line = re.sub(r"\\s*(//|#).*$", "", line)',
     '    line = line', False),
    # ⛔ 原本这里写的是 `line = raw.splitlines()[0]` → `line = raw`（"指纹用整段"）。
    #   跑出来【仍绿】,我一查:`[:40]` 截断之后,用整段和取首行**结果完全一样**
    #   （差异在第 40 字之后）⇒ 这个注入根本不产生行为差异 = **假故障**,不是测试漏了。
    #   （今天第 5 次把等价改写误判成故障。留着这段话,别再写第 6 次。）
    #   换成真能区分的:把截断长度调到 4 —— 指纹短到只剩 `cons`,不同的段会被误合并。
    ("指纹截断到 4 字(不同的段会被误合并成同一段 ⇒ 误拦正常迭代)",
     '    return line[:40]',
     '    return line[:4]', False),
    ("学 promise-gate 那个洞:被别的闸拦过就跳过(实测 60 轮只跑 27 轮)",
     '    tp = data.get("transcript_path")',
     '    if data.get("stop_hook_active"): sys.exit(0)\n    tp = data.get("transcript_path")', False),
    ("锁死:拦过的文件不记账 ⇒ 同一文件反复拦",
     '    fired.append(fname)',
     '    pass', False),
    ("读了数据也不放行(变成『禁止改代码』,会把我焊死)",
     '    if looked_at_data(msgs, fname):',
     '    if False:', False),
    ("放行时不存 state(跨轮累计全丢 ⇒ 计数永远回到 0 ⇒ 闸够不到阈值)",
     '        save_state(st)\n        hook_log(NAME, f"allow(max={mx} < {CHURN_FILE})")',
     '        hook_log(NAME, f"allow(max={mx} < {CHURN_FILE})")', False),
    ("不做跨轮增量(只数当轮尾窗 ⇒ 长 session 里严重低估,52 次只数到 10 次)",
     '    new_msgs = [m for m in msgs if (m.get("timestamp") or "") > last_ts] if last_ts else msgs',
     '    new_msgs = msgs\n    acc_reset = sd.pop("acc", None)', False),
    ("文档也算 churn(改 PROGRESS 被误拦)",
     '            if not fp.lower().endswith(CODE_EXT):',
     '            if False:', False),
    ("密度阈值调到天文数字(A 永不开火;2026-09-16 加的条件被废掉)",
     'CHURN_DENSITY = float(os.environ.get("CHURN_DENSITY", "2.0"))',
     'CHURN_DENSITY = float(os.environ.get("CHURN_DENSITY", "999999"))', False),
    ("去掉密度条件(改得广也当打转 —— 2026-09-16 那种误拦回来了)",
     '        file_rule = (rec["n"] >= CHURN_FILE and density >= CHURN_DENSITY) or rec["n"] >= CHURN_FILE_HARD',
     '        file_rule = rec["n"] >= CHURN_FILE or rec["n"] >= CHURN_FILE_HARD', False),
    ("兜底上限调到天文数字(同一函数换起始行反复改,永远看不见)",
     'CHURN_FILE_HARD = int(os.environ.get("CHURN_FILE_HARD", "40"))',
     'CHURN_FILE_HARD = int(os.environ.get("CHURN_FILE_HARD", "999999"))', False),
    # ── 对照组:等价改写,必须仍绿 ──
    ("[对照组] 密度阈值写成等价表达式",
     'CHURN_DENSITY = float(os.environ.get("CHURN_DENSITY", "2.0"))',
     'CHURN_DENSITY = float(os.environ.get("CHURN_DENSITY", str(4 / 2)))', True),
    ("[对照组] 阈值写成等价表达式",
     'CHURN_SPOT = int(os.environ.get("CHURN_SPOT", "4"))',
     'CHURN_SPOT = int(os.environ.get("CHURN_SPOT", str(2 + 2)))', True),
    ("[对照组] 日志文案微调",
     'hook_log(NAME, "allow(no code edits)")',
     'hook_log(NAME, "allow(nothing edited)")', True),
]


def run_tests():
    p = subprocess.run([PY, TEST], capture_output=True, text=True, timeout=300, cwd=HERE)
    return p.returncode


def main():
    orig = open(TARGET, encoding="utf-8").read()
    base = run_tests()
    if base != 0:
        print("⛔ 基线就不是全绿,先修好再注入"); sys.exit(2)
    print("基线 ✅ 全绿\n")

    bad = []
    for name, a, b, control in FAULTS:
        if a not in orig:
            print(f"❌ 锚点失效  {name}"); bad.append(name); continue
        if orig.count(a) > 1:
            print(f"❌ 锚点不唯一 {name}"); bad.append(name); continue
        open(TARGET, "w", encoding="utf-8").write(orig.replace(a, b))
        try:
            rc = run_tests()
        finally:
            open(TARGET, "w", encoding="utf-8").write(orig)   # 无论如何还原
        red = rc != 0
        ok = (not red) if control else red
        tag = "仍绿" if not red else "变红"
        print(f"{'✅' if ok else '❌'} {tag}  {name}{'  [对照组:预期仍绿]' if control else ''}")
        if not ok:
            bad.append(name)

    if run_tests() != 0:
        print("\n⛔ 还原后没回到全绿 —— 文件可能被写坏了"); sys.exit(2)
    print(f"\n{'❌ ' + str(len(bad)) + ' 条没达标' if bad else '✅ ' + str(len(FAULTS)) + '/' + str(len(FAULTS)) + ' 达标:每个 bug 放回去都真的被测出来'}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
