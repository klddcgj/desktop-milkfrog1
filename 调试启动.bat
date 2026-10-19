@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Desktop Pet - DEBUG
echo ============================================================
echo   桌宠 Desktop Pet  -  调试模式（保留控制台与日志）
echo ============================================================
echo.
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py -3"
if not defined PY goto nopython

echo [1/2] 素材自检...
%PY% desktop_pet.py --selftest
echo.
echo [2/2] 启动桌宠（带状态机日志；关掉本窗口或按 Ctrl+C 即退出）
echo ------------------------------------------------------------
%PY% desktop_pet.py --verbose %*
echo.
echo 桌宠已退出。
pause
exit /b 0

:nopython
echo [错误] 没有找到 Python，请先安装 Python 3.10 或更高版本
echo        安装时请勾选 Add Python to PATH
echo        下载地址 https://www.python.org/downloads/
pause
exit /b 1
