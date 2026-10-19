@echo off
rem ============================================================
rem  桌宠 Desktop Pet  ——  双击即启动
rem  1) 自动找到能用的 Python（避开 Microsoft Store 的假 python 存根）
rem  2) 缺 Pillow 自动安装
rem  3) 退出时自动打印「本次运行」的日志，一眼看清退出原因
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"
title 桌宠 Desktop Pet

echo ============================================================
echo    桌宠 Desktop Pet  ·  正在启动
echo ============================================================
echo.

if not exist "%~dp0desktop_pet.py" (
    echo [错误] 本目录下找不到 desktop_pet.py
    echo        当前目录: %CD%
    echo        请把 启动桌宠.bat 和 desktop_pet.py、assets 放在同一个文件夹里。
    pause
    exit /b 1
)

rem ---------- 1. 找一个真正能跑的 Python ----------
set "PYCMD="
python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
if not defined PYCMD (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD goto nopython

echo [1/2] 使用解释器: %PYCMD%

rem ---------- 2. 检查依赖 ----------
%PYCMD% -c "import PIL" >nul 2>nul
if not errorlevel 1 goto runpet
echo [2/2] 检测到缺少 Pillow，正在自动安装...
%PYCMD% -m pip install pillow
if errorlevel 1 goto pipfail
echo.

:runpet
echo [2/2] 启动中...（退出方式：右键宠物 -^> 退出；或关掉本窗口）
echo ------------------------------------------------------------
%PYCMD% desktop_pet.py %*
set "RC=%errorlevel%"
echo.
echo ------------------------------------------------------------
echo 桌宠已退出（退出码 %RC%）。
echo.
echo ---- 本次运行日志（完整日志见 logs\desktop_pet.log）----
powershell -NoProfile -Command "$p='%~dp0logs\desktop_pet.log'; if(Test-Path -LiteralPath $p){$l=Get-Content -LiteralPath $p -Encoding UTF8; $m=$l | Select-String -Pattern '\[START\]' | Select-Object -Last 1; if($m){$l[($m.LineNumber-1)..($l.Count-1)]}else{$l | Select-Object -Last 15}}else{'(暂无日志)'}"
echo.
echo 如果桌宠又自己退出了，把上面这几行日志发我即可定位。
pause
exit /b 0

:nopython
echo.
echo [错误] 没有找到可用的 Python。
echo.
echo   请安装 Python 3.10 或更高版本，安装时务必勾选
echo   "Add Python to PATH"（把 Python 加入环境变量）。
echo.
echo   下载地址: https://www.python.org/downloads/
echo.
pause
exit /b 1

:pipfail
echo.
echo [错误] Pillow 自动安装失败，请手动执行下面这行命令后再双击本文件：
echo.
echo       pip install pillow
echo.
pause
exit /b 1
