/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 演示模式开关：true 时无 token 自动注入 demo-token（跳过登录），false 时强制真实登录 */
  readonly VITE_DEMO_MODE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
