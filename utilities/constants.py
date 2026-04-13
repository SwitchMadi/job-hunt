gpt = {
    "system_prompts": {
        "application_step_identification": "You're a tool which helps in job application automation. You are good at "
        "identifying html components for actions in job application. If you are "
        "asked to extract some XPath or XPath pattern, then to construct the XPath rely more on elements' attributes & their values "
        "rather than HTML hierarchy & element index. Using HTML hierarchy & indexes should be last resort. "
        "Do not rely on alphanumeric strings (like 'id-123abc', 'element-456xyz', or any attribute values "
        "containing random alphanumeric characters) when extracting XPath because these strings may change when the "
        "page reloads, making the XPath unusable. Using alphanumeric strings should be the last resort. Also don't "
        "respond with long XPaths, just try to use domain specific / functionality attributes which will not match with just any "
        "other element on the page. Do not try to guess the Xpath, consider the HTML given as input as the source of truth.",
        "resume_parser": "You're a tool which helps in extracting information out of resume summary.",
    }
}
non_automatable_job_boards = [
    "instahyre.com",
    "upwork.com",
    "freelancer.com",
    "fiverr.com",
    "toptal.com",
    "guru.com",
    "peopleperhour.com",
]

# Slack Block Kit: captcha human tasks (job runner + ProcessSlackCaptchaActions Lambda)
SLACK_CAPTCHA_ACTION_OPEN_DCV = "open_dcv_session"
SLACK_CAPTCHA_ACTION_MARK_SOLVED = "captcha_mark_solved"
SLACK_CAPTCHA_ACTION_MARK_FAILED = "captcha_mark_failed"
SLACK_CAPTCHA_VIEW_SOLVED_CONFIRM = "captcha_task_solved_confirm"
SLACK_CAPTCHA_VIEW_FAILED_CONFIRM = "captcha_task_failed_confirm"
