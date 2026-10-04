#!/usr/bin/env python3
"""Fast-paced 9:16 FX reel from a speaker video (the "edit showcase" style).

    python3 fx_reel.py fx.json

Prerequisite: run build.py on the same video first (it produces <work>/clean.wav, words.json,
map.png). fx.json points at that work dir via "from_work". See templates/fx.example.json.

Effects (all anchored to words of the approved transcript, "word#2" = 2nd occurrence):
intro pixel-assemble + flying title letters, name tag, silence cut + speed-up, word-by-word
captions, a transition on every jump cut (spin / pixel / whip / glitch / zoom-blur / flip / jump),
time-stop freeze, zoom punches, slam word with shake + glitch, shrink-and-bounce, pop-art 2x2
clone, map drop with pin, count-up numbers that hold the final value, fly-in words, iris outro.
Audio: cleaned speech (sped up, 10ms fades at joins) + synthesized beat and SFX, both ducked
under the speech.
"""
import json, math, os, re, subprocess, sys, random, difflib, bisect, wave
import numpy as np, cv2

HERE = os.path.dirname(os.path.abspath(__file__)); SKILL = os.path.dirname(HERE); ASSETS = os.path.join(SKILL, 'assets')
CACHE = os.environ.get('ZN_CACHE', os.path.expanduser('~/.cache/zan-nadir-video')); FF = os.path.join(CACHE, 'ffmpeg')
cfg = json.load(open(sys.argv[1])); base = os.path.dirname(os.path.abspath(sys.argv[1]))
P = lambda p: p if os.path.isabs(p) else os.path.join(base, p)
SRC, OUT, WORK = P(cfg['video']), P(cfg['out']), P(cfg['from_work'])
TMP = OUT + '.fx'; os.makedirs(TMP, exist_ok=True)
T0, T1 = cfg.get('trim', [0, None])
SP = cfg.get('speed', 1.1)
W, H, FPS = 1080, 1920, 30
CW, CH, CX, CY, CAPY, TOPY = 1000, 564, 540, 880, 1345, 380
random.seed(7)
def run(c, **k): return subprocess.run(c, check=True, **k)

# ---------------- source + audio ----------------
probe = subprocess.run([FF, '-i', SRC], capture_output=True, text=True).stderr
sw, sh = map(int, re.search(r'Video:.*?(\d{2,5})x(\d{2,5})', probe).groups())
SFPS = float(re.search(r'([\d.]+) fps', probe).group(1))
dur = sum(float(x) * m for x, m in zip(re.search(r'Duration: (\d+):(\d+):([\d.]+)', probe).groups(), (3600, 60, 1)))
T1 = T1 or dur
raw = subprocess.run([FF, '-v', 'error', '-ss', str(T0), '-t', str(T1 - T0 + 0.1), '-i', SRC, '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True).stdout
SF = np.frombuffer(raw, np.uint8).reshape(-1, sh, sw, 3)
SR = 48000
def load(p):
    r = subprocess.run([FF, '-v', 'error', '-i', p, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], capture_output=True).stdout
    return np.frombuffer(r, np.float32).copy()
speech_src = load(os.path.join(WORK, 'clean.wav'))       # already trimmed by build.py to the same trim
D_SRC = min(T1 - T0, len(speech_src) / SR)

# ---------------- silence EDL ----------------
hop = SR // 100; n = len(speech_src) // hop
db = 20 * np.log10(np.sqrt((speech_src[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12))
db = np.convolve(db, np.ones(9) / 9, 'same'); thr = max(np.percentile(db, 25), -42)
edl = []; cur = 0.0; i = 0
while i < n:
    if db[i] < thr:
        j = i
        while j < n and db[j] < thr: j += 1
        if (j - i) >= cfg.get('min_silence', 0.3) * 100:
            a, b = i / 100 + 0.10, j / 100 - 0.08
            if b - a > 0.05 and a < D_SRC:
                if a > cur: edl.append((cur, a))
                cur = b
        i = j
    else: i += 1
if cur < D_SRC: edl.append((cur, D_SRC))
edl = [(a, min(b, D_SRC)) for a, b in edl if min(b, D_SRC) - a > 0.15]

# ---------------- word times of the approved transcript ----------------
def norm(ch):
    ch = {'ך': 'כ', 'ם': 'מ', 'ן': 'נ', 'ף': 'פ', 'ץ': 'צ'}.get(ch, ch); return ch if re.match(r'\w', ch) else ''
WW = json.load(open(os.path.join(WORK, 'words.json')))['words']
wc, wt = [], []
for w in WW:
    L = [c for c in map(norm, w['text']) if c]; m_ = max(len(L), 1)
    for k, c in enumerate(L): wc.append(c); wt.append(w['start'] + (w['end'] - w['start']) * (k + .5) / m_)
text = open(P(cfg['transcript_file']), encoding='utf-8').read().replace('|', ' ').split()
tc, ti = [], []
for k, wd in enumerate(text):
    for c in wd:
        c = norm(c)
        if c: tc.append(c); ti.append(k)
tt_ = [None] * len(tc)
for a, b, s in difflib.SequenceMatcher(None, tc, wc, autojunk=False).get_matching_blocks():
    for j in range(s): tt_[a + j] = wt[b + j]
kn = [k for k, v in enumerate(tt_) if v is not None]
for k in range(len(tt_)):
    if tt_[k] is None:
        p = bisect.bisect_left(kn, k); lo = kn[p - 1] if p > 0 else None; hi = kn[p] if p < len(kn) else None
        tt_[k] = tt_[lo] if hi is None else tt_[hi] if lo is None else tt_[lo] + (tt_[hi] - tt_[lo]) * (k - lo) / (hi - lo)
words = []
for k, wd in enumerate(text):
    ts = [tt_[q] for q in range(len(tc)) if ti[q] == k] or [0]
    words.append({'w': wd, 's': min(ts) - 0.05, 'e': max(ts) + 0.12})
def widx(ref):
    t, _, occ = ref.partition('#'); occ = int(occ or 1); c = 0
    for k, w in enumerate(words):
        if w['w'] == t or re.sub(r'[,.!?]$', '', w['w']) == t:
            c += 1
            if c == occ: return k
    raise SystemExit(f'word not found in transcript: {ref!r}')
chunks = []; curc = []
for k, w in enumerate(words):
    curc.append(k)
    if len(curc) >= 3 or len(' '.join(words[q]['w'] for q in curc)) >= 15 or w['w'][-1] in ',.?!': chunks.append(curc); curc = []
if curc: chunks.append(curc)

# ---------------- timeline ----------------
fz = cfg.get('freeze'); FREEZE_AFTER = words[widx(fz['after'])]['e'] - 0.02 if fz else -1
INTRO, FREEZE_D, END_HOLD, OUTRO = 1.5, fz.get('dur', 1.5) if fz else 0, 0.5, 2.9
segs = [('intro', 0, INTRO, 0, 0)]; t = INTRO
for a, b in edl:
    if a < FREEZE_AFTER < b:
        segs.append(('clip', t, (FREEZE_AFTER - a) / SP, a, FREEZE_AFTER)); t += (FREEZE_AFTER - a) / SP
        segs.append(('freeze', t, FREEZE_D, FREEZE_AFTER, FREEZE_AFTER)); t += FREEZE_D
        segs.append(('clip', t, (b - FREEZE_AFTER) / SP, FREEZE_AFTER, b)); t += (b - FREEZE_AFTER) / SP
    else:
        segs.append(('clip', t, (b - a) / SP, a, b)); t += (b - a) / SP
last_src = edl[-1][1] - 0.05
segs.append(('hold', t, END_HOLD, last_src, last_src)); t += END_HOLD
OUTRO_T = t; segs.append(('outro', t, OUTRO, 0, 0)); TOTAL = t + OUTRO
FREEZE_T = next((s[1] for s in segs if s[0] == 'freeze'), -99)
def seg_at(x):
    for s in segs:
        if s[1] <= x < s[1] + s[2]: return s
    return segs[-1]
def src_at(x):
    s = seg_at(x)
    return s[3] + (x - s[1]) * SP if s[0] == 'clip' else (s[3] if s[0] in ('freeze', 'hold') else (0.0 if s[0] == 'intro' else last_src))
def out_of(src):
    for s in segs:
        if s[0] == 'clip' and s[3] - 1e-6 <= src <= s[4] + 1e-6: return s[1] + (src - s[3]) / SP
    nxt = [s for s in segs if s[0] == 'clip' and s[3] > src]
    return nxt[0][1] if nxt else OUTRO_T
WS = [out_of(w['s']) for w in words]; WE = [out_of(w['e']) for w in words]
at = lambda ref: WS[widx(ref)]

EV = {}
EV['punch'] = [at(r) for r in cfg.get('punch', [])]
if cfg.get('slam'): EV['slam'] = at(cfg['slam']['at'])
if cfg.get('shrink'): EV['shrink'] = (at(cfg['shrink']['from']), at(cfg['shrink']['to']) + 0.15)
if cfg.get('shrink', {}).get('chip'): EV['chip'] = at(cfg['shrink']['chip']['at'])
if cfg.get('clone'): EV['clone'] = at(cfg['clone'])
if cfg.get('map'): EV['map'] = (at(cfg['map']['from']) - 0.1, at(cfg['map']['to']) + 0.1)
EV['counters'] = [(at(c['at']), c) for c in cfg.get('counters', [])]
if cfg.get('flyin'): EV['flyin'] = at(cfg['flyin']['at'])
cuts = [s[1] for s in segs if s[0] == 'clip'][1:]
cuts = [c for c in cuts if abs(c - (FREEZE_T + FREEZE_D)) > 0.05]
busy = [(FREEZE_T - .3, FREEZE_T + FREEZE_D + .3)]
if 'shrink' in EV: busy.append((EV['shrink'][0] - .3, EV['shrink'][1] + .3))
if 'slam' in EV: busy.append((EV['slam'] - .3, EV['slam'] + .5))
if 'clone' in EV: busy.append((EV['clone'] - .3, EV['clone'] + 1.2))
flip_t = at(cfg['flip_at']) if cfg.get('flip_at') else -99
kinds = ['spin', 'pixel', 'whip', 'glitch', 'zoomblur']; trans = {}; kk = 0
for c in cuts:
    if abs(c - flip_t) < 0.3: trans[c] = 'flip'
    elif any(a <= c <= b for a, b in busy): trans[c] = 'jump'
    else: trans[c] = kinds[kk % len(kinds)]; kk += 1
print(f'reel {TOTAL:.1f}s, {len(edl)} speech pieces, transitions:', ' '.join(f'{c:.1f}:{v}' for c, v in trans.items()))

# ---------------- sprites (Hebrew text rendered by Chromium) ----------------
SPR = {}
def cap_html(ci, hi):
    return ' '.join(f'<span class="{"hl" if j == hi else "w"}">{re.sub(r"[,.]$", "", words[q]["w"])}</span>' for j, q in enumerate(chunks[ci]))
for ci, ch in enumerate(chunks):
    for hi in range(len(ch)): SPR[f'cap_{ci}_{hi}'] = ('cap', cap_html(ci, hi))
title = cfg['intro']['title']
for k, ch in enumerate(title): SPR[f'title_{k}'] = ('title', ch)
SPR['title_sub'] = ('tsub', cfg['intro'].get('sub', ''))
if cfg.get('name'): SPR['name'] = ('name', f"{cfg['name']['name']} <small>{cfg['name']['role']}</small>")
if fz:
    SPR['freeze'] = ('tag', '⏸ עצירת זמן'); SPR['fz_title'] = ('big', fz['title'])
    if fz.get('sub'): SPR['fz_sub'] = ('chip', fz['sub'])
if cfg.get('slam'): SPR['slam'] = ('metal', cfg['slam']['text'])
if 'chip' in EV: SPR['shrink_chip'] = ('chip2', cfg['shrink']['chip']['text'])
for d in '0123456789': SPR['d' + d] = ('digit', d)
for k, (_, c) in enumerate(EV['counters']):
    if c.get('kicker'): SPR[f'ck_{k}'] = ('kick', c['kicker'])
    if c.get('label'): SPR[f'cl_{k}'] = ('chip', c['label'])
if cfg.get('map'):
    SPR['map_chip'] = ('chip', cfg['map']['chip']); SPR['pin'] = ('pinl', cfg['map'].get('pin', title))
if cfg.get('flyin'):
    for k, w in enumerate(cfg['flyin']['words']): SPR[f'fly_{k}'] = ('fly', w)
SPR['outro_q'] = ('outq', cfg['outro']['q']); SPR['outro_b'] = ('outb', cfg['outro']['button'])
css = open(os.path.join(SKILL, 'templates', 'fx_sprites.css')).read().replace('ASSETS', 'file://' + ASSETS)
html = '<html><head><meta charset=utf-8><style>' + css + '</style></head><body>' + ''.join(f'<div class="sp {c}" id="{k}">{h}</div>' for k, (c, h) in SPR.items()) + '</body></html>'
open(os.path.join(TMP, 'sprites.html'), 'w', encoding='utf-8').write(html)
json.dump(list(SPR), open(os.path.join(TMP, 'ids.json'), 'w'))
js = f"""const path=require('path');let pw;for(const p of ['playwright','/opt/node22/lib/node_modules/playwright','{CACHE}/node_modules/playwright'])try{{pw=require(p);break}}catch(e){{}}
const fs=require('fs');(async()=>{{const ids=JSON.parse(fs.readFileSync('{TMP}/ids.json'));fs.mkdirSync('{TMP}/sp',{{recursive:true}});
const b=await pw.chromium.launch();const p=await b.newPage({{viewport:{{width:1600,height:600}}}});
await p.goto('file://{TMP}/sprites.html');await p.evaluate(()=>document.fonts.ready);await p.waitForTimeout(400);
for(const id of ids){{await p.evaluate(id=>{{for(const e of document.querySelectorAll('.sp'))e.style.visibility=e.id===id?'visible':'hidden'}},id);
await (await p.$('#'+id)).screenshot({{path:'{TMP}/sp/'+id+'.png',omitBackground:true}});}}await b.close();}})();"""
open(os.path.join(TMP, 'r.js'), 'w').write(js); run(['node', os.path.join(TMP, 'r.js')])
_S = {}
def S(k):
    if k not in _S: _S[k] = cv2.imread(f'{TMP}/sp/{k}.png', cv2.IMREAD_UNCHANGED)
    return _S[k]

# ---------------- drawing helpers ----------------
def clamp(x, a=0., b=1.): return max(a, min(b, x))
def eout(x): x = clamp(x); return 1 - (1 - x) ** 3
def ein(x): x = clamp(x); return x ** 3
def einout(x): x = clamp(x); return 3 * x * x - 2 * x ** 3
def back(x, s=1.9): x = clamp(x) - 1; return x * x * ((s + 1) * x + s) + 1
def elastic(x):
    x = clamp(x)
    return x if x in (0, 1) else 2 ** (-10 * x) * math.sin((x * 10 - 0.75) * (2 * math.pi) / 3) + 1
def prog(x, a, d): return clamp((x - a) / d)
def blend(cv, img, x0, y0, al=1.0):
    h, w = img.shape[:2]; X0, Y0 = max(0, x0), max(0, y0); X1, Y1 = min(W, x0 + w), min(H, y0 + h)
    if X1 <= X0 or Y1 <= Y0: return
    sub = img[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]; a = sub[:, :, 3:4].astype(np.float32) * (al / 255.)
    roi = cv[Y0:Y1, X0:X1]; roi[:] = (roi * (1 - a) + sub[:, :, :3] * a).astype(np.uint8)
def put(cv, img, cx, cy, sx=1.0, sy=None, rot=0.0, alpha=1.0):
    if img is None or alpha <= 0.01: return
    sy = sx if sy is None else sy
    if abs(sx) < 0.01 or abs(sy) < 0.01: return
    h, w = img.shape[:2]
    if img.shape[2] == 3: img = np.dstack([img, np.full((h, w), 255, np.uint8)])
    r = math.radians(rot); c, s = math.cos(r), math.sin(r); A = np.array([[c * sx, -s * sy], [s * sx, c * sy]])
    cor = np.array([[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]]) @ A.T
    ow, oh = int(math.ceil(np.ptp(cor[:, 0]))) + 2, int(math.ceil(np.ptp(cor[:, 1]))) + 2
    M = np.hstack([A, (np.array([ow / 2, oh / 2]) - A @ np.array([w / 2, h / 2]))[:, None]]).astype(np.float32)
    blend(cv, cv2.warpAffine(img, M, (ow, oh), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0)), int(round(cx - ow / 2)), int(round(cy - oh / 2)), alpha)
def rrect(w, h, r):
    m = np.zeros((h, w), np.uint8); cv2.rectangle(m, (r, 0), (w - r, h), 255, -1); cv2.rectangle(m, (0, r), (w, h - r), 255, -1)
    for x, y in ((r, r), (w - r, r), (r, h - r), (w - r, h - r)): cv2.circle(m, (x, y), r, 255, -1, cv2.LINE_AA)
    return m
CMASK = rrect(CW, CH, 30); BORDER = CMASK.copy(); BORDER[7:-7, 7:-7][rrect(CW - 14, CH - 14, 24) > 0] = 0
SHADOW = np.zeros((CH + 120, CW + 120, 4), np.uint8); SHADOW[60:-60, 60:-60, 3] = (CMASK * .75).astype(np.uint8)
SHADOW[:, :, 3] = cv2.GaussianBlur(SHADOW[:, :, 3], (0, 0), 22)
SAND, COPPER, CREAM = (124, 178, 217), (42, 90, 166), (222, 241, 248)
def card_from(f):
    img = cv2.resize(f, (CW, CH), interpolation=cv2.INTER_LANCZOS4)
    img = cv2.addWeighted(img, 1.5, cv2.GaussianBlur(img, (0, 0), 1.2), -0.5, 0)
    out = np.dstack([img, CMASK]); out[BORDER > 0, :3] = SAND; return out
def frame_at(src): return SF[max(0, min(len(SF) - 1, int(round(src * SFPS))))]
def background(f):
    w9 = int(sh * 9 / 16); x0 = max(0, sw // 2 - w9 // 2)
    sm = cv2.GaussianBlur(cv2.resize(f[:, x0:x0 + w9], (54, 96), interpolation=cv2.INTER_AREA), (0, 0), 3)
    return (cv2.resize(sm, (W, H), interpolation=cv2.INTER_CUBIC).astype(np.float32) * 0.42 + np.array([20, 28, 42], np.float32)).clip(0, 255).astype(np.uint8)
def pixelate(img, b):
    if b <= 1: return img
    h, w = img.shape[:2]; o = cv2.resize(cv2.resize(img, (max(1, w // b), max(1, h // b)), interpolation=cv2.INTER_AREA), (w, h), interpolation=cv2.INTER_NEAREST)
    o[:, :, 3] = CMASK; return o
def glitch(img, amt, seed):
    rng = np.random.RandomState(seed); o = img.copy(); d = int(18 * amt) + 1
    o[:, :, 2] = np.roll(img[:, :, 2], d, 1); o[:, :, 0] = np.roll(img[:, :, 0], -d, 1)
    for _ in range(int(7 * amt) + 1):
        y = rng.randint(0, img.shape[0] - 30); hh = rng.randint(8, 40); o[y:y + hh] = np.roll(o[y:y + hh], int(rng.randint(-60, 60) * amt), 1)
    o[:, :, 3] = img[:, :, 3]; return o
def desat(img, amt):
    g = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)[:, :, None].astype(np.float32)
    r = img.copy(); r[:, :, :3] = (img[:, :, :3] * (1 - amt) + g * np.array([200, 225, 240]) / 255. * 1.05 * amt).clip(0, 255).astype(np.uint8); return r
LOGO = cv2.imread(os.path.join(ASSETS, 'logo.png'), cv2.IMREAD_UNCHANGED)
def logo_card(width):
    lw = width - 36; lg = cv2.resize(LOGO, (lw, int(LOGO.shape[0] * lw / LOGO.shape[1])), interpolation=cv2.INTER_AREA)
    hh = lg.shape[0] + 30; c = np.zeros((hh, width, 4), np.uint8); m = rrect(width, hh, 22); c[:, :, :3] = CREAM; c[:, :, 3] = m
    a = lg[:, :, 3:4] / 255.; roi = c[15:15 + lg.shape[0], 18:18 + lw, :3]; roi[:] = (roi * (1 - a) + lg[:, :, :3] * a).astype(np.uint8)
    b = m.copy(); b[4:-4, 4:-4][rrect(width - 8, hh - 8, 18) > 0] = 0; c[b > 0, :3] = COPPER; return c
SMALL_LOGO = logo_card(300)
BIG_LOGO = cv2.resize(LOGO, (820, int(LOGO.shape[0] * 820 / LOGO.shape[1])), interpolation=cv2.INTER_AREA)
if cfg.get('map'):
    MAP = cv2.imread(os.path.join(WORK, 'map.png'), cv2.IMREAD_UNCHANGED)
    MAP = cv2.resize(MAP, (470, int(MAP.shape[0] * 470 / MAP.shape[1])), interpolation=cv2.INTER_AREA)
    MM = json.load(open(os.path.join(WORK, 'map.json')))
def digits(s):
    ims = [S('d' + ch) for ch in s]; hh = max(i.shape[0] for i in ims); ww = sum(i.shape[1] for i in ims) - 30 * (len(ims) - 1)
    o = np.zeros((hh, ww, 4), np.uint8); x = 0
    for i in ims:
        h, w = i.shape[:2]; sub = o[:h, x:x + w]; a = i[:, :, 3:4] / 255.
        sub[:, :, :3] = (sub[:, :, :3] * (1 - a) + i[:, :, :3] * a).astype(np.uint8); sub[:, :, 3] = np.maximum(sub[:, :, 3], i[:, :, 3]); x += w - 30
    return o
TITLE = [S(f'title_{k}') for k in range(len(title))]
tw = [im.shape[1] - 10 for im in TITLE]; tx = []; x = W / 2 + sum(tw) / 2
for w_ in tw: tx.append(x - w_ / 2); x -= w_
LET = [(random.uniform(-500, 500), random.uniform(-700, 300), random.uniform(-180, 180)) for _ in TITLE]
ring = fz.get('ring', [0.66, 0.40]) if fz else None

# ---------------- render frames ----------------
N = int(round(TOTAL * FPS))
enc = subprocess.Popen([FF, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                        '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p', f'{TMP}/video.mp4'], stdin=subprocess.PIPE)
last = None
for fi in range(N):
    tt = fi / FPS; seg = seg_at(tt); kind = seg[0]; fr = frame_at(src_at(tt))
    if kind == 'outro':
        u = tt - OUTRO_T; cv = np.full((H, W, 3), CREAM, np.uint8)
        put(cv, BIG_LOGO, W / 2, 760, sx=0.2 + 0.8 * elastic(prog(u, 0.05, 0.9)), alpha=clamp(u / 0.15))
        put(cv, S('outro_q'), W / 2, 1150 + 120 * (1 - eout(prog(u, 0.5, 0.45))), alpha=prog(u, 0.5, 0.3))
        put(cv, S('outro_b'), W / 2, 1330, sx=back(prog(u, 0.95, 0.4)), alpha=prog(u, 0.95, 0.1))
        if u < 0.45 and last is not None:
            r = int((1 - eout(u / 0.45)) * 1300); m = np.zeros((H, W), np.uint8); cv2.circle(m, (W // 2, CY), r, 255, -1, cv2.LINE_AA)
            a = (m / 255.)[:, :, None]; cv = (last * a + cv * (1 - a)).astype(np.uint8); cv2.circle(cv, (W // 2, CY), r, COPPER, 10, cv2.LINE_AA)
        enc.stdin.write(cv.tobytes()); continue
    cv = background(fr); card = card_from(fr)
    cx, cy, sx, sy, rot, shake = CX, CY, 1.0, 1.0, 0.0, 0.0
    if kind == 'intro':
        card = pixelate(card, int(1 + 70 * (1 - eout(prog(tt, 0.1, 1.1))))); sx = sy = 0.85 + 0.15 * eout(prog(tt, 0, 1.2))
    if kind == 'freeze':
        u = tt - FREEZE_T; card = desat(card, 0.75 * clamp(u / 0.12) * (1 - prog(u, FREEZE_D - 0.1, 0.1))); sx = sy = 1 + 0.12 * einout(prog(u, 0, FREEZE_D))
    for c, v in trans.items():
        d = tt - c
        if not -0.2 <= d <= 0.22: continue
        p = 1 - abs(d) / 0.2 if abs(d) <= 0.2 else 0
        if v == 'spin': rot = 180 * eout((d + 0.2) / 0.2) if d < 0 else 180 + 180 * eout(d / 0.2); sx = sy = 1 - 0.45 * p
        elif v == 'pixel': card = pixelate(card, int(1 + 45 * p))
        elif v == 'glitch': card = glitch(card, p, fi)
        elif v == 'zoomblur':
            sx = sy = 1 + 0.5 * p
            if p > 0.2:
                acc = card.astype(np.float32)
                for z in (1.04, 1.08, 1.12): acc += cv2.warpAffine(card, cv2.getRotationMatrix2D((CW / 2, CH / 2), 0, z), (CW, CH)).astype(np.float32)
                card = (acc / 4).astype(np.uint8); card[:, :, 3] = CMASK
        elif v == 'whip':
            cx = CX - eout((d + 0.2) / 0.2) * 1200 if d < 0 else CX + (1 - eout(d / 0.2)) * 1200
            card = cv2.blur(card, (int(1 + 60 * p), 1)); card[:, :, 3] = CMASK
        elif v == 'flip': sx = max(0.02, abs(math.cos(math.pi / 2 * p)))
        elif v == 'jump' and 0 <= d < 0.18: sx = sy = 1.07 - 0.07 * eout(d / 0.18)
    for tp in EV['punch']:
        d = tt - tp
        if 0 <= d < 0.4: sx *= 1 + 0.16 * (1 - eout(d / 0.4)); sy = sx; shake = max(shake, 6 * (1 - d / 0.4))
    if 'slam' in EV:
        d = tt - EV['slam']
        if 0 <= d < 0.3: card = glitch(card, 1 - d / 0.3, fi + 99); shake = max(shake, 22 * (1 - d / 0.3))
    if 'shrink' in EV and EV['shrink'][0] <= tt < EV['shrink'][1]:
        a0, a1 = EV['shrink']; u = (tt - a0) / (a1 - a0); s0 = 0.42
        if 0.18 <= u < 0.82:
            v = (u - 0.18) / 0.64; hop = (v * 3) % 1; cx = CX + 300 - 600 * v; cy = CY + 120 - 330 * math.sin(math.pi * hop)
            sq = 1 + 0.25 * max(0, 1 - hop / 0.12) + 0.25 * max(0, (hop - 0.88) / 0.12); sx, sy = s0 * sq, s0 / sq; rot = -25 * math.sin(2 * math.pi * hop)
        else: sx = sy = (1 - (1 - s0) * eout(u / 0.18)) if u < 0.18 else s0 + (1 - s0) * elastic((u - 0.82) / 0.18)
    ox, oy = (random.uniform(-shake, shake), random.uniform(-shake, shake)) if shake > 0 else (0, 0)
    d = tt - EV.get('clone', -99)
    if 0 <= d < 1.0:
        put(cv, SHADOW, CX, CY + 14)
        for k, ((dx, dy), tn) in enumerate(zip([(-252, -142), (252, -142), (-252, 142), (252, 142)], [(1, 1, 1), (.7, .9, 1.35), (1.35, 1, .65), (.75, 1.3, .8)])):
            a = prog(d, 0.06 * k, 0.15)
            if a > 0:
                c2 = card.copy(); c2[:, :, :3] = (c2[:, :, :3] * np.array(tn)).clip(0, 255).astype(np.uint8); put(cv, c2, CX + dx, CY + dy, sx=0.5 * back(a))
    else:
        put(cv, SHADOW, cx + ox, cy + oy + 14, sx=sx, sy=sy, rot=rot, alpha=0.9); put(cv, card, cx + ox, cy + oy, sx=sx, sy=sy, rot=rot)
    if kind == 'freeze':
        u = tt - FREEZE_T; fa = 1 - prog(u, FREEZE_D - 0.12, 0.12); la = 0.35 * clamp(u / 0.2) * (1 - prog(u, FREEZE_D - 0.15, 0.15))
        ov = cv.copy()
        for k in range(28):
            g = k / 28 * 2 * math.pi + u * 0.4
            cv2.line(ov, (int(CX + 620 * math.cos(g)), int(CY + 620 * math.sin(g))), (int(CX + 1500 * math.cos(g)), int(CY + 1500 * math.sin(g))), (235, 245, 250), 3, cv2.LINE_AA)
        cv[:] = cv2.addWeighted(ov, la, cv, 1 - la, 0)
        put(cv, S('freeze'), CX - 280, CY - CH / 2 - 10, sx=back(prog(u, 0.05, 0.25)), alpha=fa)
        if u > 0.2 and fa > 0.5:
            bx, by = int(CX + (ring[0] - 0.5) * CW * 1.1), int(CY + (ring[1] - 0.5) * CH * 1.1); rr = int(70 + 10 * math.sin(u * 12))
            cv2.circle(cv, (bx, by), rr, COPPER, 9, cv2.LINE_AA); cv2.circle(cv, (bx, by), rr + 12, SAND, 4, cv2.LINE_AA)
        put(cv, S('fz_title'), W / 2, TOPY, sx=1 + 1.5 * (1 - eout(prog(u, 0.1, 0.22))), alpha=prog(u, 0.1, 0.08) * fa)
        if 'fz_sub' in SPR: put(cv, S('fz_sub'), W / 2, TOPY + 150, sx=back(prog(u, 0.5, 0.3)), alpha=fa)
        if prog(u, FREEZE_D - 0.1, 0.1) > 0: cv[:] = cv2.addWeighted(cv, 0.5, np.full_like(cv, 255), 0.5, 0)
    if tt < 3.2:
        for k, im in enumerate(TITLE):
            p = eout(prog(tt, 0.15 + 0.08 * k, 0.5)); fx_, fy_, fr_ = LET[k]; op = ein(prog(tt, 2.7 + 0.04 * k, 0.4))
            put(cv, im, tx[k] + fx_ * (1 - p), TOPY - 40 + fy_ * (1 - p) - 900 * op, sx=0.6 + 0.4 * back(prog(tt, 0.15 + 0.08 * k, 0.5)), rot=fr_ * (1 - p), alpha=clamp(p * 2) * (1 - op))
        put(cv, S('title_sub'), W / 2, TOPY + 150, sx=back(prog(tt, 0.85, 0.35)), alpha=prog(tt, 0.85, 0.1) * (1 - prog(tt, 2.7, 0.3)))
    if 'name' in SPR and 3.0 <= tt < 6.5:   # long enough to read
        p = eout(prog(tt, 3.0, 0.35)) * (1 - ein(prog(tt, 6.1, 0.35))); put(cv, S('name'), W + 600 - (600 + W / 2) * p, TOPY + 60, alpha=p)
    if 'slam' in EV:
        d = tt - EV['slam']
        if -0.02 <= d < 1.5: put(cv, S('slam'), W / 2 + ox, TOPY + oy, sx=1 + 2.2 * (1 - eout(clamp(d / 0.18))), rot=-6, alpha=clamp(d / 0.05) * (1 - prog(d, 1.25, 0.25)))
    if 'chip' in EV:
        d = tt - EV['chip']
        if 0 <= d < 1.6: put(cv, S('shrink_chip'), W / 2 + 40 * math.sin(d * 6), TOPY, sx=back(clamp(d / 0.3)), alpha=1 - prog(d, 1.35, 0.25))
    if 'map' in EV and EV['map'][0] <= tt < EV['map'][1]:
        u = tt - EV['map'][0]; Dm = EV['map'][1] - EV['map'][0]; drop = 1 - elastic(prog(u, 0, 0.6)); op = ein(prog(u, Dm - 0.3, 0.3))
        my = TOPY - 40 - 700 * drop - 900 * op; put(cv, MAP, W / 2, my, rot=-3 * drop); mh = MAP.shape[0]
        px = W / 2 - 235 + MM['pin']['x'] / 100 * 470; py = my - mh / 2 + MM['pin']['y'] / 100 * mh; pd = elastic(prog(u, 0.45, 0.5))
        if pd > 0:
            py2 = py - 120 * (1 - pd); cv2.circle(cv, (int(px), int(py2)), 14, COPPER, -1, cv2.LINE_AA); cv2.circle(cv, (int(px), int(py2)), 14, (255, 255, 255), 4, cv2.LINE_AA)
            put(cv, S('pin'), px, py2 - 48, sx=back(prog(u, 0.6, 0.25)))
        put(cv, S('map_chip'), W / 2, my + mh / 2 + 10, sx=back(prog(u, 0.7, 0.3)), alpha=1 - op)
    for k, (t0c, c) in enumerate(EV['counters']):
        d = tt - t0c; dd = c.get('dur', 2.4)
        if 0 <= d < dd:
            a = 1 - prog(d, dd - 0.3, 0.3); run_d = c.get('count_sec', 1.0)
            val = int(round(c.get('from', 0) + (c['to'] - c.get('from', 0)) * eout(prog(d, 0.1, run_d))))   # then holds the final value
            if c.get('kicker'): put(cv, S(f'ck_{k}'), W / 2, TOPY - 150, alpha=prog(d, 0, 0.15) * a)
            pop = 0.12 if 0 < d - (0.1 + run_d) < 0.15 else 0
            put(cv, digits(str(val)), W / 2, TOPY - 10, sx=0.9 + 0.1 * back(prog(d, 0, 0.3)) + pop, alpha=prog(d, 0, 0.12) * a)
            if c.get('label'): put(cv, S(f'cl_{k}'), W / 2, TOPY + 150, sx=back(prog(d, 0.1 + run_d, 0.3)), alpha=a)
    if 'flyin' in EV and tt < OUTRO_T:
        d = tt - EV['flyin']
        if 0 <= d:
            for k in range(len(cfg['flyin']['words'])):
                p = back(prog(d, 0.3 * k, 0.4)); side = 1 if k % 2 == 0 else -1
                put(cv, S(f'fly_{k}'), W / 2 + side * 900 * (1 - p), TOPY - 95 + 190 * k, rot=side * 25 * (1 - p), alpha=clamp(p * 2))
    if kind == 'clip' or kind == 'hold':
        for ci, ch in enumerate(chunks):
            st = WS[ch[0]]; en = WS[chunks[ci + 1][0]] if ci + 1 < len(chunks) else WE[ch[-1]] + 0.4
            if st <= tt < en:
                hi = max([j for j, q in enumerate(ch) if WS[q] <= tt] or [0])
                put(cv, S(f'cap_{ci}_{hi}'), W / 2, CAPY, sx=0.75 + 0.25 * back(prog(tt, st, 0.16))); break
    put(cv, SMALL_LOGO, W / 2, 1530)
    cv2.rectangle(cv, (0, 0), (int(W * tt / TOTAL), 10), COPPER, -1)
    last = cv; enc.stdin.write(cv.tobytes())
enc.stdin.close(); enc.wait()

# ---------------- audio ----------------
clips = [s for s in segs if s[0] == 'clip']; parts = []; fd = int(0.010 * SR)
for s in clips:
    x = speech_src[int(s[3] * SR):int(s[4] * SR)].copy(); x[:fd] *= np.linspace(0, 1, fd); x[-fd:] *= np.linspace(1, 0, fd); parts.append(x)
open(f'{TMP}/cat.raw', 'wb').write(np.concatenate(parts).astype(np.float32).tobytes())
fast = np.frombuffer(subprocess.run([FF, '-v', 'error', '-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', f'{TMP}/cat.raw', '-af', f'atempo={SP}', '-f', 'f32le', '-'], capture_output=True).stdout, np.float32)
NA = int(TOTAL * SR) + SR; speech = np.zeros(NA, np.float32); pos = 0
for s, x in zip(clips, parts):
    L2 = int(round(len(x) / SP)); o = int(s[1] * SR); seg_ = fast[pos:pos + L2]; speech[o:o + len(seg_)] += seg_; pos += L2
rng = np.random.RandomState(1); t_ = lambda d: np.arange(int(d * SR)) / SR
def lp(x, k): return np.convolve(x, np.ones(k) / k, 'same')
def kick(): t = t_(0.35); return np.sin(2 * np.pi * np.cumsum(45 + 90 * np.exp(-t * 30)) / SR) * np.exp(-t * 9)
def hat(): n_ = rng.randn(int(0.05 * SR)); return (n_ - lp(n_, 6)) * np.exp(-t_(0.05) * 90) * 0.5
def clap(): n_ = rng.randn(int(0.15 * SR)); return (n_ - lp(n_, 20)) * np.exp(-t_(0.15) * 30) * 0.6
def bass(f, d): t = t_(d); return (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)) * np.minimum(1, t * 80) * np.exp(-t * 2.2)
def whoosh(d=0.4):
    n_ = rng.randn(int(d * SR)); t = t_(d); lo = lp(n_, 40); return ((lp(n_, 8) - lo) * (t / d) + lo * (1 - t / d)) * np.sin(np.pi * t / d) ** 2 * 1.6
def pop(): t = t_(0.09); return np.sin(2 * np.pi * np.cumsum(900 * np.exp(-t * 25) + 200) / SR) * np.exp(-t * 40) * 0.8
def tick(): t = t_(0.02); return np.sin(2 * np.pi * 2400 * t) * np.exp(-t * 300) * 0.6
def impact(): t = t_(0.7); return (np.sin(2 * np.pi * np.cumsum(70 * np.exp(-t * 3) + 35) / SR) * np.exp(-t * 5) + rng.randn(len(t)) * np.exp(-t * 25) * 0.5) * 1.1
def glitchs(d=0.3): t = t_(d); return np.sign(np.sin(2 * np.pi * 180 * t)) * (rng.rand(int(d * 40) + 1) > 0.4).repeat(int(SR / 40) + 1)[:len(t)] * 0.25
def boing(): t = t_(0.35); return np.sin(2 * np.pi * np.cumsum(300 + 120 * np.sin(2 * np.pi * 14 * t) * np.exp(-t * 6)) / SR) * np.exp(-t * 7) * 0.6
def tapestop(d=0.45): t = t_(d); ph = np.cumsum(220 * (1 - t / d) ** 2 + 30) / SR; return (2 * (ph % 1) - 1) * 0.35 * (1 - t / d)
def snap(): n_ = rng.randn(int(0.06 * SR)); return (n_ - lp(n_, 4)) * np.exp(-t_(0.06) * 70)
def riser(d=1.0): n_ = rng.randn(int(d * SR)); return (n_ - lp(n_, 30)) * (t_(d) / d) ** 2 * 0.5
def chime():
    o = np.zeros(int(1.2 * SR))
    for k, f in enumerate([880, 1108.7, 1318.5]): t = t_(1.2 - 0.08 * k); o[int(0.08 * k * SR):int(0.08 * k * SR) + len(t)] += np.sin(2 * np.pi * f * t) * np.exp(-t * 4) * 0.3
    return o
sfx = np.zeros(NA, np.float32); music = np.zeros(NA, np.float32)
def add(buf, x, a, g=1.0):
    o = int(a * SR)
    if o < 0: x = x[-o:]; o = 0
    e = min(NA, o + len(x)); buf[o:e] += x[:e - o] * g
bt = 60 / cfg.get('bpm', 104); roots = [110, 87.31, 130.81, 98.0]; b = 0; tb = 0.0
while tb < TOTAL:
    add(music, kick(), tb, 0.9); add(music, hat(), tb + bt / 2, 0.5)
    if b % 2: add(music, clap(), tb, 0.45)
    if b % 4 == 0: add(music, bass(roots[(b // 4) % 4], bt * 4), tb, 0.35)
    b += 1; tb += bt
if fz:   # time stop: the beat tape-stops and stays silent until the resume
    i0, i1 = int(FREEZE_T * SR), int((FREEZE_T + FREEZE_D) * SR); L = int(0.35 * SR)
    idx = np.cumsum(np.linspace(1, 0.05, L)).astype(int).clip(0, L - 1); music[i0:i0 + L] = music[i0:i0 + L][idx] * np.linspace(1, 0, L); music[i0 + L:i1] = 0
add(sfx, whoosh(0.5), 0, 0.8)
for k in range(len(TITLE)): add(sfx, pop(), 0.45 + 0.08 * k, 0.5)
for c, v in trans.items():
    if v == 'jump': add(sfx, snap(), c, 0.4)
    elif v == 'glitch': add(sfx, glitchs(), c - 0.15, 0.8)
    elif v == 'pixel': add(sfx, glitchs(0.2), c - 0.1, 0.5); add(sfx, whoosh(0.35), c - 0.17, 0.6)
    else: add(sfx, whoosh(0.4), c - 0.2, 0.9)
if fz:
    add(sfx, tapestop(), FREEZE_T)
    for k in range(int(FREEZE_D / 0.25)): add(sfx, tick(), FREEZE_T + 0.15 + 0.25 * k, 0.7)
    add(sfx, impact(), FREEZE_T + 0.1, 0.6); add(sfx, snap(), FREEZE_T + FREEZE_D - 0.05)
for tp in EV['punch']: add(sfx, impact()[:int(0.25 * SR)], tp, 0.5)
if 'slam' in EV: add(sfx, impact(), EV['slam']); add(sfx, glitchs(), EV['slam'], 0.8)
if 'shrink' in EV:
    a0, a1 = EV['shrink']
    for k in range(3): add(sfx, boing(), a0 + (a1 - a0) * (0.18 + 0.64 * (k + 1) / 3) - 0.03, 0.8)
if 'chip' in EV: add(sfx, pop(), EV['chip'], 0.7)
if 'clone' in EV:
    for k in range(4): add(sfx, pop(), EV['clone'] + 0.06 * k, 0.7)
if 'map' in EV: add(sfx, whoosh(0.5), EV['map'][0], 0.7); add(sfx, boing(), EV['map'][0] + 0.5, 0.6)
for t0c, c in EV['counters']:
    for k in range(10): add(sfx, tick(), t0c + 0.1 + k * c.get('count_sec', 1.0) / 10, 0.6)
    add(sfx, chime(), t0c + 0.1 + c.get('count_sec', 1.0), 0.6)
if 'flyin' in EV:
    for k in range(len(cfg['flyin']['words'])): add(sfx, whoosh(0.4), EV['flyin'] + 0.3 * k, 0.8)
add(sfx, riser(), OUTRO_T - 1.0, 0.6); add(sfx, impact(), OUTRO_T + 0.1, 0.9); add(sfx, chime(), OUTRO_T + 0.5, 0.8)
# music and SFX always sit under the voice: duck both by the speech envelope
env = np.sqrt(np.convolve(speech ** 2, np.ones(2400) / 2400, 'same')); env /= env.max() + 1e-9
music *= 1 - 0.65 * np.clip(env * 4, 0, 1); sfx *= 1 - 0.45 * np.clip(env * 4, 0, 1); music[int(OUTRO_T * SR):] *= 1.6
mix = speech + music * cfg.get('music_gain', 0.16) + sfx * cfg.get('sfx_gain', 0.32)
mix = (np.clip(mix / max(1.0, np.abs(mix).max() / 0.95), -1, 1)[:int(TOTAL * SR)] * 32767).astype(np.int16)
w = wave.open(f'{TMP}/audio.wav', 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(mix.tobytes()); w.close()
kb = int(min(7000, cfg.get('max_mb', 28) * 8192 / TOTAL - 250))
run([FF, '-v', 'error', '-y', '-i', f'{TMP}/video.mp4', '-i', f'{TMP}/audio.wav', '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', 'slow',
     '-b:v', f'{kb}k', '-maxrate', f'{int(kb * 1.25)}k', '-bufsize', f'{kb * 2}k', '-pix_fmt', 'yuv420p', '-af', 'loudnorm=I=-14:TP=-1.5:LRA=9',
     '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', '-shortest', OUT])
sel = '+'.join(f'eq(n\\,{int(x * FPS)})' for x in [0.6, 2.0] + [EV[k] if isinstance(EV[k], float) else EV[k][0] for k in ('slam', 'shrink', 'clone', 'map') if k in EV][:4] + [FREEZE_T + 0.8, OUTRO_T + 1.5])
run([FF, '-v', 'error', '-y', '-i', OUT, '-vf', f"select='{sel}',scale=270:-1,tile=8x1", '-vsync', '0', '-frames:v', '1', OUT.rsplit('.', 1)[0] + '_preview.jpg'])
print(f'DONE {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB, {TOTAL:.1f}s)')
