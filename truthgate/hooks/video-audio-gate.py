#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""video-audio-gate — 拦【交付视频却没验音轨/没转录核字】。

⛔ 来历(2026-08-18,Frank:「连个台词都没有?」「凡是视频不能直接出台词和字幕
   需要后期的都不许有用」):
   我用 Agnes 生了一条 15 秒竖屏视频,ffprobe 查了**分辨率**、查了**时长**、抽帧看了画面,
   宣布「技术链路 100% 跑通」。Frank 一眼指出没台词。
   ⛔ 最难堪的是:H3 现场手册第 201 行【是我自己写的】——
      「交付前必做:`ffprobe` 核时长/分辨率/**有没有音轨** + 抽帧自己看 +
        需要对白就**转录核字**」
      我执行了「时长/分辨率/抽帧」三项,**唯独跳过音轨那一项**,而那正是唯一出问题的一项。
   ⇒ 光写进手册拦不住(我自己写的第 201 行我自己没执行)。必须变成结构性拦截。

⛔ 连带翻车:我随后又说那条是「默片」—— 也是没验就说的。
   实测它**有 AAC 轨**,只是 mean_volume -28dB 全是环境音、没有人声。
   ⇒ 「有没有 audio stream」和「音轨里有没有台词」是**两件事**,本闸两件都管。

⛔ 先查现成(2026-08-18,WebSearch「automated check generated video has audio track
   dialogue verification quality gate CI」)→ 判定 **只能自建,但判据照抄业界**:
   · 命中的现成件(Telestream Cloud QC / promwad AI-QC)全是**商业广电 QC 平台**,
     要付费要上传,不是能挂进 agent 的闸。
   · 但业界判据可直接抄,原文:「Quality gates verify that video files exist in expected
     locations, that MP4 files are playable, **that the final video has an audio stream**,
     and that the measured duration is inside the requested tolerance.」
   · 对白验证的业界做法:「automates dialogue verification using **speech-to-text**,
     transcribing spoken dialogue and **aligning it with subtitle files**」⇒ 本闸第③条。

⛔ 分工(别和已有的闸重复造):
   · `visual-proof-gate`   防「压根没取过画面就说画面正常」
   · `visual-detail-gate`  防「取了画面,但看的是降维缩略图」(判据=单画面像素数)
   · **本闸**              防「画面验了,**音轨没验**」(判据=audio stream + 是否转录过)
   三者判据正交:动作有没有发生 / 视觉证据够不够清 / 听觉证据验没验。

判据(全部成立才拦,宁漏勿误杀):
  ① 本轮对视频下了**交付类正面结论**(跑通/完成/成片/可用/出片了…)
  ② 本轮有视频产物(工具调用里出现 .mp4/.mov/.webm/.mkv)
  ③ 以下任一:
     a) ffprobe 显示该视频**完全没有 audio stream**
     b) 有音轨,但本轮**从未做过任何音频侧验证**(没查过音频流、没测过音量、没转录)
真实靶验证见 test_video_audio_gate.py(用 2026-08-18 这次的真实错误数据打靶)。
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

LOG = Path.home() / ".claude" / "hooks" / "video-audio-gate.log"
# ⛔ 2026-08-18 打靶抓到的自身 bug:第一版把冒号写进排除类,
#    Windows 路径 `C:\x\y.mp4` 被从盘符处截断成 `\x\y.mp4` ⇒ 文件找不到 ⇒
#    has_audio_stream 返回 None ⇒ 走「测不出不猜」放行,**整道闸对本机路径永远开不了火**。
#    (抄判据的坑:visual-detail-gate 从 Read 的结构化 file_path 取路径,
#     本闸要从 Bash 命令【字符串】里提,盘符冒号就成了雷。)
#    修法:冒号仍排除(否则 `-of csv=p=0` 之类会粘进来),但前面补一个可选盘符前缀。
VID_EXT = re.compile(
    r"(?:[A-Za-z]:)?[^\s\"'`,;:()\[\]<>|]+\.(?:mp4|mov|webm|mkv|m4v)", re.I)

# ① 交付类正面结论
VERDICT = re.compile(
    "(跑通|打通|完成|成片|出片|可用|能用|成功了?|搞定|没问题|正常"
    "|链路.{0,6}(通|好)|交付|已生成|生成好了|做好了|全部产出)")
# 在挑刺/在报失败 → 放行
NEGATIVE = re.compile(
    "(废片|崩了|不对|错了|重来|不合格|有问题|失败|漏了|全错|重生成|没音|无音轨|默片|返工)")

# ③b 音频侧验证动作(本轮做过其中任意一种就算验过)
AUDIO_CHECK = re.compile(
    r"(select_streams\s+a|codec_type|volumedetect|mean_volume|astats"
    r"|transcribe|whisper|\.srt|\.ass|\.vtt|媒体转录|media-transcribe)", re.I)


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(m + "\n")
    except Exception:
        pass


def has_audio_stream(path):
    """None = 测不出(没 ffprobe / 文件不在),不猜、不拦。"""
    ff = shutil.which("ffprobe")
    if not ff or not os.path.exists(path):
        return None
    try:
        r = subprocess.run(
            [ff, "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return bool((r.stdout or "").strip())


def collect(turn):
    said, vids, checked = [], [], False
    for m in turn:
        if m.get("type") != "assistant":
            continue
        for c in ((m.get("message") or {}).get("content") or []):
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                said.append(c.get("text") or "")
            elif c.get("type") == "tool_use":
                blob = json.dumps(c.get("input") or {}, ensure_ascii=False)
                if AUDIO_CHECK.search(blob):
                    checked = True
                for mm in VID_EXT.finditer(blob):
                    v = mm.group(0).replace("\\\\", "\\")
                    if v not in vids:
                        vids.append(v)
    return said, vids, checked


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tp = data.get("transcript_path")
    if not tp or not Path(tp).exists():
        return 0
    sys.path.insert(0, str(Path.home() / ".claude" / "hooks"))
    try:
        from guard_common import load_transcript_tail, turn_start_index
        msgs = load_transcript_tail(tp)
        st = turn_start_index(msgs)
        turn = msgs[st:] if st >= 0 else msgs
    except Exception:
        return 0

    said, vids, checked = collect(turn)
    tail = "\n".join(said)[-1500:]

    if not vids:
        _log("pass(no video)")
        return 0
    if not VERDICT.search(tail):
        _log("pass(no delivery verdict)")
        return 0
    if NEGATIVE.search(tail):
        _log("pass(negative = 在挑刺/在报失败)")
        return 0

    verdicts = [(v, has_audio_stream(v)) for v in vids]
    known = [(v, a) for v, a in verdicts if a is not None]
    if not known:
        _log("pass(ffprobe 测不出,不猜) " + "; ".join(v for v, _ in verdicts))
        return 0

    silent = [v for v, a in known if not a]
    if silent:
        why = "这些视频**完全没有音频流**:" + "、".join(os.path.basename(v) for v in silent)
    elif not checked:
        why = ("视频有音轨,但本轮**没做过任何音频侧验证** —— "
               "没查过音频流、没测过音量、没转录核过字。有音轨 ≠ 里面有台词。")
    else:
        _log("pass(has audio + checked) " + "; ".join(os.path.basename(v) for v, _ in known))
        return 0

    _log("BLOCK %s | %s" % (why[:60], "; ".join(os.path.basename(v) for v, _ in known)))
    print(json.dumps({"decision": "block", "reason": (
        "⛔ 视频音轨闸:你对视频下了【交付类结论】,但 %s\n"
        "⛔ 实录(2026-08-18):我生了一条 15 秒竖屏视频,ffprobe 查了**分辨率**、查了**时长**、"
        "抽帧看了画面,宣布「技术链路 100%% 跑通」。Frank 一眼:「连个台词都没有?」\n"
        "   最难堪的是 H3 现场手册第 201 行**是我自己写的**:「交付前必做 ffprobe 核时长/"
        "分辨率/**有没有音轨** + 抽帧自己看 + 需要对白就**转录核字**」——"
        "我执行了三项,唯独跳过音轨那一项,而那正是唯一出问题的一项。\n"
        "⛔ 而且「有 audio stream」≠「里面有台词」:那条其实**有 AAC 轨**,"
        "但 mean_volume -28dB 全是环境音、一句人声都没有。**两件事,都要验。**\n"
        "⛔ Frank 铁律:「凡是视频不能直接出台词和字幕需要后期的都不许有用」。\n"
        "现在做完这三步再下结论:\n"
        "  1. `ffprobe -v error -select_streams a -show_entries stream=codec_name "
        "-of csv=p=0 <video>`  → 空 = 无音轨\n"
        "  2. `ffmpeg -i <video> -af volumedetect -f null - `  → mean_volume 极低 = 静音轨\n"
        "  3. `python ~/.claude/skills/media-transcribe-free/scripts/transcribe.py <video> "
        "-o out.srt` → **读出来的字要和剧本台词对得上**\n"
        "(在挑刺/如实报「没音轨/是默片/要返工」的措辞本闸放行 —— 它只拦【说好话时漏验】。)"
    ) % why}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
