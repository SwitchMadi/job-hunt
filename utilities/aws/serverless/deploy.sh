rm -rf ~/Desktop/SharedLayer
rm -rf .aws-sam
mkdir ~/Desktop/SharedLayer
mkdir ~/Desktop/SharedLayer/python
cp -r ~/Desktop/other/job-hunt/ ~/Desktop/SharedLayer/python
cp ~/Desktop/other/job-hunt/config.yml ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/
cp ~/Desktop/other/job-hunt/config.yml ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/
sam build
sam deploy
rm ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/config.yml
rm ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/config.yml
rm -rf .aws-sam
rm -rf ~/Desktop/SharedLayer