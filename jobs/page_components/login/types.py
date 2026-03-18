from enum import Enum
from typing import List, Dict


class LoginStateType(str, Enum):
    """Enumeration of all possible login states"""

    START = "start"
    SIGN_IN_FORM = "sign_in_form"
    OPEN_SIGN_IN_FORM_BUTTON = "open_sign_in_form_button"
    ACCOUNT_CREATION_FORM = "account_creation_form"
    OPEN_ACCOUNT_CREATION_FORM_BUTTON = "open_account_creation_form_button"
    ACCOUNT_DOESNT_EXIST = "account_doesnt_exist"
    ACCOUNT_ALREADY_EXISTS = "account_already_exists"
    ACCOUNT_VERIFICATION = "account_verification"
    LOGGED_IN = "logged_in"
    CAPTCHA = "captcha"
    ACCOUNT_VERIFICATION_FAILED = "account_verification_failed"
    CONFIRMATION_POPUP = "confirmation_popup"


# State machine transition rules
STATE_MACHINE_TRANSITIONS: Dict[LoginStateType, List[LoginStateType]] = {
    LoginStateType.START: [
        LoginStateType.SIGN_IN_FORM,
        LoginStateType.OPEN_SIGN_IN_FORM_BUTTON,
        LoginStateType.ACCOUNT_CREATION_FORM,
        LoginStateType.OPEN_ACCOUNT_CREATION_FORM_BUTTON,
    ],
    LoginStateType.OPEN_SIGN_IN_FORM_BUTTON: [
        LoginStateType.CONFIRMATION_POPUP,
        LoginStateType.SIGN_IN_FORM,
        LoginStateType.OPEN_SIGN_IN_FORM_BUTTON,  # Options popup (Google, LinkedIn, Email, etc.)
    ],
    LoginStateType.OPEN_ACCOUNT_CREATION_FORM_BUTTON: [
        LoginStateType.CONFIRMATION_POPUP,
        LoginStateType.ACCOUNT_CREATION_FORM,
        LoginStateType.OPEN_ACCOUNT_CREATION_FORM_BUTTON,  # Options popup (Google, LinkedIn, Email, etc.)
    ],
    LoginStateType.SIGN_IN_FORM: [
        LoginStateType.LOGGED_IN,
        LoginStateType.ACCOUNT_DOESNT_EXIST,
        LoginStateType.ACCOUNT_VERIFICATION,
        LoginStateType.CAPTCHA,
    ],
    LoginStateType.ACCOUNT_DOESNT_EXIST: [
        LoginStateType.ACCOUNT_CREATION_FORM,
        LoginStateType.OPEN_ACCOUNT_CREATION_FORM_BUTTON,
    ],
    LoginStateType.ACCOUNT_CREATION_FORM: [
        LoginStateType.LOGGED_IN,
        LoginStateType.ACCOUNT_VERIFICATION,
        LoginStateType.ACCOUNT_ALREADY_EXISTS,
        LoginStateType.CAPTCHA,
    ],
    LoginStateType.ACCOUNT_ALREADY_EXISTS: [
        LoginStateType.SIGN_IN_FORM,
        LoginStateType.OPEN_SIGN_IN_FORM_BUTTON,
    ],
    LoginStateType.ACCOUNT_VERIFICATION: [
        LoginStateType.LOGGED_IN,
        LoginStateType.ACCOUNT_VERIFICATION_FAILED,
    ],
    LoginStateType.LOGGED_IN: [],  # Terminal state
    LoginStateType.CAPTCHA: [],  # Raises exception
    LoginStateType.ACCOUNT_VERIFICATION_FAILED: [],  # Raises exception
    LoginStateType.CONFIRMATION_POPUP: [
        LoginStateType.SIGN_IN_FORM,
        LoginStateType.ACCOUNT_CREATION_FORM,
    ],
}

# Priority order for Start state (highest to lowest)
START_STATE_PRIORITY: List[LoginStateType] = [
    LoginStateType.SIGN_IN_FORM,
    LoginStateType.OPEN_SIGN_IN_FORM_BUTTON,
    LoginStateType.ACCOUNT_CREATION_FORM,
    LoginStateType.OPEN_ACCOUNT_CREATION_FORM_BUTTON,
]
