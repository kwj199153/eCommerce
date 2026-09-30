# -*- coding: utf-8 -*-
"""
反向注入台架（第 279 轮）：证明 check-mock-retirement.cjs 的 **A7 不是空跑**。

★ 为什么用副本树、而不是改真文件：
  改真文件的话，注入中途失败会留下一个"catch 里灌 mock"的工作区 —— 那正是
  本次要消灭的东西。门禁本身支持 `MOCK_RETIRE_SRC_ROOT` 指向副本树
  （它自己的头部就写了这个用法），所以副本树是设计好的路径。

★ 判定必须看**精确失败集**：
  "整体红了"不是证据 —— 红的可能是别的断言（"红了但红的是别的"= 假证据）。
  每个注入只许红它该红的那一条，多一条少一条都算失败。

★ 全程零删除：case 之间靠**回写原始 bytes** 复位，最后只做一次整体清理。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # frontend/
SRC = ROOT / 'src'
WORK = ROOT / '.tmp_mock_inject'                        # 副本树根
NODE = Path('C:/Users/Administrator/.workbuddy/binaries/node/versions/22.22.2-3/node.exe')
CHECK = ROOT / 'scripts' / 'check-mock-retirement.cjs'

if not NODE.exists():
    sys.exit('找不到 node：' + str(NODE))
if not CHECK.exists():
    sys.exit('找不到门禁：' + str(CHECK))


def build_tree() -> int:
    """建副本树（覆盖式拷贝，零删除）。

    ★ 为什么不用 rmtree：本环境把递归删除**拦成 trash 操作**，约 200 个文件会被
      拒绝，而且异常在**跑完之后**才抛 ⇒ 退出码假绿、现场残留。
      `dirs_exist_ok=True` 覆盖已有文件，效果等价且不触碰删除路径。
    """
    dst = WORK / 'src'
    shutil.copytree(SRC, dst, dirs_exist_ok=True)
    return sum(1 for _ in dst.rglob('*') if _.is_file())


def run_gate():
    env = dict(os.environ, MOCK_RETIRE_SRC_ROOT=str(WORK / 'src'))
    p = subprocess.run(
        [str(NODE), str(CHECK)],
        capture_output=True, text=True, encoding='utf-8', errors='replace', env=env,
    )
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def fail_names(out):
    names = []
    for line in out.splitlines():
        s = line.strip()
        if s.startswith('FAIL'):
            rest = s[4:].strip()
            names.append(rest.split('  \u2190')[0].strip())
    return sorted(names)


def patch(rel, old, new):
    p = WORK / 'src' / rel
    b = p.read_bytes()
    s = b.decode('utf-8')
    # ★ 同一仓 CRLF / LF 混存（Subscription.vue 是 CRLF，candidateLibrary.ts 也是；
    #   而 productLibrary.ts 是 LF）⇒ 锚点必须在**行尾归一化**后比对，
    #   否则在 CRLF 文件上恒 0 命中，看起来像"源码已变"，其实是探针自己的坑。
    crlf = s.count('\r\n') > 0
    norm = s.replace('\r\n', '\n')
    n = norm.count(old)
    if n != 1:
        raise AssertionError('%s: 锚点命中 %d 次（期望 1）' % (rel, n))
    norm = norm.replace(old, new, 1)
    out = norm.replace('\n', '\r\n') if crlf else norm
    p.write_bytes(out.encode('utf-8'))
    return b  # 原始 bytes，供复位


# ---------------------------------------------------------------- 用例
# (名, [(rel, old, new) ...], 期望失败的断言名前缀集合)
CASES = [
    ('baseline（不动）', [], set()),
    (
        'T1 plans 回退 mockPlans',
        [('views/Subscription.vue', '    plans.value = []\n', '    plans.value = mockPlans\n')],
        {'A7'},
    ),
    (
        'T2 invoices 回退 mockInvoices',
        [('views/Subscription.vue', '    invoices.value = []\n', '    invoices.value = mockInvoices\n')],
        {'A7'},
    ),
    (
        'T3 candidateLibrary 回退假 ASIN 候选',
        [
            (
                'stores/candidateLibrary.ts',
                '      items.value = []\n',
                '      items.value = [...MOCK_CANDIDATES]\n',
            )
        ],
        {'A7'},
    ),
    (
        'T4 反面对照：把合法的置空改成另一处非 mock 赋值（不该红）',
        [('views/Subscription.vue', '    plans.value = []\n', '    plans.value = FALLBACK_SAFE\n')],
        set(),
    ),
]

print('=== 建副本树 ===')
n_files = build_tree()
print('  副本 src：%d 个文件' % n_files)
originals = {}   # rel -> bytes

ok = True
for name, patches, expect in CASES:
    # 复位（把上一轮改过的文件写回）
    for rel, b in originals.items():
        (WORK / 'src' / rel).write_bytes(b)
    originals.clear()

    if patches:
        for rel, old, new in patches:
            originals[rel] = patch(rel, old, new)

    rc, out = run_gate()
    got = fail_names(out)
    got_prefix = {g.split()[0] for g in got}

    if expect:
        passed = (rc != 0) and (got_prefix == expect)
    else:
        passed = (rc == 0) and (len(got) == 0)

    print('\n--- %s ---' % name)
    print('  门禁退出码 = %d' % rc)
    if got:
        for g in got:
            print('  FAIL  %s' % g)
    else:
        print('  （无 FAIL）')
    print('  期望失败集 = %s  ⇒  %s' % (sorted(expect) or '(空)', 'PASS' if passed else 'FAIL'))
    if not passed:
        ok = False

print('\n' + ('=' * 44))
print('反向注入台架：%s' % ('ALL PASS' if ok else 'FAILED'))
sys.exit(0 if ok else 1)
