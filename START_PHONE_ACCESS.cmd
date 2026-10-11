@echo off
cd /d "%~dp0"
echo Use your laptop Wi-Fi IPv4 address on the phone: http://ADDRESS:3010
echo Demo only. Use a trusted private network.
py -3 server.py --host 0.0.0.0
pause
