#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""exhaust-before-giveup-gate —— 事实闸：我说「缺了 X 所以没法做/没法实测」，本轮却【一次安装/下载/编译都没试】→ 拦。

⛔ 起因（2026-10-06，Frank 原话）：
   我补查 SpineViewer 时写下「这台机器没有 WSL 也没装 .NET，所以我没法实测」就收了手。
   Frank：「每次你说你做不到要自己先问自己穷尽了吗？是不是你能力之内的，如果对我电脑没什么很大副作用的
   直接执行，完全不用问，铁律」。事实：便携 .NET 8 + 从源码编译，10 分钟装好并实测通过。
   TruthGate 当时没拦——查实原因：①语义服务 17911 按 Frank 9/25 下线令关着，所有语义闸 fail-open；
   ②这一句是第四种形状：【我确实查过(没装)，但没有走「那就装」这一步】，R1(没证据就说没有)/R10(拿能力边界当借口)
   /能力边界闸(只有你能做、我够不到)都不管它。

⛔ 为什么走「词 + 事实」而不是语义：
   语义服务是 Frank 下线的，不能指望它；纯词表又会误伤(PLAN 里写过:看措辞的闸被撤是对的)。
   所以这里**两个条件同时成立才拦**，任一不成立放行：
     ① 说话条件：本轮文字里有一句，同时含【缺失词】+【可装的东西】+【做不了词】
     ② 事实条件：本轮所有 Bash/PowerShell 命令里，没有任何 安装/下载/编译/克隆 动作
   事实条件才是主角：只要我真去装了(哪怕装失败)，就放行 —— 这条闸要的是「先装再说」，不是「别说话」。

放行(真边界/非本意)：
   · 同一句里含真边界词：显存/显卡/管理员权限/验证码/滑块/付费/额度/版权/不可逆/只有你能/登录态/红线……
   · 引述/复盘：「」『』“”`` 里的话先剥掉再判(复盘时必然要把错话原样写出来)
   · 本轮已有安装类命令(见上)

安全：fail-open；同轮只拦一次(self_blocked_this_turn)；只读 transcript，不碰任何文件。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from guard_common import hook_log, self_blocked_this_turn, turn_start_index, trig
except Exception:                # 共用层坏了 → 显式桩 + 放行(与全仓一致)
    def hook_log(*a, **k):
        pass

    def self_blocked_this_turn(*a, **k):
        return False

    def turn_start_index(msgs):
        return -1

    def trig(s, n=120):
        return str(s).replace(chr(10), ' ')[:n]

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SELF = "exhaust-before-giveup"

MISSING = re.compile(r"(没有安装|没有装|没装|没安装|未安装|未装|没配|缺少|缺了|缺失|不存在|没有)")
# ⛔ 只收【具体可装的东西】。首版带了「库/包/工具/软件/环境/扩展」这类泛词，留出集扫描(14 个真实会话)当场抓到误伤：
#   「没有逐个打开仓库验证功能，也没法排除刷星」(仓库的「库」)、「…模型能力数据库…里没有，不能用」(数据库的「库」)。
#   宁可少拦也不乱拦(PLAN 里「看措辞的闸被撤」就是被误伤逼的)。
DEP = re.compile(r"(WSL|\.NET|dotnet|Node(\.js)?|npm|Python|pip|ffmpeg|Docker|Java|JDK|Git(?!Hub)|运行时|运行库|发行版|"
                 r"编译器|SDK|驱动程序|命令行工具|依赖)", re.I)
CANT = re.compile(r"(没法|无法|没办法|做不了|测不了|跑不了|验证不了|试不了|编译不了|装不了|不能|没能|放弃)")
# 真边界词：同一句里出现就放行
REAL_LIMIT = re.compile(r"(显存|显卡|GPU|内存不足|空间不足|管理员|验证码|滑块|人机|扫码|登录态|红线|付费|额度|版权|"
                        r"许可证|授权|不可逆|只有你能|你本人|物理|没有权限|无权限)")
# 引述/代码：先剥掉
QUOTED = re.compile(r"(「[^」]*」|『[^』]*』|“[^”]*”|\"[^\"]{0,80}\"|`[^`]*`)")
# 本轮出现任一类动作 = 真去试过
INSTALL = re.compile(
    r"(pip3?\s+install|-m\s+pip\s+install|npm\s+(i|install|add)\b|bun\s+(add|install|x)\b|yarn\s+add|pnpm\s+(add|i)\b|"
    r"dotnet-install|dotnet\s+(tool\s+install|publish|build)|winget\s+install|choco\s+install|scoop\s+install|"
    r"cargo\s+install|go\s+install|conda\s+install|apt(-get)?\s+install|git\s+clone|Invoke-WebRequest|\biwr\b|"
    r"curl\b[^|;&]*(\s-o\b|\s-O\b|--output)|Expand-Archive|\bunzip\b|make\s+install|cmake\b|msbuild|"
    r"gh\s+release\s+download|wget\b)", re.I)

# ── 第二种形状（2026-10-07）：「我的工具够不到那个弹窗」──
# 实录：Comfy Cloud 用 Google 登录会弹选账号窗口。我只用 opencli 点了一次、会话里没看到弹窗，就写「这个弹窗我的工具够不到」
# 让 Frank 自己去点；他连问两次。后来 `opencli --profile <已连接的> browser B bind` 一条命令就接到了弹窗，登录走通。
REACH = re.compile(r"(够不到|点不到|摸不到|看不到(这个|那个|它的)?(弹窗|小窗口|窗口|标签页?)|操作不了(这个|那个)?(弹窗|小窗口|窗口|标签页?))")
REACH_OBJ = re.compile(r"(弹窗|窗口|标签页?|页面|按钮|浏览器|工具)")
# 在回头说这件事（复盘、认错、解释原因）不算
REACH_RETRO = re.compile(r"(之前|上一轮|上一条|上次|刚才|当时|第一次|说过|是我的问题|不是工具的问题|其实|实录|由来|不等于)")
# 本轮出现任一种 = 换过能看到别的窗口的办法
REACH_TRIED = re.compile(r"(\bbind\b|--profile\b|expect_page|expect_popup|localhost:3456|/targets\b|connect_over_cdp|connectOverCDP|"
                         r"launch_persistent_context|chromium\.launch|shot-window\.ps1)", re.I)


def find_reach_excuse(said):
    """返回「工具够不到某个窗口」的那一句，没有则 None。"""
    stripped = QUOTED.sub("", said)
    for s in re.split(r"[\n。!?！？;；]+", stripped):
        s = s.strip()
        if len(s) < 8:
            continue
        if REACH.search(s) and REACH_OBJ.search(s) and not REAL_LIMIT.search(s) and not REACH_RETRO.search(s):
            return s
    return None


def _turn(msgs):
    start = turn_start_index(msgs)
    return msgs[start:] if start >= 0 else msgs[-30:]


def _said_and_cmds(turn):
    texts, cmds = [], []
    for m in turn:
        if m.get("type") != "assistant":
            continue
        c = (m.get("message") or {}).get("content")
        if isinstance(c, str):
            texts.append(c)
            continue
        for it in c or []:
            if not isinstance(it, dict):
                continue
            if it.get("type") == "text":
                texts.append(it.get("text") or "")
            elif it.get("type") == "tool_use" and it.get("name") in ("Bash", "PowerShell"):
                cmds.append(str((it.get("input") or {}).get("command") or ""))
    return "\n".join(texts), "\n".join(cmds)


def find_excuse(said):
    """返回命中的那一句，没有则 None。"""
    stripped = QUOTED.sub("", said)
    for s in re.split(r"[\n。!?！？;；]+", stripped):
        s = s.strip()
        if len(s) < 8:
            continue
        if MISSING.search(s) and DEP.search(s) and CANT.search(s) and not REAL_LIMIT.search(s):
            return s
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if self_blocked_this_turn(SELF):
        return
    tp = data.get("transcript_path")
    if not tp or not os.path.exists(tp):
        return
    try:
        from guard_common import load_transcript_tail
        msgs = load_transcript_tail(tp)
    except Exception:
        return
    said, cmds = _said_and_cmds(_turn(msgs))
    if not said.strip():
        return
    reach = find_reach_excuse(said)
    if reach is not None and not REACH_TRIED.search(cmds):
        self_blocked_this_turn(SELF, mark=True)
        hook_log(SELF, "BLOCK(said tool cannot reach a window, no second way tried)", trig(reach, 140))
        print(json.dumps({"decision": "block", "reason": (
            "⛔ 一个工具看不到，不等于够不到（Frank 2026-10-07：「你真的够不到？那以前让你自动化浏览器帮我点击登入是怎么做的」）。\n"
            f"   命中的那句：{trig(reach, 120)}\n"
            "   本轮没有出现任何一种「换个能看到别的窗口的办法」的命令。\n"
            "⇒ 照 ~/.claude/browser-routing.md 开头那张分层表往下走，至少把这一条做了再说话：\n"
            "   `opencli profile list` 看哪个配置是 connected → `opencli --profile <那个> browser <新会话> bind` 把当前前台标签（弹窗）接过来。\n"
            "   还不行：我自己的浏览器（Playwright `context.expect_page()`）、web-access（`/targets` 列全部窗口）。\n"
            "⇒ 都走完仍不行，才写做不到，并写清每一层试了什么、卡在哪。真边界照说：要他本人的密码 / 短信验证码 / 扫码。"
        )}, ensure_ascii=False))
        return
    hit = find_excuse(said)
    if hit is None:
        hook_log(SELF, "pass(no missing-dependency excuse)")
        return
    if INSTALL.search(cmds):
        hook_log(SELF, "pass(excuse present but install attempted this turn)", trig(hit, 100))
        return
    self_blocked_this_turn(SELF, mark=True)
    hook_log(SELF, "BLOCK(gave up on missing dependency, no install attempted)", trig(hit, 140))
    print(json.dumps({"decision": "block", "reason": (
        "⛔ 缺依赖不是做不到（Frank 2026-10-06 铁律）：你这轮说了「缺了某个东西所以没法做/没法实测」，"
        "但**本轮一条安装、下载、编译、克隆的命令都没跑过**。\n"
        f"   命中的那句：{trig(hit, 120)}\n"
        "⛔ 实录：我写「没有 WSL 也没装 .NET，所以没法实测」就收手；便携 .NET 8 + 从源码编译，10 分钟装好、实测通过。\n"
        "⇒ 说「没法」之前，三问先各答一遍（答得出具体证据才算）：\n"
        "   ① 这东西能不能自己装？(pip / npm / bun / 便携 zip / dotnet-install / winget / 从源码编译 / gh release 下载)\n"
        "   ② 装进项目文件夹或用户目录，对他的电脑有没有很大副作用？(没有 ⇒ 直接装，不问、不报「没法」)\n"
        "   ③ 我真的试过装了吗？还是只是看到缺就停手？\n"
        "⇒ 能装就现在装、现在测，再汇报。装过仍失败才能说做不到，而且必须写清：装了什么、卡在哪一步、报什么错。\n"
        "⇒ 真边界照说：显存/硬件不够、需要管理员权限、验证码/滑块/扫码、付费、版权/许可、不可逆操作。"
    )}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            hook_log(SELF, "error(fail-open):%s" % str(e)[:100])
        except Exception:
            pass
        sys.exit(0)
