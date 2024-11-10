rm -rf ~/Desktop/SharedLayer
rm -rf .aws-sam
mkdir ~/Desktop/SharedLayer
mkdir ~/Desktop/SharedLayer/python
cp -r ~/Desktop/other/job-hunt/ ~/Desktop/SharedLayer/python
cp ~/Desktop/other/job-hunt/config.yml ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/
cp ~/Desktop/other/job-hunt/config.yml ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/
cp /Users/bhaskar/Desktop/garbage\ or\ not/job-hunt-data/job-hunt-420615-0ce7f4f42a30.json ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/
cp /Users/bhaskar/Desktop/garbage\ or\ not/job-hunt-data/client_secret_604979190363-fof4i2inncp6nt45ls6knim4kakmj86g.apps.googleusercontent.com.json ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/
cp /Users/bhaskar/Desktop/garbage\ or\ not/job-hunt-data/job-hunt-420615-0ce7f4f42a30.json ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/
cp /Users/bhaskar/Desktop/garbage\ or\ not/job-hunt-data/client_secret_604979190363-fof4i2inncp6nt45ls6knim4kakmj86g.apps.googleusercontent.com.json ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/
sam build
sam deploy
rm ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/config.yml
rm ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/config.yml
rm ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/job-hunt-420615-0ce7f4f42a30.json
rm ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/job-hunt-420615-0ce7f4f42a30.json
rm ~/Desktop/other/job-hunt/scripts/lambdas/trigger_job_scrape/client_secret_604979190363-fof4i2inncp6nt45ls6knim4kakmj86g.apps.googleusercontent.com.json
rm ~/Desktop/other/job-hunt/scripts/lambdas/share_jobs/client_secret_604979190363-fof4i2inncp6nt45ls6knim4kakmj86g.apps.googleusercontent.com.json
rm -rf .aws-sam
rm -rf ~/Desktop/SharedLayer