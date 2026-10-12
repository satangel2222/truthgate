#!/usr/bin/env node
// Stop 看门狗(状态型, name-agnostic)——换掉旧的按模型名白名单 PreToolUse 守卫。
// 旧守卫两个毛病:①只认写死的模型名(whisper/qwen...),换个类别(TTS/新ASR)就漏、留孤儿拖卡;
//              ②连我自己的 nvidia-smi/ollama ps 诊断命令都误伤,狂刷三条铁律。
// 新思路:不猜命令、不认模型名,只在【每轮收尾】看 GPU 实况——
//   GPU 【持续】在算(util 多次采样都高) = 疑似我以为做完了却漏掉的活跃计算/孤儿 → block 一次让我去查+清理。
// 任何模型/工具的 GPU 活跃残留都覆盖,不用改名单;idle keep_alive(占显存但 util 低)不误报。
//
// ⛔ 2026-07-14 防误报改(实测定位):GPU util 是【剧烈抖动】的——桌面合成/浏览器解码/read_server 心跳
//    都会瞬时飙一下(实测抓到 42% 尖峰,连采三次却是 9/10/9=其实闲的)。旧版只采【一次】→ 抓到尖峰就误报。
//    也试过按进程归因排除常驻服务,但消费级 GPU 的 WDDM 模式 `nvidia-smi --query-compute-apps` 显存全 N/A、
//    列的还是一堆桌面程序,归因这条路在本机废掉。所以治本 = 看【持续】不看单次尖峰:先便宜采一次,
//    低就立刻放行(常见情况零额外开销);只有第一次就高才多采几次确认——真任务 util 持续高、尖峰只闪一下。
// 只查 nvidia-smi(闲时 ~170ms);CPU-fallback 型孤儿(whisper 掉 CPU、GPU util 低)已被代码层每个 spawn 的
//   timeout+SIGKILL 兜住(最多跑到超时即被杀),不靠本 hook。5 分钟内不重复;检测不到静默放行,零噪音。
const fs = require('fs');
const cp = require('child_process');
const os = require('os');
const path = require('path');

let data = {};
try { data = JSON.parse(fs.readFileSync(0, 'utf8')); } catch {}

// 已经是"被 block 后重进"的收尾 → 放行,避免自叠
if (data.stop_hook_active) process.exit(0);

// 防循环:5 分钟内 block 过就放行(合法长任务不无限 nag)
const STAMP = path.join(os.tmpdir(), 'gpu-watchdog-lastblock');
const NOW = Date.now();
try {
  const t = parseInt(fs.readFileSync(STAMP, 'utf8'), 10);
  if (Number.isFinite(t) && NOW - t < 5 * 60 * 1000) process.exit(0);
} catch {}

function run(file, args) {
  try { return cp.execFileSync(file, args, { timeout: 6000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim(); }
  catch { return ''; }
}
function sleepSync(ms) { try { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms); } catch {} }
// ⛔ 测试注入口(2026-07-29 补):这道闸此前**没有任何回归测试**,而它偏偏是防误报逻辑
//    最精细的一道(4 采样取 3 高)。在 Windows 上没法用假 .cmd 顶掉 nvidia-smi ——
//    `execFileSync` 不走 shell,实测拿到的仍是真 nvidia-smi.exe(我第一版测试因此有几条是假绿)。
//    ⇒ 留一个只在测试里设的环境变量,按序返回预设采样值。生产环境不设 = 行为完全不变。
// ⛔ 双钥匙(外部 critic 2026-07-29):单一环境变量是【没上锁的注射口】—— 一旦被写进
//    shell profile / pm2 ecosystem / CI env,这道闸就永久变成假数据驱动,而普查器看不出来
//    (它零日志、B 判据不评估)。⇒ 必须同时设 SUPEREGO_TEST=1 才生效,且生效时往 stderr 喊一声。
let _fakeIdx = 0;
const _fakeRaw = (process.env.GPU_WATCHDOG_FAKE_UTIL || '').trim();
const FAKE = (_fakeRaw && process.env.SUPEREGO_TEST === '1') ? _fakeRaw : '';
if (_fakeRaw && !FAKE) {
  try { process.stderr.write('⚠️ GPU_WATCHDOG_FAKE_UTIL 已设但缺 SUPEREGO_TEST=1 → 忽略,走真 nvidia-smi\n'); } catch {}
} else if (FAKE) {
  try { process.stderr.write('⚠️ [测试模式] GPU 采样走注入值 ' + FAKE + ',不是真实 GPU\n'); } catch {}
}
function gpuUtil() {
  if (FAKE) {
    const arr = FAKE.split(',').map((s) => parseInt(s.trim(), 10)).filter(Number.isFinite);
    if (!arr.length) return null;
    const v = arr[Math.min(_fakeIdx, arr.length - 1)];
    _fakeIdx += 1;
    return v < 0 ? null : v;        // 负数 = 模拟"取不到 GPU"
  }
  const g = run('nvidia-smi', ['--query-gpu=utilization.gpu', '--format=csv,noheader,nounits']);
  if (!g) return null;
  const n = parseInt(g.split('\n')[0].trim(), 10);
  return Number.isFinite(n) ? n : null;
}
const THRESH = 40;   // util ≥ 40% 算"活跃"
const SAMPLES = 4;   // 命中后再采样确认"持续"
const NEED = 3;      // 4 次里至少 3 次高才算真任务(容忍单次尖峰/回落)

// 便宜的第一次采样:低就立刻放行(常见情况,零额外开销)
const first = gpuUtil();
if (first == null) process.exit(0);        // 没 GPU / 取不到
if (first < THRESH) process.exit(0);       // GPU 空闲/仅 idle 常驻,静默放行

// 第一次就高 → 可疑,多采几次确认是【持续】高还是一闪而过的尖峰(桌面渲染/浏览器/心跳)
const samples = [first];
for (let i = 1; i < SAMPLES; i++) { sleepSync(400); const u = gpuUtil(); if (u != null) samples.push(u); }
const highCount = samples.filter((u) => u >= THRESH).length;
if (highCount < NEED) process.exit(0);     // 只是尖峰、不是持续负载 → 不报(防误报核心)

try { fs.writeFileSync(STAMP, String(NOW)); } catch {}

const mem = (run('nvidia-smi', ['--query-gpu=memory.used', '--format=csv,noheader,nounits']).split('\n')[0] || '').trim();
const reason =
  `⚠️ [收尾看门狗] 这一轮要结束,但 GPU 【持续】在算(util 采样 ${samples.join('/')}% ,${mem} MiB)。\n` +
  '这正是"留孤儿导致卡顿"的现场特征(2026-07-14 事故)。持续高 ≠ 瞬时尖峰,大概率真有东西在跑。分两种情况再收尾:\n' +
  '① 有意启动且在追踪的后台任务(run_in_background 的下载/转录等),或用户刚在 TG 触发的读图/转录/分镜——确认它有上界(会自己结束或你会清理),即可正常结束。\n' +
  '② 你以为这轮已做完、不该有东西在跑 = 漏网孤儿。查 `nvidia-smi` + `ollama ps` + `Get-Process python,node,ffmpeg`,按 CommandLine 确认后 `Stop-Process -Force` 杀掉,再 nvidia-smi 确认显存归还。\n' +
  '(需 util 多次采样持续≥40%(排除瞬时尖峰)才触发、5 分钟内不重复;看 GPU 实况不看命令名。真做完就查一下再收尾。)';

process.stdout.write(JSON.stringify({ decision: 'block', reason }));
process.exit(0);
