from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from selenium.webdriver.support.ui import WebDriverWait
import time

from jobs.page_components.login.base_state import LoginState
from jobs.page_components.login.types import LoginStateType
from jobs.page_components.popup import Popup
from jobs.page_components import logger
from utilities import constants
from utilities.llm import create_llm_service
from utilities.selenium import (
    get_selenium_driver,
    minify_html_for_gpt_prompt,
)

_llm_service = create_llm_service(provider="openai")

driver = get_selenium_driver()


class ConfirmationPopupState(LoginState):
    """State for handling confirmation popups that appear after clicking buttons"""

    def __init__(self, parent_application_page):
        super().__init__(parent_application_page)
        self.popup_component = None
        self._identified = False

    @property
    def current_state_type(self) -> LoginStateType:
        return LoginStateType.CONFIRMATION_POPUP

    def proceed(self, retry=False):
        """Handle the popup by closing it"""
        if not self._identified:
            self.popup_component = Popup(
                parent_application_page=self.parent_application_page,
                previous_step=None,
            )
            self.popup_component.proceed()
            self._identified = True

        if self.popup_component and self.popup_component.is_component_functional:
            self._update_steps_if_first_time()
            self.is_component_functional = True

            # Wait for popup to close and page to update
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

    def identify_next_state(self) -> Optional[LoginStateType]:
        """After closing popup, identify which form is now visible"""

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"I just closed a popup/modal. Now check which form is visible:\n"
            f"1. sign_in_form - Sign in form with username/password fields is visible\n"
            f"2. account_creation_form - Account creation/signup form with fields is visible"
        )

        class VisibleForm(Enum):
            sign_in_form = "sign_in_form"
            account_creation_form = "account_creation_form"

        class FormAfterPopup(BaseModel):
            visible_form: VisibleForm = Field(
                ...,
                description="Which form is now visible after closing the popup/modal? Determine if the sign-in form with "
                "username/password fields is visible (sign_in_form) or if the account creation/signup form with fields is visible (account_creation_form).",
            )

        form_found, form_info = _llm_service.chat(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=FormAfterPopup,
        )

        if form_found:
            if form_info.visible_form == VisibleForm.sign_in_form:
                return LoginStateType.SIGN_IN_FORM
            else:
                return LoginStateType.ACCOUNT_CREATION_FORM

        # Default to sign-in form if unclear
        return LoginStateType.SIGN_IN_FORM

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "popup_component": (
                self.popup_component.to_dict() if self.popup_component else None
            ),
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(parent_application_page=parent_application_page)

        if input_dict.get("popup_component"):
            from jobs.page_components import get_page_component_class_name

            popup_class = get_page_component_class_name(
                class_name=input_dict["popup_component"]["class"]
            )
            instance.popup_component = popup_class.from_dict(
                input_dict["popup_component"],
                parent_application_page,
            )

        instance._identified = True
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
