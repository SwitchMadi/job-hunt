from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from selenium.webdriver.support.ui import WebDriverWait
import time

from jobs.page_components.login.base_state import LoginState
from jobs.page_components.login.types import LoginStateType
from jobs.page_components.button import Button
from jobs.page_components import logger
from utilities import constants
from utilities.llm import create_llm_service
from utilities.selenium import (
    get_selenium_driver,
    minify_html_for_gpt_prompt,
    is_element_visible,
)

_llm_service = create_llm_service(provider="openai")

driver = get_selenium_driver()


class OpenAccountCreationFormButtonState(LoginState):
    """State for clicking button to open account creation form"""

    def __init__(self, parent_application_page):
        super().__init__(parent_application_page)
        self.button_x_path = None
        self.button_component = None
        self._identified = False

    @property
    def current_state_type(self) -> LoginStateType:
        return LoginStateType.OPEN_ACCOUNT_CREATION_FORM_BUTTON

    def proceed(self, retry=False):
        """Click button to open account creation form"""
        if not self._identified:
            self._identify_button()

        if self.button_component:
            self.button_component.proceed()
            if self.button_component.is_component_functional:
                self._update_steps_if_first_time()
                self.is_component_functional = True

                # Wait for form to appear
                WebDriverWait(driver, 10).until(
                    lambda d: d.execute_script("return document.readyState")
                    == "complete"
                )

    def _identify_button(self):
        """Identify the button to open account creation form"""
        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Find EMAIL-BASED account creation button (exclude OAuth like Google/LinkedIn/Facebook). "
            f"Button text: 'Sign Up', 'Create Account', 'Register', 'Sign up with Email', etc.\n\n"
            f"SELECTION ORDER (check in this sequence, stop at first match):\n"
            f"1. Button in popup → select it\n"
            f"2. Button OUTSIDE header → select it\n"
            f"3. Button in header → select it (only if no button found in steps 1-2)\n\n"
            f"Headers are site navigation areas typically at the top containing logo, menu items, navigation links. "
            f"Identify headers by semantic indicators: HTML tags (<header>, <nav>), class/ID names, data attributes (data-automation-id, data-testid), "
            f"role attributes (role='navigation', role='banner'), ARIA labels, or structural patterns (top of page, contains navigation elements)."
        )

        class PopupExists(Enum):
            true = True
            false = False

        class AccountCreationButton(BaseModel):
            # Step 1: Popup detection
            popup_exists: PopupExists = Field(
                ...,
                description="Is there a popup/modal visible on the page? Popups are blocking elements that must be handled first. "
                "Look for modal dialogs, overlay divs, elements with role='dialog', or high z-index elements that appear above the main content.",
            )
            popup_container_x_path: Optional[str] = Field(
                ...,
                description="If popup_exists is true, provide the XPath of the popup/modal container element. "
                "This should be a UNIQUE XPath that identifies the popup container (e.g., modal div, dialog element, overlay wrapper). "
                "CRITICAL: Avoid using alphanumeric attribute values (like auto-generated IDs, hashes, random strings) if uniqueness can be achieved without them. "
                "Prefer semantic attributes, stable class names, data attributes, or structural relationships. "
                "Only use alphanumeric values if absolutely necessary for uniqueness. "
                "Return empty string if popup_exists is false. This XPath will be used to construct relative button XPath if button is in popup.",
            )

            # Step 2: Button location check
            button_in_popup: PopupExists = Field(
                ...,
                description="Is the SELECTED button inside popup? Return true only if popup exists AND selected button is inside it. Otherwise false.",
            )
            button_exists_outside_header: PopupExists = Field(
                ...,
                description="If button_in_popup is false, check if an EMAIL-BASED account creation button exists OUTSIDE the header/navigation bar. "
                "Headers are site navigation areas typically at the top containing logo, menu items, navigation links. "
                "Identify headers by any semantic indicators: HTML tags (<header>, <nav>), class/ID names, data attributes (data-automation-id, data-testid), "
                "role attributes (role='navigation', role='banner'), ARIA labels, or structural patterns. "
                "Return true if such button exists outside header, false otherwise. "
                "This check helps prioritize non-header buttons over header buttons.",
            )
            button_in_header: PopupExists = Field(
                ...,
                description="Is the SELECTED button inside header/navigation bar? "
                "If button_exists_outside_header is true, you MUST select that button and return false. "
                "ONLY return true if selected button is in header AND button_exists_outside_header is false. "
                "Headers are identified by semantic indicators: HTML tags (<header>, <nav>), class/ID names, data attributes, "
                "role attributes, ARIA labels, or structural patterns (top of page, contains navigation elements).",
            )
            button_x_path: str = Field(
                ...,
                description="XPath of EMAIL-BASED account creation button (exclude OAuth). "
                "SELECTION ORDER: 1) Button in popup, 2) Button outside header, 3) Button in header. "
                "If button_in_popup is true, use relative XPath: popup_container_x_path//button[...]. Otherwise use absolute XPath.",
            )

        button_found, button = _llm_service.chat(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=AccountCreationButton,
            model="complex",
        )

        if button_found:
            if not is_element_visible(button.button_x_path):
                from jobs.page_components import ApplicationField

                prompt = "The x_path that we are trying to extract is of button to open account creation form."
                container_x_path = (
                    button.popup_container_x_path
                    if button.button_in_popup and button.popup_container_x_path
                    else None
                )
                correct_x_path = ApplicationField.extract_correct_x_path(
                    prev_x_path=button.button_x_path,
                    prompt=prompt,
                    job_title=self.parent_application_page.parent_job.title,
                    job_url=self.parent_application_page.url,
                    container_x_path=container_x_path,
                )
                if correct_x_path:
                    button.button_x_path = correct_x_path
                else:
                    raise Exception(
                        f"Couldn't extract open account creation form button XPath for "
                        f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                    )

            self.button_x_path = button.button_x_path
            self.button_component = Button(
                x_path=button.button_x_path,
                button_type="open_account_creation_form",
                parent_application_page=self.parent_application_page,
            )
            self._identified = True
        else:
            raise Exception(
                f"Couldn't find button to open account creation form for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

    def identify_next_state(self) -> Optional[LoginStateType]:
        """After clicking, check if popup appeared or form is visible"""

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"I just clicked a button to open the account creation form. Follow this structured analysis:\n\n"
            f"STEP 1: First determine if there is a popup/modal visible on the page. Popups are blocking elements that must be handled first.\n"
            f"STEP 2: If a popup exists, determine what TYPE of popup it is:\n"
            f"  - Confirmation popup: A popup with yes/no/ok/cancel/dismiss buttons that needs to be closed (no form fields inside)\n"
            f"  - Form popup: A popup that contains the account creation form with fields (username, password, etc.) already visible and ready to fill\n"
            f"  - Options popup: A popup that shows multiple sign-in/signup options (like 'Sign up with Google', 'Sign up with LinkedIn', 'Sign up with Email', etc.) "
            f"  - This options popup does NOT contain the actual form yet, but shows buttons/links to choose authentication method\n"
            f"STEP 3: Based on popup type analysis, determine the next step:\n"
            f"  - If confirmation popup exists → return confirmation_popup (must dismiss this popup first)\n"
            f"  - If form popup exists (popup contains account creation form) → return account_creation_form (form is inside popup and ready to fill)\n"
            f"  - If options popup exists (shows multiple signup options) → return open_account_creation_form_button (need to click email option to open form)\n"
            f"  - If no popup and form exists outside → return account_creation_form (form is outside popup)"
        )

        class PopupExists(Enum):
            true = True
            false = False

        class PopupType(Enum):
            confirmation_popup = "confirmation_popup"
            form_popup = "form_popup"
            options_popup = "options_popup"
            no_popup = "no_popup"

        class NextStepAfterClick(Enum):
            confirmation_popup = "confirmation_popup"
            account_creation_form = "account_creation_form"
            open_account_creation_form_button = "open_account_creation_form_button"

        class NextStep(BaseModel):
            # Step 1: Popup detection
            popup_exists: PopupExists = Field(
                ...,
                description="Is there a popup/modal visible on the page after clicking the button? Popups are blocking elements that must be handled first. "
                "Look for modal dialogs, overlay divs, elements with role='dialog', or high z-index elements that appear above the main content.",
            )

            # Step 2: Determine popup type
            popup_type: PopupType = Field(
                ...,
                description="If popup_exists is true, what type of popup is it? "
                "confirmation_popup: A popup with yes/no/ok/cancel/dismiss/close buttons that needs to be dismissed (typically NO form fields inside, just buttons). "
                "form_popup: A popup that contains the account creation form with input fields (username, password, email, etc.) already visible and ready to fill. "
                "options_popup: A popup that shows multiple sign-in/signup options/buttons (like 'Sign up with Google', 'Sign up with LinkedIn', 'Sign up with Email', etc.). "
                "This popup does NOT contain the actual form yet, but shows buttons/links to choose authentication method. "
                "no_popup: Return this if popup_exists is false.",
            )

            # Step 3: Final decision
            next_step: NextStepAfterClick = Field(
                ...,
                description="What happened after clicking the button to open account creation form? "
                "If popup_type is confirmation_popup, return confirmation_popup (must dismiss this confirmation popup first). "
                "If popup_type is form_popup, return account_creation_form (the form is inside the popup and ready to fill). "
                "If popup_type is options_popup, return open_account_creation_form_button (need to click the email-based signup option button to open the form). "
                "If popup_type is no_popup, check if account creation form is visible outside popup. If form is visible, return account_creation_form. "
                "Only return account_creation_form if the form is actually visible (either in popup or outside).",
            )

        next_found, next_step = _llm_service.chat(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=NextStep,
            model="complex",
        )

        if next_found:
            if next_step.next_step == NextStepAfterClick.confirmation_popup:
                return LoginStateType.CONFIRMATION_POPUP
            elif (
                next_step.next_step
                == NextStepAfterClick.open_account_creation_form_button
            ):
                return LoginStateType.OPEN_ACCOUNT_CREATION_FORM_BUTTON
            else:
                return LoginStateType.ACCOUNT_CREATION_FORM

        # Default to account creation form if unclear
        return LoginStateType.ACCOUNT_CREATION_FORM

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "button_x_path": self.button_x_path,
            "button_component": (
                self.button_component.to_dict() if self.button_component else None
            ),
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(parent_application_page=parent_application_page)
        instance.button_x_path = input_dict.get("button_x_path")

        if input_dict.get("button_component"):
            from jobs.page_components import get_page_component_class_name

            button_class = get_page_component_class_name(
                class_name=input_dict["button_component"]["class"]
            )
            instance.button_component = button_class.from_dict(
                input_dict["button_component"],
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
