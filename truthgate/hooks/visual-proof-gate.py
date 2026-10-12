#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop：眼见为实（2026-08-12 立；2026-09-27 PLAN.md 第 3 步改成只看动作记录）。

只看本轮做了什么（判据在 ~/.truthgate/delivery_check.py，AG 桥接用同一份）：
  改了网页文件 ⇒ 最后一次改完之后要截图并打开看过（Read 那张图；浏览器工具自己截图给到眼前的也算）。
  真浏览器跑、听控制台报错归 anti-toy-test-gate 管。

⛔ 来历：2026-08-12 我拿 `/json/version` 的 HTTP 200 连报「Chrome-9226 健康、抓取管道正常」，那浏览器里 YouTube 未登录、
   推荐流全空，空转 6 小时；2026-09-08 改完 app.js / index.html 说「installment 全改好了」，Frank：「你每次交付有没有自己看」
   —— 那一轮改之前跑过截图脚本，旧版本闸看到「本轮有过 screenshot」就放了，所以现在只认「最后一次改完之后」。
原来还按措辞拦（「正常 / 健康」挨着「页面 / 浏览器」），在解释 / 举例里误拦过（考卷 c041、c045）⇒ 去掉；
「说有画面的东西好了、却没看过」这类结论归证据表（evidence-table-gate）管，来源要有浏览器或截图。
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
        sys.exit(stop_main('visual-proof-gate', {'shot'}, hook_log))
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
