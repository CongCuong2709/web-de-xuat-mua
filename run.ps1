# Chạy bản dùng thật trên máy công ty: .\run.ps1
# Cloudflare Tunnel trỏ vào http://localhost:8100
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"
& $py manage.py migrate --noinput
& $py manage.py collectstatic --noinput -v 0
& $py -m waitress --listen=127.0.0.1:8100 --threads=8 config.wsgi:application
