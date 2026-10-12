#!/usr/bin/env python3
"""UserPromptSubmit hook·Phase1 语义规则召回(2026-07-24)——嵌入你这条消息,注入 top-K 最【语义相关】的
已钉死形状/铁律,让毛病抗体在"该出现的那一刻"精准冒出来(不是开局塞全表我略读)。
借 pro-workflow 的核心机制,复用已部署的 bge-small。嵌入+cosine+topK 全在热服务(7911 /recall)里做,
hook 只做瘦 HTTP 调用——消掉每 prompt numpy 冷启的 ~500ms 浪费(Phase4 判官一致点名的唯一短板)。
安全:fail-open(服务/异常一律静默放行,绝不阻塞你发消息);只注入 title+短摘要(低污染)。"""
import os as _os_sp, sys as _sys_sp
_sys_sp.path.insert(0, _os_sp.path.join(_os_sp.path.expanduser("~"), ".claude"))
from superego_port import BASE as _SEM  # 端口唯一出处:~/.claude/superego-port.txt
import sys, os, json, re, urllib.request

try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 意图门(2026-07-25 审计修 over-fire benign)——7911 的 0.38 阈值地板只校准过【纯 ack】负样本
# (好的继续/谢谢啦/嗯知道了/ok),对"有实义的 benign"(致谢/闲聊/翻译)无任何压制,这些与 Superego
# 行为纪律教训无关的 prompt 也会召回一条 banner,长期训练读者对 banner 失明。故在【发起召回前】
# 高精度抑制这三类纯 benign。原则:benign 词表【收紧】、actionable 词表【放宽】——只要 prompt 里出现
# 任何可执行/技术信号就【照常召回】(守住真靶子:如"我要删掉这个skill"仍开火),宁可对"谢谢+带活"的
# 混合句多召回一条(安全方向=不制造漏报),绝不误伤真需要教训的请求。
_BENIGN = re.compile(
    r"谢谢|感谢|多谢|太棒|棒极|做得好|干得好|辛苦[了啦你]|thank\s*you|thanks\b|thx\b|"      # 致谢
    r"随便聊|闲聊|聊聊天|聊会儿|天气怎么样|天气如何|吃了吗|在吗|在不在|哈哈哈|嘻嘻嘻|无聊|"    # 闲聊
    r"翻译成|翻译一下|翻译这|帮.{0,6}翻译|译成|translate\b",                                # 翻译
    re.I,
)
_ACTIONABLE = re.compile(
    r"删|改|修|加|添加|建|创建|做个|做一个|做一下|部署|跑|运行|执行|安装|卸载|配置|设置|重启|"
    r"启动|停止|杀|对账|生成|抓|爬|下载|上传|登录|注册|优化|重构|实现|开发|调试|排查|检查|"
    r"测试|验证|分析|迁移|合并|提交|推送|回滚|"
    r"看|查看|核实|确认|复核|复审|审计|确定|对不对|退了没|是谁|彻底|根治|结论|复盘|方案|"   # 调查/核对/质疑(Frank 高频)
    r"bug|error|fix|deploy|install|run|build|test|debug|api|hook|skill|数据|数据库|文件|脚本|"
    r"代码|函数|变量|服务|端口|接口|页面|组件|模块|日志|报错",
    re.I,
)


def _is_benign(prompt):
    """纯致谢/闲聊/翻译且无任何可执行/技术信号 → 抑制召回。宁漏勿误伤真召回。"""
    return bool(_BENIGN.search(prompt)) and not _ACTIONABLE.search(prompt)


def _meter(**kw):
    """把每一轮召回的实况落一行 JSONL —— 治「从没量过」。
    ⛔ 这不是日志美化,是把一堆【猜】变成【数】:注了多少字、命中几条、延迟多少、超时率多少、
       跨项目噪音占比多少。此前这些全靠估,而估错过 5 倍(check-existing 曾被写成 5KB,实测 1029 字节)。
    报表:py -3.12 ~/.claude/hooks/superego-metrics.py"""
    try:
        import datetime
        kw["ts"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        kw["sid"] = (os.environ.get("CLAUDE_CODE_SESSION_ID") or "-")[:8]
        kw["proj"] = os.path.basename((os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).rstrip("/\\"))
        # ⛔ 外部 critic 抓到:这里原本硬编码本目录,不认 SUPEREGO_LOG_DIR ——
        #   跑一次回归就把合成数据写进生产计量文件(实测 12→22 行),
        #   正是我刚给 .log 加隔离要治的那个病,在新文件上复刻了一遍。
        d = os.environ.get("SUPEREGO_LOG_DIR") or os.path.dirname(os.path.abspath(__file__))
        p = os.path.join(d, "recall-metrics.jsonl")
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(kw, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ⛔ 2026-10-02 六宇宙第 1、2 层(Frank:「全都要」):提问像在找工具 / 选型 ⇒ 注入六宇宙清单;
#   像在找客户 / 深挖 Reddit ⇒ 提醒有 Reddit Radar。判据在 ~/.truthgate/six_universes.py(AG 桥接 handle_pre 调同一份)。
#   放在这里不另开钩子:这是本来就「按提问内容注入该记起的东西」的位置。
#   ⚠️ 不能只在末尾拼进召回结果 —— 语义服务按 9/25 下线令关着,召回每次都在中途退出(超时 / 熔断),
#   所以入口先算好,不管召回走到哪一步,退出时都发出去(见文件末尾)。Superego 被关掉时一起静默。
_SIX = []


def main():
    import time
    t0 = time.time()
    data = json.loads(sys.stdin.read())
    prompt = (data.get("prompt") or "").strip()
    try:
        sys.path.insert(0, os.path.expanduser("~/.truthgate"))
        from six_universes import prompt_notes
        _SIX[:] = prompt_notes(prompt)
    except Exception:
        pass
    if len(prompt) < 4:   # 只挡纯应答(好/继续/ok);短祈使句靠服务端 0.52 相似度地板兜噪音
        _meter(outcome="skip_short", plen=len(prompt), chars=0, n=0)
        return
    if _is_benign(prompt):   # 意图门:纯 benign(致谢/闲聊/翻译)不召回,消 over-fire 噪音
        _SIX.clear()         # 闲聊也不发六宇宙提醒(这条路在 Superego 开关检查之前,外审 10-02)
        _meter(outcome="skip_benign", plen=len(prompt), chars=0, n=0)
        return
    # topk=5(2026-07-25):留出集 recall@5=96.7% vs @3=90%——都过阈值=真相关,阈值gate住benign不增污染,只在
    # "真有多条相关教训"时才显到5条(信息拉满)。这是离98%最近的诚实配置(仍非98%,是本地实用最优)。
    # ⛔ 2026-08-14 加 proj_dir(R1):让服务能召回【本项目 PROGRESS】里的事实,不只是全局教训。
    #   ⚠️ 必须传**完整路径** —— 上面记 metrics 用的 `proj` 是 basename(只有文件夹名);
    #   服务那边要拿它去找 <proj>/PROGRESS.md,给 basename 会直接找不到文件、**静默失效**。
    #   两个字段名字像、含义不同,是最容易接错的那种 —— 我差点就这么发出去了。
    #   服务侧按 proj_dir 做【按项目隔离】:只查这一个项目的索引,别的项目的 PROGRESS 不参与。
    # ⛔ 2026-08-14 总开关的【提醒端】就放在这里 —— 这是唯一一个"本来就负责往上下文注入文字"的位置。
    #   为什么不放在各道闸里:hook 协议下 stdout/stderr+exit2 都等于【拦截】,
    #   关闭状态下打印提醒 = 把"关掉"变成"每道闸都拦你一次",正好反了。
    #   而"关了却忘了"正是 7/31 那次两周静默死亡的真病根 ⇒ 提醒必须有,但只能在这一处、每轮一次。
    _off_note = ""
    try:
        import importlib.util as _il
        _tp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "superego-toggle.py")
        if os.path.exists(_tp):
            _sp = _il.spec_from_file_location("_sgt", _tp)
            _sm = _il.module_from_spec(_sp)
            _sp.loader.exec_module(_sm)
            _d = _sm.load()
            # ⛔⛔ 2026-09-08:这里【原来】是
            #     `if _d and _sm.is_off("__any__") or (_d and (_d.get("gates") or ["*"]) != ["*"])`
            #   —— 第二个条件只看"文件里 gates 列表非空",**完全绕过了 is_off 的 session/until 比对**。
            #   后果:2026-09-07 18:24 一次测试写下 `{"gates":["giveup-guard"],"session":"testsid"}`,
            #   于是**每一个真实会话**每轮都收到「Superego 关闭中」——而 `is_off()` 实测返回 False,
            #   那道闸一直好好开着。我盯着这条假警报看了整整一夜。
            #   ⛔ 最毒的是它还引用真实事故给自己背书(「7/31 关了两周没人发现」)⇒ 假警报穿着真警报的衣服。
            #   狼来了:每轮都响的假警报,会训练我无视它;等真关了的那天,我也会照样划过去。
            #   ⇒ 判据只留一个出处:对 gates 里每一项问 `is_off`(它内部做 session/until 比对),
            #     全 False 就闭嘴。
            _gates_declared = (_d.get("gates") or ["*"]) if _d else []
            _really_off = [g for g in _gates_declared if _sm.is_off(g)] if _d else []
            if _really_off:
                _SIX.clear()
                return  # 彻底静默:不读 recall、不打印 _off_note、不注入任何 context
    except Exception:
        _off_note = ""

    _projdir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    # ⛔ 2026-09-08 从 5 提到 6:实测同一批 gold —— top-3=61% / top-5=72%(正好卡在地板)
    #   / **top-6=83%** / top-8 还是 83%(再放也没用)。⇒ 6 是这条曲线的拐点。
    #   代价:多推一条相关教训;收益:少漏一条本该拦住我的抗体。阈值 0.38 仍在 gate,
    #   不相关的照样进不来(负样本 4/4 干净这一项没变)。
    # ⛔⛔ 同时把 test_recall.py 的 TOPK 从 3 改成 6 —— **它一直用 3 去测一个跑 5 的系统**,
    #   于是常年报 61%、红了很久;我还为这个假数字诊断了三轮(索引过期/内容没进索引/判据错),
    #   三次全错。**测试和生产的配置必须同源**,否则尺子量的根本不是那个东西。
    body = json.dumps({"text": prompt, "topk": 6, "thresh": 0.38,
                       "proj_dir": _projdir}).encode()   # Qwen3-Embedding 校准阈值
    req = urllib.request.Request(_SEM + "/recall", body, {"Content-Type": "application/json"})
    # ⛔ 2026-07-25 实测:原 timeout=3s,而服务真实响应 0.66~15.69s(中位 ~2s)——同一条输入连跑10次,
    #   注入字节 0 0 1955 1955 0 0 0 0 0 0 = 【每4轮丢3轮】,且超时被静默吞掉、零日志。
    #   改 4s(覆盖中位数与常见抖动;仍远小于 hook 预算),并在下面 except 里落一行可见日志。
    # ⛔ 2026-07-26 外部 critic 从 recall-metrics.jsonl 算出真实丢失率:12 轮里 3 轮 timeout = **25%**,
    #   而 p50=999ms、**p90=4106ms 正好压在 timeout=4 的天花板上** —— 4s 不是"覆盖常见抖动",
    #   是恰好卡在丢的那条线上。抬到 8s:p90 有一倍余量,而用户侧最坏多等 8 秒也远低于一轮对话的时间。
    #   (真根因是 CPU 推理在共享机器上被抢占,已知;抬超时是缓解,不是根治——服务端上 worker 才是。)
    # ⛔⛔ 2026-08-14 接上现成的熔断器(O7 的实测结论):
    #   今天 39 次召回里 4 次失败,**全部落在我自己反复重启服务的两个窗口里**;
    #   其中两次是 8068/8069ms = **正好等满 8 秒超时** —— 服务在加载模型(端口已 Bound、还不应答),
    #   而这个 hook 傻等到底。健康时的真实延迟是 中位 518ms / p90 1237ms,余量很大,
    #   ⇒ 问题不是超时设短了,是**服务不可用时没人喊停**。
    #   而 `guard_common` 里的熔断器(90 秒内不再重试)**早就存在、旁边的 intent_margin 一直在用** ——
    #   又一次「修好的东西就在旁边、这里没接上」(lessons 形状 2026-08-14-E)。
    try:
        from guard_common import _breaker_open as _bo, _breaker_trip as _bt, _breaker_reset as _br
    except Exception:
        _bo = lambda: False          # noqa: E731  拿不到就当没熔断,照常尝试(fail-open)
        _bt = _br = lambda: None     # noqa: E731
    if _bo():
        # 这里不另写日志:_meter 已经把 skip_breaker 记进 recall-metrics.jsonl,
        # 而所有召回分析都读那个文件 —— 再写一份就是两个真相源(下次必然对不上)。
        _meter(outcome="skip_breaker", plen=len(prompt), chars=0, n=0, ms=0)
        return
    try:
        hits = json.loads(urllib.request.urlopen(req, timeout=8).read()).get("hits", [])
        _br()                        # 成功 → 复位,别让一次抖动把后面 90 秒全熔断
    except Exception as e:
        _bt()                        # 失败 → 合闸,后面 90 秒的其它闸直接跳过,不再各等 8 秒
        _meter(outcome="timeout_or_error", plen=len(prompt), chars=0, n=0,
               ms=int((time.time() - t0) * 1000), err=type(e).__name__)
        raise
    ms = int((time.time() - t0) * 1000)
    if not hits:
        _meter(outcome="no_hit", plen=len(prompt), chars=0, n=0, ms=ms)
        return
    # ⛔ 2026-08-14 把日期显示出来(Frank:「是不是漏了日期时间这个参数」——他说对了)。
    #   原来这行只有 [来源] 标题 + 摘要,而标题被截到 42 字、**日期常常正好被截掉**。
    #   后果:我分不清眼前这条是【今天刚钉死的】还是【三周前、而且今天已经被推翻的】。
    #   当天真实案例:07-27 的「CPU 要 11~17 秒 ⇒ 必须上 GPU」是在污染环境里量的,
    #   今天干净实测 CPU 0.19 秒、结论整个反过来 —— 而那条旧的至今还在索引里。
    #   ⚠️ 只显示、不降权:铁律(资源边界/先查现成)永不过期,会过期的只有具体测量值。
    def _age(h):
        d = h.get("date") or ""
        if not d:
            return ""
        try:
            import datetime as _dt
            days = (_dt.date.today() - _dt.date(*map(int, d.split("-")))).days
            if days <= 1:
                return f"[{d}·今天]"
            if days <= 7:
                return f"[{d}·{days}天前]"
            return f"[{d}·{days}天前⚠️旧]"     # 超过一周就打个问号,提醒我核一下还成不成立
        except Exception:
            return f"[{d}]"

    lines = [f"  · [{h['source']}]{_age(h)} {h['title']} — {h['snip']}" for h in hits]
    ctx = (_off_note +
           "⛱[Superego·语义召回] 你这条消息语义上最相关的【你自己钉死过的教训/铁律】(全文见 lessons.md/CLAUDE.md):\n"
           + "\n".join(lines)
           + "\n—— 这几条是你为【类似情形】钉死的抗体,动手前先照一眼、别重犯同一个毛病。")
    _meter(outcome="inject", plen=len(prompt), chars=len(ctx), n=len(hits), ms=ms,
           titles=[h["title"][:38] for h in hits], via=[h.get("via", "?") for h in hits])
    ctx = "\n\n".join(_SIX + [ctx])
    _SIX.clear()
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}, ensure_ascii=False))


def _emit_six():
    """召回没走到注入那一步(太短 / 闲聊 / 熔断 / 没命中 / 报错)时,六宇宙提醒单独发出去。"""
    if _SIX:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "additionalContext": "\n\n".join(_SIX)}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
        _emit_six()
    except Exception as e:
        # fail-open 仍然保留(绝不阻塞),但不再【静默】——静默让"每4轮丢3轮"藏了很久没人知道。
        try:
            import datetime
            # ⛔ 2026-07-26 critic:_meter() 50 行上面刚因为"硬编码本目录、不认 SUPEREGO_LOG_DIR"
            #   被抓过并修好,这里的收尾 except 还是老写法 —— 同一个病,50 行外没扫到(修一处扫全身)。
            _d = os.environ.get("SUPEREGO_LOG_DIR") or os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(_d, "recall-inject.log"),
                      "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} MISS {type(e).__name__}: {e}\n")
        except Exception:
            pass
        _emit_six()   # 召回挂了,六宇宙提醒照样发
