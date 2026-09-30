# -*- coding: utf-8 -*-
"""`cdp-library-empty-probe.mjs` 的行为层反向注入台架（第 280 轮）。

为什么要这一层
==============
源码层注入（`probe_empty_state_inject.py`）证明的是**静态门禁**抓得住违规；
它证明不了「真浏览器里失败态会不会如实上屏」—— 那是 CDP 探针的判据。
所以探针的每条判据也要被反向验证一次：**在真源码上注入 ↔ 跑真浏览器 ↔ 比对精确失败集**。

3 组注入
========
  H1 删掉 AssetLibrary 的 `:error` 绑定（组件拿不到失败原因）
     ⇒ 期望 {V1-assets, V2-assets, V3-assets, V5-assets}
        （页面会说「素材库为空」、没有重试按钮、且失败文案根本不出现）
  H2 删掉 ProductLibrary 的 `#emptyText` 插槽（退回 antd 自带空态）
     ⇒ 期望 {V1-products, V2-products, V5-products}
        （V3 保持**绿**：antd 那句「暂无数据」不含我们自己的「产品库为空」措辞
          —— 这正是 V3 单独不够、必须再加 V5「唯一性」的原因）
  H3 把 assetLibrary 的 catch 改回**灌假素材**（并清空 loadError）—— 第 271 轮之前的行为
     ⇒ 期望 {V1-assets, V2-assets, V4-assets, V5-assets}
        （唯一能让 V4「没有数据行/卡」变红的一组 ⇒ 证明 V4 不是空跑。
         ★ 这里**不含 V3**，而且是判据的正确行为：灌了 1 张假素材后
           `filteredItems.length > 0` ⇒ 模板走 `v-if` 的数据分支 ⇒ **空态整个不渲染**
           （实测 `empties: []`）⇒ 当然不存在"混进空态文案"。V3 的职责是
           「空态与失败态**并存**」，"有假数据"是 V4 的职责 —— 两者不可互相顶替。）

纪律：每轮注入后还原（写回基准字节）；跑完复核 md5 回基准。
"""
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent      # frontend/
NODE = pathlib.Path(r'C:/Users/Administrator/.workbuddy/binaries/node/versions/22.22.2-3/node.exe')
PROBE = ROOT / 'scripts' / 'cdp-library-empty-probe.mjs'

ASSET_VUE = ROOT / 'src' / 'components' / 'KnowledgeBase' / 'AssetLibrary.vue'
PRODUCT_VUE = ROOT / 'src' / 'components' / 'KnowledgeBase' / 'ProductLibrary.vue'
ASSET_STORE = ROOT / 'src' / 'stores' / 'assetLibrary.ts'

TARGETS = [ASSET_VUE, PRODUCT_VUE, ASSET_STORE]
BASELINE = {p: p.read_bytes() for p in TARGETS}

HMR_WAIT = 7.0


def restore(*paths):
    for p in (paths or TARGETS):
        p.write_bytes(BASELINE[p])


def patch(path, old, new, expect=1):
    s = path.read_bytes().decode('utf-8')
    nl = '\r\n' if '\r\n' in s else '\n'
    norm = s.replace('\r\n', '\n')
    n = norm.count(old)
    if n != expect:
        raise AssertionError('%s 锚点命中 %d 次（期望 %d）' % (path.name, n, expect))
    out = norm.replace(old, new, 1)
    path.write_bytes((out.replace('\n', nl) if nl == '\r\n' else out).encode('utf-8'))


def run_probe():
    r = subprocess.run([str(NODE), str(PROBE)], capture_output=True, text=True, cwd=str(ROOT))
    reds = set()
    for ln in r.stdout.splitlines():
        m = re.match(r'(PASS|FAIL)\s+(\S+)\s', ln)
        if m and m.group(1) == 'FAIL':
            reds.add(m.group(2))
    total = re.search(r'(\d+)/(\d+) 通过', r.stdout)
    return reds, r.returncode, (total.group(0) if total else '?'), r.stdout


# ---- H1
def h1():
    patch(
        ASSET_VUE,
        '          :error="store.loadError"\n',
        '',
    )


# ---- H2
def h2():
    s = PRODUCT_VUE.read_bytes().decode('utf-8').replace('\r\n', '\n')
    m = re.search(r'      <template #emptyText>\n(?:.*\n)*?      </template>\n', s)
    if not m:
        raise AssertionError('未匹配到 ProductLibrary 的 #emptyText 块')
    out = s[:m.start()] + s[m.end():]
    PRODUCT_VUE.write_bytes(out.encode('utf-8'))


# ---- H3
def h3():
    patch(
        ASSET_STORE,
        "      items.value = []\n"
        "      loadError.value = (e as Error)?.message || '素材库加载失败'",
        "      items.value = [{ id: 'fake-asset-1', name: '假素材', url: 'https://example.com/x.png', "
        "kind: 'image', category: 'product' } as any]\n"
        "      loadError.value = null",
    )


CASES = [
    ('H1 删掉 AssetLibrary 的 :error 绑定',
     {'V1-assets', 'V2-assets', 'V3-assets', 'V5-assets'}, h1),
    ('H2 删掉 ProductLibrary 的 #emptyText 插槽（退回 antd 自带空态）',
     {'V1-products', 'V2-products', 'V5-products'}, h2),
    ('H3 assetLibrary 的 catch 改回灌假素材（第 271 轮前的行为）',
     {'V1-assets', 'V2-assets', 'V4-assets', 'V5-assets'}, h3),
]

failures = []
for name, expect, mutate in CASES:
    restore()
    try:
        mutate()
    except AssertionError as e:
        failures.append('%s 注入失败：%s' % (name, e))
        print('\n==== %s ====\n  X 注入失败：%s' % (name, e))
        continue
    time.sleep(HMR_WAIT)
    reds, code, tally, out = run_probe()
    ok = (reds == expect)
    print('\n==== %s ====' % name)
    print('  期望红集 = %s' % (sorted(expect) or '{}'))
    print('  实际红集 = %s | %s | exit=%d' % (sorted(reds) or '{}', tally, code))
    if ok:
        print('  OK 精确失败集吻合')
    else:
        print('  X 不吻合（多 = %s / 少 = %s）' % (sorted(reds - expect) or '-', sorted(expect - reds) or '-'))
        for ln in out.splitlines():
            if ln.startswith('FAIL'):
                print('    ' + ln)
        failures.append('%s 失败集不吻合：期望 %s，实际 %s' % (name, sorted(expect), sorted(reds)))
    restore()
    time.sleep(HMR_WAIT)

print('\n==== 还原复核 ====')
bad = []
for p in TARGETS:
    now = p.read_bytes()
    same = (now == BASELINE[p])
    print('  %-22s %s' % (p.name, '回基准 ✓' if same else 'X 未回基准'))
    if not same:
        bad.append(p.name)
if bad:
    failures.append('还原未回基准：%s' % bad)

# 基线复跑一次，确认注入没留下残影
reds, code, tally, _ = run_probe()
print('\n==== 还原后基线复跑：%s | exit=%d ====' % (tally, code))
if reds:
    failures.append('还原后基线仍红：%s' % sorted(reds))

if failures:
    print('\n==== 行为层反向注入未通过 ====')
    for x in failures:
        print('  X ' + x)
    sys.exit(1)

print('\n==== 行为层反向注入 ALL PASS：3 组精确失败集 + 还原回基准 + 基线复跑全绿 ====')
