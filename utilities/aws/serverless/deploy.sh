rm -rf .aws-sam

rm -rf ~/Desktop/SharedLayer
mkdir ~/Desktop/SharedLayer
mkdir ~/Desktop/SharedLayer/python
cp -r ~/Desktop/other/job-hunt/ ~/Desktop/SharedLayer/python

cp ~/Desktop/other/job-hunt/config.yml ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/
cp ~/Desktop/other/job-hunt/config.yml ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/
cp ~/Desktop/other/job-hunt/config.yml ~/Desktop/other/job-hunt/scripts/lambdas/authorization/
cp ~/Desktop/other/job-hunt/config.yml ~/Desktop/other/job-hunt/scripts/lambdas/save_user_tokens/
cp ~/Desktop/other/job-hunt/config.yml ~/Desktop/other/job-hunt/scripts/lambdas/preferred_jobs_count/
cp ~/Desktop/other/job-hunt/config.yml ~/Desktop/other/job-hunt/scripts/lambdas/save_job_preferences/
cp ~/Desktop/other/job-hunt/config.yml ~/Desktop/other/job-hunt/scripts/lambdas/get_job_preferences/
cp ~/Desktop/other/job-hunt/config.yml ~/Desktop/other/job-hunt/scripts/lambdas/upload_resume/

cp /Users/bhaskar/Desktop/temporary/job-hunt-data/job-hunt-420615-0ce7f4f42a30.json ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/
cp /Users/bhaskar/Desktop/temporary/job-hunt-data/client_secret_604979190363-ei70huqc4iirglc66t3vhc94fl96f07l.apps.googleusercontent.com.json ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/

cp /Users/bhaskar/Desktop/temporary/job-hunt-data/job-hunt-420615-0ce7f4f42a30.json ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/
cp /Users/bhaskar/Desktop/temporary/job-hunt-data/client_secret_604979190363-ei70huqc4iirglc66t3vhc94fl96f07l.apps.googleusercontent.com.json ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/

cd /Users/bhaskar/Desktop/other/job-hunt/scripts/lambdas
/Users/bhaskar/Desktop/temporary/job-hunt-venv/bin/python generate_lambda_requirement_files.py
cd /Users/bhaskar/Desktop/other/job-hunt/utilities/aws/serverless

sam build
sam deploy

rm ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/config.yml
rm ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/config.yml
rm ~/Desktop/other/job-hunt/scripts/lambdas/authorization/config.yml
rm ~/Desktop/other/job-hunt/scripts/lambdas/save_user_tokens/config.yml
rm ~/Desktop/other/job-hunt/scripts/lambdas/preferred_jobs_count/config.yml
rm ~/Desktop/other/job-hunt/scripts/lambdas/save_job_preferences/config.yml
rm ~/Desktop/other/job-hunt/scripts/lambdas/get_job_preferences/config.yml
rm ~/Desktop/other/job-hunt/scripts/lambdas/upload_resume/config.yml

rm ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/requirements.txt
rm ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/requirements.txt
rm ~/Desktop/other/job-hunt/scripts/lambdas/authorization/requirements.txt
rm ~/Desktop/other/job-hunt/scripts/lambdas/save_user_tokens/requirements.txt
rm ~/Desktop/other/job-hunt/scripts/lambdas/preferred_jobs_count/requirements.txt
rm ~/Desktop/other/job-hunt/scripts/lambdas/save_job_preferences/requirements.txt
rm ~/Desktop/other/job-hunt/scripts/lambdas/get_job_preferences/requirements.txt
rm ~/Desktop/other/job-hunt/scripts/lambdas/upload_resume/requirements.txt

rm ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/job-hunt-420615-0ce7f4f42a30.json
rm ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/job-hunt-420615-0ce7f4f42a30.json

rm ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/client_secret_604979190363-ei70huqc4iirglc66t3vhc94fl96f07l.apps.googleusercontent.com.json
rm ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/client_secret_604979190363-ei70huqc4iirglc66t3vhc94fl96f07l.apps.googleusercontent.com.json

rm -rf .aws-sam
rm -rf ~/Desktop/SharedLayer