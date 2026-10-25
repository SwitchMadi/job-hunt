# job-hunt

job-hunt is a Python-based automation project for discovering relevant jobs, extracting structured job metadata, and applying to selected opportunities through browser automation.

This repository combines:
- LinkedIn job scraping
- Job metadata extraction using LLMs
- Browser-based application automation
- User subscription / plan checks
- AWS integrations for storage, messaging, and serverless orchestration
- Job filtering and application status tracking

The codebase is designed for local execution with Selenium, PostgreSQL, and AWS-backed services, and it is geared toward automating the job application workflow for a user or team.

## Overview

The project is organized around a few core responsibilities:

1. Collect jobs from configured LinkedIn searches
2. Deduplicate and store job records in a database
3. Extract structured information from job descriptions
4. Identify which jobs are suitable for automated submission
5. Fill out application forms through browser automation
6. Track subscriptions, user preferences, and application progress

This is not a simple web app or library. It is a workflow automation system that interacts with browsers, external APIs, SQL data, and cloud services.

## Features

- LinkedIn job scraping from multiple search URLs
- Duplicate filtering based on job hash or LinkedIn ID
- Structured extraction of:
  - company
  - job title
  - location
  - employment type
  - technical and non-technical skills
  - experience requirements
  - visa sponsorship
  - salary
  - language and domain classification
- Selenium-based automation for job applications
- Reusable page component abstractions for filling forms
- User-level job filters and preference matching
- Subscription checks and plan-based application limits
- AWS S3 / DynamoDB / Lambda / WebSocket / CloudWatch integration
- Slack and DCV-based human verification workflow support
- PayPal payment integration for plan billing

## Repository Structure

```text
.
├── README.md
├── config.yml
├── scrape_jobs.py
├── requirements-mac.txt
├── requirements-windows.txt
├── jobs/
│   ├── __init__.py
│   ├── page_components/
│   │   ├── login/
│   │   ├── application_data_source.py
│   │   ├── button.py
│   │   ├── captcha.py
│   │   ├── check_box.py
│   │   ├── date_field.py
│   │   ├── drop_down.py
│   │   ├── education_section.py
│   │   ├── text_input.py
│   │   ├── upload.py
│   │   ├── work_experience_section.py
│   │   └── ...
│   └── sourcing/
│       ├── __init__.py
│       └── linkedin.py
├── user/
│   ├── __init__.py
│   └── resume.py
├── plan/
│   └── __init__.py
├── payment/
│   ├── __init__.py
│   └── paypal_gateway.py
├── scripts/
│   ├── job_application/
│   │   ├── apply_job.py
│   │   └── run.py
│   ├── jobs_sharing/
│   ├── jobs_steps_identification/
│   ├── lambdas/
│   └── ...
├── utilities/
│   ├── __init__.py
│   ├── aws/
│   ├── logging.py
│   ├── selenium.py
│   ├── sql.py
│   └── ...
├── migrations/
│   ├── 001_captcha_tasks.sql
│   └── 002_migrate_slack_interactive_to_captcha_tasks.sql
└── ...
```

## Tech Stack

- Python
- Selenium / undetected-chromedriver
- BeautifulSoup / bs4
- SQLAlchemy + PostgreSQL
- OpenAI / LLM-based extraction
- AWS S3, DynamoDB, Lambda, CloudWatch, WebSocket
- Slack integration
- PayPal payments
- PyAutoGUI, YAML, dotenv

## Installation

Clone the repository:

```bash
git clone https://github.com/SwitchMadi/job-hunt.git
cd job-hunt
```

Install dependencies:

For macOS:

```bash
pip install -r requirements-mac.txt
```

For Windows:

```bash
pip install -r requirements-windows.txt
```

## Configuration

The project expects a `config.yml` file with the browser, scraping, AWS, Slack, and subscription settings.

A representative example from the repo looks like this:

```yaml
chrome_profile_path: C:\Users\JobHunt\Desktop\job-hunt\chrome_profiles
chromedriver: C:\Users\JobHunt\Desktop\job-hunt\chromedriver.exe
selenium_driver_type: undetected
selenium_headless: false
s3_bucket: job-hunt-storage
user_email: your@email.com
websocket:
  endpoint_url: "https://ws.api.switchmadi.com"
subscription:
  trial_days: 30
llm_providers:
  default: openai
  openai:
    models:
      default: gpt-4o-mini
```

The repository also reads a startup config file pointed to by `startup_input` in `config.yml`, which typically contains the active user email.

Example:

```yaml
user_email: your@email.com
```

You will also need the required environment variables for cloud and LLM access, such as:
- `OPENAI_API_KEY` or other provider keys
- AWS credentials
- `ENCRYPTION_KEY` if using encryption helpers
- Slack and PayPal settings where applicable

## Common Workflows

### 1) Scrape jobs

```bash
python scrape_jobs.py
```

This script:
- acquires a lock
- loads the config
- fetches the Chrome profile from S3 if present
- visits configured LinkedIn job search URLs
- collects and deduplicates jobs
- extracts structured metadata using the LLM layer
- writes the results into the database

### 2) Identify application steps

```bash
python -m scripts.jobs_steps_identification.run
```

This identifies jobs that are active, not yet processed, and eligible for automated application steps.

### 3) Apply to jobs

```bash
python -m scripts.job_application.run
```

This:
- checks whether the user is allowed to apply
- validates plan/subscription status
- fetches target jobs
- launches application subprocesses
- handles timeouts and screenshots
- counts active applications and reports completion

## Database and Persistence

The project relies on SQL storage for jobs and user state. The scraper inserts into schema/table patterns such as:

- `jobs.jobs`
- `jobs.jobs_staging`
- `users.job_applications`
- subscription and user-related tables

The SQL migrations under `migrations/` indicate schema evolution for features like captcha task handling and Slack interaction migration.

## AWS and Cloud Features

The repository includes multiple AWS-related components:

- S3 storage for Chrome profiles, screenshots, and uploaded files
- DynamoDB tables for locks, session data, and WebSocket state
- Lambda handlers for serverless operations like:
  - job preferences
  - resume upload
  - job scrape triggers
  - application responses
  - auth
  - PayPal hooks
  - user token persistence

This means the repo is built not only for local automation but also for server-backed orchestration.

## Browser Automation Notes

This project depends heavily on Selenium and browser state. In practice, it expects:
- Chrome/Chromium available on the host
- proper `chromedriver` path
- a configured Chrome profile
- a working login state for sites like LinkedIn when needed

The code includes logic to handle:
- slow loads
- page changes
- timeouts
- multiple tabs
- modal dialogs
- screenshot capture on failure

## Security and Reliability

The code includes:
- lock management using DynamoDB for concurrency control
- screenshots for debugging failed automations
- retry utilities and timeout wrappers
- encryption helpers for sensitive data
- logging utilities for traceability

Use this project carefully and make sure you comply with the terms of service of the sites you automate.

## Important Notes

This repository is highly specialized and opinionated toward:
- automated job search
- browser automation
- LLM-assisted job metadata extraction
- subscription-based access control

It is not a general-purpose starter project or a simple API wrapper. It expects a working environment with browser automation, cloud credentials, and database access.

## License

This repository does not currently include an explicit license file in the checked-in branch reviewed here. If you are using it publicly or internally, verify the licensing requirements before redistribution or commercial use.

## Disclaimer

This project automates interactions with third-party websites and services. Use it responsibly and in accordance with applicable platform policies, local laws, and the terms of service of the systems it interacts with.
