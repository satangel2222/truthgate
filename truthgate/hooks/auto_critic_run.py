#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""auto_critic 的后台跑器:真的去请异构裁判,把裁定写回文件。

    py -3.12 auto_critic_run.py <裁定文件路径> <超时秒>

⛔ 它为什么单独一个文件:Stop 闸只有 25 秒预算,而 second-opinion 约 40 秒。
   同步跑必被 harness 杀掉 ⇒ 静默失效(今晚刚量过:语义层 45.5% 静默失效就是这么来的)。
   ⇒ 本进程 detached 跑,闸那边下一轮再来收。

⛔ 无论成败都必须把 done 写回去 —— 否则闸永远等一个不会来的结果,
   那就是又一个"建了但没有后果"的纸老虎。
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SO = os.path.join(os.path.dirname(HERE), "superego-critic", "second-opinion.py")


def main():
    if len(sys.argv) < 2:
        return 1
    path = sys.argv[1]
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 180
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return 1

    out, err, rc = "", "", -1
    t0 = time.time()
    try:
        r = subprocess.run(
            [sys.executable, SO, "--claim", d.get("claim", ""), "--file", d.get("file", "")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=HERE,
            # 2026-09-11: we run DETACHED (no console) => without this the child python gets its own
            # VISIBLE console that steals focus (sentinel: 08:33/09:45/11:51 popups). 0x08000000 = CREATE_NO_WINDOW.
            creationflags=0x08000000 if os.name == "nt" else 0)
        out, err, rc = (r.stdout or ""), (r.stderr or ""), r.returncode
    except subprocess.TimeoutExpired:
        err = "TIMEOUT >%ds" % timeout
    except Exception as e:
        err = "RUNNER-ERROR %s" % str(e)[:120]

    # ⛔ 无论成败都写回 done —— 不写 = 闸永远在等,等于这条链不存在
    d["done"] = True
    d["rc"] = rc
    d["elapsed"] = round(time.time() - t0, 1)
    # 去掉那行"内容会离开本机"的警告,只留裁定本身
    d["answer"] = "\n".join(l for l in out.splitlines()
                            if "离开本机" not in l and "提醒:异模型" not in l).strip()
    d["err"] = err.strip()[:300]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(1)
