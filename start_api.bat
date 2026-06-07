@echo off
chcp 65001 >nul
echo ==========================================
echo   Opencode API Gateway 启动器
echo ==========================================
echo.
echo 正在启动服务...
echo 访问地址: http://localhost:8000
echo API文档:  http://localhost:8000/docs
echo.
echo 按 Ctrl+C 停止服务
echo ==========================================
echo.

python "%~dp0opencode_api.py"

pause
