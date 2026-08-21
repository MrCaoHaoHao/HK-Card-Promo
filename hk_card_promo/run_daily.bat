@echo off
rem 每日定时任务入口：抓取各银行信用卡活动并增量入库
rem 由 Windows 任务计划程序调用；日志写入 logs\daily.log
cd /d "%~dp0"
if not exist logs mkdir logs
echo ===== %date% %time% scheduled run ===== >> logs\daily.log
rem 定时任务环境 PATH 可能不含 python，优先用完整路径，找不到则退回 python
set "PY=C:\Python314\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" main.py >> logs\daily.log 2>&1
exit /b %ERRORLEVEL%
