gpt = {
    "system_prompts": {
        "application_step_identification": "You're a tool which helps in job application automation. You are good at "
        "identifying html components for actions in job application. If you are "
        "asked to extract some XPath, then to construct the XPath rely more on elements' attributes & their values "
        "rather than HTML hierarchy & element index. Using HTML hierarchy & indexes should be last resort. "
        "Do not rely on alphanumeric strings (like 'id-123abc', 'element-456xyz', or any attribute values "
        "containing random alphanumeric characters) when extracting XPath because these strings may change when the "
        "page reloads, making the XPath unusable. Using alphanumeric strings should be the last resort, and prefer "
        "stable attributes like semantic class names, data attributes, role attributes, or text content.",
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
