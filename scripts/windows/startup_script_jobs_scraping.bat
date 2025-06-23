call C:\Users\JobHunt\Desktop\venv\Scripts\activate.bat
cd C:\Users\JobHunt\Desktop\job-hunt
python scrape_jobs.py >> C:\Users\JobHunt\Desktop\scrape_jobs.log 2>&1
python -m scripts.windows.terminate_windows_machine >> C:\Users\JobHunt\Desktop\terminate_windows_machine.log 2>&1