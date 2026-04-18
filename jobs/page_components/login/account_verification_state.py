import time
from datetime import datetime
from pydantic import BaseModel, Field
from selenium.webdriver.support.ui import WebDriverWait
from enum import Enum
from typing import Optional

from jobs.page_components.login.base_state import LoginState
from jobs.page_components.login.handle_captcha import handle_captcha
from jobs.page_components.login.types import LoginStateType
from jobs.page_components.button import Button
from jobs.page_components.text_input import TextInput
from jobs.page_components import logger, get_page_component_class_name
from utilities import constants
from utilities.google_services.gmail import Gmail
from utilities.llm import create_llm_service
from utilities.selenium import (
    get_selenium_driver,
    element_exists,
    minify_html_for_gpt_prompt,
)

_llm_service = create_llm_service(provider="openai")

driver = get_selenium_driver()


class AccountVerificationState(LoginState):
    """State for verifying account via email (OTP or link)"""

    def __init__(self, parent_application_page):
        super().__init__(parent_application_page)
        self.otp_text_box = None
        self.verify_button = None
        self.component_identified = False
        self.verification_method = None
        self.incorrectly_tagged = False

    @property
    def current_state_type(self) -> LoginStateType:
        return LoginStateType.ACCOUNT_VERIFICATION

    def proceed(self, retry=False):
        """Execute account verification"""
        if not self.component_identified:
            self._identify()

        if self.incorrectly_tagged:
            logger.warn(
                f"Page identified incorrectly as having account verification component for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )
            self.is_component_functional = False
            return

        # For link verification, we don't need to identify email - just proceed with verification
        if self.verification_method == "link":
            # Link verification will be handled after we get the verification link
            verification_email = self._identify_verification_email()
            verification_info = self._extract_verification_info(verification_email)
            driver.get(verification_info)
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            handle_captcha(self.parent_application_page)
        else:
            # OTP verification: get email, extract OTP, fill and submit
            verification_email = self._identify_verification_email()
            verification_info = self._extract_verification_info(verification_email)
            self.otp_text_box.answer = verification_info
            self.otp_text_box.proceed()

            if self.verify_button:
                self.verify_button.proceed()
                handle_captcha(self.parent_application_page)

        self._update_steps_if_first_time()
        self.is_component_functional = True

    def _identify(self, retry=False):
        """Identify verification method and fields"""
        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"In previous step I submitted email id and I have been sent email for account verification. Current page"
            f"has account verification component. Verification is through either a link or an OTP/code sent to my "
            f"email. Help me identify what is the verification method (link or OTP/code)? If it's an OTP/code or code "
            f"based verification then what is XPath of text box to submit OTP/code. If there are multiple text boxes "
            f"then give me XPath of first text box for first digit of the OTP/code. Also give me XPath of submit or "
            f"verify button if there is any.\n"
            f"If current page is not talking about verification via link or OTP then this is not an account "
            f"verification page and return false."
        )

        class IsVerificationPage(Enum):
            true = True
            false = False

        class VerificationMethod(Enum):
            link = "link"
            otp_code = "otp_code"

        class VerifyAccountComponent(BaseModel):
            is_verification_page: IsVerificationPage = Field(
                ...,
                description="Whether current page is explicitly talking about account verification via link or OTP/code sent to email. "
                "This means the page clearly indicates that email verification is required and provides instructions or fields for verification.",
            )
            verification_method: VerificationMethod = Field(
                ...,
                description="If it is a verification page, determine the verification method. Link method means clicking a verification link "
                "from email, while OTP/code method means entering a verification code/OTP received via email into a text field on the page.",
            )
            otp_text_box_x_path: str = Field(
                ...,
                description="If verification method is OTP/code, provide XPath of text box for OTP submission. If there are multiple "
                "text boxes (one for each digit of the OTP), give XPath of the first text box for the first digit. "
                "XPath should be usable in selenium chrome driver and not use HTML hierarchy. Return empty string if link method.",
            )
            verify_button_x_path: str = Field(
                ...,
                description="If verification method is OTP/code and there is a verify or submit button to submit the OTP/code, provide "
                "XPath of that button. XPath should be usable in selenium chrome driver and not use HTML hierarchy. "
                "This button is clicked after entering the OTP to verify the account. Return empty string if link method or no button present.",
            )

        component_identified, component = _llm_service.chat(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=VerifyAccountComponent,
        )

        if component_identified:
            if component.is_verification_page.value:
                self.verification_method = component.verification_method.value

                if self.verification_method == "link":
                    self._update_steps_if_first_time()
                    self.is_component_functional = True
                    self.component_identified = True
                elif element_exists(component.otp_text_box_x_path) and element_exists(
                    component.verify_button_x_path
                ):
                    self.otp_text_box = TextInput(
                        x_path=component.otp_text_box_x_path,
                        category="otp_textbox",
                        parent_application_page=self.parent_application_page,
                    )

                    self.verify_button = Button(
                        x_path=component.verify_button_x_path,
                        button_type="verify_otp",
                        parent_application_page=self.parent_application_page,
                    )

                    self._update_steps_if_first_time()
                    self.is_component_functional = True
                    self.component_identified = True
                elif not retry:
                    self._identify(retry=True)
                else:
                    raise Exception(
                        f"Couldn't identify verify account component for {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                    )
            else:
                self.incorrectly_tagged = True
                return
        else:
            raise Exception(
                f"Couldn't identify verify account component for {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

    def _identify_verification_email(self):
        """Identify verification email from Gmail"""
        gmail = Gmail(user=self.parent_application_page.parent_job.user)

        ten_minutes_ago_unix = datetime.now().timestamp() - 10 * 60
        query = f"after:{int(ten_minutes_ago_unix)}"

        email_identified = False
        while not email_identified:
            time.sleep(2)
            emails = gmail.get_emails(query=query)

            email_prompt_info = [
                {
                    "email_id": email.message_id,
                    "sender": email.sender,
                    "subject": email.title,
                    "time": datetime.fromtimestamp(email.time),
                }
                for email in emails
            ]
            user_prompt = (
                f"While applying for job title {self.parent_application_page.parent_job.title} at a company called "
                f"{self.parent_application_page.parent_job.company}, I just created an account on following URL - "
                f"{driver.current_url}.\n Following emails are what I received in my inbox -\n{email_prompt_info}\nOut "
                f"of above emails, is there any email which is account activation / email id verification email for the"
                f" account creation?"
            )

            class VerificationEmailFound(Enum):
                true = True
                false = False

            class VerificationEmail(BaseModel):
                verification_email_found: VerificationEmailFound = Field(
                    ...,
                    description="Whether a verification email for account activation or email verification was found in the inbox. "
                    "This email should be related to the account creation for the specific job application at the given company.",
                )
                email_id: str = Field(
                    ...,
                    description="Email id (message_id) of the latest verification email for the given job and company. "
                    "This is the unique identifier of the email that contains the account verification link or OTP code.",
                )

            verification_email_search_succeeded, verification_email = _llm_service.chat(
                constants.gpt["system_prompts"]["application_step_identification"],
                user_prompt,
                response_format=VerificationEmail,
            )
            email_identified = verification_email.verification_email_found.value

            if email_identified:
                return [
                    email
                    for email in emails
                    if email.message_id == verification_email.email_id
                ][0]

    def _extract_verification_info(self, email):
        """Extract verification link or OTP from email"""
        if self.verification_method == "link":
            info_extraction_prompt = "Extract the verification link, by clicking which I can verify my email."
        else:
            info_extraction_prompt = (
                "Extract the verification OTP/code, using which I can verify my email."
            )

        user_prompt = (
            f"While applying for job title {self.parent_application_page.parent_job.title}, I just "
            f"created an account on following URL - {driver.current_url}.\n Following email is the "
            f"verification email. {info_extraction_prompt}\n"
            f"Email - \nTitle - {email.title}\nSender - {email.sender}\n"
            f"Body - {email.body}"
        )

        class EmailVerificationInfo(BaseModel):
            verification_link: str = Field(
                ...,
                description="Email verification link extracted from the verification email. "
                "This is the full URL that needs to be clicked to verify the email address when verification method is 'link'.",
            )
            verification_otp: str = Field(
                ...,
                description="Email verification OTP/code extracted from the verification email. "
                "This is the verification code or one-time password that needs to be entered into the OTP text field when verification method is 'otp_code'.",
            )

        email_verification_info_found, email_verification_info = _llm_service.chat(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=EmailVerificationInfo,
        )

        if email_verification_info_found:
            return (
                email_verification_info.verification_link
                if self.verification_method == "link"
                else email_verification_info.verification_otp
            )
        else:
            raise logger.critical(
                f"Email verification {self.verification_method} couldn't be extracted.\nGPT response - {email_verification_info}"
            )

    def identify_next_state(self) -> Optional[LoginStateType]:
        """Check verification result and determine next state"""

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"I just completed account verification (via {'link' if self.verification_method == 'link' else 'OTP'}). "
            f"Analyse the whole HTML very carefully to determine:\n"
            f"1. Did verification succeed and I'm now logged in?\n"
            f"2. Did verification fail?\n\n"
            f"To determine if verification succeeded and I'm logged in, look for indicators such as:\n"
            f"- Logout button or link visible in the navigation/header\n"
            f"- User profile menu, account settings, or user name/email displayed\n"
            f"- Dashboard, home page, or application form visible (verification form/page is gone)\n"
            f"- Welcome message, greeting with user's name, or 'Email verified successfully' message\n"
            f"- Navigation menu showing authenticated sections (My Applications, My Profile, etc.)\n"
            f"- Job application form or 'Apply Now' button visible (meaning I can proceed with application)\n"
            f"- URL changed to a dashboard or post-login page (not on verification page anymore)\n"
            f"- The verification form/page disappeared and was replaced with authenticated content\n"
            f"- Success message like 'Your email has been verified' or 'Account activated'"
        )

        class VerificationResult(Enum):
            logged_in = "logged_in"
            verification_failed = "verification_failed"

        class VerificationResultCheck(BaseModel):
            result: VerificationResult = Field(
                ...,
                description="What is the result of the account verification attempt after clicking the verification link or submitting the OTP? "
                "For login success (logged_in), look for: logout button, user profile menu, dashboard/application form visible, "
                "email verified/welcome message, authenticated navigation, verification page disappeared, or success messages. "
                "Determine if verification succeeded and user is now logged in (logged_in) or if verification failed with an error message (verification_failed).",
            )

        result_found, result = _llm_service.chat(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=VerificationResultCheck,
        )

        if result_found:
            if result.result == VerificationResult.logged_in:
                return LoginStateType.LOGGED_IN
            elif result.result == VerificationResult.verification_failed:
                # This will raise exception in AccountVerificationFailedState
                return LoginStateType.ACCOUNT_VERIFICATION_FAILED

        # Default to logged in if unclear (optimistic)
        return LoginStateType.LOGGED_IN

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "otp_text_box": self.otp_text_box.to_dict() if self.otp_text_box else None,
            "verify_button": (
                self.verify_button.to_dict() if self.verify_button else None
            ),
            "verification_method": self.verification_method,
            "incorrectly_tagged": self.incorrectly_tagged,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            parent_application_page=parent_application_page,
        )

        if input_dict.get("otp_text_box"):
            otp_text_box_class = get_page_component_class_name(
                class_name=input_dict["otp_text_box"]["class"]
            )
            instance.otp_text_box = otp_text_box_class.from_dict(
                input_dict=input_dict["otp_text_box"],
                parent_application_page=parent_application_page,
            )

        if input_dict.get("verify_button"):
            verify_button_class = get_page_component_class_name(
                class_name=input_dict["verify_button"]["class"]
            )
            instance.verify_button = verify_button_class.from_dict(
                input_dict=input_dict["verify_button"],
                parent_application_page=parent_application_page,
            )

        instance.verification_method = input_dict.get("verification_method")
        instance.incorrectly_tagged = input_dict.get("incorrectly_tagged", False)
        instance.component_identified = True

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
