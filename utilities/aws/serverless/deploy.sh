rm -rf .aws-sam

rm -rf ~/Desktop/SharedLayer
mkdir ~/Desktop/SharedLayer
mkdir ~/Desktop/SharedLayer/python
cp -r ~/Desktop/switchmadi/codebase/job-hunt/ ~/Desktop/SharedLayer/python

cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/share_jobs/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/trigger_job_scrape/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/trigger_job_steps_identification/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/authorization/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/save_user_tokens/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/preferred_jobs_count/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/save_job_preferences/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/get_job_preferences/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/upload_resume/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/parse_resume/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/parse_resume_trigger/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/websocket_connect/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/websocket_disconnect/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/save_modified_resume/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/trigger_free_job_application/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/get_subscription_status/
cp ~/Desktop/switchmadi/codebase/job-hunt/config.yml ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/paypal_webhook/

cp /Users/bhaskar/Desktop/temporary/job-hunt-data/job-hunt-420615-0ce7f4f42a30.json ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/share_jobs/
cp /Users/bhaskar/Desktop/temporary/job-hunt-data/client_secret_604979190363-ei70huqc4iirglc66t3vhc94fl96f07l.apps.googleusercontent.com.json ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/share_jobs/

cp /Users/bhaskar/Desktop/temporary/job-hunt-data/job-hunt-420615-0ce7f4f42a30.json ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/trigger_job_scrape/
cp /Users/bhaskar/Desktop/temporary/job-hunt-data/client_secret_604979190363-ei70huqc4iirglc66t3vhc94fl96f07l.apps.googleusercontent.com.json ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/trigger_job_scrape/

cd /Users/bhaskar/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas
/Users/bhaskar/Desktop/temporary/job-hunt-venv/bin/python generate_lambda_requirement_files.py
cd /Users/bhaskar/Desktop/switchmadi/codebase/job-hunt/utilities/aws/serverless

sam build
sam deploy

rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/trigger_job_scrape/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/trigger_job_steps_identification/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/share_jobs/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/authorization/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/save_user_tokens/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/preferred_jobs_count/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/save_job_preferences/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/get_job_preferences/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/upload_resume/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/parse_resume/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/parse_resume_trigger/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/websocket_connect/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/websocket_disconnect/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/save_modified_resume/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/trigger_free_job_application/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/get_subscription_status/config.yml
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/paypal_webhook/config.yml

rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/trigger_job_scrape/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/trigger_job_steps_identification/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/share_jobs/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/authorization/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/save_user_tokens/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/preferred_jobs_count/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/save_job_preferences/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/get_job_preferences/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/upload_resume/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/parse_resume/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/parse_resume_trigger/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/websocket_connect/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/websocket_disconnect/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/save_modified_resume/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/trigger_free_job_application/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/get_subscription_status/requirements.txt
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/paypal_webhook/requirements.txt

rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/trigger_job_scrape/job-hunt-420615-0ce7f4f42a30.json
rm ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/share_jobs/job-hunt-420615-0ce7f4f42a30.json

rm -f ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/trigger_job_scrape/client_secret_604979190363-ei70huqc4iirglc66t3vhc94fl96f07l.apps.googleusercontent.com.json
rm -f ~/Desktop/switchmadi/codebase/job-hunt/scripts/lambdas/share_jobs/client_secret_604979190363-ei70huqc4iirglc66t3vhc94fl96f07l.apps.googleusercontent.com.json

rm -rf .aws-sam
rm -rf ~/Desktop/SharedLayer