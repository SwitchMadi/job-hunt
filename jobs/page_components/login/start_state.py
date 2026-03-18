from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
from selenium.webdriver.support.ui import WebDriverWait
import time

from jobs.page_components.login.base_state import LoginState
from jobs.page_components.login.types import (
    LoginStateType,
    START_STATE_PRIORITY,
    STATE_MACHINE_TRANSITIONS,
)
from jobs.page_components import logger
from utilities import constants
from utilities.llm import create_llm_service
from utilities.selenium import (
    get_selenium_driver,
    minify_html_for_gpt_prompt,
    element_exists,
    is_element_visible,
)

_llm_service = create_llm_service(provider="openai")

driver = get_selenium_driver()


class StartState(LoginState):
    """Initial state that identifies the starting point of the login flow"""

    def __init__(self, parent_application_page):
        super().__init__(parent_application_page)
        self.login_section_url = driver.current_url
        self._identified_state = None

    @property
    def current_state_type(self) -> LoginStateType:
        return LoginStateType.START

    def proceed(self, retry=False):
        """Identify the starting point and prepare for transition"""
        # Wait for page to load
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # Identification happens in identify_next_state
        self._update_steps_if_first_time()
        self.is_component_functional = True

    def identify_next_state(self) -> Optional[LoginStateType]:
        """
        Identify which starting state is available based on priority.
        Checks available options and returns highest priority one.
        """
        if self._identified_state:
            return self._identified_state

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Currently I am at login section. Analyse the whole HTML very carefully to identify what login/account "
            f"creation options are available on the page. Determine which of the following is present:\n"
            f"1. sign_in_form - Sign in form with username/password etc. fields is already visible and ready to fill\n"
            f"2. open_sign_in_form_button - A button/link to open/show the sign in form (sign in form not yet visible)\n"
            f"3. account_creation_form - Account creation/signup form with fields is already visible and ready to fill\n"
            f"4. open_account_creation_form_button - A button/link to open/show the account creation form (account creation form not yet visible)\n\n"
            f"CRITICAL: Be aware that popups/modals can be present on the page and can cause duplicate elements or act as blockers. "
            f"For example, a popup might contain a sign-in form while another sign-in form exists behind the popup, "
            f"or a popup might have a button while the same element type exists behind it. If multiple instances of the same option exist "
            f"(one in popup and one not in popup), ALWAYS PRIORITIZE the option that is INSIDE the popup/modal. "
            f"Popups are blocking elements that must be handled first, and elements within popups should be prioritized over elements behind popups.\n\n"
            f"CRITICAL: For buttons (open_sign_in_form_button and open_account_creation_form_button), ONLY identify EMAIL-BASED buttons. "
            f"EXCLUDE all OAuth/third-party login buttons such as: 'Sign in with Google', 'Sign in with LinkedIn', 'Sign in with Facebook', "
            f"'Sign up with Google', 'Sign up with LinkedIn', 'Sign up with Facebook', 'Login with Microsoft', 'Sign in with Apple', "
            f"or any other social media/OAuth provider buttons. Only identify buttons that open forms for email/username and password login/account creation.\n\n"
            f"PRIORITY ORDER for buttons (if multiple buttons exist):\n"
            f"1. Button inside popup (HIGHEST PRIORITY)\n"
            f"2. Button outside header/navigation bar (MEDIUM PRIORITY)\n"
            f"3. Button inside header/navigation bar (LOWEST PRIORITY)\n"
            f"When identifying buttons, ALWAYS select the button with the highest priority according to this order. "
            f"Headers typically contain site navigation, logo, menu items, and are usually at the top of the page. "
            f"Look for elements with semantic tags like <header>, <nav>, or elements with class names containing 'header', 'navbar', 'navigation', 'topbar', 'menu-bar', etc."
        )

        class AvailableOption(Enum):
            true = True
            false = False

        class StartStateOptions(BaseModel):
            sign_in_form: AvailableOption = Field(
                ...,
                description="Sign in form with username/password etc. fields is already visible and ready to fill on the page. "
                "This means the login form fields are directly accessible without clicking any button first. "
                "If the form is inside a popup/modal, prioritize that over a form behind the popup.",
            )
            open_sign_in_form_button: AvailableOption = Field(
                ...,
                description="A button/link to open/show the EMAIL-BASED sign in form exists on the page. "
                "The sign in form itself is not yet visible and requires clicking this button to reveal it. "
                "CRITICAL: This MUST be for email-based login only. EXCLUDE OAuth buttons like 'Sign in with Google', 'Sign in with LinkedIn', "
                "'Sign in with Facebook', 'Login with Microsoft', 'Sign in with Apple', or any social media/OAuth provider buttons. "
                "Only identify buttons that open a form for email/username and password login. "
                "If the button is inside a popup/modal, prioritize that over a button behind the popup.",
            )
            account_creation_form: AvailableOption = Field(
                ...,
                description="Account creation/signup form with fields is already visible and ready to fill on the page. "
                "This means the registration form fields are directly accessible without clicking any button first. "
                "If the form is inside a popup/modal, prioritize that over a form behind the popup.",
            )
            open_account_creation_form_button: AvailableOption = Field(
                ...,
                description="A button/link to open/show the EMAIL-BASED account creation form exists on the page. "
                "The account creation form itself is not yet visible and requires clicking this button to reveal it. "
                "CRITICAL: This MUST be for email-based account creation only. EXCLUDE OAuth buttons like 'Sign up with Google', 'Sign up with LinkedIn', "
                "'Sign up with Facebook', 'Register with Microsoft', 'Sign up with Apple', or any social media/OAuth provider buttons. "
                "Only identify buttons that open a form for email/username and password account creation. "
                "If the button is inside a popup/modal, prioritize that over a button behind the popup.",
            )

        options_found, options = _llm_service.chat(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=StartStateOptions,
            model="complex",
        )

        if not options_found:
            logger.error(
                f"Could not identify start state options for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )
            return None

        # Map GPT response to state types
        available_states = []
        if options.sign_in_form.value:
            available_states.append(LoginStateType.SIGN_IN_FORM)
        if options.open_sign_in_form_button.value:
            available_states.append(LoginStateType.OPEN_SIGN_IN_FORM_BUTTON)
        if options.account_creation_form.value:
            available_states.append(LoginStateType.ACCOUNT_CREATION_FORM)
        if options.open_account_creation_form_button.value:
            available_states.append(LoginStateType.OPEN_ACCOUNT_CREATION_FORM_BUTTON)

        if not available_states:
            logger.error(
                f"No valid start state options found for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )
            return None

        # Apply priority order - return first available state in priority list
        for priority_state in START_STATE_PRIORITY:
            if priority_state in available_states:
                self._identified_state = priority_state
                logger.info(
                    f"Login start state identified: {priority_state.value} for "
                    f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                )
                return priority_state

        # Fallback to first available (shouldn't happen if priority list is complete)
        self._identified_state = available_states[0]
        return available_states[0]

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "login_section_url": self.login_section_url,
            "identified_state": (
                self._identified_state.value if self._identified_state else None
            ),
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(parent_application_page=parent_application_page)
        instance.login_section_url = input_dict.get(
            "login_section_url", driver.current_url
        )
        if input_dict.get("identified_state"):
            instance._identified_state = LoginStateType(input_dict["identified_state"])
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
            next_component.prev = instance

        return instance
