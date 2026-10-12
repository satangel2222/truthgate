# -*- coding: utf-8 -*-
"""出口探针 —— 跑一道闸,回答「它走了哪条出口」。

⛔ 为什么需要它(形状 2026-09-07-S,实测):
   闸是 fail-open(出错也返回 0、也不输出),于是
   「正确地早退」和「崩了之后被 except 吞掉」**从 stdout 看一模一样** ⇒
   故障注入怎么改都不红(实测 lesson-anchor 3 条、hook-noise 3 条、rule-dup 2 条)。
   ⇒ 每条出口留一条不同措辞的日志,测试断言"走了哪条",内部 bug 才现形。

用法:
    from exit_probe import run_gate, last_exit
    d = run_gate("rule-dup-guard.py", {"tool_input": {...}})
    assert "pass(不是规则源文件)" in last_exit(d, "rule-dup-guard")

⚠️ 它把日志写进一个【隔离目录】(SUPEREGO_LOG_DIR),不污染真实日志 ——
   否则测试写的行会混进记分板,真实误伤率就算不出来了(那个坑今天已经踩过)。
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def run_gate(gate_file, payload, env_extra=None, timeout=180):
    """跑一道闸,返回隔离的日志目录(给 last_exit 用)。"""
    d = tempfile.mkdtemp(prefix="exitprobe_")
    env = dict(os.environ, SUPEREGO_LOG_DIR=d)
    if env_extra:
        env.update(env_extra)
    subprocess.run([sys.executable, os.path.join(HERE, gate_file)],
                   input=json.dumps(payload, ensure_ascii=False),
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=timeout, cwd=HERE, env=env)
    return d


def last_exit(logdir, gate_name):
    """那道闸这次走的最后一条出口(日志最后一行)。读不到返回空串。"""
    for suffix in (".log", ".test.log"):
        p = os.path.join(logdir, gate_name + suffix)
        try:
            lines = [x for x in open(p, encoding="utf-8", errors="replace").read().splitlines()
                     if x.strip()]
            if lines:
                return lines[-1]
        except OSError:
            continue
    return ""


def hit_exit(logdir, gate_name, needle):
    """这一路【有没有经过】某条出口(查所有行,不只最后一行)。

    ⛔ 为什么和 last_exit 都要有(2026-09-07 实测):
       内层函数里的出口日志会被外层的盖在后面。工具门那条确实写了,
       但最后一行是「pass(本轮没有要拦的)」⇒ 只读最后一行就看不见它,
       我差点据此判"那条判据没生效"。
       ⇒ last_exit 答【最终走了哪条】;hit_exit 答【这一路经过没经过】。
    """
    for suffix in (".log", ".test.log"):
        p = os.path.join(logdir, gate_name + suffix)
        try:
            if needle in open(p, encoding="utf-8", errors="replace").read():
                return True
        except OSError:
            continue
    return False
