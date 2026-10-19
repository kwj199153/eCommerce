@echo off
rem Start the desktop shell in dev mode (expects vite on 127.0.0.1:5174).
rem Usage: scripts\dev.cmd
rem If vite is not running, start it first: cd frontend ^&^& npm run dev
setlocal

call "%~dp0env.cmd"
if errorlevel 1 exit /b 1

cd /d "%~dp0.."

if not exist "node_modules\.bin\tauri.cmd" goto :err_no_cli

echo [dev] tauri dev %*
call "node_modules\.bin\tauri.cmd" dev %*
exit /b %errorlevel%

:err_no_cli
echo [dev] tauri CLI missing. Run: npm install
exit /b 1
