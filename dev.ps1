# Chạy bản phát triển (tự nạp lại khi sửa code): .\dev.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:DEBUG = "1"
.\.venv\Scripts\python.exe manage.py migrate --noinput
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8100
