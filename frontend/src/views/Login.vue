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
          <!-- ★ 第 113 轮：最近登录过的账号（数据来自 config/knownAccounts.ts）
               三条约束：
                 · 一个账号都没记过时整块不渲染，不留空标题；
                 · 提供「清除」—— 共享电脑上这份列表等同于"谁用过这台机器"，
                   用户必须能自己抹掉（不能只增不减）；
                 · **点选即尝试免密登录**（★ 第 123 轮改）：点一个账号 =
                   想进这个账号，所以先走 /auth/device/switch；本机没记过时
                   降级为只填邮箱，并把「为什么还要输密码」明确说出来。
                   ★ 这与「不接受没点就发生的事」不矛盾：那条防的是**页面
                     自己替你提交**，而这里是用户点了一个具体账号。详见
                     pickAccount() 的注释。 -->
          <div v-if="knownAccounts.length" class="recent-accounts">
            <div class="ra-title">
              <span>最近登录</span>
              <button type="button" class="ra-clear" @click="clearKnownAccounts">
                清除
              </button>
            </div>
            <div class="ra-list">
              <button
                v-for="a in knownAccounts"
                :key="a.id"
                type="button"
                class="ra-item"
                :class="{ active: loginForm.email === a.email, switching: switchingId === a.id }"
                :disabled="!!switchingId"
                :title="hasCred(a)
                  ? `免密登录 ${a.email}`
                  : `登录 ${a.email}（本机尚未记住，需输入一次密码）`"
                @click="pickAccount(a)"
              >
                <span class="ra-avatar">{{ (a.name || a.email).charAt(0).toUpperCase() }}</span>
                <span class="ra-meta">
                  <span class="ra-name">{{ a.name }}</span>
                  <span class="ra-mail">{{
                    switchingId === a.id ? '正在免密登录…' : a.email
                  }}</span>
                </span>
                <!-- ★ 第 125 轮：把「能不能免密」直接画在条目上。
                     ★ 切换中不显示 —— 那时文案由 ra-mail 的「正在免密登录…」
                       承担，两处同时出现会让同一条目的信息自相打架。 -->
                <span
                  v-if="!switchingId"
                  class="ra-badge"
                  :class="hasCred(a) ? 'on' : 'off'"
                >{{ hasCred(a) ? '免密' : '需密码' }}</span>
              </button>
            </div>
            <!-- ★ 第 125 轮：这条说明在侧栏的「切换账号」列表里**早就有了**
                 （AccountMenu.vue 的 sp-note，第 120 轮加），登录页却一直缺 ——
                 ⇒ 用户在登录页看得到「需密码」这个标记，却永远读不到
                 「它是什么意思、该怎么办」。这正是老板那两句
                 「有时候可以免密登录，有时候不能」「目前是只支持免密切换吗」
                 的由来：界面上只有结论，没有依据。
                 ★ 同一个解释只挂在两个入口中的一个上，等于没有。 -->
            <p class="ra-note">
              标「需密码」的账号，用密码登录一次后即可免密（凭据加密存于服务端）。
            </p>
          </div>


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

          <!-- ★ 第 122 轮：「记住登录状态」勾选框。
               它**替代**了第 120 轮那条解释性说明条（老板实测后要求去掉）：
               与其用一段文字告诉用户「这次输完密码之后就会免密」，不如把
               这件事做成他自己可控的开关 —— 本项目既有判据是「不接受
               没点就发生的事」，而此前"登录即记住"恰恰是一件没点就发生的事。
               ★ 取消勾选会**撤销**该账号已有的免密，而不只是"这次不新增"：
                 否则对已经记住过的账号，这个勾选框就是个摆设。 -->
            <a-form-item class="remember-row">
              <a-checkbox v-model:checked="rememberDevice">
                记住登录状态，下次免密切换
              </a-checkbox>
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
                  validator: async (_rule: unknown, value: string) => {
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

      <!-- 演示模式（仅 DEMO_MODE 开启时显示） -->
      <template v-if="DEMO_MODE">
        <a-divider>演示模式</a-divider>
        <a-button
          type="dashed"
          block
          @click="handleDemoLogin"
        >
          🚀 一键体验（跳过登录）
        </a-button>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { UserOutlined, LockOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useUserStore } from '@/stores/user'
import { DEMO_MODE, DEMO_TOKEN, DEMO_REFRESH_TOKEN, DEMO_USER } from '@/config/demoMode'
import { useKnownAccounts, forgetAllAccounts, type KnownAccount } from '@/config/knownAccounts'
import { isRemembered, rememberedAccountCount, forgetRemembered } from '@/config/authVault'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

/**
 * 登录成功后的落点。
 *
 * ★ 支持 `?redirect=`：从受保护页（如「团队成员」）被引导过来时，
 *   登录完应当回到原处，而不是一律丢回首页 —— 否则用户会觉得
 *   刚才点的那一下"白点了"，又得自己找回去。
 *
 * ★ 只接受**站内绝对路径**：`//evil.com` 会被浏览器当成协议相对 URL
 *   跳到外站，是典型的开放重定向口子，这里必须挡掉。
 */
function redirectTarget(): string {
  const raw = route.query.redirect
  const path = typeof raw === 'string' ? raw : ''
  if (path.startsWith('/') && !path.startsWith('//')) return path
  return '/'
}

const activeTab = ref('login')

// 登录表单
const loginForm = reactive({
  email: '',
  password: '',
})

/**
 * 是否把这次的登录凭据交给服务端托管（= 本机免密切换）。
 *
 * ★ 默认 true：与本次改动之前的行为一致。**不勾选**才是主动选择 ——
 *   反过来（默认不勾）等于让常用账号的用户每次登录都要记得勾一下，
 *   那是把机制的负担转嫁给用户。
 *
 * ★ 名字刻意不叫「记住密码」：本项目**不保存密码**，服务端加密托管的
 *   是 refresh token（第 119 轮决策）。叫「记住密码」会承诺一件没做的事，
 *   正是项目明令禁止的「命名承诺型偏差」。
 */
const rememberDevice = ref(true)

// 注册表单
const registerForm = reactive({
  email: '',
  name: '',
  password: '',
  confirmPassword: '',
})

// ====== 账号历史（★ 第 113 轮）======
// 读的是 `config/knownAccounts.ts` 的响应式镜像（唯一真源，模块导入时已自举）。
// 这里**只读 + 只清除**，写入点在 `stores/user.ts` 的 setAuthData()。
const knownAccounts = useKnownAccounts()

/**
 * 正在尝试免密切换的账号 id（空串 = 没有在切）。
 *
 * ★ 为什么必须有它：点选现在会**发一次网络请求**，而原生的 <button>
 *   没有内置 loading 态。少了这个闸门会出两个真问题：
 *     · 连点两下 ⇒ 两次 switch 并发，后到的响应会覆盖先到的 token 与 user，
 *       而两次响应的到达顺序并不保证 ⇒ 可能出现「点的是 A，进去的是 B」；
 *     · 等待期间界面毫无变化，用户以为没点上，于是接着点。
 *   ⇒ 它同时承担「防重入」与「给出反馈」两件事，模板里两处消费：
 *     `:disabled` 与 `:class="{ switching: ... }"`。
 */
const switchingId = ref('')

/**
 * 本机**是否已记住**这个账号（决定点下去是免密、还是需要输一次密码）。
 *
 * ★★★ 第 125 轮新增。起因是老板截图里的一处**自相矛盾**：
 *   鼠标停在「胡说树」上，原生 tooltip 写着「免密登录 263977396@qq.com」，
 *   点下去弹出的却是「本设备尚未记住 263977396@qq.com」——
 *   同一个按钮，两句相反的承诺。
 *
 *   根因不是文案写错，而是**信息缺失**：`KnownAccount`
 *   （config/knownAccounts.ts）里没有「本机是否记住过它」这个字段。
 *   那份列表记的是「谁用过这台机器」（账号历史），与「本机现在能不能免密」
 *   （免密凭据清单）本来就是**两件事**。写模板时手上只有前者，
 *   于是 title 只能无条件写「免密登录」。
 *
 * ★★★ 而这个缺陷的**同构版本**在侧栏「切换账号」列表里**早就修好了**
 *   （AccountMenu.vue，第 119 / 120 轮）：那边有 `hasCred()` 判「免密 / 需密码」、
 *   有 `switchTitle()` 把「点了会怎样」提前说清、还有一条说明解释
 *   「标需密码的账号，用密码登录一次后即可免密」。
 *   ⇒ 同一个状态、同一份判定，**两个列表只有一个展示了它** ——
 *     老板那句「有时候可以免密登录，有时候不能」，正是从缺了展示的那一侧看出去的。
 *
 *   ⇒ 修法刻意与 AccountMenu **同源同形**：判定一律走 `config/authVault.ts` 的
 *     `isRemembered`（免密清单的前端唯一出口），不在这里另判一遍；连"怎么建立
 *     响应式依赖"都照那边的写法来 —— 免得同一种判定长出第二种消费姿势、日后漂移。
 *
 * ★ 为什么是 `void rememberedAccountCount.value` 而不是 computed：
 *   `isRemembered()` 读的是 `authVault.ts` 里的模块级 ref，而模板里的**函数调用**
 *   不会被 Vue 自动追踪 —— 不显式读一下某个响应式值，标记就会停在旧值上
 *   （现象：「刚免密进过一次，回到登录页标记却没变」）。
 *   `rememberedAccountCount` 正是那个 ref 的 computed 出口，读它即建立依赖。
 *   ★ 这一行**不是**在取数：删掉它不会报任何错，只会让界面悄悄变旧。
 *     故门禁把这一形态钉住（check-auth-vault.cjs 的「免密标记必须建立响应式依赖」）。
 */
function hasCred(a: KnownAccount): boolean {
  void rememberedAccountCount.value
  return isRemembered(a.id)
}

/**
 * 点选历史账号（★ 第 123 轮：从「只填邮箱」升级为「**先尝试免密登录**」）。
 *
 * ★★★ 起因是老板的实测反馈：
 *   「已经勾选记住密码了，可是选择最近的登录账号，每次登录还是要重新输
 *     密码，只是登录完后切换账号这个功能正常」
 *
 *   原实现只把邮箱填进输入框，用户随后必然要点「登录」—— 而那条路是
 *   `/auth/login`（密码验证），**无论本机有没有记住都绕不开密码**。
 *   于是「记住登录状态，下次免密切换」这句承诺在这一格上根本不成立：
 *   用户点了「最近登录」，拿到的是一个"还得自己输"的空表单。
 *
 *   ⇒ 点选 = 尝试免密，与头像下拉里的「切换账号」走**同一条**通道
 *     （`userStore.switchToAccount`）—— 同一种用户意图不该有两套实现。
 *
 * ★ **未登录态能不能调 switch**？能，而且这是刻意设计的（第 119 轮）：
 *   `/auth/device/switch` 不要求真身份，它靠 httpOnly Cookie 里的
 *   device_id 认"这台机器"，正是为了覆盖「当前身份已不可用」这个场景。
 *   已用真服务实测（`.workbuddy/probes/_r123probe.py`）：
 *     无 Authorization + 有 device cookie → **200 已切换**
 *     无 cookie                            → 401「本机没有记住任何登录状态…」
 *     有 cookie 但该账号没被记住            → 401「本机未记住该账号的登录状态…」
 *
 * ★ **降级路径必须完整保留**：本机没记过时仍然只填邮箱 + 密码留空，
 *   并把原因说出来 —— 否则用户只能对着一份"点了没反应"的列表猜。
 *   ★ 先填邮箱再尝试：无论成败用户都看得到自己选了谁，免密失败时
 *     这就已经是降级后的可用状态，不需要再补一次动作。
 */
const pickAccount = async (a: KnownAccount) => {
  if (switchingId.value) return
  loginForm.email = a.email
  loginForm.password = ''
  activeTab.value = 'login'

  switchingId.value = a.id
  try {
    const switched = await userStore.switchToAccount(a.id)
    if (switched) {
      message.success(`已切换到 ${switched.name || switched.email}`)
      router.push(redirectTarget())
      return
    }
    // 走到这里 = 本机没记住这个账号（或凭据已过期 / 服务端不可达）。
    // ★ 文案必须回答用户此刻唯一的问题：「那我为什么还要输密码？」
    //   含糊地说「免密失败」等于让他自己猜，而他会猜成"功能是坏的"。
    //
    // ★★★ 第 125 轮补：**必须同时把本地标记也去掉**。
    //   少了这一行，条目上的「免密」会一直挂着骗人：用户点一次失败、标记不变，
    //   就再点一次，来回几次之后他得到的结论是「这功能时好时坏」——
    //   而真因是「服务端早就没记住它了，只是界面没说」。
    //   ⇒ 这正是老板那两句话的**同一条根**：**界面显示的状态落后于真实状态**。
    //
    //   ★ 与侧栏 AccountMenu.vue 的失败分支**同源同形**（它第 119 轮就写了
    //     这一行）。不是为了对称好看，而是同一个判断不该有第二种处置 ——
    //     两个入口点同一个账号，失败后的结果必须一样。
    //   ★ 失败方向也是安全的：最坏结果只是标记变成「需密码」、用户多输一次；
    //     反过来（保留标记）会让他一直去点一个注定失败的入口。
    forgetRemembered(a.id)
    message.info(`本设备尚未记住 ${a.email}，输入一次密码后即可免密切换`)
  } finally {
    switchingId.value = ''
  }
}

/** 抹掉本机这份列表（共享电脑上它等价于"谁用过这台机器"） */
const clearKnownAccounts = () => {
  forgetAllAccounts()
  message.success('已清除本机记住的账号')
}

/**
 * 从「切换账号」入口跳过来时带上了 `?email=`，预填邮箱。
 *
 * ★ 只预填、不提交：切换账号在不保存凭据的前提下必然要重新登录，
 *   但"要重新输密码"不等于"要重新输邮箱"。
 * ★ 不做 `router.replace` 清 query：留着它刷新后行为一致，
 *   而邮箱本来就已经显示在下面的「最近登录」里，不增加暴露面。
 *
 * ★ 第 122 轮：这里原本还渲染一句「正在切换到 X —— 用密码登录一次
 *   即可」的说明条（第 120 轮加的）。老板实测后明确要求去掉：它在解释
 *   一件**本可以让他自己开关**的事。同一件事现在由下面的「记住登录状态」
 *   勾选框承担 —— 它是用户可见、可撤销的选择，而不是一段只能读的文字。
 *   ★ 预填邮箱这一半**保留**：要重新输密码不等于要重新输邮箱。
 */
onMounted(() => {
  const raw = route.query.email
  if (typeof raw === 'string' && raw) {
    loginForm.email = raw
  }
})

// 处理登录
const handleLogin = async () => {
  try {
    await userStore.login({
      email: loginForm.email,
      password: loginForm.password,
      // ★ 第 122 轮：把「要不要记住」交给用户当场决定（见模板里的勾选框）。
      //   它最终决定 stores/user.ts 会不会把凭据交给服务端托管。
      remember: rememberDevice.value,
    })
    message.success('🎉 登录成功')
    router.push(redirectTarget())
  } catch (error: any) {
    // ★ 第 117 轮：认证端点的 401 已改为由拦截器**直接交回本组件**
    //   （见 api/request.ts 的 401 分支短路），所以这里必须自己给文案。
    //   修复前依赖拦截器弹提示，而它固定说「登录已过期，请重新登录」——
    //   把「密码打错」渲染成「你被踢出去了」，是误导。
    //   只处理 401：其它状态码（400/422/500…）仍由拦截器统一提示，
    //   在这里再弹一次会变成两条。
    if (error?.response?.status === 401) {
      message.error(error?.response?.data?.detail || '登录失败，请检查邮箱与密码')
    }
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
    router.push(redirectTarget())
  } catch (error: any) {
    // ★ 同上：认证端点的 401 由本组件负责解释。
    if (error?.response?.status === 401) {
      message.error(error?.response?.data?.detail || '注册失败，请检查填写内容')
    }
  }
}

// 测试模式：一键体验
const handleDemoLogin = async () => {
  // 自动填充测试账号
  loginForm.email = DEMO_USER.email
  loginForm.password = 'demo123456'

  // 模拟登录（Phase 0 演示用）
  localStorage.setItem('access_token', DEMO_TOKEN)
  localStorage.setItem('refresh_token', DEMO_REFRESH_TOKEN)
  localStorage.setItem('user_info', JSON.stringify({
    ...DEMO_USER,
    created_at: new Date().toISOString(),
    last_login_at: new Date().toISOString(),
  }))

  // 更新 store 状态
  // ★ refresh_token 在这里是**刻意不设**的（第 117 轮明确下来）：
  //   demo 凭据后端一律不认，把它设进 store 只会让 401 拦截器
  //   （api/request.ts）发起一次注定失败的刷新。
  //
  //   判定真源 api/authRefreshPolicy.ts 只看 `userStore.hasRefreshToken`，
  //   而那个 getter 显式排除了 demo 伪凭据（stores/user.ts）——
  //   所以演示模式天然落在「不刷新」那一侧，这里不需要任何配合。
  //
  //   ★ 注意这已经从「想设也设不了」变成了「主动选择不设」：
  //     state 本身已有独立出口 `refreshTokenValue`
  //     （`refreshToken` 那个名字被同名 action 占用），随时可设。
  //
  //   localStorage 里那枚 demo-refresh-token 是演示登录的既有写法，
  //   不影响判定 —— 拦截器不读 localStorage，只读 store 内存态。
  userStore.$patch({
    token: DEMO_TOKEN,
    user: {
      ...DEMO_USER,
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
  padding: var(--space-40);
  background-color: var(--bg-elevated);
  border-radius: var(--radius-12);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
}

.logo {
  text-align: center;
  margin-bottom: var(--space-24);
}

.logo h1 {
  font-size: var(--font-size-28);
  color: var(--primary);
  margin-bottom: var(--space-8);
}

.logo p {
  font-size: var(--font-size-14);
  color: var(--text-tertiary);
}

/* ===== 最近登录（★ 第 113 轮）===== */
.recent-accounts {
  margin-bottom: var(--space-16);
}
.ra-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
  margin-bottom: var(--space-8);
}
.ra-clear {
  border: 0;
  background: transparent;
  color: var(--text-disabled);
  font-size: var(--font-size-12);
  cursor: pointer;
  padding: 0 var(--space-4);
  border-radius: var(--radius-4);
}
.ra-clear:hover { color: var(--danger); background: var(--danger-hover-bg); }

.ra-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  max-height: 168px;
  overflow-y: auto;
}
.ra-item {
  display: flex;
  align-items: center;
  gap: var(--space-10);
  width: 100%;
  text-align: left;
  border: 1px solid var(--border-base);
  background: var(--bg-base);
  border-radius: var(--radius-8);
  padding: var(--space-6) var(--space-10);
  cursor: pointer;
  transition: all 0.15s;
}
.ra-item:hover { border-color: var(--primary); background: var(--bg-hover-light); }
.ra-item.active { border-color: var(--primary); }
/* ★ 第 123 轮：点选会发一次真实请求，所以要给得出反馈。
   ★ 禁用整份列表而不是只禁被点的那一条：并发两次 switch 会让
     「点了 A 却进了 B」成为可能（两次响应到达顺序不保证）。 */
.ra-item:disabled { cursor: default; opacity: 0.6; }
.ra-item.switching {
  border-color: var(--primary);
  background: var(--bg-hover-light);
  opacity: 1;
}

/* ★ 第 125 轮：条目上的「免密 / 需密码」标记。
   ★ 为什么必须画在条目上、而不是只写在 tooltip 里：老板这轮的困惑
     「有时候可以免密登录，有时候不能」正是「不知道哪些能免密」的症状 ——
     而 tooltip 要 hover 才出现，且此前它无条件写「免密登录」，
     等于把唯一的线索变成了一条**会撒谎**的线索。
   ★ 两个状态刻意不等权：免密是常态（primary 色、浅底），
     「需密码」是临时状态（灰、只有描边），免得整列看起来像在报警。 */
.ra-badge {
  margin-left: auto;
  flex-shrink: 0;
  font-size: var(--font-size-11);
  line-height: 16px;
  padding: 0 var(--space-6);
  border-radius: var(--radius-4);
  white-space: nowrap;
}
.ra-badge.on {
  color: var(--primary);
  background: var(--bg-hover-light);
}
.ra-badge.off {
  color: var(--text-disabled);
  border: 1px solid var(--border-base);
}

/* 说明行（★ 第 125 轮）：对应 AccountMenu.vue 的 .sp-note。
   ★ 字号比列表正文还小一号，颜色用 tertiary 而非 disabled ——
     它是要读的说明，不是失效状态。 */
.ra-note {
  margin: var(--space-6) 0 0;
  font-size: var(--font-size-11);
  line-height: 1.5;
  color: var(--text-tertiary);
}

/* 「记住登录状态」勾选框（★ 第 122 轮）
   ★ 它替代了第 120 轮那条说明条（老板实测后要求去掉），
     所以这里不再需要单独的字号/边框覆盖 —— Ant 的 checkbox
     默认样式已经够低调，它本来就是**可选**而不是**警告**。 */
.remember-row {
  margin-bottom: var(--space-16);
}

.ra-avatar {
  width: 26px;
  height: 26px;
  min-width: 26px;
  border-radius: var(--radius-circle);
  background: linear-gradient(135deg, #52c41a, #389e0d);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-12);
  font-weight: 600;
  flex-shrink: 0;
}
.ra-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 1px;
  /* ★ 第 125 轮：占满头像与右侧状态标记之间的空间 ——
     否则「免密 / 需密码」会被长邮箱顶到卡片外面去。 */
  flex: 1;
}
.ra-name {
  font-size: var(--font-size-13);
  color: var(--text-primary);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ra-mail {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
