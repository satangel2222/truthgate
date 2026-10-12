#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台任务「还在跑」闸 —— 我说后台任务/子代理还在跑,但本会话没有任何一个真的在动 ⇒ 拦。

⛔ 起因(2026-09-11,airbnb ai manager,Frank 原话):「外审是坏了还是你欺骗我说他在跑?跑了那么久没反应」。
   实录:我派了一个后台外审子代理,之后**两次**对他说「外审还在跑」,一次都没核查。第一手真相:
   它的 `subagents/agent-<id>.meta.json` 写着 `"stoppedByUser": true`,转写最后一行是
   `[Request interrupted by user for tool use]`(09:56:36)—— 他打断我的工具调用时它一起停了,36 分钟前就停了。
⛔ 更糟:`commitment-execution-gate.py` 把「还在跑」写成了**豁免词** ⇒ 说"还在跑"是一张免检通行证。

⛔⛔ 判据的第一版是错的,记在这里别再犯(同一轮,我自己用第一手证据推翻的):
   我先拿 `%TEMP%/.../tasks/<id>.output` 的大小/修改时间当"在不在跑"——**子代理跑着的时候它也一直是 0 字节**
   (实测:活着的那个 0 字节、转写 841KB 且 24 秒前刚写;正常跑完的那个也是 0 字节)。
   ⇒ 那个文件对子代理毫无信号,第一版会把**真在跑的**也拦掉;而它的 10 条自检全绿,因为样本是按我的错前提造的。
   真信号只有两个:①meta.json 的 `stoppedByUser` ②子代理自己的转写 `subagents/agent-<id>.jsonl` 的修改时间。
   后台 Bash 任务没有转写,它的 `.output` 是边跑边写的,那个仍然算数。

判据:最后一条回复宣称有后台任务在跑,且本会话 3 小时内建的任务里【没有一个】在 STALE_MIN 分钟内写过东西
     (或被标了 stoppedByUser)⇒ 拦,把每个任务"几分钟没动 / 被中断"摆出来。
ponytail: 有一个活的就放行 —— 分不出我说的是哪一个;若活的是别的任务、我说的那个已死,会漏拦。要更准就得解析我那句话在指谁。
豁免:引用/复盘/实录语境里复述那句话(我在检讨,不是在宣称)。
"""
import glob
import json
import os
import re
import sys
import tempfile
import time

STALE_MIN = 10
RECENT_H = 3
CLAIM = re.compile(r"(还|仍|正)在(后台)?(跑|运行|执行|审)|在后台(跑|运行)|still\s+running|is\s+running\s+in\s+the\s+background", re.I)
QUOTING = re.compile(r"(引用|复盘|实录|原话|复述|我(之前|刚才|两次)说)")
# ⛔ 2026-09-15 误伤根治(本会话连响 5 次):触发句是「这轮我一个字都没说有后台任务在跑」——
#    一句【否定】(我明说没在跑)+【在谈这道闸本身】,却因含「还在跑」被判成宣称。
#    QUOTING 没收否定句、也没收「讨论闸/误报」的元语境。加两类豁免;真阳性(外审还在跑/子代理正在后台运行)不受影响。
# 否定:没(说|有)…(在)?(跑|运行)、不(在|再)…(跑|运行)、没(在|有在)…(跑|动)、(跑|运行|执行)完(了|毕)、已(结束|停|退)。
NEGATED = re.compile(r"没(说|有|在|再)?[^。]{0,10}(在)?(跑|运行|执行|动)|不(在|再)[^。]{0,6}(跑|运行)|"
                     r"(跑|运行|执行)完(了|毕|成)|已(经)?(结束|停|退出|跑完|做完)|"
                     r"(no|not|zero|never)\s+[^.]{0,20}running|一个(都|也)没", re.I)
# 元语境:我在讨论这道闸/误报本身,不是在宣称有任务在跑(闸名多在「」里、或提到 误报/superego/台账)。
META = re.compile(r"「[^」]*(在跑|在运行|后台任务)[^」]*」|(误报|后台任务闸|这道闸|那道闸|这几道闸|superego|台账|误伤)", re.I)


def session_dirs(transcript_path):
    """transcript = ~/.claude/projects/<slug>/<sid>.jsonl
       ⇒ 子代理 = ~/.claude/projects/<slug>/<sid>/subagents ;后台 Bash = %TEMP%/claude/<slug>/<sid>/tasks"""
    if not transcript_path:
        return None, None
    slug = os.path.basename(os.path.dirname(transcript_path))
    sid = os.path.splitext(os.path.basename(transcript_path))[0]
    return (os.path.join(os.path.dirname(transcript_path), sid, "subagents"),
            os.path.join(tempfile.gettempdir(), "claude", slug, sid, "tasks"))


def activity(sub_dir, tasks_dir, now=None):
    """返回 [(名字, 类型, 几分钟没写, 是否被用户停掉)],只含 RECENT_H 小时内建的任务。"""
    now = now or time.time()
    out, agent_ids = [], set()
    for meta in glob.glob(os.path.join(sub_dir or "", "agent-*.meta.json")):
        aid = os.path.basename(meta)[len("agent-"):-len(".meta.json")]
        agent_ids.add(aid)
        if now - os.path.getmtime(meta) > RECENT_H * 3600 and not os.path.exists(os.path.join(sub_dir, "agent-%s.jsonl" % aid)):
            continue
        try:
            m = json.load(open(meta, encoding="utf-8"))
        except Exception:
            m = {}
        jl = os.path.join(sub_dir, "agent-%s.jsonl" % aid)
        last = os.path.getmtime(jl) if os.path.exists(jl) else os.path.getmtime(meta)
        if now - last > RECENT_H * 3600:
            continue
        out.append((m.get("description") or aid, "子代理", int((now - last) / 60), bool(m.get("stoppedByUser"))))
    for p in glob.glob(os.path.join(tasks_dir or "", "*.output")):
        tid = os.path.basename(p)[:-len(".output")]
        if tid in agent_ids:                       # 子代理的 .output 恒为 0 字节、不是信号(见文件头)
            continue
        idle = (now - os.path.getmtime(p)) / 60
        if idle > RECENT_H * 60:
            continue
        out.append((tid, "后台命令", int(idle), False))
    return out


def nothing_alive(acts, stale_min=STALE_MIN):
    """有任务、且没有一个在 stale_min 分钟内写过(或全被用户停了)⇒ True。没有任务 ⇒ 也 True(说在跑是无中生有)。"""
    return not any(idle <= stale_min and not stopped for _, _, idle, stopped in acts)


def claims_running(text):
    """模块级真函数(测试直接调)。逐句判:引用/复盘语境里的那句不算宣称。"""
    for sent in re.split(r"[。\n!?！？]", text or ""):
        if CLAIM.search(sent) and not QUOTING.search(sent) and not NEGATED.search(sent) and not META.search(sent):
            return True
    return False


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return
    try:
        from guard_common import turn_budget_ok as _tbo
        tp = data.get("transcript_path")
        if tp and not _tbo(tp):
            return
    except Exception:
        pass
    if not claims_running(data.get("last_assistant_message") or ""):
        return
    acts = activity(*session_dirs(data.get("transcript_path")))
    if not nothing_alive(acts):
        return
    try:
        from guard_common import hook_log
        hook_log("bg-running-claim-gate", "BLOCK 说在跑但没有一个在动",
                 "; ".join("%s %dmin%s" % (n[:20], i, " stopped" if s else "") for n, _, i, s in acts))
    except Exception:
        pass
    print("⛔ 后台任务闸:你说有后台任务还在跑,但本会话没有一个真的在动:", file=sys.stderr)
    if not acts:
        print("   · (近 %d 小时一个后台任务都没有)" % RECENT_H, file=sys.stderr)
    for name, kind, idle, stopped in acts[:6]:
        print("   · [%s] %s —— %s" % (kind, name[:40], "被用户打断时一起停了" if stopped else "%d 分钟没写过" % idle),
              file=sys.stderr)
    print("  ⇒ 先核真相再说话:子代理看 subagents/agent-<id>.jsonl 的修改时间 + meta.json 的 stoppedByUser;\n"
          "    停了就明说,并重派或换路。\n"
          "  ⛔ 2026-09-11 Frank:「外审是坏了还是你欺骗我说他在跑?」—— 它 36 分钟前就被中断了。", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
