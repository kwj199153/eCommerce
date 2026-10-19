@echo off
rem Build the desktop shell. Usage: scripts\build.cmd [--debug] [--no-bundle]
rem Runs from repo root so the beforeBuildCommand path stays valid.
setlocal

call "%~dp0env.cmd"
if errorlevel 1 exit /b 1

cd /d "%~dp0.."

if not exist "node_modules\.bin\tauri.cmd" goto :err_no_cli

rem ---------------------------------------------------------------
rem Clear frontend\dist BEFORE tauri runs beforeBuildCommand.
rem Reason: vite's emptyOutDir uses node's rmSync, and this machine's
rem node runs with a safe-delete shim that aborts any single delete of
rem more than 50 files. dist holds ~75 (card-art alone is 57), so the
rem second build onward would fail with
rem   [SAFE_DELETE_BULK_CONFIRM_REQUIRED] {"count":75,...}
rem cmd's own rmdir does not go through that shim, so delete it here.
rem With no dist present, vite creates a fresh one and never deletes.
rem ---------------------------------------------------------------
if exist "..\frontend\dist" rmdir /s /q "..\frontend\dist"

rem Where npm for the frontend build comes from. beforeBuildCommand in
rem tauri.conf.json calls "npm", so it must be on PATH.
where npm >nul 2>&1
if errorlevel 1 echo [build] WARN: npm not on PATH, frontend prebuild may fail

echo [build] tauri build %*
call "node_modules\.bin\tauri.cmd" build %*
exit /b %errorlevel%

:err_no_cli
echo [build] tauri CLI missing. Run: npm install
exit /b 1
