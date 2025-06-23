call C:\Users\JobHunt\Desktop\venv\Scripts\activate.bat
cd C:\Users\JobHunt\Desktop\job-hunt
git pull origin main
python -m scripts.jobs_steps_identification.run >> C:\Users\JobHunt\Desktop\jobs_steps_identification.log 2>&1
python -m scripts.windows.terminate_windows_machine >> C:\Users\JobHunt\Desktop\terminate_windows_machine.log 2>&1