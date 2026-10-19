# desktop —— 店管管 桌面 / 平板壳（Tauri 2）

同一份前端产物，包成两个壳：Windows 安装包（NSIS exe）与 Android APK（平板）。
壳只做四件事：注入后端地址、提供原生存盘、加窗口/应用名、处理安全区。业务逻辑全在前端。

## 一、产品名只有一个真源

| 位置 | 字段 | 现值 |
|---|---|---|
| `src-tauri/tauri.conf.json` | `productName` | **店管管** |
| 同上 | `app.windows[0].title` | 店管管（Windows 标题栏） |
| `src-tauri/gen/android/.../values/strings.xml` | `app_name` / `main_activity_title` | 店管管（安卓桌面图标名 / 最近任务名） |

**`strings.xml` 是 `productName` 的派生物，而 `src-tauri/gen/` 被 `.gitignore` 忽略。**
⇒ 换机器 `tauri android init` 会按 `productName` 自动生成中文名；
若已有 `gen/` 是从旧英文名初始化出来的，`productName` 改了 **不会** 自动回写，必须手改这两行：

```bash
# 检查是否同步
grep -n "app_name" src-tauri/gen/android/app/src/main/res/values/strings.xml
```

> 第 382 轮只改了 `app.windows[0].title`（窗口标题），漏了 `productName`，
> 结果 app 内是「店管管」、平板桌面图标却是 `ShopButler`。第 383 轮已补齐。

**包名 `cn.shopbutler.desktop` 刻意保留**：它是应用的身份证，改了签名/升级链就断，
已装的旧版无法覆盖升级。它不出现在任何界面上。

## 二、后端地址

`src-tauri/src/lib.rs::DEFAULT_API_ORIGIN` = `https://111.229.201.117:8090`。

- **必须是 https**：8090 只讲 TLS，明文请求会被 nginx 回
  `400 The plain HTTP request was sent to HTTPS port`，表现为「每条请求都 400」。
- 证书是 Let's Encrypt 的 **IP 证书**（short-lived，几天有效期）。系统根链默认信任，
  Android WebView 也能过校验；但**续期一断，壳里所有请求会集体失败**，
  界面上的症状是「账号或密码错误」——先查证书，别先查密码。
- 覆盖顺序：运行时 `ECOM_API_ORIGIN` > 编译期 `ECOM_API_ORIGIN` > 上面的兜底。
  设成单个 `-` ⇒ 注入空串，前端退回相对路径（配合 vite proxy 的常规开发）。

## 三、构建

```bat
:: Windows 安装包 -> src-tauri\target\release\bundle\nsis\店管管_0.1.0_x64-setup.exe
scripts\build.cmd

:: 平板 APK -> app\build\outputs\apk\universal\release\
::   --split-per-abi 出单架构包（平板是 arm64-v8a）
scripts\android.cmd build --apk --split-per-abi

:: 开发态（需先起 vite；tauri.conf 的 devUrl 是 127.0.0.1:5173）
scripts\dev.cmd
```

两个脚本都会先跑 `beforeBuildCommand`（`npm --prefix ../frontend run build`），
也就是**全套前端门禁 + vue-tsc + vite build**；门禁红则壳打不出来。

`android.cmd build` 会先 `rmdir /s /q ..\frontend\dist`：vite 的 `emptyOutDir`
一次删 >50 文件会被本机 node 的 safe-delete 拦下，改用 cmd 的 rmdir 绕开。

## 四、签名（Android）

私钥在本机 `keystore/ecom-release.jks`，**不入库**（`.gitignore` 已忽略）。
换机器或私钥丢失时重新生成：

```bat
keytool -genkeypair -v -keystore keystore\ecom-release.jks -alias ecom ^
  -keyalg RSA -keysize 2048 -validity 10950 ^
  -storepass ecom-release-2026 -keypass ecom-release-2026 ^
  -dname "CN=DianGuanGuan, OU=Desktop, O=DianGuanGuan, L=Fuzhou, ST=Fujian, C=CN"
```

`tauri android build` 产出的是 **unsigned** APK，需手动对齐 + 签名：

```bat
set BT=D:\work\Android\sdk\build-tools\36.0.0
rem ★ `-f 4` 里的 4 不能省：少了它 zipalign 会把 `4` 当成参数字符串解析失败，
rem   报错信息只说 usage，不说"你漏了对齐值"（第 383 轮踩过）。
"%BT%\zipalign.exe" -p -f 4 app-arm64-release-unsigned.apk app-aligned.apk
"%BT%\apksigner.bat" sign --ks keystore\ecom-release.jks --ks-key-alias ecom ^
  --ks-pass pass:ecom-release-2026 --key-pass pass:ecom-release-2026 ^
  --out 店管管-pad-arm64-0.1.0.apk app-aligned.apk
```

⚠️ **签名换了就必须卸载重装**（`INSTALL_FAILED_UPDATE_INCOMPATIBLE`）。
同签名才能 `adb install -r` 覆盖升级、保住本地登录态。

## 五、Android 安全区补丁（`gen/` 里的补丁物，**必须手动维护**）

`enableEdgeToEdge()` 是 Tauri 2 模板**自带**的，内容会铺到系统状态栏底下。
前端 `styles/safe-area.css` 只负责消费 `var(--sat)` 一类变量 —— **值必须由壳推**，
`env(safe-area-inset-*)` 在 Android WebView 里恒为 `0px`，不是可选方案。

改的是这个文件：

```
src-tauri/gen/android/app/src/main/java/cn/shopbutler/desktop/MainActivity.kt
```

它必须包含 `onWebViewCreate` → `installInsetBridge` → `__ECOM_APPLY_INSETS__`
（定义 + 调用两处），并且把物理像素除以 `displayMetrics.density` 后再写 CSS 变量。

★★★ **`gen/` 被 `.gitignore` 忽略** ⇒ 这个补丁**不在版本库里**。
跑一次 `scripts\android.cmd init`（或删了 `gen/` 重建）就会**静默退回模板**，
症状是"重新打包后顶部又压状态栏了"，而 `git status` 是干净的、构建也不报错。

兜底判据：`npm run check:android-safe-area`（已串进 `frontend` 的 `build`）。
它把 Kotlin 推送的变量集合与 `safe-area.css` 消费的集合**双向对账**，
`gen/` 不存在时整组判 SKIP（别人 clone 后没有它，不该误判成红）。

写回补丁的最快方式：从 `docs/android-安全区-r384.md` 里复制整份 `MainActivity.kt`。

## 六、其它两个坑

- `src-tauri/gen/` 与 `target/` 都是生成物，已在 `.gitignore` 里。
  行尾门禁用 `git ls-files --eol --others --exclude-standard` 取清单，
  这两条一旦漏掉，清单会从 1200+ 涨到 3800+（构建产物里的 exe/pdb/jar 被判 CRLF）。
- `.jks` / `.keystore` 必须在 `.gitattributes` 里声明 `binary`：
  容器里有裸 CR，不声明会被行尾门禁当成「漂移的文本」而 FAIL。
