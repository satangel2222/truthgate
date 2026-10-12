# -*- coding: utf-8 -*-
"""跑完【某一道闸】的所有测试:`py -3.12 run_gate_tests.py <闸名或文件名>`。

⛔ 存在的理由(2026-09-07):故障注入案例只能指定一个 cmd,而多数闸有好几份测试。
   注入打在判据 A 上、只跑了测试 B ⇒ 报"仍绿" —— 那不是闸不设防,是尺子拿错了。
   实测:一次跑出 10 条这样的假"仍绿"(strawman 的 PROBE、no-nagging 的 HARD_CHOICE…)。

任一份测试失败 ⇒ 退出码非 0(故障注入据此判"变红")。
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def tests_for(gate):
    """按【正文里有没有提到这道闸】来找,**不按文件名**。

    ⛔⛔ 2026-09-07 同一天第二次栽在形状 -M(尺子拿错/拿漏)上:
      第一版是"文件名词匹配 + 正文确认"。文件名那一关**恰好把真正那份筛掉了** ——
      `regress-on-guard-edit` 的并发封顶(MAX_CONCURRENT)和僵尸标记(MARK_TTL)
      测在 **`test_regress_concurrency.py`** 里(名字里既没 guard 也没 edit)
      ⇒ 它永远进不了候选 ⇒ 那三条故障注入怎么改都"仍绿",
      而我差一点又把它读成"这道闸不设防"。
      ⇒ **文件名是人起的、会不一致;正文里提到哪个闸才是事实。**

    正文确认这一关要留着 —— 它治的是反方向的错:`progress-gate` 曾按名字匹配到 3 份,
    其中两份 `test_progress_inject*` 测的是 `progress-inject.py`,
    改坏 progress-gate 它们照样绿,把真信号稀释成"仍绿"。
    """
    # ⛔ 判据必须带 `.py` —— 只写裸名会两头出错(当天实测):
    #   ①**误纳**:别的测试在注释里顺口提一句 "critic-gate" 就被算成它的测试,
    #     真信号被稀释成"仍绿";
    #   ②**递归**:本运行器自己的元测试 `test_run_gate_tests.py` 正文里就有
    #     "zz-no-such-gate.py" 这类夹具名 ⇒ 它把自己当成候选 ⇒ 自己跑自己 ⇒ 120 秒超时。
    #   带 `.py` 之后实测:`test_regress_concurrency.py` 命中 1(该收的收进来),
    #   `test_no_nagging_guard.py` 对 critic-gate 命中 0(该挡的挡住)。递归另有护栏(见 main)。
    stem = os.path.splitext(os.path.basename(gate))[0]
    keys = {stem + ".py", stem.replace("-", "_") + ".py", stem.replace("_", "-") + ".py"}
    # ⛔ 2026-09-07:带 `.py` 的规则对【模块】不成立。`guard_common` 这类是被
    #   `import guard_common` / `from guard_common import ...` 引用的,正文里根本没有 `.py`
    #   ⇒ 它的两份关键测试(并发日志、自动补记账)全被漏掉,新加的注入自然"仍绿"。
    #   这是我修"误纳"时开出的第二个漏纳(今天第 5 次同形状) ⇒ 把 import 形式一并算进去。
    #   仍然精确:import 语句是明确的依赖声明,不是"注释里顺口提一句"。
    _mod = stem.replace("-", "_")
    keys |= {"import %s" % _mod, "from %s import" % _mod}
    # ⛔ 2026-09-07 同一个洞的第三面:判据只会拼 `.py`,而闸有 `.cjs/.js/.mjs` 的 ——
    #   `test_pm2_guard.cjs_fix.py` 正文里写的是 "pm2-guard.cjs",一个 `.py` 键都对不上
    #   ⇒ 报「找不到任何测试」⇒ 它的故障注入【基线直接判红】,而测试其实好好地在那儿,
    #   我差点据此以为这道闸坏了。⇒ 按【闸在硬盘上的真实文件名】补键,不靠我猜后缀。
    #   (his-browser-guard 之所以侥幸能匹配,是因为它的测试正文里恰好还出现了
    #    `his_browser_guard.py` 这个名字 —— 靠巧合过关,不是判据对。)
    for _ext in (".py", ".js", ".cjs", ".mjs"):
        for _v in (stem, stem.replace("-", "_"), stem.replace("_", "-")):
            if os.path.isfile(os.path.join(HERE, _v + _ext)):
                keys.add(_v + _ext)
    out = []
    for f in sorted(os.listdir(HERE)):
        if not f.startswith("test_") or not f.endswith(".py"):
            continue
        try:
            body = open(os.path.join(HERE, f), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        # ⛔ 跳过【驱动本运行器的那份元测试】:它正文里全是当夹具用的闸名
        #   (zz-no-such-gate.py / critic-gate.py …),按内容找就会把它当成每一道闸的测试,
        #   然后自己跑自己。它测的是运行器,不是任何一道闸。
        if "run_gate_tests" in body:
            continue
        # ⛔ 2026-09-07:跳过【全仓扫描型】测试。它们正文里会枚举一大堆闸名
        #   (合规体检自检、兜底桩体检…),按内容匹配就会被算成【每一道闸】的测试。
        #   后果实测:`run_gate_tests false-done-gate` 把 `test_gate_conformance_selfcheck.py`
        #   也跑了 —— 它测的是体检本身,跟 false-done 无关,红了却让 false-done 的基线自检失败。
        #   判据:提到 ≥5 个不同闸名的,是扫描器不是某一道闸的测试。
        # ⛔ 但【文件名对得上】的不适用这条:那是最强的正向证据。
        #   实录:第一版没加这个例外,把 `test_fault_injection_gate.py` 也当成扫描器排掉了
        #   ⇒ `fault-injection-gate` 变成"一个测试都找不到" ⇒ 它的基线自检当场失败。
        #   **我为了修一个误纳,造出了一个漏纳。** 修误伤时最容易顺手开一个洞(已发作 4 次)。
        _fname_hit = any(k[:-3].replace("-", "_") in f.replace("-", "_") for k in keys)
        # ⛔ 2026-09-18:只数【hooks 里真实存在的闸文件】。原来数任意 `x_y.py` 字样 ⇒
        #   测试自己造的夹具脚本名(heavy_gpu.py / cpu_embed.py …)也算 ⇒ `test_launch_bound.py`
        #   被当成扫描器排掉 ⇒ launch-bound 的故障注入【从来没跑过它】,当天新加的注入因此"仍绿"。
        #   改后对 96 道有注入样本的闸实测:多挑 5 份、少挑 0 份,5 份都是绿的。
        _gates_named = {n for n in re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)+\.py", body)
                        if any(os.path.isfile(os.path.join(HERE, v))
                               for v in (n, n.replace("_", "-"), n.replace("-", "_")))}
        if not _fname_hit and len(_gates_named) >= 5:
            continue
        if any(k in body for k in keys):
            out.append(f)
    return out


def main():
    if len(sys.argv) < 2:
        print("用法: run_gate_tests.py <闸名>")
        return 2
    gate = sys.argv[1]
    ts = tests_for(gate)
    if not ts:
        print("!! 找不到 %s 的任何测试 —— 这本身就是问题(合规体检第①条)" % gate)
        return 3
    # ⛔ 递归护栏:某份测试的正文里可能提到别的闸名,于是它被选中 → 它又调本运行器 → 无限套娃。
    #   实测撞过一次(元测试里的夹具名 "zz-no-such-gate.py"),表现是 120 秒超时,
    #   看起来像"某个测试很慢",很难联想到是递归。⇒ 用环境变量记深度,套第二层就拒绝。
    env = dict(os.environ)
    if env.get("RUN_GATE_TESTS_DEPTH"):
        print("!! 已在 run_gate_tests 里了,拒绝套娃(防递归)")
        return 0
    env["RUN_GATE_TESTS_DEPTH"] = "1"
    bad = []
    for t in ts:
        r = subprocess.run([sys.executable, os.path.join(HERE, t)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=600, cwd=HERE, env=env)
        tag = "OK  " if r.returncode == 0 else "FAIL"
        print("  %s %s" % (tag, t))
        if r.returncode != 0:
            bad.append(t)
    print("%d/%d 通过" % (len(ts) - len(bad), len(ts)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
