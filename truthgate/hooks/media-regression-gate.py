#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""媒体降级闸 —— 新出的片子比【已验收的上一条】变差了,就不许收尾。

⛔ 为什么建它(2026-08-12 真实翻车):
   我拿首帧驱动法重做第二镜的反打,交付时只验了「楚天啸正脸拿到没」——拿到了,于是我说"成功"。
   Frank 一眼看出三处我没验的:①画风从真人写实变成动漫脸 ②前景人物穿错衣服(变成"对着另一个自己说话")
   ③15 秒变 8 秒、动作像慢放。ffprobe 一量:**576×1024 vs 锚点 768×1376(少 44% 像素)、8.0s vs 15.08s**。
   这些**数字层面的降级,机器完全判得出来,却没有任何闸在看** ⇒ 补上。

⛔ 它的边界(必须诚实):
   本闸只判【数字】:分辨率、时长、帧率、音轨有无。
   **画风走样 / 穿错衣服 / 对着自己说话,数字一律看不出来** —— 所以命中时它会同时
   强制要求「新帧 vs 锚点帧并排图」,把眼睛这一关顶到人面前,而不是假装数字过了就没事。

判据(纯机器,无语义):
   本轮新产出的视频 A,与【同目录下更早的同类视频】B 相比:
     · 像素数 A < B*0.95      → 降级
     · 时长   A < B*0.60      → 缩水(留足余量:分镜本来就可长可短,只抓"砍一半"这种)
     · 帧率   A < B           → 降级
     · B 有音轨而 A 没有       → 丢音轨
   任一命中 → block。

放行:同目录没有更早的同类视频(第一条片子,无参照物)→ 静默放行。
豁免:确实是有意为之(如故意做短预告),在本轮说明后重跑即可 —— 见下方 ACK 说明。
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOOK_DIR)


def _logfile():
    """同 jargon-gate:路径向 `log_path()` 要,别自己拼(不然测试写的记录会混进生产日志)。"""
    try:
        from guard_common import log_path
        return log_path("media-regression-gate")
    except Exception:
        return os.path.join(HOOK_DIR, "media-regression-gate.log")

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm")
ACK = "MEDIA-REGRESSION-ACK"          # 本轮文本里出现它 = 我已明确认账并说明理由,放行


def log(msg):
    try:
        with open(_logfile(), "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def probe(path):
    """只读元数据,不解码帧。失败返回 None(宁可不拦,不可误拦)。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,width,height,r_frame_rate",
             "-show_entries", "format=duration", "-of", "json", path],
            capture_output=True, text=True, timeout=25).stdout
        d = json.loads(out)
        v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
        if not v:
            return None
        has_audio = any(s.get("codec_type") == "audio" for s in d.get("streams", []))
        num, _, den = (v.get("r_frame_rate") or "0/1").partition("/")
        fps = round(int(num) / int(den or 1), 2) if den and int(den or 1) else 0.0
        return {"w": v.get("width") or 0, "h": v.get("height") or 0, "fps": fps,
                "dur": round(float(d.get("format", {}).get("duration") or 0), 2),
                "audio": has_audio}
    except Exception as e:
        log(f"probe fail {path}: {e}")
        return None


def anchor_for(path):
    """同目录下【更早】的同类视频里,挑像素数最大的那条当锚点(= 已验收的基准)。"""
    d = os.path.dirname(path)
    try:
        mine = os.path.getmtime(path)
        cands = []
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if p == path or not f.lower().endswith(VIDEO_EXT):
                continue
            if os.path.getmtime(p) >= mine:      # 只跟更早的比
                continue
            info = probe(p)
            if info:
                cands.append((info["w"] * info["h"], p, info))
        if not cands:
            return None, None
        cands.sort(reverse=True)
        return cands[0][1], cands[0][2]
    except Exception as e:
        log(f"anchor fail {path}: {e}")
        return None, None


def compare(new_i, old_i):
    bad = []
    # 2026-09-05 修真 bug: probe 探测失败返 None(见 anchor 的 return None,None),
    #   compare 原直接下标 new_i["w"] -> TypeError。探测不出尺寸=无法判降级=放行(fail-open)。
    if not new_i or not old_i:
        return bad
    if new_i["w"] * new_i["h"] < old_i["w"] * old_i["h"] * 0.95:
        drop = 100 - round(new_i["w"] * new_i["h"] / max(1, old_i["w"] * old_i["h"]) * 100)
        bad.append(f"分辨率降级 {new_i['w']}x{new_i['h']} < 锚点 {old_i['w']}x{old_i['h']}(少 {drop}% 像素)")
    if old_i["dur"] and new_i["dur"] < old_i["dur"] * 0.60:
        bad.append(f"时长缩水 {new_i['dur']}s vs 锚点 {old_i['dur']}s")
    if new_i["fps"] and old_i["fps"] and new_i["fps"] < old_i["fps"]:
        bad.append(f"帧率降级 {new_i['fps']} < {old_i['fps']}")
    if old_i["audio"] and not new_i["audio"]:
        bad.append("丢音轨(锚点有、这条没有)")
    return bad


def project_opted_out(data):
    """跨项目污染防线:任何项目都能一键关掉本闸,不用改全局配置。

    关法(任选其一,放项目根即可):
      · 建空文件  .no-media-gate
      · 或在 .claude/settings.json 里写 {"mediaGate": false}
    为什么要有:本闸装在【全局】settings.json,所有项目收尾都会跑。
    有些项目同目录本来就混放不同用途的视频(成片 + 素材片段 + 缩略预览),
    那里"新片比旧片小"是常态、不是缺陷 ⇒ 必须给它们一个不打扰的出口。
    """
    root = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ""
    if not root:
        return False
    if os.path.exists(os.path.join(root, ".no-media-gate")):
        return True
    try:
        p = os.path.join(root, ".claude", "settings.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                if json.load(f).get("mediaGate") is False:
                    return True
    except Exception:
        pass
    return False


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return
    if project_opted_out(data):
        log("skip(project opted out)")
        return
    tp = data.get("transcript_path")
    if not tp or not os.path.exists(tp):
        return

    try:
        from guard_common import load_transcript_tail, turn_start_index
        msgs = load_transcript_tail(tp)
        start = turn_start_index(msgs)
        window = msgs[start:] if start >= 0 else msgs
    except Exception:
        window, msgs = [], []
        try:
            with open(tp, encoding="utf-8") as f:
                for ln in f.readlines()[-400:]:
                    try:
                        window.append(json.loads(ln))
                    except Exception:
                        pass
        except Exception:
            return

    blob = json.dumps(window, ensure_ascii=False)
    if ACK in blob:
        log("skip(ACK)")
        return

    # 本轮文本里出现过的视频路径(生成/解压/改名后我总会把路径写进对话或命令)
    paths = set()
    for m in re.finditer(r'[A-Za-z]:[\\/][^\s"\'<>|]{3,200}?\.(?:mp4|mov|mkv|webm)', blob):
        p = m.group(0).replace("\\\\", "\\")
        if os.path.exists(p):
            paths.add(os.path.abspath(p))
    if not paths:
        return

    now = time.time()
    findings = []
    for p in sorted(paths):
        try:
            if now - os.path.getmtime(p) > 3 * 3600:   # 只看本轮新产出的(3 小时内)
                continue
        except Exception:
            continue
        new_i = probe(p)
        if not new_i:
            continue
        apath, old_i = anchor_for(p)
        if not old_i:
            continue                                    # 无参照物 → 放行
        bad = compare(new_i, old_i)
        if bad:
            findings.append((p, apath, bad))

    if not findings:
        return

    lines = ["⛔ 媒体降级闸:你这轮新出的片子,比【同目录里更早那条】变差了,而你正要收尾。",
             "   2026-08-12 实录:反打镜 576×1024/8.0s vs 锚点 768×1376/15.08s —— 我当时只验"
             "「正脸拿到没」就宣布成功,是 Frank 一眼看出画风/时长/慢动作三处问题。", ""]
    for p, a, bad in findings:
        lines.append(f"· {os.path.basename(p)}  (锚点: {os.path.basename(a)})")
        for b in bad:
            lines.append(f"    - {b}")
    lines += [
        "",
        "现在二选一,别只改措辞:",
        "  ① **重做**到不低于锚点(换应用/调分辨率参数/补足时长),再收尾;",
        f"  ② 确实是有意为之(如故意做短预告)→ 在回复里写明理由并带上 {ACK} 这个标记,本闸即放行。",
        "",
        "⛔ 另外它只判数字:**画风走样/穿错衣服/人物不对,数字一律看不出来**。",
        "   所以收尾前必须再做一件事:把【新片抽帧】和【锚点抽帧】拼成并排图,自己 Read 那张图看整体,",
        "   不是只看你想验的那一点。(2026-08-12 就是这么漏掉「真人写实变动漫脸」的)",
    ]
    reason = "\n".join(lines)
    log("BLOCK: " + "; ".join(os.path.basename(p) for p, _, _ in findings))
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:      # 闸自己崩了绝不能拖垮收尾
        log(f"FATAL {e}")
