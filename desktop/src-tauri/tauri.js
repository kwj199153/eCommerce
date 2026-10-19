// ★★★ 这个文件不是"我们自己要调 CLI"，而是给 Gradle 的 rust 插件兜底。
//
// Tauri 生成的 `src-tauri/gen/android/buildSrc/.../BuildTask.kt` 里这样调 CLI：
//
//     val executable = """node"""
//     val args = listOf("tauri", "android", "android-studio-script")
//     workingDir(File(projectDir, rootDirRel))   // = src-tauri
//
// `node tauri` 里的 "tauri" 会被 Node **当成模块名**解析，于是从 cwd = src-tauri
// 往上找 `node_modules/tauri` —— 没有这个包（CLI 的 bin 叫 `node_modules/.bin/tauri`，
// 是 .cmd 壳，Node 的模块解析既不认 .bin 也不认 .cmd）。
//
//     Error: Cannot find module 'D:\...\src-tauri\tauri'
//     > A problem occurred starting process 'command 'node.bat''
//
// 报错里一个字都没提 CLI 路径不对。补法就一个文件：Node 对 `require('tauri')`
// 会先试相对文件 `./tauri.js`，命中就用它 ⇒ 把 argv 原样转发给真正的 CLI 入口。
//
// ★ 为什么用 createRequire：本包 `"type": "module"` ⇒ 本文件是 ESM，没有 require；
//   而 CLI 入口是 CJS，用动态 import() 会把执行时机推到微任务之后。
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
require('../node_modules/@tauri-apps/cli/tauri.js')
