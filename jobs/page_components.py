from abc import ABC, abstractmethod
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import ElementClickInterceptedException
from selenium.webdriver.common.action_chains import ActionChains
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime

from utilities import minify_html_for_gpt_prompt, constants
from utilities.selenium import get_selenium_driver
from utilities.logging import get_logger
from utilities.gpt import get_gpt_response
from utilities.google_services.gmail import Gmail


logger = get_logger(name="job")
driver = get_selenium_driver(headless=False)
driver.set_page_load_timeout(15)


class PageComponent(ABC):
    @abstractmethod
    def proceed(self):
        pass

    @abstractmethod
    def to_dict(self):
        pass

    @abstractmethod
    def from_dict(self, input_dict, parent_application_page):
        pass


class Button(PageComponent):
    def __init__(
        self,
        x_path,
        button_type,
        parent_application_page,
        click_result=None,
    ):
        global driver
        self.x_path = x_path
        self.button_type = button_type
        self.parent_application_page = parent_application_page
        self.click_result = click_result

        self.next = None
        self.prev = None
        self.is_component_functional = True
        self.attempt = 1
        self.max_attempt = 3

    def proceed(self):
        global driver

        try:
            element = driver.find_element(By.XPATH, self.x_path)
            driver.execute_script("arguments[0].scrollIntoView(true);", element)
            element.click()
            time.sleep(10)
        except ElementClickInterceptedException as e:
            logger.info(
                f"element click intercepted in class Button's proceed method.\n{e}\nButton instance - {vars(self)}"
            )
            element = driver.find_element(By.XPATH, self.x_path)
            actions = ActionChains(driver)
            actions.move_to_element(element).click().perform()
            time.sleep(10)
        except Exception as e:
            if self.attempt <= self.max_attempt:
                logger.info(
                    f"Retrying class Button's proceed method.\nButton instance - {vars(self)}"
                )
                time.sleep(2 * (self.attempt**2))
                self.attempt += 1
                return self.proceed()
            else:
                logger.exception(
                    f"Unexpected error occurred in class Button's proceed method.\n{e}\nButton instance - {vars(self)}"
                )
                self.is_component_functional = False

        return

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "x_path": self.x_path,
            "button_type": self.button_type,
            "click_result": self.click_result,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            button_type=input_dict["button_type"],
            parent_application_page=parent_application_page,
            click_result=input_dict["click_result"],
        )
        if input_dict["next"]:
            next_class = globals()[input_dict["next"]["class"]]
            next_component = next_class.from_dict(
                input_dict["next"], parent_application_page
            )

            instance.next = next_component
            next_component.prev = instance

        return instance


class TextInput(PageComponent):
    def __init__(
        self,
        x_path,
        input_type,
        parent_application_page,
    ):
        global driver
        self.x_path = x_path
        self.input_type = input_type
        self.parent_application_page = parent_application_page
        self.is_component_functional = True

        self.next = None
        self.prev = None

    def proceed(self):
        global driver

        try:
            element = driver.find_element(By.XPATH, self.x_path)
            element.send_keys(self.input_text)
            element.send_keys(Keys.RETURN)
        except Exception as e:
            logger.exception(
                f"Unexpected error occurred in class TextInput's proceed method.\n{e}\n"
                f"TextInput instance - {vars(self)}"
            )
            self.is_component_functional = False

        return

    @property
    def input_text(self):
        if self.input_type == "username":
            input_text = self.parent_application_page.parent_job.user.email
        elif self.input_type == "password":
            input_text = self.parent_application_page.parent_job.user.password
        else:
            raise Exception(
                f"Invalid input_type for class TextInput - {self.input_type}"
            )

        return input_text

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "x_path": self.x_path,
            "input_type": self.input_type,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            input_type=input_dict["input_type"],
            parent_application_page=parent_application_page,
        )

        if input_dict["next"]:
            next_class = globals()[input_dict["next"]["class"]]
            next_component = next_class.from_dict(
                input_dict["next"], parent_application_page
            )

            instance.next = next_component
            next_component.prev = instance

        return instance


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
                self._verify_email_address()

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
                self._verify_email_address()
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
                            parent_application_page=self.parent_application_page,
                        )
                        self.login_username_input.proceed()

                        self.login_password_input = TextInput(
                            x_path=login_step.password_x_path,
                            input_type="password",
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
                        parent_application_page=self.parent_application_page,
                    )
                    self.create_account_username_input.proceed()

                    self.create_account_password_input = TextInput(
                        x_path=create_account_steps.password_x_path,
                        input_type="password",
                        parent_application_page=self.parent_application_page,
                    )
                    self.create_account_password_input.proceed()

                    self.create_account_confirm_password_input = TextInput(
                        x_path=create_account_steps.confirm_password_x_path,
                        input_type="password",
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

    def _verify_email_address(self):
        gmail = Gmail(user=self.parent_application_page.parent_job.user)

        five_minutes_ago_unix = int(self.account_created_at.timestamp())
        query = f"after:{five_minutes_ago_unix} is:unread"

        email_verified = False

        while not email_verified:
            emails = gmail.get_emails(query=query)

            email_prompt_info = [
                {
                    "email_id": email.message_id,
                    "sender": email.sender,
                    "subject": email.title,
                }
                for email in emails
            ]
            user_prompt = (
                f"While applying for job title {self.parent_application_page.parent_job.title}, I just "
                f"created an account on following URL - {driver.current_url}.\n Following emails are what I "
                f"received in my inbox -\n{email_prompt_info}\nOut of above emails, is there any email "
                f"which is account activation / email id verification email for the account creation?"
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
                    description="Email id of the verification email",
                )

            verification_email_search_succeeded, verification_email = get_gpt_response(
                constants.gpt["system_prompts"]["application_step_identification"],
                user_prompt,
                response_format=VerificationEmail,
            )

            if verification_email_search_succeeded:
                if verification_email.verification_email_found.value:
                    verification_email = [
                        email
                        for email in emails
                        if email.message_id == verification_email.email_id
                    ][0]

                    user_prompt = (
                        f"While applying for job title {self.parent_application_page.parent_job.title}, I just "
                        f"created an account on following URL - {driver.current_url}.\n Following email is the "
                        f"verification email. Extract the link, by clicking which I can verify my email.\n"
                        f"Email - \nTitle - {verification_email.title}\nSender - {verification_email.sender}\n"
                        f"Body - {verification_email.body}"
                    )

                    class EmailVerificationLink(BaseModel):
                        link: str = Field(..., description="Email verification link")

                    email_verification_link_found, email_verification_link = (
                        get_gpt_response(
                            constants.gpt["system_prompts"][
                                "application_step_identification"
                            ],
                            user_prompt,
                            response_format=EmailVerificationLink,
                        )
                    )

                    if email_verification_link_found:
                        driver.get(email_verification_link.link)
                        email_verified = True
                        time.sleep(10)
                    else:
                        raise logger.critical(
                            f"Email verification link couldn't be extracted.\nGPT response - {email_verification_link}"
                        )
            else:
                logger.critical(
                    f"Verification email search failed.\nGPT response - {verification_email}"
                )

        return

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

        login_password_input_class = globals()[
            input_dict["login_password_input"]["class"]
        ]
        instance.login_password_input = login_password_input_class.from_dict(
            input_dict=input_dict["login_password_input"],
            parent_application_page=parent_application_page,
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

        create_account_password_input_class = globals()[
            input_dict["create_account_password_input"]["class"]
        ]
        instance.create_account_password_input = (
            create_account_password_input_class.from_dict(
                input_dict=input_dict["create_account_password_input"],
                parent_application_page=parent_application_page,
            )
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

        if input_dict["next"]:
            next_class = globals()[input_dict["next"]["class"]]
            next_component = next_class.from_dict(
                input_dict["next"], parent_application_page
            )

            instance.next = next_component
            next_component.prev = instance

        return instance
