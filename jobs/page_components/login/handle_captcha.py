"""Captcha handling entry point for login flows (delegates to ``ApplicationPage``)."""


def handle_captcha(parent_application_page) -> bool:
    """
    Run the same captcha / Slack / DCV flow as the job application page.

    Uses a lazy import so the login package does not import ``jobs`` at module load time.
    """
    from jobs import ApplicationPage

    if not isinstance(parent_application_page, ApplicationPage):
        raise TypeError(
            "parent_application_page must be an ApplicationPage instance "
            f"(got {type(parent_application_page).__name__})"
        )
    return parent_application_page.handle_captcha()
