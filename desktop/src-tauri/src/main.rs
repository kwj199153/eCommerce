// ★★★ `windows_subsystem = "windows"` 只在 release 生效：开发时保留控制台
//   （看得到 println / panic），发布版才不会带一个黑框窗口。
//   这个属性必须写在**二进制的根**（main.rs），写在 lib.rs 里无效。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    ecommerce_desktop_lib::run()
}
