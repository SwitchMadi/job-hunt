from abc import ABC, abstractmethod
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import ElementClickInterceptedException
from selenium.webdriver.common.action_chains import ActionChains
from enum import Enum
from pydantic import BaseModel, Field

from utilities import minify_html_for_gpt_prompt
from utilities.selenium import get_selenium_driver
from utilities.logging import get_logger
from utilities.gpt import get_gpt_response
from utilities import constants


logger = get_logger(name="job", file_name="job-hunt")
driver = get_selenium_driver(headless=False)
driver.set_page_load_timeout(15)


class PageComponent(ABC):
    @abstractmethod
    def proceed(self):
        pass


class Button(PageComponent):
    def __init__(
        self,
        x_path,
        button_type,
        parent_application_page,
        parent_component=None,
        click_result=None,
    ):
        global driver
        self.x_path = x_path
        self.action_type = button_type
        self.parent_application_page = parent_application_page
        self.parent_component = parent_component
        self.click_result = click_result

        self.next = None
        self.prev = None
        self.is_component_functional = True

    def proceed(self, attempt=1, max_attempt=3):
        global driver

        try:
            element = driver.find_element(By.XPATH, self.x_path)
            driver.execute_script("arguments[0].scrollIntoView(true);", element)
            element.click()
            time.sleep(2)
        except ElementClickInterceptedException as e:
            logger.info(
                f"element click intercepted in class Button's proceed method.\n{e}\nButton instance - {vars(self)}"
            )
            element = driver.find_element(By.XPATH, self.x_path)
            actions = ActionChains(driver)
            actions.move_to_element(element).click().perform()
            time.sleep(2)
        except Exception as e:
            if attempt <= max_attempt:
                logger.info(
                    f"Retrying class Button's proceed method.\nButton instance - {vars(self)}"
                )
                time.sleep(2 * (attempt**2))
                return self.proceed(attempt=attempt + 1)
            else:
                logger.exception(
                    f"Unexpected error occurred in class Button's proceed method.\n{e}\nButton instance - {vars(self)}"
                )
                self.is_component_functional = False

        return


class TextInput(PageComponent):
    def __init__(
        self,
        x_path,
        input_type,
        input_text,
        parent_application_page,
        parent_component=None,
    ):
        global driver
        self.x_path = x_path
        self.input_type = input_type
        self.input_text = input_text
        self.parent_application_page = parent_application_page
        self.parent_component = parent_component

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
                f"Unexpected error occurred in class TextInput's proceed method.\n{e}\nTextInput instance - {vars(self)}"
            )

        return


class Login(PageComponent):
    def __init__(self, parent_application_page):
        self.parent_application_page = parent_application_page

        self.next = None
        self.prev = None
        self.is_component_functional = True

        self.login_steps_identified = False
        self.creds_form_input_button = None
        self.username_input = None
        self.password_input = None
        self.login_security_enabled = False
        self.login_button = None

    def proceed(self):
        if not self.login_steps_identified:
            self._identify_login_steps()

        if self.login_security_enabled:
            return

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

        while self.username_input is None:
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
                    self.creds_form_input_button = Button(
                        x_path=login_step.open_form_input_x_path,
                        button_type="click_to_open_form_input",
                        parent_application_page=self.parent_application_page,
                        parent_component=self,
                    )
                    self.creds_form_input_button.proceed()
                elif login_step.step == LoginStep.enter_credentials:
                    self.username_input = TextInput(
                        x_path=login_step.username_x_path,
                        input_type="username",
                        input_text=self.parent_application_page.parent_job.user.email,
                        parent_application_page=self.parent_application_page,
                        parent_component=self,
                    )
                    self.username_input.proceed()

                    self.password_input = TextInput(
                        x_path=login_step.password_x_path,
                        input_type="password",
                        input_text=self.parent_application_page.parent_job.user.password,
                        parent_application_page=self.parent_application_page,
                        parent_component=self,
                    )
                    self.password_input.proceed()

                    self.login_security_enabled = (
                        login_step.login_security_enabled.value
                    )

                    if self.login_security_enabled:
                        logger.critical(
                            "Security is enabled on login, so skipping login!"
                        )
                        return
                    else:
                        self.login_button = Button(
                            x_path=login_step.login_x_path,
                            button_type="login",
                            parent_application_page=self.parent_application_page,
                            parent_component=self,
                        )
                        self.login_button.proceed()
            else:
                logger.critical(
                    f"First login step could not be identified.\nGPT response - {login_step}"
                )
