@echo off
cd /d C:\Users\akshi\OneDrive\Desktop\web
C:\Users\akshi\OneDrive\Desktop\web\backend\.venv\Scripts\python.exe backend\manage.py run_maintenance --inactive-days 7 --empty-room-minutes 10 --max-storage-gb 20 --target-storage-gb 15 >> logs\maintenance.log 2>&1
