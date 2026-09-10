<template>
  <div class="login-container">
    <div class="login-card">
      <div class="logo">
        <h1>跨境电商AI SaaS</h1>
        <p>一站式 AI 原生跨境电商全链路平台</p>
      </div>

      <!-- 登录/注册切换 -->
      <a-tabs v-model:activeKey="activeTab" centered>
        <a-tab-pane key="login" tab="登录">
          <a-form
            :model="loginForm"
            @finish="handleLogin"
            layout="vertical"
            class="login-form"
          >
            <a-form-item
              name="email"
              :rules="[{ required: true, message: '请输入邮箱' }]"
            >
              <a-input
                v-model:value="loginForm.email"
                placeholder="邮箱地址"
                size="large"
              >
                <template #prefix>
                  <UserOutlined />
                </template>
              </a-input>
            </a-form-item>

            <a-form-item
              name="password"
              :rules="[{ required: true, message: '请输入密码' }]"
            >
              <a-input-password
                v-model:value="loginForm.password"
                placeholder="密码"
                size="large"
              >
                <template #prefix>
                  <LockOutlined />
                </template>
              </a-input-password>
            </a-form-item>

            <a-form-item>
              <a-button
                type="primary"
                html-type="submit"
                :loading="userStore.isLoading"
                block
                size="large"
              >
                登录
              </a-button>
            </a-form-item>
          </a-form>
        </a-tab-pane>

        <a-tab-pane key="register" tab="注册">
          <a-form
            :model="registerForm"
            @finish="handleRegister"
            layout="vertical"
            class="login-form"
          >
            <a-form-item
              name="email"
              :rules="[
                { required: true, message: '请输入邮箱' },
                { type: 'email', message: '请输入有效的邮箱地址' },
              ]"
            >
              <a-input
                v-model:value="registerForm.email"
                placeholder="邮箱地址"
                size="large"
              >
                <template #prefix>
                  <UserOutlined />
                </template>
              </a-input>
            </a-form-item>

            <a-form-item
              name="name"
              :rules="[{ required: true, message: '请输入用户名' }]"
            >
              <a-input
                v-model:value="registerForm.name"
                placeholder="用户名（用于显示）"
                size="large"
              />
            </a-form-item>

            <a-form-item
              name="password"
              :rules="[
                { required: true, message: '请输入密码' },
                { min: 6, message: '密码至少 6 位' },
              ]"
            >
              <a-input-password
                v-model:value="registerForm.password"
                placeholder="密码（至少 6 位）"
                size="large"
              >
                <template #prefix>
                  <LockOutlined />
                </template>
              </a-input-password>
            </a-form-item>

            <a-form-item
              name="confirmPassword"
              :rules="[
                { required: true, message: '请确认密码' },
                {
                  validator: async (_rule, value) => {
                    if (value && value !== registerForm.password) {
                      throw new Error('两次密码不一致')
                    }
                  },
                },
              ]"
            >
              <a-input-password
                v-model:value="registerForm.confirmPassword"
                placeholder="确认密码"
                size="large"
              >
                <template #prefix>
                  <LockOutlined />
                </template>
              </a-input-password>
            </a-form-item>

            <a-form-item>
              <a-button
                type="primary"
                html-type="submit"
                :loading="userStore.isLoading"
                block
                size="large"
              >
                注册
              </a-button>
            </a-form-item>
          </a-form>
        </a-tab-pane>
      </a-tabs>

      <!-- 演示模式 -->
      <a-divider>演示模式</a-divider>
      <a-button
        type="dashed"
        block
        @click="handleDemoLogin"
      >
        🚀 一键体验（跳过登录）
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { UserOutlined, LockOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

const activeTab = ref('login')

// 登录表单
const loginForm = reactive({
  email: '',
  password: '',
})

// 注册表单
const registerForm = reactive({
  email: '',
  name: '',
  password: '',
  confirmPassword: '',
})

// 处理登录
const handleLogin = async () => {
  try {
    await userStore.login({
      email: loginForm.email,
      password: loginForm.password,
    })
    message.success('🎉 登录成功')
    router.push('/')
  } catch (error) {
    // 错误已在拦截器中处理
  }
}

// 处理注册
const handleRegister = async () => {
  try {
    await userStore.register({
      email: registerForm.email,
      password: registerForm.password,
      name: registerForm.name,
    })
    message.success('🎉 注册成功')
    router.push('/')
  } catch (error) {
    // 错误已在拦截器中处理
  }
}

// 测试模式：一键体验
const handleDemoLogin = async () => {
  // 自动填充测试账号
  loginForm.email = 'demo@ecommerce.ai'
  loginForm.password = 'demo123456'

  // 模拟登录（Phase 0 演示用）
  localStorage.setItem('access_token', 'demo-token')
  localStorage.setItem('refresh_token', 'demo-refresh-token')
  localStorage.setItem('user_info', JSON.stringify({
    id: 'demo-user-001',
    email: 'demo@ecommerce.ai',
    name: '演示用户',
    role: 'admin',
    is_active: true,
    is_verified: false,
    created_at: new Date().toISOString(),
    last_login_at: new Date().toISOString(),
  }))

  // 更新 store 状态
  userStore.$patch({
    token: 'demo-token',
    user: {
      id: 'demo-user-001',
      email: 'demo@ecommerce.ai',
      name: '演示用户',
      role: 'admin',
      is_active: true,
      is_verified: false,
      created_at: new Date().toISOString(),
      last_login_at: new Date().toISOString(),
    },
  })

  message.success('🎉 已进入演示模式')
  router.push('/')
}
</script>

<style scoped>
.login-container {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-card {
  width: 420px;
  padding: 40px;
  background-color: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
}

.logo {
  text-align: center;
  margin-bottom: 24px;
}

.logo h1 {
  font-size: 28px;
  color: #1890ff;
  margin-bottom: 8px;
}

.logo p {
  font-size: 14px;
  color: #8c8c8c;
}
</style>
