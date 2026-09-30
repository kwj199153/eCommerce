# -*- coding: utf-8 -*-
"""`check-empty-state-honesty.cjs` 的反向注入台架（第 280 轮）。

证明什么
========
门禁**全绿**只说明"当前代码合规"，不说明"它抓得住违规"。
本台架在**副本树**上把 4 种违规各注入一次，看门禁的**精确失败集**
（`FAIL` 的判据名集合）是否与事先推断**逐条相等** —— 多一条少一条都算失败
（"整体红了但红的是别的"是假证据）。

4 组注入 + 1 组基线 + 1 组反面对照
================================
  baseline  不改任何东西                      ⇒ 期望 红集 = {}
  T1 消费点去掉 :error 绑定                    ⇒ 期望 {D3a}
  T2 组件模板改成「不互斥」（直接铺空态文案）    ⇒ 期望 {D2a}
  T3 某页**额外**插入一个裸三元 a-empty         ⇒ 期望 {D4}
  T4 某页整块删掉 <AsyncEmpty>                  ⇒ 期望 {D3a, D3b}
  T5 反面对照：只改空态**文案**（合法改动）      ⇒ 期望 {}（不许红）

纪律
====
  · 只动副本树（`.tmp_empty_inject/src`），工作区 `src/` 全程零改动；
  · 每个用例跑完**从基准字节复位**（不靠"改回来"）；
  · 建副本树用**覆盖式拷贝**（`dirs_exist_ok=True`），零删除 —— 沙箱会把 `rmtree`
    拦成 trash 并拒绝，且异常在**跑完后**才抛（退出码假绿）。
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent      # frontend/
SRC = ROOT / 'src'
WORK = ROOT / '.tmp_empty_inject' / 'src'
NODE = pathlib.Path(r'C:/Users/Administrator/.workbuddy/binaries/node/versions/22.22.2-3/node.exe')
GATE = ROOT / 'scripts' / 'check-empty-state-honesty.cjs'

SUBSCRIPTION = 'views/Subscription.vue'
PRODUCT = 'components/KnowledgeBase/ProductLibrary.vue'
ASSET = 'components/KnowledgeBase/AssetLibrary.vue'
CANDIDATE = 'components/KnowledgeBase/CandidateLibrary.vue'
COMPONENT = 'components/common/AsyncEmpty.vue'


def build_tree():
    """覆盖式拷贝（零删除）。"""
    (WORK).mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC, WORK, dirs_exist_ok=True)
    return sum(1 for x in WORK.rglob('*') if x.is_file())


def rd(rel):
    p = WORK / rel
    b = p.read_bytes()
    s = b.decode('utf-8')
    nl = '\r\n' if '\r\n' in s else '\n'
    return p, s.replace('\r\n', '\n'), nl


def wr(p, norm, nl, raw_orig=None):
    if raw_orig is not None:
        p.write_bytes(raw_orig)          # 复位：直接写回基准字节
        return
    out = norm.replace('\n', nl) if nl == '\r\n' else norm
    p.write_bytes(out.encode('utf-8'))


def patch(rel, old, new, expect_hits=1):
    p, norm, nl = rd(rel)
    n = norm.count(old)
    if n != expect_hits:
        raise AssertionError('%s 锚点命中 %d 次（期望 %d）' % (rel, n, expect_hits))
    wr(p, norm.replace(old, new, 1), nl)


def run_gate():
    env = dict(os.environ)
    env['EMPTY_STATE_SRC_ROOT'] = str(WORK)
    r = subprocess.run([str(NODE), str(GATE)], capture_output=True, text=True, env=env)
    reds = set()
    for ln in r.stdout.splitlines():
        m = re.match(r'\s*(PASS|FAIL)\s+(D\w+)\s', ln)
        if m and m.group(1) == 'FAIL':
            reds.add(m.group(2))
    total = re.search(r'(\d+)/(\d+) 通过', r.stdout)
    return reds, r.returncode, (total.group(0) if total else '?'), r.stdout


CASES = []


def case(name, expect, mutate):
    CASES.append((name, expect, mutate))


# ---- T1：消费点丢掉 :error 绑定
def t1():
    patch(PRODUCT, '          :error="store.loadError"\n', '', 1)


case('T1 消费点去掉 :error 绑定', {'D3a'}, t1)


# ---- T2：组件模板改成「不互斥」
def t2():
    patch(
        COMPONENT,
        '<a-empty :description="error ? `${label}加载失败，请重试` : emptyDescription">',
        '<a-empty :description="emptyDescription">',
        1,
    )


case('T2 组件模板不再区分失败/空态', {'D2a'}, t2)


# ---- T3：某页额外插入一个裸三元
def t3():
    patch(
        ASSET,
        '        <AsyncEmpty\n',
        '        <a-empty :description="store.loadError ? \'素材库加载失败，请重试\' : \'素材库为空\'" />\n'
        '        <AsyncEmpty\n',
        1,
    )


case('T3 某页额外插入裸三元空态', {'D4'}, t3)


# ---- T4：整块删掉 <AsyncEmpty>
def t4():
    p, norm, nl = rd(CANDIDATE)
    m = re.search(r'      <AsyncEmpty\n(?:.*\n)*?        />\n', norm)
    if not m:
        raise AssertionError('未匹配到 CandidateLibrary 的 <AsyncEmpty> 块')
    wr(p, norm[:m.start()] + norm[m.end():], nl)


case('T4 整块删掉 <AsyncEmpty>（退回表格自带空态）', {'D3a', 'D3b'}, t4)


# ---- T5：反面对照（合法改动，不许红）
def t5():
    patch(SUBSCRIPTION, 'empty-description="暂无可选套餐"', 'empty-description="还没有可选套餐"', 1)


case('T5 反面对照：只改空态文案', set(), t5)


def cleanup():
    """逐个 unlink + rmdir（沙箱会拦 rmtree）。"""
    if not WORK.exists():
        return 0
    files = [x for x in WORK.rglob('*') if x.is_file()]
    for x in files:
        try:
            x.unlink()
        except OSError:
            pass
    dirs = sorted([d for d in WORK.rglob('*') if d.is_dir()], key=lambda d: -len(str(d)))
    for d in dirs:
        try:
            d.rmdir()
        except OSError:
            pass
    try:
        WORK.rmdir()
    except OSError:
        pass
    try:
        WORK.parent.rmdir()
    except OSError:
        pass
    return len(files)


# ============================================================ 主流程
print('==== 建副本树 ====')
n = build_tree()
print('  拷贝 %d 个文件 -> %s' % (n, WORK))

# 基准字节（复位用）
BASELINE = {}
for rel in (SUBSCRIPTION, PRODUCT, ASSET, CANDIDATE, COMPONENT):
    BASELINE[rel] = (WORK / rel).read_bytes()


def reset_all():
    for rel, raw in BASELINE.items():
        (WORK / rel).write_bytes(raw)


failures = []
print('\n==== 基线 ====')
reds, code, tally, _ = run_gate()
print('  红集 = %s | %s | exit=%d' % (sorted(reds) or '{}', tally, code))
if reds:
    failures.append('基线就红了：%s' % sorted(reds))

for name, expect, mutate in CASES:
    reset_all()
    try:
        mutate()
    except AssertionError as e:
        failures.append('%s 注入失败：%s' % (name, e))
        print('\n==== %s ====\n  X 注入失败：%s' % (name, e))
        continue
    reds, code, tally, out = run_gate()
    ok = (reds == expect)
    print('\n==== %s ====' % name)
    print('  期望红集 = %s' % (sorted(expect) or '{}'))
    print('  实际红集 = %s | %s | exit=%d' % (sorted(reds) or '{}', tally, code))
    if ok:
        print('  OK 精确失败集吻合')
    else:
        print('  X 不吻合（多 = %s / 少 = %s）' % (sorted(reds - expect) or '-', sorted(expect - reds) or '-'))
        print('  --- 门禁输出 ---')
        for ln in out.splitlines():
            print('    ' + ln)
        failures.append('%s 失败集不吻合：期望 %s，实际 %s' % (name, sorted(expect), sorted(reds)))

reset_all()
print('\n==== 复位并清理 ====')
removed = cleanup()
print('  副本树已清（%d 个文件）' % removed)

if failures:
    print('\n==== 反向注入未通过 ====')
    for x in failures:
        print('  X ' + x)
    sys.exit(1)

print('\n==== 反向注入 ALL PASS：基线 + 4 组精确失败集 + 1 组反面对照 ====')
