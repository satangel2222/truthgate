#!/usr/bin/env python3
r"""Stop 闸:每轮收尾【回头看】—— 我这一轮让机器多烧了多少?烧得凶就拦一次,逼我处理。

⛔ 2026-08-14 起因(Frank 亲口点名这个洞):
   「每次凡是你动用了本地资源后,你没有回头看有没有导致卡顿,有没有回头看?
     还没做之前,凡是有用到本地所有资源跑的任务,前面要提醒,后面要观察之后才放行,你做了吗?」
   答案是**没有**。那天我起了 102 个子进程连打常驻语义服务,它 OOM 降级后
   【占着 5G 显存 + 拿 CPU 烧 11 个核】,**是 Frank 先感觉到卡、来问我,我才去查的**。
   他当了我的监视器 —— 这正是整个 Superego 存在的理由:他不该当我的 QA。

⛔ 为什么现有两道闸都没接住(这是本闸的设计依据,别再重复它们的假设):
   ① `launch-bound-guard.py`(PreToolUse·前置):要【四条全中】才拦,其中一条是
      "脚本里含 torch/cuda/SentenceTransformer 等重活信号"。而当天那个跑分脚本里
      **一个都没有** —— 它只是个 subprocess 循环。**闸对「重活」的定义只认【单个进程的体量】,
      认不出【扇出放大】**:102 次 subprocess,每次都触发一次模型推理,危害在倍数不在体量。
   ② `gpu-turn-end-watchdog.cjs`(Stop·后置):只看 GPU util。它自己的注释写着
      "CPU-fallback 型孤儿已被代码层每个 spawn 的 timeout+SIGKILL 兜住,不靠本 hook" ——
      **那个假设当天被证伪**:元凶是【GPU util 只有 13%、却拿 CPU 烧 11 核】的常驻服务,
      既没有 spawn 超时兜着,也不被 GPU 闸看见。**它精准落在两道防御中间的缝里。**

⇒ 本闸的设计原则:**前置靠模式匹配总会漏(重活的形态无穷),后置直接量结果就不会漏。**
   不猜命令、不认脚本名、不预判形态 —— 只在收尾问一句「刚才这段时间,我名下的进程烧了几个核」。

⛔ 先查现成(2026-08-14,按 CLAUDE.md 铁律执行后才动手):
   · Watchdog Process Manager(skill)= 监管【你打算长期跑的服务】(重启策略/限额),不是"这轮把机器弄热了没"
   · Claude-Code-Usage-Monitor(GitHub)= token/额度用量,与机器 CPU 无关
   · CPU Usage Monitor(skill)= **给我主动去调的工具,不是自动开火的闸** —— 而"我不会去调它"正是病根
     (和 memsearch 同一个形状:工具再好,靠我想起来用 = 等于没有)
   · gh search 只找到 2 个泛化 hook 合集,无同类
   ⇒ **判定:只能自建**,零依赖薄壳。

成本(每轮都跑,必须便宜):**零额外等待**。
   办法 = 把上一轮的 CPU 累计快照存盘,这一轮采一次、做差、除以两轮之间的墙钟。
   这样得到的正是【我这一轮期间的真实平均占用】,不需要 sleep 采两次。一次进程枚举 ~150ms。

归属(只算我的,绝不把 Frank 自己的活算我头上):命令行指向 `.claude` / 本项目目录 / scratchpad 的才算。
安全:fail-open(任何异常一律放行)、同一轮只拦一次、5 分钟内不重复 nag、stop_hook_active 直接放行。
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import guard_common as _gc          # noqa: F401 —— 只为接进「闸的分母」统计(hook-stats.jsonl)
except Exception:
    pass                                # 统计是附加品,拿不到也不影响这道闸

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, ".resource-echo.json")
STAMP = os.path.join(HERE, ".resource-echo-lastblock")

# ⛔ 阈值按【核数】定,不按百分比拍脑袋 —— 24 核机上 300% 只占 12.5%,是明显但不致命的水位;
#   当天真正伤到他的是 1099%(11 核 / 46%)。设 300% 能在"他还没感觉到"之前就叫住我。
BUSY_PCT = 300.0
MIN_SEC = 20.0          # 两轮间隔太短(<20s)时算出来的瞬时值噪音大,跳过
NAG_COOLDOWN = 300      # 秒


def _sample():
    """全机进程 pid -> {p,c,m,n}:一次系统调用(NtQuerySystemInformation)拿 CPU 秒数 / 内存 / 名字,约 0.02 秒。
    命令行不在这里拿 —— 只有烧 CPU 超标的那一两个进程才需要,见 _cmdline。
    2026-10-03:原来每次收尾都开 PowerShell + 用 WMI 把全机每个进程的命令行查一遍(_sample_ps),空闲 3.6 秒、
    机器忙时 10 秒以上 ⇒ AG 端 4.5 秒时限里它是超时第一名(ag-gate-timeouts.log 7,061 行里 866 行),等于从没跑完过;
    而且 WMI 查询本身就在烧 CPU(WmiPrvSE 开机以来累计约 53 个 CPU 小时,全机前列)。
    读数核对过:361 个进程新旧两种做法逐个比,差的中位数 0;烧 1 秒 CPU 读数涨 1.01 秒。"""
    try:
        import ctypes
        import struct
        import psutil  # noqa: F401 —— _cmdline 要用;没装就整个走老路(慢,但自带命令行)
        if struct.calcsize("P") != 8:
            raise OSError("下面的偏移量是 64 位布局")
        size = ctypes.c_ulong(1 << 20)
        while True:
            buf = ctypes.create_string_buffer(size.value)
            st = ctypes.WinDLL("ntdll").NtQuerySystemInformation(5, buf, size, ctypes.byref(size)) & 0xFFFFFFFF
            if st == 0:
                break
            if st != 0xC0000004:                       # 只有「缓冲区太小」才重试
                raise OSError(hex(st))
            size.value += 1 << 16
        out, off = {}, 0
        while True:                                    # SYSTEM_PROCESS_INFORMATION 链表
            nxt, = struct.unpack_from("<L", buf, off)
            user, kern = struct.unpack_from("<qq", buf, off + 40)      # 单位 100 纳秒
            nlen, = struct.unpack_from("<H", buf, off + 56)
            nptr, pid = struct.unpack_from("<Q", buf, off + 64)[0], struct.unpack_from("<Q", buf, off + 80)[0]
            ws, = struct.unpack_from("<Q", buf, off + 144)
            c = (user + kern) / 1e7
            if pid and c > 0:
                name = ctypes.wstring_at(nptr, nlen // 2) if nptr else ""
                out[pid] = {"p": pid, "c": round(c, 2), "m": round(ws / 1048576),
                            "n": name[:-4] if name.lower().endswith(".exe") else name}
            if not nxt:
                return out
            off += nxt
    except Exception:
        return _sample_ps()


def _cmdline(v):
    """超标的进程才查命令行(归属判定必须靠它);_sample_ps 那条老路已经带着了。"""
    if "l" not in v:
        try:
            import psutil
            v["l"] = " ".join(psutil.Process(int(v["p"])).cmdline())
        except Exception:
            v["l"] = ""                                # 查不了(已退出 / 系统进程)⇒ 不算我的,宁可漏报
    return v["l"]


def _sample_ps():
    """老路(兜底):一次进程枚举 pid -> {p,c,m,n,l}. 用 CIM 拿 CommandLine。"""
    ps = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$c=@{}; Get-CimInstance Win32_Process | %{ $c[[int]$_.ProcessId]=$_.CommandLine };"
        "Get-Process | ? { $_.CPU -gt 0 } | % { [pscustomobject]@{"
        "  p=$_.Id; c=[math]::Round($_.CPU,2); m=[math]::Round($_.WS/1MB);"
        "  n=$_.Name; l=$c[[int]$_.Id] } } | ConvertTo-Json -Compress"
    )
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=25)
    rows = json.loads((r.stdout or "").strip() or "[]")
    if isinstance(rows, dict):
        rows = [rows]
    return {int(x["p"]): x for x in rows if x.get("p") is not None}


def _mine(cmdline, proj):
    """归属:这个进程是不是【我这边】起的活?
    ⛔ 宁可漏报也别错报 —— 把 Frank 自己开的东西算到我头上,会让这道闸变成噪音,两周后被忽略。"""
    if not cmdline:
        return False
    low = cmdline.replace("/", "\\").lower()
    if "\\.claude\\" in low:
        return True
    if "\\temp\\claude\\" in low or "scratchpad" in low:
        return True
    if proj and proj.replace("/", "\\").lower() in low:
        return True
    return False


def main():
    data = json.loads(sys.stdin.read() or "{}")
    if data.get("stop_hook_active"):
        return
    proj = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ""

    now = time.time()
    # ⛔ 2026-09-05 快速放行: 距上轮<20s 直接放行, 不枚举全进程(省 3.65s PowerShell+WMI)。
    #   反正下面 dt<MIN_SEC 也会跳过判断 —— 枚举了也白枚举。收尾常一轮接一轮<20s, 这是最大浪费。
    prev = {}
    try:
        with open(SNAP, encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:
        prev = {}
    _pts = float(prev.get("ts") or 0)
    if _pts and (now - _pts) < MIN_SEC:
        return

    cur = _sample()

    # 先把这一轮的快照写下去(无论后面拦不拦)—— 少写一次,下一轮就没有基线可比
    try:
        with open(SNAP, "w", encoding="utf-8") as f:
            json.dump({"ts": now, "cpu": {str(p): v["c"] for p, v in cur.items()}}, f)
    except Exception:
        pass

    dt = now - float(prev.get("ts") or 0)
    if not prev or dt < MIN_SEC or dt > 7200:
        return                                    # 没基线 / 间隔太短或太久 → 这轮不判

    pcpu = prev.get("cpu") or {}
    hot = []
    for pid, v in cur.items():
        before = pcpu.get(str(pid))
        if before is None:
            continue                              # 本轮新起又已退出的进程抓不到,交给下一轮
        pct = (float(v["c"]) - float(before)) / dt * 100.0
        if pct >= BUSY_PCT and _mine(_cmdline(v), proj):
            hot.append((pct, v))
    if not hot:
        return

    try:
        if now - os.path.getmtime(STAMP) < NAG_COOLDOWN:
            return
    except Exception:
        pass
    try:
        open(STAMP, "w").write(str(now))
    except Exception:
        pass

    hot.sort(key=lambda x: -x[0])
    lines = "\n".join(
        "  · %-10s pid %-6s **%.1f 个核**  内存 %s MB\n    %s"
        % (v.get("n"), v.get("p"), pct / 100, v.get("m"), (v.get("l") or "")[:150])
        for pct, v in hot[:4])
    total = sum(p for p, _ in hot) / 100

    print(
        "⛔ 回头看闸(资源):这一轮跑完了,但**我名下的进程在刚过去的 %.0f 秒里烧了 %.1f 个核**：\n%s\n"
        "⇒ 现在就回头看,别等他来问：\n"
        "   ① 这是不是我这轮起的?(`Get-CimInstance Win32_Process -Filter \"ProcessId=<pid>\"` 看 CommandLine + CreationDate)\n"
        "   ② 它跑完还会不会自己停?有没有上界?会不会一直占着?——三个答得上就说明它,答不上就清掉。\n"
        "   ③ **只清我自己起的**;不是我起的一律不动、只报告(资源边界铁律⑤)。\n"
        "⛔ 2026-08-14 实录:我起了 102 个子进程连打常驻语义服务,它 OOM 降级后【占着 5G 显存 + 拿 CPU 烧 11 个核】,\n"
        "   **是 Frank 先感觉到卡、来问我「突然很卡,是不是你造成的」,我才去查的**。他当了我的监视器。\n"
        "   前置闸没拦是因为它只认【单个进程的体量】(torch/cuda 字样),认不出【扇出放大】;\n"
        "   GPU 闸没拦是因为那玩意 GPU util 只有 13%%、烧的是 CPU。**它精准落在两道防御中间的缝里。**\n"
        "⇒ 处理完(或确认它有界、马上会停)再收尾。%d 秒内不再重复本提示。"
        % (dt, total, lines, NAG_COOLDOWN))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass        # fail-open:绝不因为一道观测闸挡住正常收尾
