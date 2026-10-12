#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop：别拿玩具测试糊弄（2026-09-25 立；2026-09-27 PLAN.md 第 3 步改成只看动作记录）。

只看本轮做了什么（判据在 ~/.truthgate/delivery_check.py，AG 桥接用同一份）：
  · 改了网页文件 ⇒ 最后一次改完之后要真浏览器跑一遍、并监听控制台报错（pageerror / console.error）
  · 改了接口代码（文件里写着路由）⇒ 最后一次改完之后要真发一次请求 —— 这项是新规矩，先只记账一周
  「截图并打开看」归 visual-proof-gate 管；两道一起就是 REQUIREMENTS 第 3 条「用户会走的路自己先走一遍」。
原来还按措辞拦（回复里有「页面…正常」「控制台…零报错」就拦），在解释 / 举例里误拦过（考卷 c043、c044）⇒ 去掉；
说网页好了却拿不出证据，归证据表（evidence-table-gate）管。用户这轮说了不用测 ⇒ 放行。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser('~/.truthgate'))
try:
    from guard_common import hook_log
    from delivery_check import stop_main
except Exception:          # 判据文件坏了 ⇒ 放行（fail-open）
    sys.exit(0)

if __name__ == '__main__':
    try:
        sys.exit(stop_main('anti-toy-test-gate', {'browser', 'console', 'request'}, hook_log))
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
