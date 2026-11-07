@echo off
chcp 65001 >nul
title 咕咕嘎嘎
echo 正在启动 咕咕嘎嘎...
echo.
python "%~dp0launch_radar.py"
if errorlevel 1 (
  echo.
  echo 启动失败。请把这个窗口截图发给 Codex。
  pause
)
