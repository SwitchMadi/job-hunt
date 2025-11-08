from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
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


class AccountAlreadyExistsState(LoginState):
    """State when account creation fails because account already exists"""

    def __init__(self, parent_application_page):
        super().__init__(parent_application_page)
        self.error_message = None

    @property
    def current_state_type(self) -> LoginStateType:
        return LoginStateType.ACCOUNT_ALREADY_EXISTS

    def proceed(self, retry=False):
        """Account already exists - log and prepare for sign-in"""
        logger.info(
            f"Account creation failed: Account already exists for job {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}. Proceeding to sign-in."
        )
        self._update_steps_if_first_time()
        self.is_component_functional = True

    def identify_next_state(self) -> Optional[LoginStateType]:
        """Identify whether sign-in form is open or needs button click"""

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"I just tried to create an account and got an error that the account already exists. Now I need to sign in. "
            f"Follow this structured analysis:\n\n"
            f"STEP 1: First determine if there is a popup/modal visible on the page. Popups are blocking elements that must be handled first.\n"
            f"STEP 2: If a popup exists, check if it contains a sign-in form or button to open sign-in form.\n"
            f"STEP 3: Based on popup analysis, determine what options are available (sign_in_form or open_sign_in_form_button).\n\n"
            f"CRITICAL: If a popup exists and contains the sign-in form or button, ALWAYS prioritize that over elements behind the popup. "
            f"Popups are blocking elements, so elements inside popups should be prioritized."
        )

        class PopupExists(Enum):
            true = True
            false = False

        class AvailableOption(Enum):
            true = True
            false = False

        class SignInOptions(BaseModel):
            # Step 1: Popup detection
            popup_exists: PopupExists = Field(
                ...,
                description="Is there a popup/modal visible on the page? Popups are blocking elements that must be handled first. "
                "Look for modal dialogs, overlay divs, elements with role='dialog', or high z-index elements that appear above the main content.",
            )

            # Step 2: Check popup for sign-in elements
            popup_has_sign_in_form: AvailableOption = Field(
                ...,
                description="If popup_exists is true, does the popup contain a sign-in form with fields (username, password, etc.)? "
                "This means the login form fields are directly accessible within the popup. Return false if popup doesn't exist.",
            )
            popup_has_sign_in_button: AvailableOption = Field(
                ...,
                description="If popup_exists is true, does the popup contain a button/link to open the sign-in form? "
                "Return false if popup doesn't exist.",
            )

            # Step 3: Final decision - prioritize popup elements
            sign_in_form: AvailableOption = Field(
                ...,
                description="Sign in form with username/password fields is available and ready to fill. "
                "If popup exists and has the form (popup_has_sign_in_form=true), this should be true. "
                "If no popup or popup doesn't have form, check if form exists outside popup. "
                "ALWAYS prioritize form inside popup if popup exists and has it.",
            )
            open_sign_in_form_button: AvailableOption = Field(
                ...,
                description="A button/link to open the sign in form is available. "
                "If popup exists and has the button (popup_has_sign_in_button=true), this should be true. "
                "If no popup or popup doesn't have button, check if button exists outside popup. "
                "ALWAYS prioritize button inside popup if popup exists and has it.",
            )

        options_found, options = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=SignInOptions,
            model="complex",
        )

        if options_found:
            # Prefer form if available, else button
            if options.sign_in_form.value:
                return LoginStateType.SIGN_IN_FORM
            elif options.open_sign_in_form_button.value:
                return LoginStateType.OPEN_SIGN_IN_FORM_BUTTON

        # Default to sign-in form if unclear
        return LoginStateType.SIGN_IN_FORM

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
