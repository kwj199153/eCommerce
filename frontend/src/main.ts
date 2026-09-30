import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'

import App from './App.vue'
import router from './router'

// 全局共享样式层（S0 归位：原先散落在组件内的非 scoped 块）
import './styles/popup.css'          // teleport 到 body 的弹层样式
import './styles/antd-tag-tokens.css' // antd Tag 色名 → 本项目语义 token 映射层
import './styles/sidebar-nav.css'     // 侧边栏分组标题 / 分节菜单的唯一真源（第 260 轮）

// 创建应用实例
const app = createApp(App)

// 使用插件
app.use(createPinia())
app.use(router)
app.use(Antd)

// 挂载
app.mount('#app')
