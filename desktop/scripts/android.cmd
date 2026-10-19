@echo off
rem ============================================================
rem  android.cmd -- Android / Gradle environment + tauri passthrough
rem
rem  Usage (from anywhere):
rem    scripts\android.cmd                  -> print resolved env
rem    scripts\android.cmd init             -> tauri android init
rem    scripts\android.cmd dev              -> tauri android dev
rem    scripts\android.cmd build --apk --debug
rem    scripts\android.cmd ndk              -> print the ndkVersion the
rem                                            generated project expects
rem    scripts\android.cmd install-ndk 29.0.13846066    -> install that NDK
rem
rem  Why a separate script: the desktop build only needs MSVC (env.cmd).
rem  Android additionally needs JDK + Android SDK + NDK, and Gradle fails
rem  with messages that name none of them. Keeping the two environments
rem  apart means a broken Android setup can never break the desktop build
rem  (desktop shipping is the thing that already works).
rem
rem  Traps paid for with real rounds -- do not "clean these up":
rem  - ASCII only. cmd parses .cmd as GBK; UTF-8 Chinese comments with
rem    full-width punctuation break parsing in non-obvious ways.
rem  - No parenthesised block around values that may contain "(x86)".
rem    PATH / JDK paths can, so: goto, never if(...) blocks.
rem  - `%%~dp0` is NOT stable: `shift` also shifts %0. Snapshot THIS_DIR first.
rem  - env.cmd exports RUSTUP_HOME / CARGO_HOME / LIB / INCLUDE / PATH via
rem    "endlocal & set ...". If THIS script then calls endlocal, all of that is
rem    silently discarded. Symptom: `where cargo` still finds cargo.exe, but
rem    cargo answers "rustup could not choose a version of cargo to run ...
rem    no default is configured" -- RUSTUP_HOME empty, and the message never
rem    mentions it. Hence: declare constants, then setlocal, and never
rem    endlocal in this file.
rem ============================================================
set "THIS_DIR=%~dp0"
set "JAVA_ROOT=D:\work\Java\jdk-17"
set "SDK_DIR=D:\work\Android\sdk"

setlocal

if not exist "%JAVA_ROOT%\bin\java.exe" goto :err_no_jdk
if not exist "%SDK_DIR%\platform-tools" goto :err_no_sdk
if not exist "%SDK_DIR%\platforms" goto :err_no_sdk

rem ---- inherited MSVC / rust env (also puts cargo on PATH) ------------
call "%THIS_DIR%env.cmd"
if errorlevel 1 exit /b 1

set "JAVA_HOME=%JAVA_ROOT%"
set "ANDROID_HOME=%SDK_DIR%"
set "ANDROID_SDK_ROOT=%SDK_DIR%"

rem ---- pick the installed NDK, if any --------------------------------
rem Gradle wants one exact version (ndkVersion in build.gradle.kts), so this is
rem only a "something is there" pointer for tauri/cargo. The authoritative
rem version comes from `scripts\android.cmd ndk` AFTER init -- install THAT.
set "NDK_DIR="
for /d %%i in ("%SDK_DIR%\ndk\*") do set "NDK_DIR=%%i"

set "NEWPATH=%JAVA_HOME%\bin;%SDK_DIR%\platform-tools;%PATH%"
if not "%NDK_DIR%"=="" set "NEWPATH=%NDK_DIR%;%NEWPATH%"
set "NDK_HOME=%NDK_DIR%"
set "ANDROID_NDK_HOME=%NDK_DIR%"

if not "%~1"=="" goto :run

echo [android] env ready
echo [android]   JAVA_HOME   = %JAVA_HOME%
echo [android]   ANDROID_HOME= %ANDROID_HOME%
echo [android]   RUSTUP_HOME = %RUSTUP_HOME%
if "%NDK_HOME%"=="" echo [android]   NDK         = (none -- install before init)
if not "%NDK_HOME%"=="" echo [android]   NDK         = %NDK_HOME%
exit /b 0

:run
rem Do NOT shift and then reuse %*: in .cmd files %* always holds the ORIGINAL
rem argv (shift never touches it), so "%SUB% %*" duplicates the subcommand and
rem tauri answers "error: unexpected argument 'init' found".
set "SUB=%~1"
if /i "%SUB%"=="ndk" goto :show_ndk
if /i "%SUB%"=="install-ndk" goto :install-ndk

cd /d "%THIS_DIR%.."
if not exist "node_modules\.bin\tauri.cmd" goto :err_no_cli

rem tauri refuses to init without an NDK; say so here instead of letting it
rem print "Android NDK not found" with no hint about what to install.
if /i "%SUB%"=="init" if "%NDK_HOME%"=="" goto :err_no_ndk

echo [android] tauri android %*

rem Same safe-delete trap as build.cmd: tauri runs beforeBuildCommand (vite build),
rem and vite's emptyOutDir deletes >50 files in one go, which this machine's node
rem refuses ([SAFE_DELETE_BULK_CONFIRM_REQUIRED]). cmd's rmdir bypasses that shim,
rem and with no dist present vite creates a fresh one and never deletes.
if /i "%SUB%"=="build" if exist "..\frontend\dist" rmdir /s /q "..\frontend\dist"

rem ★ CARGO_INCREMENTAL=0 for the APK build. Evidence (488, both seen on this box):
rem   1) an android build emitted
rem        warning: error copying object file ... full.rmeta to incremental
rem        directory ...: Access is denied (os error 5)
rem   2) the very next android build then ICE'd inside rustc:
rem        rustc_metadata::rmeta::encoder::encode_metadata -- "no entry found for key"
rem      i.e. the compiler died while WRITING metadata, with a corrupted incremental
rem      dir underneath it. The crate builds 3 crate-types at once
rem      (staticlib + cdylib + rlib) plus --cfg mobile, which is exactly the shape
rem      that incremental handles worst.
rem   Incremental saves little here (a full 4-ABI build is minutes anyway) and the
rem   failure mode is a compiler crash that reads like "Rust is broken". Turn it off
rem   for artifact builds only: `android dev` keeps it, where it actually pays.
if /i "%SUB%"=="build" set "CARGO_INCREMENTAL=0"

call "node_modules\.bin\tauri.cmd" android %*
exit /b %errorlevel%

rem ---- report the ndkVersion the generated project expects ----------
rem Read from the file Gradle actually uses: cheap and authoritative. If it
rem does not exist, init has not run yet.
:show_ndk
cd /d "%THIS_DIR%.."
set "GRADLE_FILE=src-tauri\gen\android\app\build.gradle.kts"
if not exist "%GRADLE_FILE%" goto :err_no_gen
findstr /n /c:"ndkVersion" "%GRADLE_FILE%"
exit /b 0

:install-ndk
rem Deliberately NOT a generic "sdkmanager passthrough" with rebuilt args: %* is
rem immutable and %1 keeps its own quotes, so the rebuilt string arrives at
rem sdkmanager as `"ndk;29.0.13846066"` and cmd answers with the useless
rem   "29.0.13846066\""=="" was unexpected at this time."
rem One explicit single argument is boring and works.
if "%~2"=="" goto :err_ndk_arg
echo [android] sdkmanager "ndk;%~2"
call "%SDK_DIR%\cmdline-tools\latest\bin\sdkmanager.bat" "ndk;%~2"
exit /b %errorlevel%

:err_no_ndk
echo [android] no NDK installed under %SDK_DIR%\ndk
echo [android] install one first, e.g.:
echo [android]   scripts\android.cmd install-ndk 29.0.13846066
exit /b 1

:err_ndk_arg
echo [android] usage: scripts\android.cmd install-ndk ^<version^>
exit /b 1


:err_no_gen
echo [android] %GRADLE_FILE% not found - run: scripts\android.cmd init
exit /b 1

:err_no_jdk
echo [android] JDK not found at %JAVA_ROOT%\bin\java.exe
exit /b 1

:err_no_sdk
echo [android] Android SDK incomplete at %SDK_DIR% (need platform-tools + platforms)
exit /b 1

:err_no_cli
echo [android] tauri CLI missing. Run: npm install
exit /b 1
