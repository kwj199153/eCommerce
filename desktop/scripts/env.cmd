@echo off
rem ============================================================
rem  env.cmd -- prepare MSVC link environment for cargo / tauri
rem  Called by build.cmd / dev.cmd via CALL. Do not run directly.
rem
rem  Why this file exists (all three verified on this machine):
rem  1) Git Bash ships /usr/bin/link.exe (coreutils hardlink tool).
rem     Its name collides with the MSVC linker. When cargo invokes a
rem     bare "link.exe", Git's one wins and fails with the cryptic
rem     "link: extra operand 'xxx.o'".
rem  2) The official vcvars64.bat uses reg.exe to locate VS and the
rem     Windows SDK. reg.exe is blocked by the command security policy
rem     here, so vcvars aborts half way and LIB ends up incomplete,
rem     producing "LNK1181: cannot open input file kernel32.lib".
rem  3) Therefore: do not use vcvars. Build LIB / INCLUDE from the
rem     directories directly. Versions are discovered by scanning,
rem     so upgrading VS or the SDK needs no edit here.
rem
rem  Two cmd.exe traps this file deliberately avoids:
rem  - Keep it ASCII-only. cmd parses .cmd as GBK; UTF-8 Chinese
rem    comments with full-width quotes break parsing.
rem  - SDK_ROOT contains "(x86)". A ")" inside for(...) or if(...)
rem    closes the block early. Hence delayed expansion (!VAR!) and
rem    goto instead of parenthesised blocks.
rem ============================================================
setlocal enabledelayedexpansion

set "VS_ROOT=D:\work\MSVC"
set "RUST_ROOT=D:\work\Rust"
set "SDK_ROOT=C:\Program Files (x86)\Windows Kits\10"

if not exist "%VS_ROOT%\VC\Tools\MSVC" goto :err_no_msvc

set "VCDIR="
for /d %%i in ("%VS_ROOT%\VC\Tools\MSVC\*") do set "VCDIR=%%i"
if "%VCDIR%"=="" goto :err_no_toolset

set "SDKVER="
for /d %%i in ("!SDK_ROOT!\Lib\10.*") do set "SDKVER=%%~nxi"
if "!SDKVER!"=="" goto :err_no_sdk

set "NEWLIB=%VCDIR%\lib\x64;%SDK_ROOT%\Lib\%SDKVER%\ucrt\x64;%SDK_ROOT%\Lib\%SDKVER%\um\x64"
set "NEWINC=%VCDIR%\include;%SDK_ROOT%\Include\%SDKVER%\ucrt;%SDK_ROOT%\Include\%SDKVER%\um;%SDK_ROOT%\Include\%SDKVER%\shared"
set "NEWPATH=%RUST_ROOT%\cargo\bin;%VCDIR%\bin\Hostx64\x64;%PATH%"

echo [env] VC  = %VCDIR%
echo [env] SDK = %SDKVER%

rem No parenthesised block after endlocal: NEWPATH contains "(x86)".
endlocal & set "LIB=%NEWLIB%" & set "INCLUDE=%NEWINC%" & set "RUSTUP_HOME=%RUST_ROOT%\rustup" & set "CARGO_HOME=%RUST_ROOT%\cargo" & set "PATH=%NEWPATH%"
exit /b 0

:err_no_msvc
echo [env] MSVC not found at %VS_ROOT%\VC\Tools\MSVC
exit /b 1

:err_no_toolset
echo [env] no MSVC toolset under %VS_ROOT%\VC\Tools\MSVC
exit /b 1

:err_no_sdk
echo [env] no Windows SDK under %SDK_ROOT%\Lib
exit /b 1
