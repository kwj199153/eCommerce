# -*- coding: utf-8 -*-
"""
反向注入探针（第 279 轮）：证明 CDP 场景 f 的 F1/F3 判据在「改前」会红。

★ 为什么不用 git 恢复：
  本文件带着**本轮未提交的改动**（正是要验的这份）。`git checkout -- <file>` 会
  静默把整轮改动一起抹掉 —— 本仓那条「禁无差别 git show HEAD:f > f」讲的就是这个。
  所以注入前先把原始 bytes 备份到独立文件，恢复只走备份。

★ 注入的是**行为等价于改前**的最小改动（不是把整块 mock 搬回来）：
  catch 里 `invoices.value = []` → 灌一条假账单；并删掉 `invoicesError.value = ...`。
  效果 = 改前：用户看到假账单、且界面把失败说成「暂无」。

用法：python scripts/.probe_f_inject.py inject | restore
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / 'src' / 'views' / 'Subscription.vue'
BACKUP = ROOT / 'scripts' / '.probe_f_inject.bak'

INJECT_CONST = (
    "// \u2605 临时注入（反向注入探针用，跑完立即还原 \u2014\u2014 见 .probe_f_inject.py）\n"
    "const MOCK_INV_FOR_PROBE: Invoice[] = [\n"
    "  { id: 'inv-x', number: 'INV-20260901-001', amount: 99, currency: 'CNY', status: 'paid',\n"
    "    description: '\u5047\u8d26\u5355', issued_at: '2026-09-01T00:00:00Z', paid_at: '2026-09-01T00:05:00Z', pdf_url: '#' },\n"
    "]\n"
)
ANCHOR_CONST = "const plansError = ref('')\n"
OLD_ASSIGN = "    invoices.value = []\n"
NEW_ASSIGN = "    invoices.value = MOCK_INV_FOR_PROBE\n"
OLD_ERR = "    invoicesError.value = (e as Error)?.message || '\u8d26\u5355\u52a0\u8f7d\u5931\u8d25'\n"


def norm_read():
    b = TARGET.read_bytes()
    s = b.decode('utf-8')
    crlf = s.count('\r\n') > 0
    return b, s, crlf, s.replace('\r\n', '\n')


def write_norm(norm, crlf):
    out = norm.replace('\n', '\r\n') if crlf else norm
    TARGET.write_bytes(out.encode('utf-8'))


def do_inject():
    b, _s, crlf, norm = norm_read()
    BACKUP.write_bytes(b)  # ★ 先备份，再动手
    checks = [(norm.count(ANCHOR_CONST), 1, 'ANCHOR_CONST'),
              (norm.count(OLD_ASSIGN), 1, 'OLD_ASSIGN'),
              (norm.count(OLD_ERR), 1, 'OLD_ERR')]
    for got, want, name in checks:
        if got != want:
            sys.exit('[FAIL] %s 命中 %d 次（期望 %d）' % (name, got, want))
    norm = norm.replace(ANCHOR_CONST, INJECT_CONST + ANCHOR_CONST, 1)
    norm = norm.replace(OLD_ASSIGN, NEW_ASSIGN, 1)
    norm = norm.replace(OLD_ERR, '', 1)
    write_norm(norm, crlf)
    print('[ok] 已注入：假账单 %r + 删掉 invoicesError 赋值' % 'INV-20260901-001')


def do_restore():
    if not BACKUP.exists():
        sys.exit('[FAIL] 找不到备份 %s' % BACKUP)
    TARGET.write_bytes(BACKUP.read_bytes())
    BACKUP.unlink()
    print('[ok] 已从备份还原（%d B）' % TARGET.stat().st_size)


if __name__ == '__main__':
    cmd = (sys.argv[1] if len(sys.argv) > 1 else '').lower()
    if cmd == 'inject':
        do_inject()
    elif cmd == 'restore':
        do_restore()
    else:
        sys.exit('用法：.probe_f_inject.py inject | restore')
