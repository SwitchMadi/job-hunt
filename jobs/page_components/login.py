import time
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

from jobs.page_components import (
    PageComponent,
    Button,
    TextInput,
    logger,
    get_page_component_class_name,
)
from utilities import minify_html_for_gpt_prompt, constants
from utilities.google_services.gmail import Gmail
from utilities.gpt import get_gpt_response
from utilities.selenium import get_selenium_driver, element_exists


driver = get_selenium_driver(headless=False)
driver.set_page_load_timeout(15)


class Login(PageComponent):
    def __init__(self, parent_application_page):
        self.parent_application_page = parent_application_page
        self.login_section_url = driver.current_url

        self.next = None
        self.prev = None
        self.is_component_functional = False

        self.login_steps_identified = False
        self.first_step = None

        self.login_form_input_button = None
        self.login_username_input = None
        self.login_password_input = None
        self.login_security_enabled = False
        self.login_button = None

        self.resend_verification_email_button = None

        self.create_account_form_input_button = None
        self.create_account_username_input = None
        self.create_account_password_input = None
        self.create_account_confirm_password_input = None
        self.create_account_consent_checkbox = None
        self.create_account_security_enabled = False
        self.create_account_button = None
        self.account_created_at = None

        self.verify_account = None

    def proceed(self):
        if not self.login_steps_identified:
            self._identify_login_section_steps()

            self.is_component_functional = True
            self.parent_application_page.redo_steps()

            is_login_successful, login_failure_reason = self.is_login_successful
            if is_login_successful:
                return

        if self.login_security_enabled:
            raise Exception("Security is enabled on login, so skipping login!")

        if self.first_step == "click_to_open_form_input":
            self.login_form_input_button.proceed()

        logger.info("Trying to login...")
        self.login_username_input.proceed()
        self.login_password_input.proceed()
        self.login_button.proceed()

        is_login_successful, login_failure_reason = self.is_login_successful
        if not is_login_successful:
            if login_failure_reason in ["non_existent_account", "wrong_credentials"]:
                logger.info(
                    f"Login failed as account doesn't exist. Creating new account..."
                )
                self.create_account_form_input_button.proceed()

                if self.create_account_security_enabled:
                    raise Exception(
                        "Security is enabled on create account activity, so skipping creating account!"
                    )

                self.create_account_username_input.proceed()
                self.create_account_password_input()
                self.create_account_confirm_password_input()

                if self.create_account_consent_checkbox:
                    self.create_account_consent_checkbox.proceed()

                self.account_created_at = datetime.utcnow()
                self.create_account_button.proceed()
            elif login_failure_reason == "email_not_verified":
                logger.info(
                    f"Email not verified. Triggering email verification email..."
                )
                self._trigger_email_verification_email()

            if self.is_verification_email_sent:
                logger.info(f"Verifying email...")
                self.verify_account = VerifyAccount(
                    parent_application_page=self.parent_application_page
                )
                self.verify_account.proceed()

        self.parent_application_page.redo_steps(stop_step=self)
        return

    def _identify_login_section_steps(self):
        self._identify_login_steps()

        is_login_successful, login_failure_reason = self.is_login_successful
        if not is_login_successful:
            if login_failure_reason in ["non_existent_account", "wrong_credentials"]:
                self._identify_create_account_steps()

                logger.info(
                    f"Retrying login to extract resend verification email button..."
                )
                self.parent_application_page.redo_steps()

                if self.first_step == "click_to_open_form_input":
                    self.login_form_input_button.proceed()

                self.login_username_input.proceed()
                self.login_password_input.proceed()
                self.login_button.proceed()

            self._trigger_email_verification_email()

            if self.is_verification_email_sent:
                self.verify_account = VerifyAccount(
                    parent_application_page=self.parent_application_page
                )
                self.verify_account.proceed()
            else:
                raise Exception("It seems account verification email couldn't be sent.")

        self.login_steps_identified = True

    def _identify_login_steps(self):
        global driver

        class LoginStep(str, Enum):
            click_to_open_form_input = "click_to_open_form_input"
            enter_credentials = "enter_credentials"

        class LoginSecurityEnabled(Enum):
            true = True
            false = False

        class LoginNextStep(BaseModel):
            step: LoginStep = Field(
                ...,
                description="Based on the whole HTML, what is the immediate & mandatory next step to login using"
                "username and password.\n"
                "click_to_open_form_input - I have to open username & password form by clicking somewhere\n"
                "enter_credentials - Form is already open and I have to enter credentials",
            )
            username_x_path: str = Field(
                ...,
                description="If at enter_credentials stage then XPath of email / username input field",
            )
            password_x_path: str = Field(
                ...,
                description="If at enter_credentials stage then XPath of password input field",
            )
            login_security_enabled: LoginSecurityEnabled = Field(
                ...,
                description="If at enter_credentials stage then Whether any captcha or security question or puzzle is "
                "to be solved to login",
            )
            login_x_path: str = Field(
                ...,
                description="If at enter_credentials stage then XPath of login button where display is not None",
            )
            open_form_input_x_path: str = Field(
                ...,
                description="If at click_to_open_form_input stage then XPath of "
                "the button which will open username & password form",
            )

        while self.login_username_input is None:
            user_prompt = (
                f"Following HTML page is job application page for {self.parent_application_page.parent_job.title}. "
                f"Currently I am at login section. I have to login using username and password. Analyse the whole HTML "
                f"very carefully for determining the immediate next step to login. Respond with just 1 next step, not "
                f"any further than 1 step.\n"
                f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}"
            )

            login_next_step_found, login_step = get_gpt_response(
                constants.gpt["system_prompts"]["application_step_identification"],
                user_prompt,
                response_format=LoginNextStep,
            )
            if login_next_step_found:
                if login_step.step == LoginStep.click_to_open_form_input:
                    self.first_step = "click_to_open_form_input"
                    self.login_form_input_button = Button(
                        x_path=login_step.open_form_input_x_path,
                        button_type="login_form_input",
                        parent_application_page=self.parent_application_page,
                    )
                    self.login_form_input_button.proceed()
                elif login_step.step == LoginStep.enter_credentials:
                    self.login_security_enabled = (
                        login_step.login_security_enabled.value
                    )
                    if self.login_security_enabled:
                        raise Exception(
                            "Security is enabled on login, so skipping login!"
                        )
                    else:
                        self.login_username_input = TextInput(
                            x_path=login_step.username_x_path,
                            input_type="username",
                            input_text=self.parent_application_page.parent_job.user.email,
                            parent_application_page=self.parent_application_page,
                        )
                        self.login_username_input.proceed()

                        self.login_password_input = TextInput(
                            x_path=login_step.password_x_path,
                            input_type="password",
                            input_text=self.parent_application_page.parent_job.user.password,
                            parent_application_page=self.parent_application_page,
                        )
                        self.login_password_input.proceed()

                        self.login_button = Button(
                            x_path=login_step.login_x_path,
                            button_type="login",
                            parent_application_page=self.parent_application_page,
                        )
                        self.login_button.proceed()
            else:
                raise Exception(
                    f"First login step could not be identified.\nGPT response - {login_step}"
                )

        return

    def _identify_create_account_steps(self):
        user_prompt = (
            f"Following HTML page is job application page for {self.parent_application_page.parent_job.title}. "
            f"Currently I am at login section. I just tried logging in and failed. Analyse the whole HTML "
            f"very carefully for finding button to go into create account section.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}"
        )

        class CreateAccountButton(BaseModel):
            create_account_x_path: str = Field(
                ...,
                description="XPath of create account button",
            )

        create_account_button_found, create_account_button = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=CreateAccountButton,
        )
        if create_account_button_found:
            self.create_account_form_input_button = Button(
                x_path=create_account_button.create_account_x_path,
                button_type="create_account_form_input",
                parent_application_page=self.parent_application_page,
            )
            self.create_account_form_input_button.proceed()

            user_prompt = (
                f"Following HTML page is job application page for {self.parent_application_page.parent_job.title}. "
                f"Currently I am at create account section. Analyse the whole HTML very carefully for identifying "
                f"XPaths of elements to create account.\n"
                f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}"
            )

            class CreateAccountSecurityEnabled(Enum):
                true = True
                false = False

            class CreateAccountSteps(BaseModel):
                username_x_path: str = Field(
                    ...,
                    description="XPath of email / username input field",
                )
                password_x_path: str = Field(
                    ...,
                    description="XPath of new password input field",
                )
                confirm_password_x_path: str = Field(
                    ...,
                    description="XPath of confirm password input field",
                )
                create_account_security_enabled: CreateAccountSecurityEnabled = Field(
                    ...,
                    description="Whether any captcha or security question or puzzle is to be solved to create "
                    "account",
                )
                create_account_x_path: str = Field(
                    ...,
                    description="XPath of create account / submit button where display is not None",
                )
                mandatory_opt_in_checkbox_x_path: str = Field(
                    ...,
                    description="XPath of just 1 mandatory opt-in / consent checkbox that must be clicked in order to"
                    "create account. Return just '' (empty string) if mandatory opt-in / consent checkbox "
                    "not present.",
                )

            create_account_steps_found, create_account_steps = get_gpt_response(
                constants.gpt["system_prompts"]["application_step_identification"],
                user_prompt,
                response_format=CreateAccountSteps,
            )
            if create_account_steps_found:
                self.create_account_security_enabled = (
                    create_account_steps.create_account_security_enabled.value
                )
                if self.create_account_security_enabled:
                    raise Exception(
                        "Security is enabled on create account activity, so skipping creating account!"
                    )
                else:
                    self.create_account_username_input = TextInput(
                        x_path=create_account_steps.username_x_path,
                        input_type="username",
                        input_text=self.parent_application_page.parent_job.user.email,
                        parent_application_page=self.parent_application_page,
                    )
                    self.create_account_username_input.proceed()

                    self.create_account_password_input = TextInput(
                        x_path=create_account_steps.password_x_path,
                        input_type="password",
                        input_text=self.parent_application_page.parent_job.user.password,
                        parent_application_page=self.parent_application_page,
                    )
                    self.create_account_password_input.proceed()

                    self.create_account_confirm_password_input = TextInput(
                        x_path=create_account_steps.confirm_password_x_path,
                        input_type="password",
                        input_text=self.parent_application_page.parent_job.user.password,
                        parent_application_page=self.parent_application_page,
                    )
                    self.create_account_confirm_password_input.proceed()

                    if create_account_steps.mandatory_opt_in_checkbox_x_path:
                        self.create_account_consent_checkbox = Button(
                            x_path=create_account_steps.mandatory_opt_in_checkbox_x_path,
                            button_type="create_account_consent",
                            parent_application_page=self.parent_application_page,
                        )
                        self.create_account_consent_checkbox.proceed()

                    self.create_account_button = Button(
                        x_path=create_account_steps.create_account_x_path,
                        button_type="create_account",
                        parent_application_page=self.parent_application_page,
                    )
                    self.account_created_at = datetime.utcnow()
                    self.create_account_button.proceed()
            else:
                raise Exception(
                    f"Create account steps could not be identified.\nGPT response - {create_account_steps}"
                )
        else:
            raise Exception(
                f"Create account button could not be found.\nGPT response - {create_account_button}"
            )

        return

    @property
    def is_login_successful(self):
        user_prompt = (
            f"Following HTML page is job application page for {self.parent_application_page.parent_job.title}. "
            f"I just tried to login using username and password. Either I logged in successfully and current HTML is of"
            f" the page next to login section OR login was unsuccessful and there is some error message. Analyse the "
            f"HTML very carefully for determining whether login was successful or not.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}"
        )

        class LoginSuccessful(Enum):
            true = True
            false = False

        class LoginFailureReason(Enum):
            non_existent_account = "non_existent_account"
            wrong_credentials = "wrong_credentials"
            email_not_verified = "email_not_verified"
            other = "other"

        class IsLoginSuccessful(BaseModel):
            login_successful: LoginSuccessful = Field(
                ..., description="Whether login was successful or not"
            )
            login_failure_reason: LoginFailureReason = Field(
                ...,
                description="If login not successful then what's the reason of failed login",
            )

        login_success_determined, is_login_successful = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=IsLoginSuccessful,
        )
        if login_success_determined:
            return (
                is_login_successful.login_successful.value,
                is_login_successful.login_failure_reason.value,
            )
        else:
            raise Exception(
                f"Login success could not be determined.\nGPT response - {is_login_successful}"
            )

    def _trigger_email_verification_email(self):
        user_prompt = (
            f"Following HTML page is job application page for {self.parent_application_page.parent_job.title}. "
            f"Currently I am at login section. I just tried logging in and it says that I need to verify my email "
            f"address first. Analyse the whole HTML very carefully for finding button to resend verification email.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}"
        )

        class ResendVerificationEmailButton(BaseModel):
            resend_verification_email_x_path: str = Field(
                ...,
                description="XPath of button to resend verification email",
            )

        resend_verification_email_button_found, resend_verification_email_button = (
            get_gpt_response(
                constants.gpt["system_prompts"]["application_step_identification"],
                user_prompt,
                response_format=ResendVerificationEmailButton,
            )
        )
        if resend_verification_email_button_found:
            self.resend_verification_email_button = Button(
                x_path=resend_verification_email_button.resend_verification_email_x_path,
                button_type="resend_verification_email",
                parent_application_page=self.parent_application_page,
            )
            self.account_created_at = datetime.utcnow()
            self.resend_verification_email_button.proceed()
        else:
            raise Exception(
                f"Resend verification email button could not be found.\nGPT response - "
                f"{resend_verification_email_button}"
            )

    @property
    def is_verification_email_sent(self):
        user_prompt = (
            f"Following HTML page is job application page for {self.parent_application_page.parent_job.title}. "
            f"I just tried creating account. Either verification email was sent which can be considered success OR "
            f"create account step was unsuccessful and there is some error message. Analyse the "
            f"HTML very carefully for determining whether create account step was successful or not.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}"
        )

        class CreateAccountSuccessful(Enum):
            true = True
            false = False

        class IsCreateAccountSuccessful(BaseModel):
            create_account_successful: CreateAccountSuccessful = Field(
                ..., description="Whether create account step was successful or not"
            )

        create_account_success_determined, is_create_account_successful = (
            get_gpt_response(
                constants.gpt["system_prompts"]["application_step_identification"],
                user_prompt,
                response_format=IsCreateAccountSuccessful,
            )
        )
        if create_account_success_determined:
            return is_create_account_successful.create_account_successful.value
        else:
            raise Exception(
                f"Create account step success could not be determined.\nGPT response - {is_create_account_successful}"
            )

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "login_section_url": self.login_section_url,
            "login_steps_identified": self.login_steps_identified,
            "first_step": self.first_step,
            "login_form_input_button": (
                self.login_form_input_button.to_dict()
                if self.login_form_input_button
                else None
            ),
            "login_username_input": self.login_username_input.to_dict(),
            "login_password_input": self.login_password_input.to_dict(),
            "login_security_enabled": self.login_security_enabled,
            "login_button": self.login_button.to_dict(),
            "resend_verification_email_button": (
                self.resend_verification_email_button.to_dict()
                if self.resend_verification_email_button
                else None
            ),
            "create_account_form_input_button": self.create_account_form_input_button.to_dict(),
            "create_account_username_input": self.create_account_username_input.to_dict(),
            "create_account_password_input": self.create_account_password_input.to_dict(),
            "create_account_confirm_password_input": self.create_account_confirm_password_input.to_dict(),
            "create_account_consent_checkbox": (
                self.create_account_consent_checkbox.to_dict()
                if self.create_account_consent_checkbox
                else None
            ),
            "create_account_security_enabled": self.create_account_security_enabled,
            "create_account_button": self.create_account_button.to_dict(),
            "verify_account": self.verify_account.to_dict(),
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(parent_application_page=parent_application_page)
        instance.is_component_functional = True
        instance.login_section_url = input_dict["login_section_url"]
        instance.login_steps_identified = input_dict["login_steps_identified"]
        instance.first_step = input_dict["first_step"]

        if input_dict["login_form_input_button"]:
            login_form_input_button_class = globals()[
                input_dict["login_form_input_button"]["class"]
            ]
            instance.login_form_input_button = login_form_input_button_class.from_dict(
                input_dict=input_dict["login_form_input_button"],
                parent_application_page=parent_application_page,
            )

        login_username_input_class = globals()[
            input_dict["login_username_input"]["class"]
        ]
        instance.login_username_input = login_username_input_class.from_dict(
            input_dict=input_dict["login_username_input"],
            parent_application_page=parent_application_page,
        )
        instance.login_username_input.input_text = (
            parent_application_page.parent_job.user.email
        )

        login_password_input_class = globals()[
            input_dict["login_password_input"]["class"]
        ]
        instance.login_password_input = login_password_input_class.from_dict(
            input_dict=input_dict["login_password_input"],
            parent_application_page=parent_application_page,
        )
        instance.login_password_input.input_text = (
            parent_application_page.parent_job.user.password
        )

        instance.login_security_enabled = input_dict["login_security_enabled"]

        login_button_class = globals()[input_dict["login_button"]["class"]]
        instance.login_button = login_button_class.from_dict(
            input_dict=input_dict["login_button"],
            parent_application_page=parent_application_page,
        )

        resend_verification_email_button_class = globals()[
            input_dict["resend_verification_email_button"]["class"]
        ]
        instance.resend_verification_email_button = (
            resend_verification_email_button_class.from_dict(
                input_dict=input_dict["resend_verification_email_button"],
                parent_application_page=parent_application_page,
            )
        )

        create_account_form_input_button_class = globals()[
            input_dict["create_account_form_input_button"]["class"]
        ]
        instance.create_account_form_input_button = (
            create_account_form_input_button_class.from_dict(
                input_dict=input_dict["create_account_form_input_button"],
                parent_application_page=parent_application_page,
            )
        )

        create_account_username_input_class = globals()[
            input_dict["create_account_username_input"]["class"]
        ]
        instance.create_account_username_input = (
            create_account_username_input_class.from_dict(
                input_dict=input_dict["create_account_username_input"],
                parent_application_page=parent_application_page,
            )
        )
        instance.create_account_username_input.input_text = (
            parent_application_page.parent_job.user.email
        )

        create_account_password_input_class = globals()[
            input_dict["create_account_password_input"]["class"]
        ]
        instance.create_account_password_input = (
            create_account_password_input_class.from_dict(
                input_dict=input_dict["create_account_password_input"],
                parent_application_page=parent_application_page,
            )
        )
        instance.create_account_password_input.input_text = (
            parent_application_page.parent_job.user.password
        )

        create_account_confirm_password_input_class = globals()[
            input_dict["create_account_confirm_password_input"]["class"]
        ]
        instance.create_account_confirm_password_input = (
            create_account_confirm_password_input_class.from_dict(
                input_dict=input_dict["create_account_confirm_password_input"],
                parent_application_page=parent_application_page,
            )
        )
        instance.create_account_confirm_password_input.input_text = (
            parent_application_page.parent_job.user.password
        )

        if input_dict["create_account_consent_checkbox"]:
            create_account_consent_checkbox_class = globals()[
                input_dict["create_account_consent_checkbox"]["class"]
            ]
            instance.create_account_consent_checkbox = (
                create_account_consent_checkbox_class.from_dict(
                    input_dict=input_dict["create_account_consent_checkbox"],
                    parent_application_page=parent_application_page,
                )
            )

        instance.create_account_security_enabled = input_dict[
            "create_account_security_enabled"
        ]

        create_account_button_class = globals()[
            input_dict["create_account_button"]["class"]
        ]
        instance.create_account_button = create_account_button_class.from_dict(
            input_dict=input_dict["create_account_button"],
            parent_application_page=parent_application_page,
        )

        instance.verify_account = VerifyAccount.from_dict(
            input_dict=input_dict["verify_account"],
            parent_application_page=parent_application_page,
        )

        if input_dict["next"]:
            next_class = get_page_component_class_name(
                class_name=input_dict["next"]["class"]
            )
            next_component = next_class.from_dict(
                input_dict["next"], parent_application_page
            )

            instance.next = next_component
            next_component.prev = instance

        return instance


class VerifyAccount(PageComponent):
    def __init__(self, parent_application_page):
        self.parent_application_page = parent_application_page

        self.otp_text_box = None
        self.verify_button = None
        self.component_identified = False
        self.verification_method = None
        self.incorrectly_tagged = False

        self.next = None
        self.prev = None
        self.is_component_functional = False

    def proceed(self):
        if not self.component_identified:
            self._identify()

        if self.incorrectly_tagged:
            logger.warn(
                f"Page identified incorrectly as having account verification component for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )
            return

        verification_email = self._identify_verification_email()
        verification_info = self._extract_verification_info(verification_email)

        if self.verification_method == "link":
            driver.get(verification_info)
        else:
            self.otp_text_box.input_text = verification_info
            self.otp_text_box.proceed()

            if self.verify_button:
                self.verify_button.proceed()

    def _identify(self, retry=False):
        global driver

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
                description="Whether current page is explicitly talking about verification via link or OTP?",
            )
            verification_method: VerificationMethod = Field(
                ...,
                description="If it is verification page then what is account verification method (Link or OTP/code sent"
                " over email)?",
            )
            otp_text_box_x_path: str = Field(
                ...,
                description="If it is verification page then what is XPath of text box for OTP submission. If there are"
                " multiple text boxes for each OTP/code digit then give XPath of the first text box for "
                "first digit.",
            )
            verify_button_x_path: str = Field(
                ...,
                description="If it is verification page and there is any verify or submit button to submit the OTP/code"
                " then XPath of the verify or submit button.",
            )

        component_identified, component = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=VerifyAccountComponent,
        )

        if component_identified:
            if component.is_verification_page.value:
                self.verification_method = component.verification_method.value

                if self.verification_method == "link":
                    self.is_component_functional = True
                    self.component_identified = True
                elif element_exists(component.otp_text_box_x_path) and element_exists(
                    component.verify_button_x_path
                ):
                    self.otp_text_box = TextInput(
                        x_path=component.otp_text_box_x_path,
                        input_type="otp_textbox",
                        parent_application_page=self.parent_application_page,
                    )

                    self.verify_button = Button(
                        x_path=component.verify_button_x_path,
                        button_type="verify_otp",
                        parent_application_page=self,
                        click_result="Submits OTP for account verification",
                    )

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
        gmail = Gmail(user=self.parent_application_page.parent_job.user)

        ten_minutes_ago_unix = datetime.now().timestamp() - 10 * 60
        query = f"after:{int(ten_minutes_ago_unix)} is:unread"

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
                    description="Whether verification email found or not",
                )
                email_id: str = Field(
                    ...,
                    description="Email id of the latest verification email for the given job & company",
                )

            verification_email_search_succeeded, verification_email = get_gpt_response(
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
            verification_link: str = Field(..., description="Email verification link")
            verification_otp: int = Field(
                ..., description="Email verification OTP/code"
            )

        email_verification_info_found, email_verification_info = get_gpt_response(
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

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "otp_text_box": self.otp_text_box.to_dict(),
            "verify_button": self.verify_button.to_dict(),
            "verification_method": self.verification_method,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            parent_application_page=parent_application_page,
        )

        otp_text_box_class = get_page_component_class_name(
            class_name=input_dict["otp_text_box"]["class"]
        )
        instance.otp_text_box = otp_text_box_class.from_dict(
            input_dict=input_dict["otp_text_box"],
            parent_application_page=parent_application_page,
        )

        verify_button_class = get_page_component_class_name(
            class_name=input_dict["verify_button"]["class"]
        )
        instance.verify_button = verify_button_class.from_dict(
            input_dict=input_dict["verify_button"],
            parent_application_page=parent_application_page,
        )

        instance.verification_method = input_dict["verification_method"]
        instance.component_identified = True

        if input_dict["next"]:
            next_class = get_page_component_class_name(
                class_name=input_dict["next"]["class"]
            )
            next_component = next_class.from_dict(
                input_dict["next"], parent_application_page
            )

            instance.next = next_component
            next_component.prev = instance

        return instance
