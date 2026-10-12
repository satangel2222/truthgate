#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""visual-detail-gate — 拦【看了缩略图/拼图就对画面内容下正面结论】。

⛔ 来历(2026-08-18,Frank:「你居然没看生成出来的效果?为何 superego 又坏掉嘛?」):
   我生成第一条视频后,抽 4 帧拼成一张 1680x321 的 tile 图(单格仅 13.5 万像素),
   Read 了它,然后宣布「运镜和内容都对上了」。
   Frank 让我真看,按原分辨率(1088x832 = 90.5 万像素)逐帧再看 —— **是废片**:
   人物复制成两个一模一样的女人、男主角完全没出现、酒局场景全错、站位错、动作错。
   **两者差 6.7 倍;那个尺寸下我根本看不出「画面里有两个人」这种事。**

⛔ 为什么 visual-proof-gate 放行了我(读它源码实测):
   它的判据第③条是「本轮**没有任何取画面的动作**(captureScreenshot / 读过 .png)」。
   我读了 .png ⇒ 它放行。**它验的是"动作发生过",不是"证据够不够看清"。**
   ⇒ 本闸补那一层:不看动作,看**被读的那张图单画面有多少像素**。

⛔ 分工:visual-proof-gate 防「压根没看图就说画面正常」;
   本闸防「看了图,但看的是降维后的缩略图/拼图」。
   历史同形状:lessons「形状W:把【降维后的表示】当成【现场】」—— 本次第 12 次。

⛔ 先查现成(2026-08-18):WebSearch「low resolution thumbnail quality gate minimum pixels」
   → 命中的全是**给人用的在线画质检测网站**(测模糊/噪点/DPI/压缩率),
   没有「拦 agent 拿缩略图下结论」这种东西 ⇒ **只能自建**。
   但业界基线可用来校准阈值:**640x360(23 万像素)是 AI 处理最低可用线,低于此人脸出伪影**
   ⇒ 本闸取 30 万(~640x470),卡在安全侧。

判据(三条同时成立才拦,宁漏勿误杀):
  ① 本轮对画面内容下了**正面结论**(对上了/没问题/正常/成功/可用…)
  ② 本轮 Read 过图片
  ③ 那些图里**最大的单画面有效像素 < MIN_PIXELS**(拼图按 tile 格数均摊)
真实靶验证:害我误判的拼图 134,820 像素 → 拦;原帧 905,216 像素 → 放行。
"""
import json
import os
import re
import struct
import sys
from pathlib import Path

LOG = Path.home() / ".claude" / "hooks" / "visual-detail-gate.log"
MIN_PIXELS = 300_000
IMG_EXT = re.compile(r"\.(png|jpe?g|webp)$", re.I)

VERDICT = re.compile(
    "(对上了|都对|没问题|没崩|正常|符合预期|符合要求|成功了?|可用|能用|不错|挺好"
    "|画面(很)?(好|干净|稳)|运镜.{0,4}(对|好)|锁脸.{0,4}(住|好|稳)"
    "|一致性.{0,4}(好|没问题))")
NEGATIVE = re.compile("(废片|崩|不对|错了|重来|不合格|有问题|失败|漏了|全错|重生成)")
TILE = re.compile(r"tile=(\d+)x(\d+)")


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(m + "\n")
    except Exception:
        pass


def img_size(p):
    """只读文件头拿尺寸,不解码整张图(便宜、无依赖)。"""
    try:
        with open(p, "rb") as f:
            head = f.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", head[16:24])
            return w, h
        if head[:2] == b"\xff\xd8":
            with open(p, "rb") as f:
                d = f.read()
            i = 2
            while i < len(d) - 9:
                if d[i] != 0xFF:
                    i += 1
                    continue
                marker = d[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                    h, w = struct.unpack(">HH", d[i + 5:i + 9])
                    return w, h
                i += 2 + struct.unpack(">H", d[i + 2:i + 4])[0]
    except Exception:
        pass
    return None


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

    said, imgs, tiles = [], [], 1
    for m in turn:
        if m.get("type") != "assistant":
            continue
        for c in ((m.get("message") or {}).get("content") or []):
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                said.append(c.get("text") or "")
            elif c.get("type") == "tool_use":
                inp = c.get("input") or {}
                blob = json.dumps(inp, ensure_ascii=False)
                t = TILE.search(blob)
                if t:
                    tiles = max(tiles, int(t.group(1)) * int(t.group(2)))
                if c.get("name") == "Read":
                    fp = inp.get("file_path") or ""
                    if IMG_EXT.search(fp):
                        imgs.append(fp)

    tail = "\n".join(said)[-1200:]
    if not imgs:
        _log("pass(no image read)")
        return 0
    if not VERDICT.search(tail):
        _log("pass(no positive verdict)")
        return 0
    if NEGATIVE.search(tail):
        _log("pass(negative verdict = 在挑刺)")
        return 0

    best, detail = 0, []
    for p in imgs:
        wh = img_size(p) if os.path.exists(p) else None
        if not wh:
            _log("pass(size unknown) " + os.path.basename(p))
            return 0
        # ⛔ 2026-08-18 打靶抓到的自身 bug:原来把 tiles 全局套在【每一张】图上 ——
        #    本轮只要出现过一次 tile=4x1,连原分辨率单帧也被除以 4(90.5万→22.6万),
        #    于是"我明明看了清晰单帧"也被误拦。
        #    修法:只对【确实像拼图】的那张均摊 —— 判据是极端宽高比(拼图必然被拉得很扁/很长)。
        ar = wh[0] / wh[1] if wh[1] else 1
        is_tile = tiles > 1 and (ar >= 2.5 or ar <= 0.4)
        per = (wh[0] * wh[1]) // (tiles if is_tile else 1)
        detail.append("%s %dx%d/%d格=%d像素" % (os.path.basename(p), wh[0], wh[1], tiles, per))
        best = max(best, per)
    if best >= MIN_PIXELS:
        _log("pass(%d px) %s" % (best, "; ".join(detail)))
        return 0

    _log("BLOCK %d px %s" % (best, "; ".join(detail)))
    print(json.dumps({"decision": "block", "reason": (
        "⛔ 画面细节闸:你对画面下了【正面结论】,但本轮 Read 的图**单画面只有 %d 像素**"
        "(阈值 %d)。%s\n"
        "⛔ 实录(2026-08-18):我抽 4 帧拼成 1680x321 的 tile 图(单格 13.5 万像素)、Read 了它,"
        "就宣布「运镜和内容都对上了」。按原分辨率(90.5 万像素)逐帧再看 —— **是废片**:"
        "人物复制成两个一模一样的女人、男主角完全没出现、场景全错。**两者差 6.7 倍。**\n"
        "⛔ `visual-proof-gate` 验的是「有没有取过画面」,我读了 .png 它就放行 —— "
        "**它管动作发生过,管不了证据够不够看清**。本闸补那一层。\n"
        "业界基线:640x360(23 万像素)是 AI 处理最低可用线,低于此人脸出伪影。\n"
        "历史同形状:lessons「形状W:把【降维后的表示】当成【现场】」,本次第 12 次。\n"
        "现在:按**原分辨率**抽单帧(别 tile、别 scale 缩小)重新 Read,再下结论。"
    ) % (best, MIN_PIXELS, "; ".join(detail))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
