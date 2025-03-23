from abc import ABC, abstractmethod
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
)
from selenium.webdriver.common.action_chains import ActionChains
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional

from utilities.selenium import (
    get_selenium_driver,
    start_observer,
    get_observed_element,
    get_element_xpath,
    simulate_empty_area_click,
)
from utilities.logging import get_logger
from utilities import pascal_to_snake_casing
from utilities import minify_html_for_gpt_prompt, constants
from utilities.gpt import get_gpt_response


logger = get_logger(name="job")
driver = get_selenium_driver()
driver.set_page_load_timeout(15)


def get_page_component_class_name(class_name):
    module_name = pascal_to_snake_casing(class_name)
    if class_name == "VerifyAccount":
        module_name = "login"
    try:
        return globals()[class_name]
    except KeyError:
        return eval(f'globals()["{module_name}"].{class_name}')


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
        except ElementNotInteractableException as e:
            logger.info(
                f"element not interactable in class Button's proceed method.\n{e}\nButton instance - {vars(self)}"
            )
            element = driver.find_element(By.XPATH, self.x_path)
            driver.execute_script("arguments[0].click();", element)
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
            next_class = get_page_component_class_name(
                class_name=input_dict["next"]["class"]
            )
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
        input_text=None,
    ):
        global driver
        self.x_path = x_path
        self.input_type = input_type
        self.input_text = input_text
        self.parent_application_page = parent_application_page
        self.is_component_functional = True

        self.next = None
        self.prev = None

    def proceed(self):
        global driver

        if self.input_text is None:
            raise Exception("input_text cannot be undefined.")

        try:
            element = driver.find_element(By.XPATH, self.x_path)
            if self.input_type == "otp_textbox":
                element.click()
                for otp_digit in str(self.input_text):
                    active_element = driver.switch_to.active_element
                    active_element.send_keys(f"{otp_digit}")
            else:
                element.send_keys(self.input_text)
                element.send_keys(Keys.RETURN)
        except Exception as e:
            logger.exception(
                f"Unexpected error occurred in class TextInput's proceed method.\n{e}\n"
                f"TextInput instance - {vars(self)}"
            )
            self.is_component_functional = False

        return

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
            next_class = get_page_component_class_name(
                class_name=input_dict["next"]["class"]
            )
            next_component = next_class.from_dict(
                input_dict["next"], parent_application_page
            )

            instance.next = next_component
            next_component.prev = instance

        return instance


class SearchField(PageComponent):
    @classmethod
    def validate_search_field(cls, x_path, field_title):
        global driver

        # Clear previous network requests
        driver.requests.clear()

        element = driver.find_element(By.XPATH, x_path)
        driver.execute_script("arguments[0].scrollIntoView(true);", element)

        # Send specialKey to trigger search
        special_key = "special_key"
        element.send_keys(special_key)
        time.sleep(2)  # Adjust based on realistic wait times for API calls

        # Known tracking/analytics domains to exclude
        tracking_domains = [
            "firebase.com",
            "google-analytics.com",
            "clevertap.com",
            "moengage.com",
            "facebook.com",
            "fbcdn.net",
            "analytics.google.com",
            "segment.io",
            "mixpanel.com",
            "hotjar.com",
            "inkedin.com/li/track",
        ]

        # Function to filter out tracking requests
        def is_tracking_domain(url):
            return any(domain in url for domain in tracking_domains)

        # Criteria 1: Network call with specialKey (excluding tracking domains)
        is_search_field = False
        for request in driver.requests:
            if request.response and not is_tracking_domain(request.url):
                # Check URL params
                if special_key in request.url:
                    is_search_field = True
                    break
                # Check POST request payload
                if request.method == "POST" and request.body:
                    try:
                        body_str = request.body.decode("utf-8")
                        if special_key in body_str:
                            is_search_field = True
                            break
                    except:
                        pass  # skip if decoding fails

        simulate_empty_area_click()

        simulate_empty_area_click(field_title)
        return is_search_field


class DropDown(PageComponent):
    def __init__(
        self, x_path, title, parent_application_page, options=[], option_chosen=None
    ):
        self.x_path = x_path
        self.title = title
        self.parent_application_page = parent_application_page

        if options:
            self.options = options
            self.options_identified = True
        else:
            self.options_identified = True

        self.options = options
        self.option_chosen = option_chosen
        self.dropdown_button = None
        self.is_component_functional = False

        self.next = None
        self.prev = None

    def proceed(self):
        global driver

        self.dropdown_button.proceed()

        option_x_path = [
            option for option in self.options if option["text"] == self.option_chosen
        ][0]["x_path"]
        option = driver.find_element(By.XPATH, option_x_path)
        option.click()

    def extract_options(self, retry=False):
        self.dropdown_button = Button(
            x_path=self.x_path,
            button_type="dropdown",
            parent_application_page=self.parent_application_page,
        )

        start_observer()
        self.dropdown_button.proceed()
        observed_element = get_observed_element()
        observed_element_x_path = get_element_xpath(observed_element)

        global driver

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"There is a dropdown on this page with title as following -\n{self.title}\n"
            f"I am using javascript mutation observer to observer DOM changes. When I clicked the dropdown, the "
            f"observer observed that following element was added to the DOM -\n"
            f"{observed_element.get_attribute('outerHTML')}\n"
            f"Extract all options available in dropdown menu."
        )

        class Option(BaseModel):
            text: str = Field(..., description="Text shown in the dropdown option")
            x_path: str = Field(..., description="XPath of the option")

        class DropdownOptions(BaseModel):
            options: list[Option]

        options_found, options = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=DropdownOptions,
        )
        if options_found:
            self.options = [
                {"text": option.text, "x_path": option.x_path} for option in options
            ]
            self.options_identified = True
            self.dropdown_button.proceed()
            return
        else:
            if not retry:
                self.dropdown_button.proceed()
                return self.extract_options(retry=True)

            logger.error(
                f"Couldn't extract dropdown fields for {self.title}. URL - {self.parent_application_page.url}"
            )
            return


class ApplicationField(PageComponent):
    def __init__(self, parent_application_page, field_info=None):
        self.parent_application_page = parent_application_page
        self.field_info = field_info

        self.field_component = None
        self.component_identified = False

        self.next = None
        self.prev = None
        self.is_component_functional = False

    def proceed(self):
        if not self.component_identified:
            return self._identify()

        self.field_component.proceed()

    def _identify(self, retry=False):
        global driver
        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"The webpage has following application field for applying to the job -\n"
            f"Field title - {self.field_info.field_title}\n"
            f"Field category - {self.field_info.field_category.value}\n"
            f"Analyse the whole HTML very carefully for extracting XPath of the application field."
        )

        class FieldType(Enum):
            textBox = "text_box"
            checkBox = "check_box"
            radioButton = "radio_button"
            dropdown = "dropdown"
            addButton = "add_button"
            upload = "upload"

        class ApplicationFieldInfo(BaseModel):
            x_path: str = Field(
                ...,
                description="XPath of the application field",
            )
            field_type: FieldType = Field(
                ...,
                description="Application field type like textbox, checkbox, dropdown etc.",
            )

        application_field_found, application_field = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=ApplicationFieldInfo,
        )
        if application_field_found:
            print(application_field)
            self.field_info = Button(
                x_path=application_field.x_path,
                button_type="tnc_consent",
                parent_application_page=self.parent_application_page,
            )

            self.field_component.proceed()
            if self.field_component.is_component_functional:
                self.is_component_functional = True
                self.component_identified = True
            elif not retry:
                self._identify(retry=True)
            else:
                raise Exception(
                    f"Couldn't extract TnC field for {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                )
        else:
            raise Exception(
                f"Couldn't extract following application field {self.field_info.field_category} for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

    def _get_field_component(self, application_field):
        if application_field.field_type.value == "text_box":
            field_component = TextInput(
                x_path=application_field.x_path,
                input_type=self.field_info.field_category,
                parent_application_page=self.parent_application_page,
            )
            field_component.input_text = self.field_value

    @classmethod
    def revalidate_field_type(cls, field_type, x_path):
        if field_type == "text_box":
            is_search_field = SearchField.validate_search_field(x_path)
            if is_search_field:
                simulate_empty_area_click()
                return "search_field"

            start_observer()
            element = driver.find_element(By.XPATH, x_path)
            element.click()
            observed_element = get_observed_element()
            if observed_element is None:
                return "text_box"
            else:
                simulate_empty_area_click()
                return "dropdown"

        return field_type

    @property
    def field_value(self):
        if self.field_info.field_category.value == "first_name":
            return self.parent_application_page.parent_job.user.first_name
        elif self.field_info.field_category.value == "last_name":
            return self.parent_application_page.parent_job.user.last_name
        elif self.field_info.field_category.value == "email":
            return self.parent_application_page.parent_job.user.email
        elif self.field_info.field_category.value == "password":
            return self.parent_application_page.parent_job.user.password

    @classmethod
    def extract_field_answer(
        cls,
        job_title,
        job_url,
        company_name,
        question,
        answer_type,
        closest_answer=None,
        options=[],
        parsed_resume=None,
    ):
        user_prompt = (
            f"While filling job application for {job_title} at a company called "
            f"{company_name}, I need you to help me answer following question -\n{question}\n"
        )

        if answer_type == "enum":
            options_list = "\n".join(
                f"{i + 1}. {option}" for i, option in enumerate(options)
            )
            if closest_answer:
                user_prompt += (
                    f"Answer to the question is '{closest_answer}', but I have to select out of following "
                    f"options -\n{options_list}\n"
                )
            else:
                user_prompt += (
                    f"I have to select an option out of following options -\n{options_list}\n If based on "
                    f"the given context there is no answer that makes sense then pick the option which is "
                    f"safest from a candidate's point of view."
                )

            FieldAnswerOptions = Enum(
                "FieldAnswerOptions", {option: option for option in options}
            )

            class FieldAnswer(BaseModel):
                answer: FieldAnswerOptions = Field(
                    ...,
                    description="Correct option based on input",
                )

        elif answer_type == "text":
            user_prompt += (
                f"Answer should be precise and as short as you can write. Also answer should reflect that these are my "
                f"words, not Chat GPT's words. Answer like human candidate and not a language model. If based on the "
                f"given context there is no answer then don't answer the question at all.\n"
            )

            class FieldAnswer(BaseModel):
                answer: Optional[str] = Field(
                    ...,
                    description="Correct answer based on user data. Answer should be precise and as short as you can "
                    "write. Also answer should reflect that these are my words, not Chat GPT's words.",
                )

        else:
            raise Exception(f"Unknown parameter - {answer_type}")

        if closest_answer is None:
            user_prompt += (
                f"Following is context having user resume data using which you have to find answer -\n"
                f"{parsed_resume}\n"
            )

        user_prompt += "Give me correct answer for the question."

        field_answer_found, field_answer = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=FieldAnswer,
        )
        if field_answer_found:
            return (
                field_answer.answer
                if answer_type == "text"
                else field_answer.answer.value
            )
        else:
            logger.error(
                f"Couldn't extract field answer for {job_title}. URL - {job_url}"
            )
            return None

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "field_component": self.field_component.to_dict(),
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            parent_application_page=parent_application_page,
        )

        field_component_class = get_page_component_class_name(
            class_name=input_dict["field_component"]["class"]
        )
        instance.field_component = field_component_class.from_dict(
            input_dict=input_dict["field_component"],
            parent_application_page=parent_application_page,
        )

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
