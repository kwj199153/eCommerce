# -*- coding: utf-8 -*-
"""修复 ReviewDeskConfig 的 TS 索引类型报错（一次真正的落盘修改）。

报错原文：
  Property '' does not exist on type '{ approve: string; reject: string; issue: string; }'
⇒ 字面量对象的键被推成三个联合，`pendingAct` 可以为 `''` ⇒ 索引失败。
"""
from __future__ import annotations

from pathlib import Path

VIEW = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "components" / "TaskConfigPanel" / "configs"
    / "ReviewDeskConfig.vue"
)

src = VIEW.read_bytes().decode("utf-8").replace("\r\n", "\n")

old = """const confirmTitle = computed(() => ({
  approve: '批准这条处置？',
  reject: '驳回这条处置？',
  issue: '发放补偿？（不可逆）',
}[pendingAct.value] || '确认操作'))

const confirmText = computed(() => ({
  approve: '批准后进入待发放状态；发放仍需你再点一次。',
  reject: '驳回后这条处置会标记为 rejected，可以重新生成草稿。',
  issue: '发放会**生成券码**且不可撤销 —— 券码一旦发出就是既成事实。',
}[pendingAct.value] || ''))"""

new = """/** ★ 必须显式声明成 `Record<string, string>`：字面量对象的键会被推成
 *   `'approve' | 'reject' | 'issue'`，而 `pendingAct` 合法的默认值是 `''`
 *   ⇒ 用 `''` 去索引会直接 TS2339（不是 lint 洁癖，是真编译不过）。 */
const CONFIRM_TITLES: Record<string, string> = {
  approve: '批准这条处置？',
  reject: '驳回这条处置？',
  issue: '发放补偿？（不可逆）',
}
const CONFIRM_TEXTS: Record<string, string> = {
  approve: '批准后进入待发放状态；发放仍需你再点一次。',
  reject: '驳回后这条处置会标记为 rejected，可以重新生成草稿。',
  issue: '发放会生成券码且不可撤销 —— 券码一旦发出就是既成事实。',
}

const confirmTitle = computed(() => CONFIRM_TITLES[pendingAct.value] || '确认操作')
const confirmText = computed(() => CONFIRM_TEXTS[pendingAct.value] || '')"""

assert src.count(old) == 1, f"锚点命中 {src.count(old)} 次"
VIEW.write_bytes(src.replace(old, new, 1).encode("utf-8"))
print("fixed confirm maps")
