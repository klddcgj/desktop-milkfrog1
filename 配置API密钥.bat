@echo off
rem ============================================================
rem  Desktop Pet  ——  接入大模型 API Key（图形向导）
rem  选厂商 -> 粘贴 Key -> 保存并测试，Key 只写进本机 config.json
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"
title 桌宠 · 配置 API Key

echo ============================================================
echo    桌宠 Desktop Pet  ·  配置大模型 API Key
echo ============================================================
echo.

set "PYCMD="
python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
if not defined PYCMD (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD goto nopython

echo 正在打开配置向导窗口...
%PYCMD% desktop_pet.py --setup-llm

echo.
echo 向导已关闭。配好后直接双击「启动桌宠.bat」即可用大模型聊天。
pause
exit /b 0

:nopython
echo [错误] 没有找到可用的 Python，请先安装 Python 3.10+ 并勾选 Add Python to PATH。
pause
exit /b 1
