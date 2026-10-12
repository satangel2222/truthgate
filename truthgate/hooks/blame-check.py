#!/usr/bin/env python3
"""Stop hook: 拦截"外部甩锅"结论。

触发条件(全部满足才拦):本轮把某症状(慢/失败/超时/降级…)以**结论口吻**归因到
限流/风控/网络抖动/玄学/平台变卦这类外部原因,且整轮**没有任何第一手核实**
(截图/看原始响应/看状态码/干净重试)。—— 2026-07-11 gemini A/B 误判限流的教训固化。

安全设计:
- fail-open:任何解析异常一律放行,绝不因脚本自身出错拦住每一轮(不影响正常写代码)。
- 只拦一次:只拦一次:【我自己】拦过才不再拦(per-gate 标记,见 guard_common.self_blocked_this_turn);别的闸拦过不影响我,避免死循环。
- 只读:只读 transcript + 打印决策,从不碰代码/文件/git,对代码零风险。
- 需 blame + symptom + 结论词 三者同现才触发 → 纯讨论概念、或已用非截图方式核实过,均不拦。
每次运行留一行日志到 blame-check.log(可核验它真的在跑)。"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:            # ⛔ 必须带兜底:原来是裸 import —— guard_common 一坏,这道闸第一行就炸,
    from guard_common import hook_log, turn_start_index# 下面精心写的 fail-open 降级桩全成了到不了的死代码(外部critic抓到)
except Exception:
    def turn_start_index(msgs):          # guard_common 挂了时的保守桩:-1=整份算本轮,宁可少拦
        return -1
    def hook_log(*a, **k):
        pass
try:            # ⛔ 独立一条:2026-07-26 critic 实测,打包成 `import hook_log, trig` 时只要 trig 缺一个
    from guard_common import trig                # (比如 guard_common 回退到旧版),**完好的 hook_log 会被一起降级成哑巴、日志静默全灭**
except Exception:
    def trig(x, n=120):
        return "trig=?"
import sys
import json
import re
import os
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")   # Windows 下 stdout 默认 cp1252,中文/emoji 会崩
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from guard_common import (strip_doc, should_downgrade, should_escalate,
                              escalate_block)
except Exception:
    def strip_doc(t):
        return t or ""
    def should_downgrade(*a, **k):
        return False   # 语义层不可用就保持关键字原判(fail-safe,不漏拦)
    def should_escalate(*a, **k):
        return False   # 升级层不可用 → 不新增拦截(与 downgrade 方向相反,各自安全侧)
    def escalate_block(*a, **k):
        return False   # 同上:拿不到就当没这层,行为与接线前完全一致

# Superego Phase3 语义确认范例(2026-07-25):关键字命中后,和这两组比语义,明显更像 NEG 才把误拦降级放行。
# POS=真把症状甩锅给外部原因的结论(该拦);NEG=在讨论/描述/引用"甩锅拦截"这条规则本身(误伤,该放行)。
_BLAME_POS = [
    "接口失败了,八成是被限流了", "图没出来,估计是平台风控挡的", "同步挂掉应该是网络抖动导致的",
    "变慢是因为对方偷偷改了接口", "下载超时,多半是他们服务器不稳", "任务降级了,肯定是被 rate limit 了",
    "没反应大概率是 DNS 或网络问题", "跑不通,应该是平台升级把接口改了",
    # 2026-07-27 资源类(新):零测量就把故障判给机器,一句话终结调查
    "专用 Chrome 反复崩,这是硬件边界,8G 机器扛不住", "跑不动,机器配置太低",
    "任务失败多半是内存不够", "浏览器起不来是这台机器资源不够",
    # ⛔ 拿【规格数字】(机器有多少内存/几 G 显卡)当归因依据 —— 数字不等于量过。
    #   这几条是外部 critic 的对抗样本:上一轮我为了治误伤加 NEG 范例,把语义层拉偏,
    #   "8G 显存不够,跑不动" 被降级放行 = 治误伤顺手放松真拦截(本文件警告过 3 次的形状)。
    "生成一直失败,8G 显存不够,跑不动", "浏览器反复崩,这台机器只有 8GB 内存,跑不动",
    "任务全挂,机器 16GB 内存扛不住,硬件边界",
]
# ⛔ 2026-07-28 接【升级层】(should_escalate, escalate_block):关键字没命中时问语义要不要拦。
#   病根(2026-07-27 Frank「是不是死板地抓文字而不是语义?」):语义原本只能做减法(命中后降级),
#   关键字是唯一入口 ⇒ 词表没覆盖的说法 100% 漏拦,补一次逃一次,这是架构必然。
#   ⛔ 升级层的 NEG 不能复用降级层那组(那些全是"讨论规则"类)——升级层要判的是
#   【关键字没命中的普通文本】,所以 NEG 必须是**正常技术陈述**。用途不同,锚点也得分开。
_BLAME_ESC_POS = [
    "这次慢应该是对面服务不稳定吧", "估计是网络抖了一下,重跑就好",
    "平台那边最近是不是改了什么", "环境问题,跟我的代码没关系",
    "多半是他们那边的问题,我这边逻辑没动过", "可能是缓存没刷新导致的吧",
    "It's probably their API being flaky again.", "Likely a transient network issue on their side.",
]
_BLAME_ESC_NEG = [
    "我查了原始响应体,是我传的参数少了一个字段", "第一手日志显示我自己的正则写错了",
    "对方接口返回 500,我贴了原始响应并加了重试,已实测通过",
    "全量回归 44/44 通过,没有红的", "我改了三处判据,回归已重跑",
    "这个函数的输入是文件路径,输出是布尔值", "端到端实测:真错误 exit=2、正常文本 exit=0",
    # ⛔ 2026-07-28 接上升级层后,【既有回归】当场抓到两条误伤 —— 补的不是留出集里的失败样本
    #   (那是调参刷分),而是这两类**真实存在的正当模式**,升级层原来的 NEG 完全没覆盖:
    #   ① 自诊断 + 可修的本地原因(提到了外部词,但结论是"我改一下就行",不是推卸);
    "这个测试失败是因为本地网络环境没配好代理,我改一下配置就行,和代码逻辑无关",
    "接口连不上是我本地代理没开,开了就好了", "报错是我环境变量写错了,改完就通过",
    #   ② 真探测过之后的归因(有第一手,那是结论不是甩锅)。
    "我 import yt_dlp 实际探测过,确认本地没装这个包", "跑了 nvidia-smi 确认显存占满,才下的结论",
    "我实际连了一次那个端口,确认对面没监听",
]
_BLAME_NEG = [
    "这个闸拦截把失败归因到限流风控网络抖动的甩锅结论", "blame-check 抓的是限流风控网络抖动这类外部甩锅词",
    "我在描述甩锅结论拦截的触发条件和边界", "举个例子,像'八成是风控'这种措辞就属于甩锅",
    "归因前要先看第一手现场,别甩锅给限流或网络", "总册里这条铁律讲的是别把慢和失败甩锅给外部",
    "我已经截图看了原始响应,确认不是限流才下的结论", "这段是在解释关键字闸为什么会误伤自己",
    # 2026-07-27 资源类的合法说法:量过了、或在讨论这条规则、或在做资源封顶设计 —— 都不是甩锅
    "我跑了 nvidia-smi,显存 7.8/8.0G 已占满,确认是爆显存", "实测机器 63.8GB 内存、空闲 31GB,与硬件无关",
    "这条闸拦的是把崩溃甩锅给硬件不够的结论", "给自己封顶显存 fraction 0.72,别抢满拖卡他的桌面",
    # 2026-07-27 外部 critic 实测抓到的误伤:写复盘/交接文档/性能观测汇报,都必然出现这些词但都不是甩锅
    "我当时判'8G 机器扛不住',隔天一测真凶是自己代码里的 reaper",      # 复盘:引述旧错并给出真相
    "误判成内存不够、机器带不动,其实是被自己代码杀的",                # 交接文档:记录误判
    "训练 OOM 崩了,batch 从 32 降到 8,现在跑通了",                    # 自诊断+已修,不是推卸
    "生成很慢,chrome 进程 92 个、内存吃满、磁盘 IO 打满,先看是不是我自己造成的",  # 观测汇报
    "生成很慢,chrome 进程 92 个,内存吃满,磁盘 IO 打满",   # 纯观测罗列(没有"所以是机器不行"的判决)
    "当前负载:CPU 头名 camoufox 173%,内存堆积 chrome×92=11.5GB,磁盘 IO 311MB/s",
]

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blame-check.log")

# 2026-07-24 审计 finding#22:补日常最顺口的网络甩锅(只认"网络抖动"漏了"网络问题/不稳定/太差/丢包")
# 2026-07-25 审计误报修 + round2 外科回补:上一轮为治误报把整条「网络环境」分支删掉,顺手漏掉了真甩锅
#   「网络环境太差/不好/不稳定」(网络与质量词间插一个"环境"字就整条不命中)。改法=在网络与质量词之间允许
#   【可选中间词 环境/状况/状态】:于是「网络环境太差/网络环境不稳定」照拦;而「网络环境没配好代理,我改下配置
#   就行」因"没配好"不在质量词表(问题/不稳/不好/太差/波动/拥堵)→ 仍不命中 = 自诊断+可修的本地原因照放(原误报不回退)。
BLAME = re.compile(
    r"限流|限速|被限|风控|网络抖动|网络(?:环境|状况|状态)?(?:问题|不稳|不好|太差|波动|拥堵)|网速(慢|差|不好)|丢包|DNS"
    r"|玄学|平台变卦|平台变了|平台(改|调整|升级)了|对方(改|变)了|服务器(抽风|不稳)|rate.?limit|throttl", re.I)
# ⛔ 2026-07-27(GLM 代跑 all-for-one-image 那轮暴露的整类缺口):上面 BLAME 覆盖的全是【网络/平台/风控】,
#   漏掉了另一整类同样"三条全中"的甩锅——【机器/资源不行】。实录:专用 Chrome 起不来,结论"这是硬件边界
#   (8G GPU + 反节流参数烧 GPU)",整轮零测量就收工;隔天一测机器 63.8GB 内存、空闲 31GB,真凶是项目自己的
#   idle reaper 每 60s 杀浏览器 —— 一整晚白干。"硬件不行"比"限流"更毒:限流会恢复,硬件是【永久判决】,
#   一句话终结整条调查线。这些短语【本身就是结论】(不像"限流"还要配"八成是"),所以不要求 CONCLUDE 紧贴,
#   但仍要求 SYMPTOM 在窗口内 + 没有第一手测量(OBSERVED)。
BLAME_HW = re.compile(
    r"硬件(边界|限制|瓶颈|不行|不够)|机器(不行|扛不住|带不动|太老|配置低|配置太低)"
    r"|(内存|显存|GPU|CPU|显卡|磁盘|资源)\s*(不够|不足|太小|吃满|跑满|扛不住|瓶颈)"
    r"|爆(显存|内存)|OOM|带不动|跑不动|机器(性能|配置)(不行|不够|太低)", re.I)
# ⛔ 2026-08-11(第7次拿同一块盘下错结论那轮)缺口:上面 BLAME_HW 只覆盖【容量不够】那一家
#   (不够/不行/瓶颈/边界),完全接不住更毒的【硬件坏了】那一家。实录原文
#   「是你的 C 盘硬件正在死亡…唯一根治=换掉 C 盘」——一个词都没命中,exit=0 静默放行。
#   而且当轮我跑过 Get-CimInstance/Get-Counter ⇒ 就算命中也会被 OBSERVED_TOOL 免死:
#   **"量过了"根本不等于"量对了"** —— 我量的是 `Avg. Disk sec/Read`(零 I/O 时被极少数
#   坏扇区重试拉爆均值的骗人指标),真读文件是 933~1068MB/s,盘比 E 盘还快。
#   真凶是【多实例抢端口】(9222 被两个 Chrome 分走 IPv4/IPv6 → 客户端 404;僵尸占 7911 → 10048)。
#   ⇒ 故本族【不吃 OBSERVED/OBSERVED_TOOL 那套通用免死】,只认两种真能证伪它的第一手证据:
#      ①端口/实例清点(netstat 等) ②真读文件的吞吐基准。见 _hw_fail_exempt()。
BLAME_HW_FAIL = re.compile(
    r"(硬盘|磁盘|盘|SSD|NVMe|固态|硬件|内存条|主板|显卡)\s*(坏|损坏|故障|失效|报废|挂了|快挂|濒死|"
    r"正在死|快死|要死|寿命(到|尽|完)|物理损坏|不行了)"
    r"|换(盘|硬盘|磁盘|SSD|机器|主板|显卡|内存)|(盘|硬盘|磁盘|SSD)\s*该换|坏道|坏块|bad\s*block", re.I)
# 只有这两类证据能真正证伪"硬件坏了":端口/实例清点(抓多实例冲突) + 真读文件基准(抓假指标)。
HW_FAIL_EXEMPT = re.compile(
    r"netstat|Get-NetTCPConnection|lsof|ss -|端口(清点|占用|冲突)|LISTENING"
    r"|ReadAllBytes|MB/s|吞吐|真读文件|dd if=|fio\b|CrystalDiskMark|Measure-Command.{0,40}Read", re.I)
# ⛔ 2026-08-26 新增:**唯一能证伪「这块盘坏了」的尺子是盘【自己】的累计计数**,不是事件日志条数。
#   实测对照:Windows 事件日志 8 分钟报 46,404 条 `has a bad block`,而同一时刻盘的
#   `Media and Data Integrity Errors` 13 天只涨 35 个(36,199→36,234)、`Critical Warning: 0x00`、
#   `Available Spare 99%`、`Percentage Used 15%`、`Error Information Log Entries: 0`。
#   他机器档案里也早有定论:「NVMe 上 Event ID 7 不代表物理坏块」(08-03~08-07 已纠正,我又犯了两次)。
#   ⇒ 要断言磁盘硬件坏,本轮必须真跑过下面任一样东西;跑 Get-CimInstance 查内存不算数。
DISK_PROBE = re.compile(
    r"smartctl|DiskInfo64|CrystalDiskInfo|Get-StorageReliabilityCounter|Get-PhysicalDisk"
    r"|Media and Data Integrity|Available Spare|Critical Warning|Percentage Used"
    r"|Data Units (Read|Written)|nvme (smart-log|error-log)|Reallocated_Sector", re.I)
# regex-sanity: ok — 2026-07-29 实测:贴测试结果放行(需 SYMPTOM+CONCLUDE 邻近共现)
SYMPTOM = re.compile(r"慢|失败|超时|挂了|挂掉|报错|降级|缩水|卡住|卡顿|不出图|没出图|没反应"
                     r"|崩了|崩溃|反复崩|秒退|起不来|连不上|跑不起来"
                     # 2026-07-27 critic 对抗样本 B3("任务全挂…16GB 内存扛不住")实测漏拦:
                     # 原只有"挂了|挂掉",接不住"全挂/挂死";症状词表缺一个,整条甩锅就免检。
                     r"|全挂|挂死|出不来|没出来|跑不完|用不了|不工作"
                     # 2026-08-11 又一次"词表缺一个整条免检"(同 07-27 那条实录):本次真实错误原文
                     # 「自动化 Chrome 全部 Not Responding、卡死」—— 有"卡住|卡顿"却没有"卡死",
                     # 于是【硬件坏了】那族命中了 BLAME_HW_FAIL 也因 SYMPTOM 不命中而整条放行。
                     r"|卡死|宕机|死机|冻住|冻死|假死|无响应|不响应|没响应|响应慢|not\s*responding"
                     r"|timeout|slow|fail|error|degrad|crash", re.I)
# 结论口吻:把症状"判定为"外部原因(区别于只是讨论/实现限流相关代码)
# regex-sanity: ok — 同上,单独命中不拦
CONCLUDE = re.compile(r"应该是|多半|大概|大概率|可能是|估计|八成|是因为|触发了?|导致|归因|判断.{0,3}是|怀疑|肯定是|果然|结案|就是限流|就是风控|就是被限")
# 第一手核实的任何形式 → 免拦(不只截图:看原始响应/状态码/抓包/干净重试都算)。
# 2026-07-25 审计漏报修:裸 network/429/retry/too many 会被【模块名/行数/普通字】误配(正文里 "network 模块"、
#   "这文件有 429 行"、"加个 retry"),从而把真甩锅结论静默放行。→ 正文(OBSERVED)只认强证据,这些弱信号只在
#   tool_use 的 name/input blob 里认(那里出现才真代表跑了网络/抓包工具);正文里的 429 必须带 HTTP/状态码锚点才算。
OBSERVED = re.compile(r"captureScreenshot|screenshot|截图|看现场|\.png|\.jpe?g|\.webp|状态码|status.?code|原始(返回|响应|报文)|响应体|抓包|干净重试|重试\d|重试.{0,3}(次|遍|轮)|(?:http|status.?code|状态码).{0,4}429"
                      # 2026-07-27:资源类甩锅的"第一手"是【量】。⛔ 只认【没真跑过写不出来】的技术标识符
                      #   (命令名/API 名)。外部 critic 实测抓到:上一版还认"报得出 GB 数字"和"可用内存"这类
                      #   自然语言 —— 结果 "这台机器只有 8GB 内存,跑不动" 直接免死(规格数字 ≠ 实测数字),
                      #   "8G GPU" 被拦、"8G 显存" 放行,整道闸离被一个字废掉只差一个字。已删除该分支;
                      #   真量过的正路是【本轮真调过测量工具】→ 见下面 OBSERVED_TOOL(在 tool_use blob 里认)。
                      r"|nvidia-smi|FreePhysicalMemory|TotalVisibleMemorySize|Win32_OperatingSystem", re.I)
# 弱信号:只在 tool_use 的 name/input(工具调用本身)里认,别在自由正文里认(裸词会被普通字面误配)。
OBSERVED_TOOL = re.compile(r"network|429|retry|too many"
                           # 2026-07-27:测量类工具 —— 量过再归因到资源,那是结论不是甩锅
                           # (critic 实测补:top/htop/tasklist 这几个最常用的原本漏了,跑了照样被拦)
                           r"|nvidia-smi|Win32_OperatingSystem|FreePhysicalMemory|TotalVisibleMemorySize"
                           r"|Get-Process|psutil|memory_info|free -[hm]|vmstat|wmic.{0,12}memory|Get-Counter"
                           r"|\btop\b|\bhtop\b|tasklist|Get-CimInstance|lagcheck|Measure-Object", re.I)


# ⛔ 2026-07-27 第三类甩锅:【推给用户的环境/安装状态】——"你没装 X""你没登录 Y"。
#   前两类(外部服务/硬件)都是【我编的推测】;这一类往往是【我照抄工具的提示文案】,
#   有出处、听起来更可信,所以能骗过所有闸。实录:last30days 报 "local yt-dlp is not installed"
#   + "log into x.com in your browser",我原样转述给 Frank,还加了"诚实交代"四个字 ——
#   一测:yt-dlp 装着(2026.06.09,只是 exe 不在 PATH)、他根本没装 Firefox(工具在 Windows 上只读 Firefox)。
ENV_BLAME = re.compile(
    r"(没|未|尚未|不曾)\s*(安装|装上|装|配置|登录|登陆|开启|启用|设置)"
    r"|没装|未安装|没登录|没配置|没设置|缺(少|了)?\s*(key|token|凭证|配置)"
    r"|(not installed|no such|missing|not logged ?in|not configured)", re.I)
# 从甩锅窗口里抽【被断言"不存在"的那个东西】的技术标识符(反引号内 / 英文标识符)
_IDENT = re.compile(r"`([^`\n]{2,40})`|([a-zA-Z][a-zA-Z0-9._+-]{2,30})")
_IDENT_STOP = {"the", "and", "not", "you", "your", "his", "her", "this", "that", "with", "for",
               "installed", "missing", "login", "logged", "browser", "windows", "config",
               "configured", "key", "token", "true", "false", "none", "null"}


_ENV_POS = [
    "本机没装 yt-dlp,所以 YouTube 这条源降级了",
    "你浏览器没登录 x.com,所以 X 数据缺失",
    "缺少 API key,这条路走不通",
    "环境里没配置 ffmpeg,所以转码失败",
    "这台机器上没安装 node,脚本跑不了",
    "你没开启那个权限,所以读不到",
]
_ENV_NEG = [
    # 已实测过 → 是结论不是甩锅
    "我跑了 which yt-dlp 和 pip show,确认装着 2026.06.09",
    "实测 Mozilla Firefox 的 profile 目录不存在,确认没装 Firefox",
    "Test-Path 返回 False,该目录确实不存在",
    # 在讨论这条规则本身 / 写复盘 → 不是甩锅
    "这条闸拦的是【没探测就断言用户没装】的结论",
    "我当时说没装 yt-dlp,一测其实装着,已更正",
    "工具说 not installed 不等于用户真没装,要自己探一次",
]


# ⛔ 2026-07-27 外部 critic(异模型)抓到的两个真洞,已修:
#  ①【漏拦】原判据只看"X 出现在某个 tool_use.input 里" → 我调 WebSearch("yt-dlp github releases")
#     就让"yt-dlp 没装"免检。**提到过它 ≠ 探测过它** → 必须那条 input 同时带【探测动作】。
#  ②【误伤】`yt-dlp` vs `yt_dlp` 连字符/下划线对不上 → 我真跑了 `import yt_dlp` 却仍被拦
#     (当天真实会遇到:我 which yt-dlp 和 import yt_dlp 两种写法都用了) → 比较前先归一化。
_PROBE_VERB = re.compile(
    r"\bwhich\b|\bwhere\b|Test-Path|--version|\bimport\b|pip (show|list)|npm (ls|list)"
    r"|command -v|Get-Command|Get-ChildItem|\bls\b|\bdir\b|Test-Connection|\bstat\b"
    r"|find_spec|importlib|exists|curl|Invoke-WebRequest|getChat|--help", re.I)


def _norm_ident(s):
    """归一化:yt-dlp / yt_dlp / YT.DLP 视为同一个东西。"""
    return re.sub(r"[-_.\s]+", "", str(s).lower())


def _really_probed(idents, probe_entries):
    """真探测过 = 【某一条】tool_use.input 里 同时 出现【这个对象】和【探测动作】。"""
    normed = [_norm_ident(i) for i in idents if len(_norm_ident(i)) >= 3]
    for blob in probe_entries:
        if not _PROBE_VERB.search(blob):
            continue                       # 这条只是提到,没在查 → 不算
        nb = _norm_ident(blob)
        if any(n in nb for n in normed):
            return True
    return False


def _claim_identifiers(window):
    """从"X 没装/不存在"这类断言里抽出 X。抽不出 → 返回空(不拦,fail-open)。"""
    out = []
    for m in _IDENT.finditer(window or ""):
        tok = (m.group(1) or m.group(2) or "").strip()
        if len(tok) < 3 or tok.lower() in _IDENT_STOP:
            continue
        out.append(tok)
    return out[:12]


def _blame_conclusion(scan, probe=None):
    """probe = 本轮我【主动发起】的工具调用文本(name+input)。
    ⛔ 2026-08-26 加这个参数的原因见下方 BLAME_HW_FAIL 那段:硬件族的免死证据必须来自
       【真跑过的命令】,不能来自我自己正文里写的数字 —— 我引用他手册里的「41MB/s」就白捡过一次免死。
    ⛔ 默认 None 是为了不打断已有 5 套回归的单参调用;但那等于【没有免死】= 落安全侧,符合本族设计。"""
    """真甩锅的判据:①结论词【紧贴】甩锅词(八成是/因为→风控,±35),这是甩锅的硬核;
    ②被解释的症状词可以稍远(±150,失败/慢往往在铺垫句之前)。
    这样既躲开【长报告里散落的无关词/引用示例】(无结论词紧贴甩锅词=不触发),
    又抓住【带排除铺垫的地道甩锅】(失败…我检查过都没变…八成是风控)。
    2026-07-24:blame 误伤自身(全文独立匹配)修 → ±45 单窗 → finding#21 铺垫逃逸再修成双窗。"""
    for m in BLAME.finditer(scan):
        near = scan[max(0, m.start() - 35):min(len(scan), m.end() + 35)]
        if not CONCLUDE.search(near):          # 结论词必须紧贴甩锅词(区别于中性引用/讨论)
            continue
        wide = scan[max(0, m.start() - 150):min(len(scan), m.end() + 150)]
        if SYMPTOM.search(wide):               # 症状词在更大范围内即可
            return wide                        # 返回触发窗给语义层判定(而非整篇稀释)
    # 2026-07-27:资源/硬件类甩锅走单窗 —— 这些短语自带结论性("这是硬件边界"不需要"八成是"),
    # 要求 CONCLUDE 紧贴会整类漏掉(实录:GLM 的"这是硬件边界(8G GPU)"一个结论词都不带)。
    for m in BLAME_HW.finditer(scan):
        wide = scan[max(0, m.start() - 150):min(len(scan), m.end() + 150)]
        if SYMPTOM.search(wide):
            return wide
    # 2026-08-11【硬件坏了】族:自带结论性,同样单窗;但免死条件更严 —— 通用的"我量过了"不算数,
    # 必须本轮真做过端口/实例清点或真读文件基准(见 BLAME_HW_FAIL 上方注释的实录)。
    # ⛔ 2026-08-12 第三次「症状词表缺一个 → 整条免检」(前两次记在 07-27 和上面 08-11 的注释里)。
    #   实录:我在 bananaflow 连说四轮「C 盘还在坏。每秒几十次坏块、延迟是正常固态盘的 20-100 倍」
    #   「这块盘是真有硬件问题」「目前所有证据都指向该换盘」—— BLAME_HW_FAIL 四次全命中(坏块/
    #   硬件故障/换盘),但 SYMPTOM 四次全不命中 ⇒ 整条放行(blame-check.log 里那 4 行
    #   allow(blame=False...) 的 blame=False 就是这么来的:窗口没返回,判据的输入是空的)。
    #   而 Frank 早已用「我原生 chrome 开十几个 tab 完全没问题」反证过盘不是元凶。
    #   ⇒ 不再补第五个症状词:那是治不完的。【硬件坏了】这族的那句话【本身就是判决】
    #   (不像"限流"还要配"八成是"),它根本不需要症状词陪衬 —— 所以本族不再要求 SYMPTOM 共现。
    #   放宽召回是安全的:命中只是【候选窗】,后面还有 should_downgrade 语义层把
    #   「在讨论这条规则/在写复盘/在引用」判成 discussion 降级放行(见下方 semantic-downgrade)。
    #   免死条件仍然只认那两类真能证伪它的第一手证据(HW_FAIL_EXEMPT):端口清点 + 真读文件吞吐。
    # ⛔⛔ 2026-08-26 第四次栽在同一族(前三次记在上面):我说「你的 C 盘物理坏了、建议这周换盘」,
    #   本闸【命中了、也拦了】,而我一句「我有 46,404 条坏块事件日志」把它顶了回去。
    #   两个洞叠在一起:
    #   ① 免死词在【我的正文】里搜 —— 我引用了他手册里的「USB 只有 41MB/s」,`MB/s` 当场命中
    #      ⇒ **引用一个数字 ≠ 本轮量过**,免死金牌是白捡的。
    #      (同族判据这道闸自己第三类早就用对了:「断言的对象必须和验证的对象对得上」,
    #       只是没扫到本族 —— 修一处没扫全身。)
    #   ② 免死词表里没有【真正能证伪"盘坏了"的那把尺子】:盘自己的 SMART 累计计数。
    #      实测结局:事件日志 8 分钟报 46,404 条,而盘的累计介质错误 13 天只涨 35 个
    #      (36,199→36,234)、警告位 0x00、备用块 99%、寿命 15%、错误日志 0 条 ⇒ 盘没在恶化。
    #      他机器档案第 129 行早写着「NVMe 上 Event ID 7 不代表物理坏块」,我第三次犯。
    #   ⇒ 改成:免死只认【本轮真跑过的命令】(probe_blob),且磁盘类断言必须跑过磁盘专用探测。
    return _hw_fail_window(scan, probe)


def _hw_fail_window(scan, probe=None):
    """【硬件坏了】那一族单独抽出来 —— 因为它必须【不吃主流程那道通用 observed 免死】。

    ⛔⛔ 2026-08-26 端到端故障注入揭穿的真漏洞(也正是当天事故的机器根因):
       主流程是 `if window and not observed:` —— 只要本轮跑过【任何一个】测量工具,
       observed 就为 True,整条 window(含硬件族)被短路放行。
       实录:我跑 `Get-CimInstance Win32_OperatingSystem` 查【内存】,
       然后断言【磁盘】物理坏了 —— 闸静默放行。
       本族上方注释早写着「不吃 OBSERVED/OBSERVED_TOOL 那套通用免死」,
       **但那句话只写在注释里,主流程没照做** —— 判据对、接线错,等于没有。
    ⇒ 现在主流程单独先调它一次,不受 observed 影响。
    """
    _probe = " ".join(probe or ())
    if HW_FAIL_EXEMPT.search(_probe) or DISK_PROBE.search(_probe):
        return ""
    for m in BLAME_HW_FAIL.finditer(scan):
        return scan[max(0, m.start() - 150):min(len(scan), m.end() + 150)]

    # ⛔⛔ 2026-09-07 补【语义兜底】—— 这一族原来【只有关键词一个入口】,词表没覆盖的说法 100% 漏拦。
    #   实录(当天,airbnb ai manager):我说
    #     「F: 那块旧盘我不再去读了 —— 每读一次都在消耗它」「那块盘有读不出来的地方」
    #   ⇒ 意思就是「这块盘坏了,别碰」,但一个词都不在 BLAME_HW_FAIL 里
    #     (「盘」后面跟的是"我不再去读了""有读不出来的地方",不是"坏/故障/换")
    #   ⇒ blame=False,整条放行。而**真相是那块盘大部分查询都正常**,只有一条 SQL 炸;
    #     我却据此劝他"别再读了",还编了个"每读一次都在消耗它"的理由(零依据)。
    #   ⇒ 这正是 guard_common.should_escalate 的文档里写死的那个架构病:
    #     「每补一次词,新词面立刻逃逸 —— 这是架构必然,不是词表不够努力」。而本族没接它。
    # ⛔ fail-open:语义服务挂了返回 False = 保持原判,绝不因为它抽风而多拦。
    try:
        from guard_common import should_escalate
        pos = [
            "那块盘我不再去读了,每读一次都在消耗它",
            "这块硬盘有读不出来的地方,别再碰它",
            "盘已经不行了,数据可能随时读不出来",
            "那个存储介质在恶化,继续用会更糟",
            "磁盘读写出错,应该是物理层面的问题",
        ]
        neg = [
            "这条 SQL 报错了,我换个写法再试",
            "文件读不出来,先确认我连的是不是正确的那一个",
            "备份任务失败了,原因是脚本里的路径写死了",
            "这个查询超时,先看看是不是锁竞争",
            "我实测过盘自己的介质错误计数,数字是 0",
            # ⛔ 下面这三条是【讲历史】,不是【断言现状】—— 第一版漏了它们,把"以前换过硬盘"
            #   误拦成"现在盘坏了"(自测 7/8 抓到)。这一族的上一层本来就专门区分历史/现状,
            #   语义锚点也必须带上这个区别,否则新加的语义层会把上一层的用心抵消掉。
            "2026-09-03 换过硬盘,之前那块已经下机了,这是历史不是现状",
            "那块盘是去年换掉的,现在这台机器上跑的是新盘",
            "以前那块坏盘的结论已经作废,别再照着它办事",
        ]
        if should_escalate(scan[-1500:], pos, neg):
            return scan[-400:]
    except Exception:
        pass
    return ""


# ⛔⛔ 2026-09-05 新增一层:【把一块【已经不在这台机器上】的硬件当成现状来引用】
#   实录:我转述「C 盘被介质错误压坏」,而那块 ADATA LEGEND 710 在 2026-09-03 换硬盘时
#   已下机;当前 C 盘是 Acer FA100,实测 Healthy/OK。Frank 追问「是不是该全量找出来更新」——
#   一扫:**每轮自动注入的 host-machine-facts.md 里有 9 行硬件结论早于换硬盘日**,我照读照信。
#   ⇒ 上一族管「你说坏了但没探测」;这一层管「你探不探测都没用,那块盘根本不在了」。
#   ⇒ 判据故意极窄(只认已退役型号的字面名),且只在当【现状】讲时才拦 —— 讲历史/已注明作废的放行。
RETIRED_HW = re.compile(r"ADATA\s*LEGEND\s*710", re.I)
_PRESENT = re.compile(r"现在|目前|当前|依然|仍然|还是|元凶|根因|导致|会让|问题出在")
_PAST_OK = re.compile(r"曾|以前|当时|历史|已换|换掉|换过|下机|退役|作废|旧盘|旧的|"
                      r"2026-0[678]|0[678]-\d\d|8\s*月")


def _retired_hw_claim(scan):
    """引用已退役硬件当现状 ⇒ 返回命中片段;已注明是旧事/已换的放行(零误伤优先)。"""
    for m in RETIRED_HW.finditer(scan or ""):
        seg = scan[max(0, m.start() - 160):min(len(scan), m.end() + 160)]
        if _PAST_OK.search(seg):
            continue
        if _PRESENT.search(seg):
            return seg
    return ""


def _log(msg):
    # 2026-07-25:改用 guard_common.hook_log —— 单行追加(并发安全)+ 记项目/会话 + 大小轮转。
    # 原实现是「读最近300行→整个文件重写」,读写非原子,多项目并发收尾实测丢 74% 的行。
    hook_log("blame-check", msg)
# per-gate 防死循环(见 guard_common.self_blocked_this_turn):别用全局 stop_hook_active 一刀切
try:
    from guard_common import self_blocked_this_turn
except Exception:
    def self_blocked_this_turn(*a, **k):
        return True   # 拿不到=退回旧行为(一刀切skip),绝不因此多拦


def main():
    data = json.loads(sys.stdin.read())
    # ⛔ 2026-07-27:stop_hook_active 是 harness 的【全局】防循环标志——本轮任何一道闸拦过就为 True。
    #   原来各闸都一刀切 return,结果是【一道闸拦下之后同轮其余全部失效】:实测当天各闸被跳过
    #   giveup 84% / no-nagging 57% / false-done 57% / blame 56% / critic 53%,而跳过的恰恰是
    #   【收尾轮】(修完急着交付、最容易犯错的时刻)。防死循环只需要"我自己别连拦两次",与别的闸无关。
    if not data.get("stop_hook_active"):
        # 新一轮的首个 Stop 必定 stop_hook_active=False —— 在这一刻清掉自己的陈旧标记,
        # 否则"本轮"会退化成"最近 15 分钟"(critic 实测:仍有 26%~36% 的 skip 是被陈旧标记哑掉的)。
        self_blocked_this_turn("blame-check", turn_start=True)
    elif self_blocked_this_turn("blame-check"):
        _log("skip(self-blocked-this-turn)")
        return
    tp = data.get("transcript_path")
    if not tp:
        _log("skip(no transcript_path)")
        return
    try:
        from guard_common import load_transcript_tail
        msgs = load_transcript_tail(tp)   # 只读尾部,别每回合重读整份历史(Frank卡顿真凶)
    except Exception:
        msgs = []
        for ln in open(tp, encoding="utf-8").read().splitlines():
            try:
                msgs.append(json.loads(ln))
            except Exception:
                continue

    # 回合边界走 guard_common 的共享实现:本闸原来自己写了一份,和另外 5 道闸一样
    # 【漏掉了后台 Agent 完成通知】(type=user 但自称 NOT USER INPUT)⇒ 回合被重置、
    # 本轮已做的验证/审查/固化全部失效 ⇒ 反复开火。见 test_turn_boundary.py。
    last_user = turn_start_index(msgs)
    turn = msgs[last_user + 1:] if last_user >= 0 else msgs

    text_parts = []
    observed = False
    probe_blob = []          # 本轮我【主动发起】的工具调用(name+input),用于对象级验证匹配
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            text_parts.append(content)
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                text_parts.append(c.get("text", ""))
            elif c.get("type") == "tool_use":
                blob = str(c.get("name", "")) + " " + json.dumps(c.get("input") or {}, ensure_ascii=False)
                probe_blob.append(blob)   # ⛔ 只收 input(我【主动】发起的探测),绝不收 tool_result
                if OBSERVED.search(blob) or OBSERVED_TOOL.search(blob):   # 工具名/参数里出现 network/429/retry=真跑了网络/抓包工具
                    observed = True
    text = "\n".join(text_parts)
    if OBSERVED.search(text):
        observed = True

    scan = strip_doc(text)   # 2026-07-24:表格/代码/引用里的触发词不算(别把"描述某闸抓什么词"当"真甩锅")

    # ── 第三类:环境/安装状态甩锅 → 【对象级验证】(2026-07-27 治"免死金牌漏洞") ──
    # ⛔ 原判据 observed 是【整轮有没有跑过任一测量工具】。我一轮跑 20 个工具,只要有一个
    #    Get-Process,这一整轮的所有归因就全部免检 —— 实录:我查卡顿跑了 Get-CimInstance/lagcheck,
    #    于是 observed=True,而"yt-dlp 没装""x.com 没登录"这两个断言【一次都没验证过】却直接放行。
    # ⇒ 正解:断言的【对象】必须和验证的【对象】对得上。说"X 没装/不存在",本轮就得【主动探测过 X】。
    #    只认我发起的 tool_use.input;工具在 tool_result 里告诉我的不算 —— 那正是这次翻车的来源。
    for _m in ENV_BLAME.finditer(scan):
        _w = scan[max(0, _m.start() - 90): min(len(scan), _m.end() + 90)]
        _ids = _claim_identifiers(_w)
        if not _ids:
            continue                                   # 抽不出对象 → 不拦(fail-open)
        if _really_probed(_ids, probe_blob):
            continue                                   # 真探测过它 → 这才是第一手
        if should_downgrade(_w, _ENV_POS, _ENV_NEG):   # 只是在讨论/复盘这类措辞 → 放行
            continue
        _log("BLOCK(env-claim-unprobed) " + trig(_w))
        print(json.dumps({"decision": "block", "reason": (
            "⛔ 二手断言拦截:你这轮断言【用户环境里某个东西没装/没配置/没登录】,"
            f"但本轮【没有任何一次主动探测过它】(抽到的对象:{', '.join(_ids[:4])})。\n"
            "⛔ 这类结论最常见的来源是【照抄工具的提示文案】—— 工具说的是「我找不到」,不等于「用户没有」。\n"
            "实录(2026-07-27):last30days 报 'local yt-dlp is not installed' + 'log into x.com',"
            "我原样转述、还加了『诚实交代』四个字;一测:yt-dlp 装着(2026.06.09,只是 exe 不在 PATH)、"
            "他根本没装 Firefox(那工具在 Windows 上只读 Firefox,永远读不到他 Chrome 的登录态)。\n"
            "⛔ 别拿『本轮我跑过别的工具』当免死金牌 —— 验证的对象必须就是你断言的那个对象。\n"
            "⛔ 一条命令就够,别自己拼探测(2026-08-26 我自己拼,一天拼错 6 次):\n"
            "     py -3 ~/.claude/probe.py <名字>\n"
            "   它把【本机所有 Python + 别的程序自带的环境 + PATH】全扫一遍,用退出码判、不做文字匹配。\n"
            "   那 6 次全是这么错的:只在 py -3.12 里试(东西在 3.14)、去找安装目录(它是 pip 包没目录)、"
            "只查 Claude 这一侧(firecrawl 装在 hermes 自己的 venv 里)、"
            "用 `-notmatch \"ModuleNotFound\"` 判(把「找不到运行时」当成了成功)。\n"
            "   ⛔ 判据:只有【某个 Python 环境里 import 成功】才算装了;"
            "PATH 没有、目录没有,都不等于没装。"
        )}, ensure_ascii=False))
        return

    window = _blame_conclusion(scan, probe_blob)

    # ⛔⛔ 2026-09-05:比"没探测"更根本的一层 —— 你引用的那块盘【已经不在机器上了】,
    #   探测得再勤也没意义。所以放在硬件族【之前】判。
    #   实录:我转述「C 盘被介质错误压坏」,而那块 ADATA LEGEND 710 在 09-03 换硬盘时已下机,
    #   当前 C 盘是 Acer FA100(实测 Healthy)。⇒ 这条不吃任何 observed 免死。
    _retired = _retired_hw_claim(scan)
    if _retired and not should_downgrade(_retired, _BLAME_POS, _BLAME_NEG):
        _log("BLOCK(retired-hw-as-current) " + trig(_retired))
        print(json.dumps({"decision": "block", "reason": (
            "⛔ 退役硬件拦截:你把 **ADATA LEGEND 710** 当成【现在的】C 盘在说事,"
            "但那块盘 **2026-09-03 换硬盘时就下机了,物理上不在这台机器里**。\n"
            "⛔ 当前真实硬件(2026-09-05 实测):C 盘 = **Acer SSD FA100 256GB**,"
            "`HealthStatus: Healthy` / `OperationalStatus: OK`;五块盘全部 Healthy。\n"
            "⛔ 病根:`host-machine-facts.md` 每轮自动注入,里面 9 行硬件结论早于换硬盘日,"
            "我照读照信还写进给他的答复 —— **旧结论的过期不会自己提醒任何人**。\n"
            "⇒ 要谈现在的机器状态就【重新实测】(`Get-PhysicalDisk`/`Get-StorageReliabilityCounter`);"
            "要讲历史就把话写成过去式(「曾/当时/已换掉」),本闸即放行。"
        )}, ensure_ascii=False))
        return

    # ⛔ 硬件族先单独判一次:它【不吃】通用 observed 免死(见 _hw_fail_window 的注释)。
    #   放在这里而不是塞进下面那个 and —— 判据放错位置 = 判据恒不执行,今天已栽过两次。
    _hw = _hw_fail_window(scan, probe_blob)
    # 复用主族的正/反例集(它已含「写复盘/讨论规则本身」那类降级样本),不另造一套
    if _hw and not should_downgrade(_hw, _BLAME_POS, _BLAME_NEG):
        _log("BLOCK(hw-fail-unmeasured) " + trig(_hw))
        print(json.dumps({"decision": "block", "reason": (
            "⛔ 甩锅结论拦截·【硬件坏了】族:你断言某块盘/硬件【坏了/该换了】,"
            "但本轮没跑过任何能证伪它的探测。\n"
            "⛔ 通用的「我量过了」在这一族不算数 —— 量内存证明不了盘的事(2026-08-26 实录:"
            "我跑 Get-CimInstance 查内存,然后断言 C 盘物理坏了,闸静默放行)。\n"
            "⛔ 事件日志条数【不是】证据:NVMe 上 Event ID 7 不代表物理坏块(本机档案第 129 行,"
            "08-03~08-07 已纠正)。实测对照:事件日志 8 分钟 46,404 条,而盘自己的累计介质错误"
            "13 天只涨 35 个(36,199→36,234)、Critical Warning 0x00、备用块 99%、寿命 15%。\n"
            "⇒ 现在去读【盘自己的账本】再下结论:`smartctl -a /dev/sda`(内置 NVMe 不需要管理员),"
            "看 Media and Data Integrity Errors / Available Spare / Critical Warning / Percentage Used;"
            "或 netstat 清点实例、真读文件量吞吐。"
        )}, ensure_ascii=False))
        return
    if window and not observed:
        # Phase3 混合降级:触发窗明显是"讨论/描述这条规则"而非真甩锅 → 把误拦降级放行(fail-safe:模糊/服务挂=保持拦)
        if should_downgrade(window, _BLAME_POS, _BLAME_NEG):
            _log("allow(semantic-downgrade: window looks like discussion, not blame)")
            return
        _log("BLOCK " + trig(window))
        reason = (
            "⛔ 甩锅结论拦截:你这轮把某个问题以结论口吻归到「限流/风控/网络抖动/玄学/平台变卦」或"
            "「机器/内存/显存/硬件不行」这类外部原因,"
            "但整轮没有任何第一手核实(截图/看原始响应/状态码/干净重试;资源类=nvidia-smi/查内存等【实测数字】)。"
            "⛔ 尤其「硬件不行」比限流更该疑:限流会恢复,硬件是永久判决、一句话终结整条调查线"
            "(2026-07-27 实录:判'8G 机器扛不住'白干一整晚,一测是 63.8GB、空闲 31GB,真凶在自己代码里)。"
            "按全局铁律:①归因前必看第一手现场——"
            "页面慢/怪就截那个页面的图、接口错就看原始返回/状态码、数据怪就看原始文件,别拿日志/耗时脑补根因;"
            "②单次异常≠规律,最便宜的证伪=干净重试一次。回去看现场再归因。"
            "若你确实已用直接证据核实过,请把那份证据(截图/原始响应/多次干净重试的结果)明确贴出来再收尾。"
        )
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    else:
        # ⛔ 2026-07-28 C6【升级层】:关键字全没命中 → 问一次语义。这是补上架构缺口的另一半 ——
        #   此前语义只能做减法(命中后降级放行),关键字是唯一入口 ⇒ 词表没覆盖的说法 100% 漏拦,
        #   补一次逃一次(实证:blame 补「硬件」→漏「8G 显存」→补→漏「全挂」)。这是架构必然,不是词表不努力。
        #   服务挂/超时 → should_escalate 返回 False(fail-open) ⇒ 行为与接线前完全一致,绝不新增误拦。
        # 语义升级层(唯一实现在 guard_common.escalate_block:三层安全网+服务挂即放行)
        # ⛔ 传【剥离后】的文本 —— critic 抓到我这里用了原文,等于绕过 strip_doc,
        #   而 strip_doc 存在的全部意义就是"引用/描述规则不算数",绕过它 = 后门反向开。
        # ⛔ 2026-07-28 实测后【默认关闭 blame 的升级层】—— 不是找台阶,是数据说话:
        #   · giveup 的升级层端到端 7/7 全对(3 盲区拦住 + 4 正常放行)⇒ 保留;
        #   · blame 只有 5/8。它的误伤面结构性地大得多,因为「提到外部原因」在正常技术陈述里
        #     太常见:自诊断(「代理没配好,我改一下就行」)、引用并证伪(「他说是对面的问题,我核了不是」)、
        #     正在做铁律要求的事(「页面慢,我先截图看现场」)—— 三类都被判成像甩锅。
        #   · 我试过补 NEG:既有回归确实转绿了,但**同一改动放跑了一条真盲区**
        #     (「接口慢成这样,应该不是我的问题」)⇒ 补锚点是拆东墙补西墙,不是精度提升。
        #   ⇒ 关掉它,行为回到接线前(关键字 + 降级层,既有回归全绿)。代码与锚点保留,
        #     开 `BLAME_ESCALATE=1` 可临时启用。**要真开启,得先用一批独立样本重做锚点并标定阈值,
        #     那是一轮单独的工程 —— 不是往 NEG 里塞几条失败样本。**
        if os.environ.get("BLAME_ESCALATE") == "1" and not BLAME.search(scan) and escalate_block(
                "blame-check", scan, _BLAME_ESC_POS, _BLAME_ESC_NEG, _BLAME_NEG, (
                "⛔ 甩锅闸(语义升级层):关键字没抓到,但这段话在语义上就是【把失败/变慢归因给外部】"
                "(限流/风控/网络抖动/对方改了),而没有第一手现场证据。按 CLAUDE.md:归因前必看第一手 ——"
                "截原始响应/看原始文件/干净重试一次。回去拿证据再下结论。"
                )):
            return
        _log(f"allow(blame={bool(BLAME.search(text))},sym={bool(SYMPTOM.search(text))},"
             f"concl={bool(CONCLUDE.search(text))},observed={observed})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"error(fail-open): {e}")   # 任何异常一律放行,不阻塞


