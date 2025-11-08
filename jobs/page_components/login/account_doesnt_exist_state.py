from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from selenium.webdriver.support.ui import WebDriverWait
import time

from jobs.page_components.login.base_state import LoginState
from jobs.page_components.login.types import LoginStateType
from jobs.page_components import logger
from utilities import constants
from utilities.gpt import get_gpt_response
from utilities.selenium import (
    get_selenium_driver,
    minify_html_for_gpt_prompt,
)

driver = get_selenium_driver()


class AccountDoesntExistState(LoginState):
    """State when login fails because account doesn't exist"""

    def __init__(self, parent_application_page):
        super().__init__(parent_application_page)
        self.error_message = None

    @property
    def current_state_type(self) -> LoginStateType:
        return LoginStateType.ACCOUNT_DOESNT_EXIST

    def proceed(self, retry=False):
        """Account doesn't exist - log and prepare for account creation"""
        logger.info(
            f"Login failed: Account doesn't exist for job {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}. Proceeding to account creation."
        )
        self._update_steps_if_first_time()
        self.is_component_functional = True

    def identify_next_state(self) -> Optional[LoginStateType]:
        """Identify whether account creation form is open or needs button click"""

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"I just tried to login and got an error that the account doesn't exist. Now I need to create an account. "
            f"Follow this structured analysis:\n\n"
            f"STEP 1: First determine if there is a popup/modal visible on the page. Popups are blocking elements that must be handled first.\n"
            f"STEP 2: If a popup exists, check if it contains an account creation form or button to open account creation form.\n"
            f"STEP 3: Based on popup analysis, determine what options are available (account_creation_form or open_account_creation_form_button).\n\n"
            f"CRITICAL: If a popup exists and contains the account creation form or button, ALWAYS prioritize that over elements behind the popup. "
            f"Popups are blocking elements, so elements inside popups should be prioritized."
        )

        class PopupExists(Enum):
            true = True
            false = False

        class AvailableOption(Enum):
            true = True
            false = False

        class AccountCreationOptions(BaseModel):
            # Step 1: Popup detection
            popup_exists: PopupExists = Field(
                ...,
                description="Is there a popup/modal visible on the page? Popups are blocking elements that must be handled first. "
                "Look for modal dialogs, overlay divs, elements with role='dialog', or high z-index elements that appear above the main content.",
            )

            # Step 2: Check popup for account creation elements
            popup_has_account_creation_form: AvailableOption = Field(
                ...,
                description="If popup_exists is true, does the popup contain an account creation/signup/registration form with fields (username, password, confirm password etc.)? "
                "CRITICAL: Do NOT confuse with sign-in/login form. Account creation forms have buttons like 'Sign Up', 'Create Account', 'Register' etc. "
                "IMPORTANT: Check form-button association. If you see form fields followed by a 'Sign In' button, that is a sign-in form. "
                "If a 'Create Account' button appears AFTER a sign-in form, that button is NOT associated with the visible form fields. "
                "The account creation form must be VISIBLE with its fields directly accessible. "
                "If you only see a 'Create Account' button/link but no account creation form fields are visible, return false (button is not associated with visible account creation fields). "
                "Return false if popup doesn't exist.",
            )
            popup_has_account_creation_button: AvailableOption = Field(
                ...,
                description="If popup_exists is true, does the popup contain a button/link to open the account creation form? "
                "Return false if popup doesn't exist.",
            )

            # Step 3: Final decision - prioritize popup elements
            account_creation_form: AvailableOption = Field(
                ...,
                description="Account creation/signup/registration form with fields (username, email, password, confirm password etc.) is available and ready to fill. "
                "CRITICAL: Do NOT confuse with sign-in/login form. Account creation forms have buttons like 'Sign Up', 'Create Account', 'Register' etc. "
                "IMPORTANT: Check form-button association. If you see form fields followed by a 'Sign In' button, that is a sign-in form. "
                "If a 'Create Account' button appears AFTER a sign-in form, that button is NOT associated with the visible form fields. "
                "The account creation form must be VISIBLE with its fields directly accessible. "
                "If you only see a 'Create Account' button/link but no account creation form fields are visible, return false (button is not associated with visible account creation fields). "
                "If popup_has_account_creation_form=true, return true. Otherwise check outside popup. Prioritize popup form if exists.",
            )
            open_account_creation_form_button: AvailableOption = Field(
                ...,
                description="A button/link to open the account creation form is available. "
                "If popup exists and has the button (popup_has_account_creation_button=true), this should be true. "
                "If no popup or popup doesn't have button, check if button exists outside popup. "
                "ALWAYS prioritize button inside popup if popup exists and has it.",
            )

        options_found, options = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=AccountCreationOptions,
            model="complex",
        )

        if options_found:
            # Prefer form if available (especially if in popup), else button (especially if in popup)
            if options.account_creation_form.value:
                return LoginStateType.ACCOUNT_CREATION_FORM
            elif options.open_account_creation_form_button.value:
                return LoginStateType.OPEN_ACCOUNT_CREATION_FORM_BUTTON

        # Default to account creation form if unclear
        return LoginStateType.ACCOUNT_CREATION_FORM

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "error_message": self.error_message,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(parent_application_page=parent_application_page)
        instance.error_message = input_dict.get("error_message")
        instance.is_component_functional = True

        if input_dict.get("next"):
            from jobs.page_components import get_page_component_class_name

            next_class = get_page_component_class_name(
                class_name=input_dict["next"]["class"]
            )
            next_component = next_class.from_dict(
                input_dict["next"], parent_application_page
            )
            instance.next = next_component
            if next_component:
                next_component.prev = instance

        return instance
