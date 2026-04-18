from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
from datetime import datetime
from selenium.webdriver.support.ui import WebDriverWait
import time

from jobs.page_components.login.base_state import LoginState
from jobs.page_components.login.types import LoginStateType
from jobs.page_components.button import Button
from jobs.page_components.text_input import TextInput
from jobs.page_components import logger
from utilities import constants
from utilities.llm import create_llm_service
from utilities.selenium import (
    get_selenium_driver,
    minify_html_for_gpt_prompt,
    element_exists,
    is_element_in_popup,
)
from selenium.webdriver.common.by import By
from urllib.parse import urlparse

_llm_service = create_llm_service(provider="openai")

driver = get_selenium_driver()


class AccountCreationFormState(LoginState):
    """State for filling and submitting account creation form"""

    def __init__(self, parent_application_page):
        super().__init__(parent_application_page)
        self.form_container_x_path = None
        self.form_container_in_popup = (
            False  # Persist whether form was in popup at identification time
        )
        self.username_input = None
        self.password_input = None
        self.confirm_password_input = None
        self.consent_checkboxes = []
        self.create_account_button = None
        self.account_created_at = None
        self._identified = False

    @property
    def current_state_type(self) -> LoginStateType:
        return LoginStateType.ACCOUNT_CREATION_FORM

    def proceed(self, retry=False):
        """Fill and submit account creation form"""
        if not self._identified:
            self._identify_form_fields()

        if self.username_input:
            self.username_input.proceed()

        if self.password_input:
            self.password_input.proceed()

        if self.confirm_password_input:
            self.confirm_password_input.proceed()

        for consent_checkbox in self.consent_checkboxes:
            consent_checkbox.proceed()

        if self.create_account_button:
            self.account_created_at = datetime.utcnow()
            self.create_account_button.proceed()
            self.parent_application_page.handle_captcha()
            self._update_steps_if_first_time()
            self.is_component_functional = True

            # Wait for page to update after account creation attempt
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            # ===== HARDCODED DOMAIN-SPECIFIC LOGIC - SEARCH FOR "HARDCODED DOMAIN" TO FIND ALL INSTANCES =====
            # Workaround for myworkdayjobs.com bug: When form is in popup and button is clicked, popup closes
            # but nothing happens. Need to navigate back to job URL to verify if login/account creation succeeded.
            if self.form_container_x_path:
                try:
                    current_url = driver.current_url
                    parsed_url = urlparse(current_url)
                    domain = parsed_url.netloc.lower()

                    # Check if domain is myworkdayjobs.com and form was in popup (use persisted value)
                    if "myworkdayjobs.com" in domain and self.form_container_in_popup:
                        # Check if form container still exists - if not, popup closed, need to navigate back
                        time.sleep(3)
                        if not element_exists(self.form_container_x_path):
                            logger.info(
                                f"myworkdayjobs.com detected with form in popup. Form container disappeared after button click. "
                                f"Navigating to job URL to verify account creation. Job URL: {self.parent_application_page.url}"
                            )
                            driver.get(self.parent_application_page.url)
                            WebDriverWait(driver, 10).until(
                                lambda d: d.execute_script("return document.readyState")
                                == "complete"
                            )
                except Exception as e:
                    logger.warning(
                        f"Error in hardcoded domain-specific logic for myworkdayjobs.com: {e}"
                    )
            # ===== END HARDCODED DOMAIN-SPECIFIC LOGIC =====

    def _identify_form_fields(self, retry=False, previous_non_unique_xpaths=None):
        """Identify form container and all form fields in a single GPT call"""
        base_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"CRITICAL TASK: Identify the ACCOUNT CREATION FORM container and all its fields. "
            f"IMPORTANT: There may be multiple forms visible on this page (e.g., account creation form and sign-in form both present). "
            f"You MUST identify the container element that wraps ONLY the ACCOUNT CREATION FORM (signup form, NOT sign-in form). "
            f"Focus VERY CAREFULLY on finding a unique container that distinguishes the account creation form from any sign-in form. "
            f"Look for distinguishing attributes like: form id, form class, form name, data attributes, aria labels, or parent container classes/ids. "
            f"The container could be a <form> element, <div> with form class, modal/dialog containing the form, or any wrapper element. "
            f"CRITICAL FOR CONTAINER XPath: Avoid using alphanumeric attribute values (like auto-generated IDs, hashes, random strings) in the container XPath. "
            f"Only use them if absolutely necessary for uniqueness. Prefer semantic attributes, class names, form names, data attributes, or structural relationships. "
            f"After identifying the form container XPath, construct all field XPaths RELATIVE to this container XPath. "
            f"This means the field XPaths should use the container XPath as context (e.g., using the container in the XPath expression). "
            f"Find all fields WITHIN that container:\n"
            f"1. Username/email input field (relative XPath from container)\n"
            f"2. Password input field (relative XPath from container)\n"
            f"3. Confirm password input field (relative XPath from container - if present)\n"
            f"4. Optional consent checkboxes (relative XPath from container - there can be multiple checkboxes for terms, privacy, etc.)\n"
            f"5. Create account/submit button (relative XPath from container)\n\n"
            f"CRITICAL POPUP AWARENESS: Be aware that popups/modals can be present on the page and can cause duplicate form elements. "
            f"For example, an account creation form might exist inside a popup while another account creation form exists behind the popup. "
            f"If multiple instances of the account creation form exist (one in popup and one not in popup), ALWAYS PRIORITIZE identifying the form container "
            f"that is INSIDE the popup/modal. Popups are blocking elements that must be handled first, and form elements within popups should be "
            f"prioritized over form elements behind popups. When identifying the container, choose the one inside the popup if a popup is present."
        )

        # Add retry information if this is a retry
        if retry and previous_non_unique_xpaths:
            retry_prompt = (
                f"\n\nCRITICAL RETRY REQUEST: The following XPaths were NOT UNIQUE (matched multiple elements):\n"
                f"{chr(10).join(f'- {xpath}' for xpath in previous_non_unique_xpaths)}\n\n"
                f"You MUST provide XPaths that match EXACTLY ONE element each. "
                f"Make the XPaths more specific by using additional attributes, better container context, or more precise selectors. "
                f"Each XPath must be unique - if it matches multiple elements, the automation will fail."
            )
            user_prompt = base_prompt + retry_prompt
        else:
            user_prompt = base_prompt

        class AccountCreationFormFields(BaseModel):
            form_container_x_path: str = Field(
                ...,
                description="XPath of the container element that wraps the ACCOUNT CREATION FORM (signup form, NOT sign-in form). "
                "This must be a UNIQUE XPath that identifies ONLY the account creation form container. CRITICAL: If there are multiple forms on the page, "
                "this XPath must be specific enough to target ONLY the account creation form's container. Use form id, class, name, data attributes, "
                "aria labels, parent structure, or any other distinguishing features to ensure uniqueness. "
                "IMPORTANT: Avoid alphanumeric attribute values (like auto-generated IDs, hashes, random strings) if possible. "
                "Only use them if absolutely necessary for uniqueness. Prefer semantic attributes, stable class names, form names, or structural relationships. "
                "CRITICAL: If a popup/modal contains an account creation form, prioritize identifying the container inside the popup over one behind the popup.",
            )
            username_x_path: str = Field(
                ...,
                description="XPath of username/email input field constructed RELATIVE to the form_container_x_path. "
                "Use the container XPath as context in your XPath expression. Don't use HTML hierarchy to construct XPath. "
                "Example format: Use form_container_x_path in the XPath (e.g., form_container_x_path//input[@type='email'] or similar relative expression).",
            )
            password_x_path: str = Field(
                ...,
                description="XPath of password input field constructed RELATIVE to the form_container_x_path. "
                "Use the container XPath as context in your XPath expression. Don't use HTML hierarchy to construct XPath.",
            )
            confirm_password_x_path: Optional[str] = Field(
                ...,
                description="XPath of confirm password input field constructed RELATIVE to the form_container_x_path. "
                "Use the container XPath as context in your XPath expression. Don't use HTML hierarchy to construct XPath. "
                "Return empty string if this confirm password field is not present in the form.",
            )
            mandatory_consent_checkbox_x_paths: List[str] = Field(
                ...,
                description="List of XPaths of mandatory consent checkboxes constructed RELATIVE to the form_container_x_path. "
                "Use the container XPath as context in each XPath expression. There can be multiple checkboxes for terms of service, privacy policy, data processing consent, etc. "
                "Don't use HTML hierarchy to construct XPaths. Return empty list if no mandatory consent checkboxes are present.",
            )
            create_account_button_x_path: str = Field(
                ...,
                description="XPath of create account/submit button constructed RELATIVE to the form_container_x_path. "
                "Use the container XPath as context in your XPath expression. Don't use HTML hierarchy to construct XPath. "
                "This button typically has text like 'Sign Up', 'Create Account', 'Register', 'Submit', or similar.",
            )

        fields_found, fields = _llm_service.chat(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=AccountCreationFormFields,
            model="complex",
        )

        if not fields_found:
            raise Exception(
                f"Could not identify account creation form fields for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

        self.form_container_x_path = fields.form_container_x_path

        # Persist whether form container is in popup at identification time
        # This is needed for domain-specific logic that runs after popup might have closed
        if self.form_container_x_path:
            self.form_container_in_popup = is_element_in_popup(
                self.form_container_x_path
            )

        # Validate XPaths: check for missing (0 elements) vs non-unique (>1 elements)
        xpaths_to_check = {
            "form_container_x_path": fields.form_container_x_path,  # TODO: remove this check
            "username_x_path": fields.username_x_path,
            "password_x_path": fields.password_x_path,
            "create_account_button_x_path": fields.create_account_button_x_path,
        }
        if fields.confirm_password_x_path:
            xpaths_to_check["confirm_password_x_path"] = fields.confirm_password_x_path
        for i, checkbox_xpath in enumerate(fields.mandatory_consent_checkbox_x_paths):
            xpaths_to_check[f"consent_checkbox_x_path_{i}"] = checkbox_xpath

        missing_xpaths = {}  # xpath_name -> xpath_value
        non_unique_xpaths = []

        for xpath_name, xpath_value in xpaths_to_check.items():
            if xpath_value:  # Only check non-empty XPaths
                elements = driver.find_elements(By.XPATH, xpath_value)
                if len(elements) == 0:
                    missing_xpaths[xpath_name] = xpath_value
                elif len(elements) > 1:
                    non_unique_xpaths.append(f"{xpath_name}: {xpath_value}")

        # First, try to fix missing XPaths with extract_correct_x_path
        from jobs.page_components import ApplicationField

        prompts_map = {
            "username_x_path": "The x_path that we are trying to extract is of username/email input field.",
            "password_x_path": "The x_path that we are trying to extract is of password input field.",
            "confirm_password_x_path": "The x_path that we are trying to extract is of confirm password input field.",
            "create_account_button_x_path": "The x_path that we are trying to extract is of create account button.",
        }

        xpaths_fixed = False
        for xpath_name, xpath_value in missing_xpaths.items():
            base_prompt = prompts_map.get(
                xpath_name,
                f"The x_path that we are trying to extract is of {xpath_name}.",
            )

            # Include container XPath context if available (fields are relative to container)
            container_x_path = None
            if fields.form_container_x_path and xpath_name != "form_container_x_path":
                prompt = (
                    f"{base_prompt} "
                    f"CRITICAL: This element should be inside the form container with XPath: {fields.form_container_x_path}. "
                    f"The XPath should be constructed relative to this container or be an absolute XPath that targets the element within this container."
                )
                container_x_path = fields.form_container_x_path
            else:
                prompt = base_prompt

            correct_x_path = ApplicationField.extract_correct_x_path(
                prev_x_path=xpath_value,
                prompt=prompt,
                job_title=self.parent_application_page.parent_job.title,
                job_url=self.parent_application_page.url,
                container_x_path=container_x_path,
            )
            if correct_x_path:
                # Update the field with corrected XPath
                if hasattr(fields, xpath_name):
                    setattr(fields, xpath_name, correct_x_path)
                xpaths_fixed = True
                # Re-check uniqueness of corrected XPath
                elements = driver.find_elements(By.XPATH, correct_x_path)
                if len(elements) > 1:
                    non_unique_xpaths.append(f"{xpath_name}: {correct_x_path}")
            else:
                # If extract_correct_x_path fails, add to non_unique_xpaths to retry GPT
                non_unique_xpaths.append(f"{xpath_name}: {xpath_value} (not found)")

        # If any XPaths are not unique or couldn't be fixed, retry GPT once
        if non_unique_xpaths and not retry:
            return self._identify_form_fields(
                retry=True, previous_non_unique_xpaths=non_unique_xpaths
            )
        elif non_unique_xpaths and retry:
            raise Exception(
                f"XPaths are still not unique or missing after retry for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}. "
                f"Non-unique/missing XPaths: {', '.join(non_unique_xpaths)}"
            )

        # Validate username XPath exists (already fixed in validation step if missing)
        if not element_exists(fields.username_x_path):
            raise Exception(
                f"Username field XPath not found after validation for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

        self.username_input = TextInput(
            x_path=fields.username_x_path,
            category="username",
            parent_application_page=self.parent_application_page,
        )

        # Validate password XPath exists (already fixed in validation step if missing)
        if not element_exists(fields.password_x_path):
            raise Exception(
                f"Password field XPath not found after validation for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

        self.password_input = TextInput(
            x_path=fields.password_x_path,
            category="password",
            parent_application_page=self.parent_application_page,
        )

        # Optional confirm password
        if fields.confirm_password_x_path and element_exists(
            fields.confirm_password_x_path
        ):
            self.confirm_password_input = TextInput(
                x_path=fields.confirm_password_x_path,
                category="password",
                parent_application_page=self.parent_application_page,
            )

        # Handle multiple consent checkboxes
        for checkbox_x_path in fields.mandatory_consent_checkbox_x_paths:
            if element_exists(checkbox_x_path):
                consent_checkbox = Button(
                    x_path=checkbox_x_path,
                    button_type="create_account_consent",
                    parent_application_page=self.parent_application_page,
                )
                self.consent_checkboxes.append(consent_checkbox)

        # Validate create account button XPath exists (already fixed in validation step if missing)
        if not element_exists(fields.create_account_button_x_path):
            raise Exception(
                f"Create account button XPath not found after validation for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

        self.create_account_button = Button(
            x_path=fields.create_account_button_x_path,
            button_type="create_account",
            parent_application_page=self.parent_application_page,
        )

        self._identified = True

    def identify_next_state(self) -> Optional[LoginStateType]:
        """Check account creation result and determine next state"""
        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"I just tried to create an account. Analyse the whole HTML very carefully to determine:\n"
            f"1. Did account creation succeed and I'm now logged in?\n"
            f"2. Did account creation fail with 'account already exists' error?\n"
            f"3. Is account verification required (email verification needed)?\n\n"
            f"To determine if account creation succeeded and I'm logged in, look for indicators such as:\n"
            f"- Logout button or link visible in the navigation/header\n"
            f"- User profile menu, account settings, or user name/email displayed\n"
            f"- Dashboard, home page, or application form visible (signup form is gone)\n"
            f"- Welcome message, greeting with user's name, or 'Account created successfully' message\n"
            f"- Navigation menu showing authenticated sections (My Applications, My Profile, etc.)\n"
            f"- Job application form or 'Apply Now' button visible (meaning I can proceed with application)\n"
            f"- URL changed to a dashboard or post-login page (not on login/signup page anymore)\n"
            f"- The account creation form disappeared and was replaced with authenticated content"
        )

        class AccountCreationResult(Enum):
            logged_in = "logged_in"
            account_already_exists = "account_already_exists"
            account_verification = "account_verification"

        class AccountCreationResultCheck(BaseModel):
            result: AccountCreationResult = Field(
                ...,
                description="What is the result of the account creation attempt after submitting the account creation form? "
                "For login success (logged_in), look for: logout button, user profile menu, dashboard/application form visible, "
                "welcome/account created message, authenticated navigation, or signup form disappeared. "
                "Determine if account was created and user is logged in (logged_in), creation failed because account already exists "
                "(account_already_exists), or requires email verification (account_verification).",
            )

        result_found, result = _llm_service.chat(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=AccountCreationResultCheck,
            model="complex",
        )

        if result_found:
            if result.result == AccountCreationResult.logged_in:
                return LoginStateType.LOGGED_IN
            elif result.result == AccountCreationResult.account_already_exists:
                return LoginStateType.ACCOUNT_ALREADY_EXISTS
            elif result.result == AccountCreationResult.account_verification:
                return LoginStateType.ACCOUNT_VERIFICATION

        # Default to account verification if unclear (most common flow)
        return LoginStateType.ACCOUNT_VERIFICATION

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "form_container_x_path": self.form_container_x_path,
            "form_container_in_popup": self.form_container_in_popup,
            "username_input": (
                self.username_input.to_dict() if self.username_input else None
            ),
            "password_input": (
                self.password_input.to_dict() if self.password_input else None
            ),
            "confirm_password_input": (
                self.confirm_password_input.to_dict()
                if self.confirm_password_input
                else None
            ),
            "consent_checkboxes": [
                checkbox.to_dict() for checkbox in self.consent_checkboxes
            ],
            "create_account_button": (
                self.create_account_button.to_dict()
                if self.create_account_button
                else None
            ),
            "account_created_at": (
                self.account_created_at.isoformat() if self.account_created_at else None
            ),
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(parent_application_page=parent_application_page)
        instance.form_container_x_path = input_dict.get("form_container_x_path")
        instance.form_container_in_popup = input_dict.get(
            "form_container_in_popup", False
        )

        if input_dict.get("account_created_at"):
            instance.account_created_at = datetime.fromisoformat(
                input_dict["account_created_at"]
            )

        from jobs.page_components import get_page_component_class_name

        if input_dict.get("username_input"):
            username_class = get_page_component_class_name(
                class_name=input_dict["username_input"]["class"]
            )
            instance.username_input = username_class.from_dict(
                input_dict["username_input"],
                parent_application_page,
            )

        if input_dict.get("password_input"):
            password_class = get_page_component_class_name(
                class_name=input_dict["password_input"]["class"]
            )
            instance.password_input = password_class.from_dict(
                input_dict["password_input"],
                parent_application_page,
            )

        if input_dict.get("confirm_password_input"):
            confirm_password_class = get_page_component_class_name(
                class_name=input_dict["confirm_password_input"]["class"]
            )
            instance.confirm_password_input = confirm_password_class.from_dict(
                input_dict["confirm_password_input"],
                parent_application_page,
            )

        if input_dict.get("consent_checkboxes"):
            for consent_checkbox_dict in input_dict["consent_checkboxes"]:
                consent_class = get_page_component_class_name(
                    class_name=consent_checkbox_dict["class"]
                )
                consent_checkbox = consent_class.from_dict(
                    consent_checkbox_dict,
                    parent_application_page,
                )
                instance.consent_checkboxes.append(consent_checkbox)

        if input_dict.get("create_account_button"):
            create_button_class = get_page_component_class_name(
                class_name=input_dict["create_account_button"]["class"]
            )
            instance.create_account_button = create_button_class.from_dict(
                input_dict["create_account_button"],
                parent_application_page,
            )

        instance._identified = True
        instance.is_component_functional = True

        if input_dict.get("next"):
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
