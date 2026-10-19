# Android 壳的安全区：对话区顶部压在系统状态栏上（r384）

> 现象：pad 上「每个 agent 的对话区顶部」都和系统状态栏重叠。
> 结论：**重叠成立，且是全局的（不是某一页）**。修法照 eEducation 第 489 轮那套：
> 壳把 inset 推成 CSS 变量，页面整体下移。
> 本轮改的是**壳**，前端只补了一条门禁（消费端上一轮就写好了）。

## 一、实测：重叠了多少

设备 MRX-AL09（华为 MatePad Pro）· 横屏 **2560×1600** · `density 400`（2.5x）
⇒ 逻辑视口 **1024×640 CSS px**（≤ 1100 ⇒ 走窄屏单栏形态）。

系统栏实测（`dumpsys window displays`）：

```
mDisplayFrame=Rect(0, 0 - 2560, 1600)
InsetsSource type=ITYPE_STATUS_BAR     frame=[0,0][2560,80]  visible=true
InsetsSource type=ITYPE_NAVIGATION_BAR frame=[0,0][0,0]      visible=false
```

⇒ **状态栏 80 物理 px = 32 CSS px**；导航栏隐藏（横屏手势）。

### 修复前的像素证据

| 判据 | 修复前 | 含义 |
|---|---|---|
| header 底边线（横贯分隔线） | **y = 121** | 而 header 顶边 = **y = 0** ⇒ 整条头栏从屏幕最顶开始画 |
| 折叠按钮 ≡ 最上一条线 | **y = 47** | 47 < 80 ⇒ 落在状态栏带内 |
| 折叠按钮三条线 | 47–49 / 57–71 / 79–81 | 第三条线跨在状态栏下沿上 |

后果不只是"看着挤"：**按钮的上半截被系统抢走了点击**。
`adb shell input tap 105 72`（按钮中心）点下去，系统把它当成状态栏点击，
**侧栏根本打不开** —— 用户感知是"这个按钮坏了"。

截图为证：`docs/assets/r384/before-overlap.png`（时间 7:11 与 ≡ 叠在一起）。

## 二、根因：`--sat` 从头到尾没人赋值

链路上有两半，**只有一半在**：

| 一半 | 位置 | 状态 |
|---|---|---|
| **消费端**（读 `var(--sat)` 做 padding） | `frontend/src/styles/safe-area.css` | ✅ 上一轮已写好（`.workspace-container` / `.login-container` / 窄屏 fixed 栏） |
| **生产端**（把 inset 写成 CSS 变量） | `desktop/.../MainActivity.kt` | ❌ **还是 `android init` 的模板**，从未推送过 |

模板里只有 `enableEdgeToEdge()`：它让内容铺满全屏，**把 inset 交还应用自己消费**。
没人消费 ⇒ `--sat` 停在 `safe-area.css` 的默认值 `0px` ⇒ 所有 `padding-top: var(--sat)`
等于 `padding-top: 0`。**页面不报错、构建不报警**。

三个"永远不报错"叠加在一起，所以浏览器里怎么测都测不出来：

1. `env(safe-area-inset-*)` 在 **Android WebView 里恒为 `0px`**
   （它是浏览器特性：Safari 靠 `viewport-fit=cover` 填值、Chrome 对刘海填值；
   WebView 把状态栏当 **window insets** 交给 activity，从不转成 CSS 变量）；
2. `gen/` 被 `.gitignore` 忽略 ⇒ 补丁物不在版本库里，`git status` 永远干净；
3. 桌面端 / Web 端**不经过 MainActivity** ⇒ 所有浏览器侧检查全绿。

## 三、修法（照 eEducation 489 的形态）

`MainActivity.kt` 加三件事，**不改前端任何样式**：

1. **`onWebViewCreate(webView)`** —— 这里才拿得到 WebView 实例
   （`onCreate` 里 Tauri 还没建出来，写在那儿等于没有）；
2. **`addDocumentStartJavaScript`** 注入取值函数 `__ECOM_APPLY_INSETS__(t,b,l,r)`
   —— 每个新文档都执行，导航一次不会丢；
3. **`setOnApplyWindowInsetsListener`** 读 `systemBars() | displayCutout()`，
   除以 `displayMetrics.density` 后推给页面。

三个细节都是踩过才知道的：

- **为什么推变量而不是给 content view 加 padding**：padding 区显示的是**原生背景**，
  登录页的紫色渐变会在顶上多一顶 32px 的"白帽子"。推变量则背景仍由网页绘制。
- **为什么不关 edge-to-edge**：Android 15+（targetSdk 35+）强制 edge-to-edge，
  关掉只会在旧系统上"看起来好了"。
- **为什么必须除 density**：inset 是物理像素，CSS 要 CSS px。
  忘了除就是 2.5 倍留白 —— "看起来只是有点大"，没有绝对值可比，极难归因。

## 四、验证：7 个入口，位移一律 +80px

`desktop/out/店管管-pad-arm64-0.1.0.apk`（`lastUpdateTime=19:32`）装到平板上，
逐 agent 切换后截图测量（`--status-bar 80`）：

| agent | 按钮顶边 | header 底边线 | 落在状态栏内 | 判定 |
|---|---|---|---|---|
| 店秘书 | 127 | 201 | 0 行 | ✅ |
| 选品分析师 | 127 | 201 | 0 行 | ✅ |
| 竞品监控员 | 127 | 201 | 0 行 | ✅ |
| AIGC 媒体生成器 | 127 | 201 | 0 行 | ✅ |
| 广告分析师 | 127 | 201 | 0 行 | ✅ |
| 智能客服 | 127 | 201 | 0 行 | ✅ |
| 运营复盘师 | 127 | 201 | 0 行 | ✅ |

**每个数字都恰好差 80**：

```
header 底线  121 → 201   (+80)
按钮顶边      47 → 127   (+80)
80 物理 px = 32 CSS px × density 2.5  ✓
```

数值一致本身就说明"所有 agent 共用同一条 header" —— 所以是**一处修、七处好**。

侧栏（窄屏下是 `position: fixed` 浮层）也一并让位了：
`docs/assets/r384/after-sidebar.png` 里「店管管 · 亚马逊1」从状态栏下方开始。

## 五、门禁：`npm run check:android-safe-area`

新增 `frontend/scripts/check-android-safe-area.cjs`（7 条，已串进 `build`）：

| id | 判据 |
|---|---|
| A1 | bridge **定义 + 调用**两处齐全（只定义不调用 = 变量永远拿不到值） |
| A2 | 挂在 `onWebViewCreate` 上（写 `onCreate` 等于没有） |
| A3 | `addDocumentStartJavaScript` + 老 WebView 降级分支 |
| **A4** | ★★ **CSS 消费的变量集合 ↔ Kotlin 推送的集合，双向对账** |
| A5 | 按 `displayMetrics.density` 换算 |
| A6 | `main.ts` 导入了 `safe-area.css` |
| A7 | `.workspace-container` / `.login-container` 都有 `padding-top: var(--sat)` |

**A4 是核心**：它防的不是"删了"，而是**改名型**静默失效 ——
比如 CSS 改用 `--safe-top`、Kotlin 还在推 `--sat`。这种改动页面不报错，
只是"不让位了"，肉眼还容易归因成"这次打包有问题"。

`gen/` 不存在时整组判 **SKIP**（别人 clone 后没有它，不该误判成红），
前端侧的 A6/A7 仍照跑。

### 反向注入：6 变异 / 6 抓到 / 0 逃逸

`.workbuddy/probes/mutate-android-safe-area.cjs` —— **不写任何源文件**：
复制到临时目录、改副本、用门禁自己认的 env 指过去，跑完删掉。

| 变异 | 期望 | 结果 |
|---|---|---|
| M1 删掉 `onWebViewCreate` 覆盖 | A2 红 | ✅ |
| M2 Kotlin 把 `--sat` 改名 `--safe-top` | A4 红 | ✅ |
| M3 删掉 `addDocumentStartJavaScript` | A3 红 | ✅ |
| M4 删掉 `main.ts` 的 css 导入 | A6 红 | ✅ |
| M5 删掉 `.login-container` 安全区块 | A7 红 | ✅ |
| M6 去掉 density 换算 | A5 红 | ✅ |

判据自己踩过的两个坑（都已修，留档防复发）：

- **A1 正则漏了 `window.`**：实际调用形态是 `__X__&&window.__X__(`，
  第一版正则写成 `__X__&&__X__(` ⇒ 假红。
- **像素探针把状态栏时钟当成了按钮**：x 区间 60..150 覆盖了「7:33」，
  修复后仍报"重叠 53 行"。收窄到 **60..100**（左 < 107 避开时钟、右 < 160 避开正文）
  后，两个版本的按钮都是干净的三簇。

## 六、没做的与前提

- **登录页未真机验证**：`.login-container` 的规则与工作台同构（同一份 CSS、同一个变量），
  但要看到登录页得清应用数据，本轮没做 ⇒ 记为待验。
- **`80px` 是这台机器的实测值**，不是常量。换设备/换方向（竖屏、刘海屏）需要重测，
  判据里的 `--status-bar` 参数就是给这个用的。
- **只影响 Android 壳**：Web 端与 Windows 壳不经过 `MainActivity`，
  `--sat` 保持 `0px` ⇒ 布局逐字不变（这也是 safe-area.css 默认值的意义）。
- **补丁物会被覆盖**：`scripts\android.cmd init` 重建 `gen/` 之后，
  必须按本文第三节重打 `MainActivity.kt`，然后跑一次
  `npm run check:android-safe-area` 确认不是模板。

## 附录：`MainActivity.kt` 全文（重打 `gen/` 后从这里复制）

```kotlin
package cn.shopbutler.desktop

import android.os.Bundle
import android.webkit.WebView
import androidx.activity.enableEdgeToEdge
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature

class MainActivity : TauriActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    // ★ 必须在 super.onCreate **之前**（enableEdgeToEdge 要求）
    enableEdgeToEdge()
    super.onCreate(savedInstanceState)
  }

  override fun onWebViewCreate(webView: WebView) {
    super.onWebViewCreate(webView)

    installInsetBridge(webView)

    ViewCompat.setOnApplyWindowInsetsListener(webView) { _, insets ->
      val bars = insets.getInsets(
        WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout()
      )
      pushInsets(webView, bars.top, bars.bottom, bars.left, bars.right)
      // ★ 返回 insets 而不是 CONSUMED：软键盘走 ime()，吞掉会废掉下游的 inset 处理
      insets
    }
    ViewCompat.requestApplyInsets(webView)

    // ★ 兜底一次：listener 首次分发可能早于文档解析（evaluateJavascript 落到 about:blank 就丢了）
    webView.postDelayed({ pushCurrentInsets(webView) }, 1200)
  }

  private fun installInsetBridge(webView: WebView) {
    val script = """
      (function () {
        if (window.__ECOM_APPLY_INSETS__) return;
        window.__ECOM_APPLY_INSETS__ = function (t, b, l, r) {
          var s = document.documentElement.style;
          s.setProperty('--sat', (t || 0) + 'px');
          s.setProperty('--sab', (b || 0) + 'px');
          s.setProperty('--sal', (l || 0) + 'px');
          s.setProperty('--sar', (r || 0) + 'px');
        };
      })();
    """.trimIndent()

    if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
      WebViewCompat.addDocumentStartJavaScript(webView, script, setOf("*"))
    } else {
      webView.evaluateJavascript(script, null)
    }
  }

  private fun pushInsets(webView: WebView, top: Int, bottom: Int, left: Int, right: Int) {
    val d = resources.displayMetrics.density
    if (d <= 0f) return
    val js = "window.__ECOM_APPLY_INSETS__&&window.__ECOM_APPLY_INSETS__(" +
      "${top / d},${bottom / d},${left / d},${right / d})"
    webView.evaluateJavascript(js, null)
  }

  private fun pushCurrentInsets(webView: WebView) {
    val insets = ViewCompat.getRootWindowInsets(webView) ?: return
    val bars = insets.getInsets(
      WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout()
    )
    pushInsets(webView, bars.top, bars.bottom, bars.left, bars.right)
  }
}
```

> 注意：Kotlin 三引号模板里**不能出现 `$`**（会被当模板前缀）；
> `pushInsets` 里那两个 `$` 是**普通双引号串**的模板，合法且必要。
