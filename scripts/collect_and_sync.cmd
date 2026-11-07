@echo off
chcp 65001 >nul
title 招标雷达 本机采集同步
echo 正在本机采集并生成云端同步包...
echo.
python "%~dp0collect_and_sync.py" %*
echo.
if errorlevel 1 (
  echo 采集或同步失败，请截图上面的信息。
) else (
  echo 完成。
)
pause
