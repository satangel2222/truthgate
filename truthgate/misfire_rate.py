"""一周误拦率 → 自动降级（PLAN 第 5 步：一周误拦率超过五分之一，自动降成只记账并报 Frank）。
「误拦」：闸拦了我，我在回复里写一行「误报：<闸名> — <理由>」（两端同一个说法；AG 桥接 9/25 起就认这句）。
  Claude 端：扫近 7 天会话记录 —— 那道闸本轮拦过我（收尾反馈 / 调用工具前的报错里段头是它的命令），之后我写了这句 ⇒ 记一次；
  AG 端：桥接记在 hooks/semantic-superego-gate.log 的 MISFIRE-CLAIMED。
「拦截」：闸自己的日志（只数带时间戳、窗口内的 BLOCK / DENY）+ AG 桥接记的 trig='<闸>' BLOCK。
误拦 / 拦截 > 1/5、且拦满 5 次 ⇒ 写进 ~/.claude/superego-observe.json 的 observe（两端同一个开关），记下日期和数；
安全 / 红线 / 资源 / 数据 / 防失控类（定案理由以这几个字开头，或共用层的永不熔断名单）只报不降 —— 后果不可逆，误拦多也由他定。
结果写 state/misfire-rate.json；开局核对（source_news.alarms）读它，把自动降级和「安全类误拦偏高」报出来。
用法：py -3 misfire_rate.py [--dry-run] [--days 7]
"""
import argparse, datetime as dt, glob, json, os, re, shutil, sys, time
from collections import Counter
from pathlib import Path

H = Path.home()
TG = H / '.truthgate'
RATE, MIN_BLOCKS = 0.2, 5
SAFE_PREFIX = ('安全', '红线', '资源', '数据', '防失控')
MISFIRE_RE = re.compile(r"误报[:：]\s*([a-z0-9-]+)\s*[—\-–]+\s*(.{4,200})")
GATE_HDR = re.compile(r'\[[^\]\n]*?[/\\]([\w.-]+?)\.(?:py|cjs|mjs|js)"?\]:')   # 收尾反馈 / 调用工具前报错里的段头
TS = re.compile(r'^(20\d\d-\d\d-\d\d) (\d\d:\d\d:\d\d)')


def log_blocks(hooks, since):
    """闸日志里窗口内的真拦截（BLOCK / DENY，不含只记账的 WOULDBLOCK）+ AG 桥接记的拦截。"""
    c = Counter()
    for p in glob.glob(os.path.join(hooks, '*.log')):
        name = os.path.basename(p)[:-4]
        if name.endswith('.test') or '.lost.' in name:
            continue
        try:
            for line in open(p, encoding='utf-8', errors='replace'):
                m = TS.match(line)
                if not m or f'{m.group(1)} {m.group(2)}' < since:
                    continue
                if name == 'semantic-superego-gate':
                    g = re.search(r"\[antigravity\|[^\]]*\] trig='([\w-]+)' BLOCK\b", line)
                    if g:
                        c[g.group(1)] += 1
                elif re.search(r'\b(?:BLOCK|DENY)\b', line) and not re.search(r'\bWOULD(?:BLOCK|NUDGE)', line):
                    c[name] += 1
        except OSError:
            pass
    return c


def ag_misfires(hooks, since):
    c = Counter()
    p = os.path.join(hooks, 'semantic-superego-gate.log')
    try:
        for line in open(p, encoding='utf-8', errors='replace'):
            m = TS.match(line)
            g = re.search(r"trig='([\w-]+)' MISFIRE-CLAIMED", line)
            if m and g and f'{m.group(1)} {m.group(2)}' >= since:
                c[g.group(1)] += 1
    except OSError:
        pass
    return c


def claude_misfires(projects, since_epoch):
    """会话记录里：本轮被那道闸拦过、之后我写了「误报：<它> — 理由」⇒ 记一次（一轮同一道闸只记一次）。"""
    sys.path.insert(0, str(TG / 'hooks'))
    from guard_common import is_real_user_msg, _text_of
    since_iso = dt.datetime.fromtimestamp(since_epoch, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    c, reasons = Counter(), {}
    for p in glob.glob(os.path.join(projects, '*', '*.jsonl')):
        try:
            if os.path.getmtime(p) < since_epoch:
                continue
            with open(p, 'rb') as f:
                b = f.read()
        except OSError:
            continue
        if '误报'.encode('utf-8') not in b:
            continue
        blocked, claimed = set(), set()
        for line in b.split(b'\n'):
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get('timestamp', '') < since_iso:
                continue
            if is_real_user_msg(m):
                blocked, claimed = set(), set()
                continue
            t = _text_of((m.get('message') or {}).get('content'))
            if m.get('type') == 'user':
                blocked |= set(GATE_HDR.findall(t))
            elif m.get('type') == 'assistant':
                for g, why in MISFIRE_RE.findall(t):
                    if g in blocked and g not in claimed:
                        claimed.add(g)
                        c[g] += 1
                        reasons.setdefault(g, why.strip()[:120])
    return c, reasons


def decide(blocks, misfires, observe, keep_reasons, never):
    out = []
    for g, n in blocks.items():
        m = misfires.get(g, 0)
        if n < MIN_BLOCKS or m / n <= RATE or g in observe:
            continue
        safe = g in never or (keep_reasons.get(g) or '').startswith(SAFE_PREFIX)
        out.append({'gate': g, 'blocks': n, 'misfires': m, 'rate': round(m / n, 2), 'action': 'report' if safe else 'demote'})
    return sorted(out, key=lambda x: -x['rate'])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    obs_p = Path(os.environ.get('SUPEREGO_OBSERVE_FILE') or H / '.claude' / 'superego-observe.json')
    hooks = os.environ.get('TG_MF_HOOKS') or str(TG / 'hooks')
    projects = os.environ.get('TG_TRANSCRIPTS') or str(H / '.claude' / 'projects')
    state_p = Path(os.environ.get('TG_MF_STATE') or TG / 'state' / 'misfire-rate.json')
    since_epoch = time.time() - a.days * 86400
    since = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(since_epoch))
    blocks = log_blocks(hooks, since)
    cm, reasons = claude_misfires(projects, since_epoch)
    misfires = cm + ag_misfires(hooks, since)
    obs = json.loads(obs_p.read_text(encoding='utf-8'))
    dec_files = sorted(glob.glob(str(TG / 'exam' / 'gate-decisions-*.json')))
    keep = (json.loads(Path(dec_files[-1]).read_text(encoding='utf-8')).get('keep') or {}) if dec_files else {}
    sys.path.insert(0, str(TG / 'hooks'))
    from guard_common import _BUDGET_NEVER
    todo = decide(blocks, misfires, set(obs.get('observe') or []), keep, _BUDGET_NEVER)
    for x in todo:
        x['why'] = reasons.get(x['gate'], '')
    demote = [x for x in todo if x['action'] == 'demote']
    if demote and not a.dry_run:
        shutil.copy(obs_p, obs_p.with_name(obs_p.name + '.bak-before-auto-demote-' + time.strftime('%Y%m%d-%H%M%S')))
        obs.setdefault('observe', []).extend(x['gate'] for x in demote)
        auto = obs.setdefault('_auto_demoted', {})
        for x in demote:
            auto[x['gate']] = f"{time.strftime('%Y-%m-%d')} 近 {a.days} 天误拦 {x['misfires']}/{x['blocks']}（> 1/5）自动降成只记账（misfire_rate.py）"
        obs_p.write_text(json.dumps(obs, ensure_ascii=False, indent=1), encoding='utf-8')
    state = {'ran_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'days': a.days, 'dry_run': a.dry_run, 'decisions': todo,
             'stats': {g: [n, misfires.get(g, 0)] for g, n in blocks.most_common()}}
    if not a.dry_run:
        state_p.parent.mkdir(parents=True, exist_ok=True)
        state_p.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'decisions': todo, 'misfires': dict(misfires)}, ensure_ascii=False))
    return state


if __name__ == '__main__':
    main()
