/**
 * 功能模块开关（前端侧）
 *
 * 与后端 `core/config.py` 的附加模块开关**一一对应**：
 * | 前端 | 后端 | 说明 |
 * |---|---|---|
 * | `VITE_VOICE_CLONE_ENABLED` | `VOICE_CLONE_ENABLED` | 语音克隆（客服音色） |
 *
 * ★ 默认值铁律：附加模块开关**默认 false**（与后端一致）。
 *   与 `demoMode.ts` 的默认 true 不同 —— 那是「兼容旧行为」，
 *   而这里是「装了也不生效，必须显式打开」，默认必须是关。
 *
 * ★ 为什么前端也要一个开关（不能只靠后端 404）：
 *   只有后端开关时，Tab 照常显示 → 用户点进去 → 面板请求 /voice-clone/config
 *   → 拿到 404 → 显示「模块未启用」空态。这是**降级兜底**，不是真隐藏。
 *   前端开关让「总开关关闭 ⇒ 入口整个消失」，让「可插拔」在前端也成立。
 *
 * ⚠️ 两个开关需一起打开：
 *   - frontend/.env.local : VITE_VOICE_CLONE_ENABLED=true
 *   - backend/.env        : VOICE_CLONE_ENABLED=true
 *   只开前端 → Tab 出现但所有请求 404（面板会给出明确提示）；
 *   只开后端 → 路由存在但前端无入口（功能不可达）。
 */

/** 语音克隆（客服音色）模块是否启用。默认关闭，与后端 VOICE_CLONE_ENABLED 对齐。 */
export const VOICE_CLONE_ENABLED: boolean =
  import.meta.env.VITE_VOICE_CLONE_ENABLED === 'true'
