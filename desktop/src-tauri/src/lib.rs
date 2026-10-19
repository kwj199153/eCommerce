//! 店管管 壳的入口库（Tauri 2）。
//!
//! 形态与 `eEducation/desktop` 同构（那边踩过的坑这里直接继承，不再重踩一遍）。
//!
//! ★★★ 为什么入口在 lib 而不在 main：Tauri 2 的移动端（Android / iOS）把整个应用
//!   编译成一个**库**供原生工程调用，`main.rs` 在移动端根本不执行。所以 `run()` 必须
//!   住在 lib 里，并由 `#[cfg_attr(mobile, tauri::mobile_entry_point)]` 暴露入口符号。
//!   ⚠️ 把逻辑写进 main.rs 是 Tauri 2 最常见的「桌面能跑、Android 白屏」原因。
//!
//! 本文件做三件事：
//!   1. 注入后端地址（`window.__ECOM_API_ORIGIN__`）
//!   2. 注入存盘能力（`window.__ECOM_SAVE_FILE__`）+ 对应的原生命令
//!   3. run
//!
//! ★ 每加一个插件，**三处必须同时改**：Cargo.toml 依赖 · 这里 `.plugin(...)` ·
//!   capabilities/default.json 的 permissions。只改两处 = 编译过、运行时报权限拒绝。

use base64::Engine as _;
use tauri_plugin_dialog::DialogExt;

/// 后端 origin（**不含** `/api` 后缀、**不含**尾部斜杠）。
///
/// 取值优先级（前者覆盖后者）：
///   1. 运行时环境变量 `ECOM_API_ORIGIN` —— 开发时临时指另一台后端，不用重新编译；
///      显式设成单个 `-` ⇒ 注入**空串**，前端退回相对路径（配合 vite proxy 的常规开发）；
///   2. 编译期环境变量 `ECOM_API_ORIGIN` —— **发布包**用它钉死
///      （`set ECOM_API_ORIGIN=… && scripts\build.cmd`）；
///   3. 兜底 = 线上产品口 `https://111.229.201.117:8090`
///      （`docs/产品侧上线契约.md` §3.3：`/api/` 与 `/static/` 都在同一个 vhost 内反代）。
///
/// ★★★ 为什么兜底**不是** `127.0.0.1:8000`（与 eEducation 相反的那一处）：
///   那边兜底指本机、靠环境变量覆盖上线；这里的交付形态是「装到客户机就能用」，
///   而装上去以后既没有 `.env`、也没有人设环境变量 —— 兜底指本机的结果是
///   **每一台机器上都表现为「账号或密码错误」**（请求打在没人监听的 8000 上）。
///   所以本仓把兜底钉在线上口，开发态反而由 `dev.cmd` 显式覆盖成 `-`。
///
/// ★★★ 为什么是 **https** 而不是 http（第 383 轮实测纠正）：
///   `8090` 这个口只讲 TLS —— 发明文 http 会让 nginx 直接回
///   `400 The plain HTTP request was sent to HTTPS port`，即**每条请求 400**。
///   证书是 Let's Encrypt 签的 IP 证书（short-lived，约 6 天），系统根证书链默认信任
///   （实测 `curl` 不带 `-k` 也是 200）⇒ Android WebView 同样能过校验，
///   因此 release 包不再需要 `usesCleartextTraffic`。
///   ⚠️ 该证书只有几天有效期：续期一旦断，壳里所有请求会集体失败，
///      表现为「登录页一直提示账号或密码错误」——排查时先看证书，不要先查密码。
const DEFAULT_API_ORIGIN: &str = "https://111.229.201.117:8090";

fn api_origin() -> String {
    let norm = |v: &str| v.trim().trim_end_matches('/').to_string();

    if let Ok(v) = std::env::var("ECOM_API_ORIGIN") {
        if v.trim() == "-" {
            // 显式「相对路径」：注入空串，前端 apiBaseUrl() 退化成 `/api/v1`
            return String::new();
        }
        let v = norm(&v);
        if !v.is_empty() {
            return v;
        }
    }
    if let Some(v) = option_env!("ECOM_API_ORIGIN") {
        if v.trim() == "-" {
            return String::new();
        }
        let v = norm(v);
        if !v.is_empty() {
            return v;
        }
    }
    DEFAULT_API_ORIGIN.to_string()
}

/// 生成在**页面任何脚本之前**执行的注入脚本。
///
/// ← 前端读它的两处（字符串必须**逐字一致**）：
///     · `frontend/src/config/runtimeApi.ts` → `__ECOM_API_ORIGIN__`
///     · `frontend/src/utils/saveFile.ts`     → `__ECOM_SAVE_FILE__`
///   ★ 改一处不改另一处，结果不是报错，而是「壳里静默地走相对路径」
///     （所有接口拿到 200 + index.html）或「导出静默无事发生」。
fn init_script(origin: &str) -> String {
    // 用 serde_json 转义，避免地址里的特殊字符把脚本拼坏
    let lit = serde_json::to_string(origin).unwrap_or_else(|_| "\"\"".to_string());

    // ★★★ 存盘函数为什么在**调用时**才去找 invoke：`window.__TAURI_INTERNALS__`
    //   由 Tauri 自己的注入脚本建立，两者谁先执行取决于内核版本 —— 注入时刻取引用会
    //   出现「有时拿到 undefined、有时正常」的偶发失败。惰性解析后顺序完全不影响结果。
    // ★ 用 `__TAURI_INTERNALS__` 而不是开 `withGlobalTauri`：后者会把整套 API 挂到
    //   `window.__TAURI__`（多一份可被页面脚本调用的面），这里只需要一个 invoke。
    format!(
        r#"window.__ECOM_API_ORIGIN__ = {lit};
window.__ECOM_SAVE_FILE__ = async function (filename, base64) {{
  var internals = window.__TAURI_INTERNALS__;
  if (!internals || typeof internals.invoke !== 'function') {{
    throw new Error('Tauri 运行时就绪前已被调用');
  }}
  return await internals.invoke('save_export_file', {{ filename: filename, base64Data: base64 }});
}};"#
    )
}

/// 把前端给的字节**存到用户选的位置**。
///
/// 返回值：`Ok(Some(绝对路径))` = 已写入；`Ok(None)` = 用户取消；`Err(..)` = 失败。
///
/// ★★★ 为什么必须由壳来做：Web 上 `a[download]` 由**浏览器下载管理器**接手
///   （存下载目录、显示下载条、失败会报错）。WebView2 里没有下载管理器，
///   `a[download]` 多数情况**什么都没发生** —— 不报错、不弹框、控制台干净。
///
/// ★ 参数用 base64 而不是字节数组：Tauri 2 的 IPC 走 JSON 序列化，
///   `Vec<u8>` 从 JS 传过来会变成 `number[]`（体积约 3.5 倍、解析极慢）。
async fn save_export_file_impl(
    app: tauri::AppHandle,
    filename: String,
    base64_data: String,
) -> Result<Option<String>, String> {
    // 1) 先解码再弹框：base64 坏了就不该让用户白选一次路径
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(base64_data.as_bytes())
        .map_err(|e| format!("文件内容编码无效：{e}"))?;

    // 2) 原生保存框。
    //    ★ 用 `.save_file(cb)` 回调式而不是 `blocking_save_file()`：blocking 版在
    //      主线程调用会 panic，而 async command 跑在哪个线程取决于 Tauri 的调度。
    //    ★ 回调结果用 mpsc 递回来；`recv()` 放进 `spawn_blocking` —— 直接在 async fn
    //      里 `.recv()` 会占死一个 worker 线程（用户把对话框放着不动时，运行时少一格）。
    let (tx, rx) = std::sync::mpsc::channel();
    app.dialog()
        .file()
        .set_file_name(&filename)
        .save_file(move |picked| {
            let _ = tx.send(picked);
        });

    let picked = tauri::async_runtime::spawn_blocking(move || rx.recv())
        .await
        .map_err(|e| format!("保存对话框异常：{e}"))?
        .map_err(|e| format!("保存对话框未返回结果：{e}"))?;

    let Some(file_path) = picked else {
        // 用户点了取消 —— 这不是错误，前端据此**不弹「已导出」**
        return Ok(None);
    };

    // 3) 写盘。
    let path = file_path
        .into_path()
        .map_err(|e| format!("所选路径不可用：{e}"))?;
    std::fs::write(&path, &bytes).map_err(|e| format!("写入失败：{e}"))?;
    Ok(Some(path.display().to_string()))
}

#[tauri::command]
async fn save_export_file(
    app: tauri::AppHandle,
    filename: String,
    base64_data: String,
) -> Result<Option<String>, String> {
    save_export_file_impl(app, filename, base64_data).await
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut context = tauri::generate_context!();

    // ★★★ 窗口仍然由 `tauri.conf.json` 声明（唯一真源），但这里把声明取出来自己建 ——
    //   只为了能挂 `initialization_script`。conf 的 WindowConfig 没有这个字段，
    //   而注入必须赶在页面脚本之前（用 on_page_load + eval 会落在 about:blank 上被清掉）。
    //   ⚠️ 取走后必须清空声明，否则框架会按声明再建一个同 label 的窗口 ⇒ 冲突。
    let win_cfg = context.config_mut().app.windows.drain(..).next();

    let script = init_script(&api_origin());

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![save_export_file])
        .setup(move |app| {
            if let Some(cfg) = win_cfg {
                tauri::WebviewWindowBuilder::from_config(app.handle(), &cfg)?
                    .initialization_script(&script)
                    .build()?;
            }
            Ok(())
        })
        .run(context)
        .expect("error while running tauri application");
}
