/**
 * 技能仓库 API
 *
 * 数据源：后端 PostgreSQL（/api/v1/skills、/api/v1/agents），唯一权威源。
 *
 * 三个设计取舍（与后端一致，改动时别顺手"修正"）：
 *  1. **列表不返回正文**（content）——正文动辄数千字符，列表页一次要展示几十条，
 *     全带上等于把列表接口变成一次全量导出。点开详情时再按需拉。
 *     这与 `platformRules.ts` 的「文档列表不带 content」同判据。
 *  2. **Agent 目录是后端给的**（`/agents`）而不是前端硬编码 ——
 *     它同时含前端 id 与后端 agent_name，是两套 ID 空间的唯一桥接。
 *     前端再抄一份 = 第二份实现，改一处就静默失配。
 *  3. **`load_skill` 不进前端**：技能的"加载"发生在后端 Agent 内部（模型调工具），
 *     前端只负责管理，不参与运行时披露。
 */

import { get, post, put, del } from './request'
import type {
  Skill,
  SkillRevision,
  AgentCatalogItem,
  ToolCatalogItem,
  ToolGroup,
  ToolUsage,
} from '@/stores/skills'

/** 平台 Agent 目录（勾选界面的数据源；含前端 id 与后端 agent_name 的对应） */
export async function fetchAgents(): Promise<{ items: AgentCatalogItem[]; total: number }> {
  return get('/agents')
}

/**
 * 平台工具目录（**工具技能**勾选的数据源）。
 *
 * ★ 为什么这个端点必须存在（第 185 轮）：
 *   在此之前「工具定义」是一个自由文本输入框，用户可以填任意字符串 ——
 *   包括根本不存在的工具名（旧 placeholder 举例的 `export_report` 就是一例，
 *   全仓不存在）。本端点把「有哪些工具」从**要用户猜**变成**可枚举的事实**。
 *
 * ★ `grouped` 的分组口径由**后端**给：工具是按 Agent 装配的，
 *   前端自己按 `agent` 字段再分一遍 = 第二份实现，改一处就静默失配
 *   （与 `fetchAgents` 同判据）。
 *
 * ★ 只含**真接线**的工具（55 个）。那些「注册了但没有任何 Agent 绑定」的
 *   后端刻意不下发 —— 勾了也调不起来，让用户勾一个不生效的工具更糟。
 *   （第 204 轮把最后 19 个悬空工具接给了各自的 Agent，总数 36 → 55。）
 */
export async function fetchTools(): Promise<{
  items: ToolCatalogItem[]
  grouped: ToolGroup[]
  total: number
}> {
  return get('/tools')
}

/**
 * 工具 ← 技能 的**反向引用**（工具仓库视图的数据源，第 208 轮）。
 *
 * ★ 为什么需要它：正向边（技能引用了哪些工具）界面上早就有了
 *   （编辑抽屉的「配套工具」+ 卡片上的工具 tag）；**反向边完全没有展示面**。
 *   那就是「工具仓库」相对「技能仓库」唯一真正新增的信息。
 *
 * ★ 与 `/tools` **不同鉴权档**（同前缀不代表同档）：
 *     `/tools`      静态平台元数据（有哪些工具）⇒ 后端不鉴权；
 *     本端点        内容是「**你账号下**哪些技能引用了它」
 *                   ⇒ 过 `get_acting_user`，否则就是越权枚举。
 *
 * ★ `unknownTools` / `unusedTools` 由**后端算好**：
 *   它们与 `usage` 是同一次遍历的三个投影。前端拿 `usage` 与目录表自己做差集
 *   = 第二份实现，改一处就静默失配 —— 而症状只是"某个工具的引用数不对"，
 *   没有任何一处会报错。
 */
export async function fetchToolUsage(): Promise<ToolUsage> {
  return get('/tools/usage')
}

/** 技能列表（不含正文） */
export async function fetchSkills(): Promise<{ items: Skill[]; total: number }> {
  return get('/skills')
}

/** 技能详情（**含正文**） */
export async function fetchSkill(id: string): Promise<Skill> {
  return get(`/skills/${id}`)
}

export async function createSkill(data: Partial<Skill>): Promise<Skill> {
  return post('/skills', data as any)
}

export async function updateSkill(id: string, data: Partial<Skill>): Promise<Skill> {
  return put(`/skills/${id}`, data as any)
}

export async function deleteSkill(id: string): Promise<{ message: string; id: string }> {
  return del(`/skills/${id}`)
}

/** 版本历史（按时间倒序） */
export async function fetchSkillRevisions(
  id: string
): Promise<{ items: SkillRevision[]; total: number }> {
  return get(`/skills/${id}/revisions`)
}

/**
 * 回滚到某个历史版本。
 *
 * ★ 回滚**不删历史** —— 它本身产生一条新快照（action=rollback）。
 *   否则"回滚"这个动作会抹掉证据，事后无从知道什么时候被回滚过。
 */
export async function rollbackSkill(id: string, revisionId: string): Promise<Skill> {
  return post(`/skills/${id}/rollback`, { revisionId })
}

/**
 * 设置该技能对哪些 Agent 生效（**全量覆盖**语义）。
 *
 * ★ 传**后端 agent_name**；后端也接受前端 id 并做归一（`find_by_id`），
 *   但前端手里已经有 `AgentCatalogItem.name`，直接传它最不容易错。
 * ★ 覆盖而不是增量：勾选界面就是"一组 checkbox 的当前值"，
 *   增量接口会让并发两次勾选产生无法解释的合并结果。
 */
export async function setSkillAgents(id: string, agentNames: string[]): Promise<Skill> {
  return put(`/skills/${id}/agents`, { agentNames })
}

/**
 * 设置该技能**配备**哪些工具（**全量覆盖**语义，「skill 配装」的唯一写口）。
 *
 * ★★ 必须记住它**不是权限**：`skill.tools` 在运行期既不授予也不限制任何工具。
 *   Agent 手上真正有哪些工具由**代码装配**决定（真源 `TOOL_CATALOG`，
 *   由 `tests/test_tool_catalog.py` 判据 A 与真实装配点双向钉死）。
 *   本字段的唯一去处是 `render_skill_body()` 往提示词里渲染
 *   「本技能配套工具」—— 是**提示词引导**（软）。
 *   界面上必须如实标注，否则用户会以为"勾了就等于授权"。
 *
 * ★ 后端对**未注册的工具名 422 硬拒**（不静默丢弃）：静默丢弃会让用户看到
 *   「勾了 3 个、保存后只剩 1 个」却不知道为什么；工具退役后旧名字更会从
 *   「生效」变成「永久空转」而界面上看不出差别。
 *
 * ★ 与 `setSkillAgents` 同形态（`PUT` + 目标值 + 全量覆盖），理由同源。
 */
export async function setSkillTools(id: string, toolNames: string[]): Promise<Skill> {
  return put(`/skills/${id}/tools`, { toolNames })
}

/**
 * 收藏 / 取消收藏（⭐，第 194 轮）。
 *
 * ★ 传**明确的目标值**而不是「切换」：toggle 不幂等 —— 网络重试、用户双击、
 *   乐观更新失败后重发，都会让状态翻转**两次**，结果与用户意图相反，
 *   而界面上看不出哪里错了（星标正好回到点击前的样子）。
 *   与 `setSkillAgents` 同形态（`PUT` + 目标值），理由也同源。
 *
 * ★ 返回**服务端回执** `{ id, favorited }`：前端以它为准，不拿本地推测值
 *   当真源（本地那份只是乐观更新的临时态）。
 *
 * ★ 这个端点也过归属校验：拿不存在的 `skill_id` 去收藏会得到 403/404
 *   同一个响应 —— 不能因为"收藏只是个人偏好"就变成存在性探测器。
 */
export async function setSkillFavorite(
  id: string,
  favorited: boolean
): Promise<{ id: string; favorited: boolean }> {
  return put(`/skills/${id}/favorite`, { favorited })
}
