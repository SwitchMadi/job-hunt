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
    start_dom_mutation_observer,
    get_observed_element,
    get_element_xpath,
    simulate_empty_area_click,
    start_network_observer,
    get_observed_network_calls,
    stop_network_observer,
    element_exists,
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
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", element
            )
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
    def __init__(self, x_path, title, category, parent_application_page):
        self.x_path = x_path
        self.title = title
        self.category = category
        self.parent_application_page = parent_application_page

        self.options_container_x_path = None
        self._answer = None

        self.is_component_functional = False

        self.next = None
        self.prev = None

    @classmethod
    def validate_search_field(cls, x_path, field_title):
        global driver

        start_network_observer()

        element = driver.find_element(By.XPATH, x_path)
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", element
        )

        special_key = "special_key"
        element.send_keys(special_key)
        time.sleep(2)  # Allow API calls to trigger

        captured_requests = get_observed_network_calls()
        stop_network_observer()

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

        def is_tracking_domain(url):
            return any(domain in url for domain in tracking_domains)

        is_search_field = False
        for request in captured_requests:
            if not is_tracking_domain(request["url"]):
                # Check decoded query params
                for key, value in request.get("decodedQueryParams", {}).items():
                    if special_key == value:
                        is_search_field = True
                        break

                # Check POST body
                if (
                    not is_search_field
                    and request["method"] == "POST"
                    and request["body"]
                ):
                    if special_key in request["body"]:
                        is_search_field = True
                        break

                if is_search_field:
                    break

        simulate_empty_area_click(field_title)
        return is_search_field

    def proceed(self):
        input_count = min(2, len(self.answer.split(" ")))
        while input_count >= 0:
            if input_count > 0:
                input_key = " ".join(self.answer.split(" ")[:input_count])
            else:
                input_key = "a"

            element = driver.find_element(By.XPATH, self.x_path)

            if not self.options_container_x_path:
                start_dom_mutation_observer()
                element.send_keys(input_key)
                time.sleep(2)
                options_container = get_observed_element()
                self.options_container_x_path = get_element_xpath(options_container)
            else:
                element.send_keys(input_key)
                time.sleep(2)

            options = DropDown.extract_dropdown_options(
                job_title=self.parent_application_page.parent_job.title,
                job_url=self.parent_application_page.url,
                question=self.title,
                options_container_x_path=self.options_container_x_path,
            )
            if options:
                closest_option = (
                    self.answer
                    if [option for option in options if option["text"] == self.answer]
                    else None
                )

                if closest_option is None:
                    closest_option = ApplicationField.extract_field_answer(
                        job_title=self.parent_application_page.parent_job.title,
                        job_url=self.parent_application_page.url,
                        company_name=self.parent_application_page.parent_job.company,
                        question=self.title,
                        answer_type="enum",
                        options=[option["text"] for option in options],
                        closest_answer=self.answer,
                    )

                option = [
                    option for option in options if option["text"] == closest_option
                ][0]
                option_element = driver.find_element(By.XPATH, option["x_path"])
                option_element.click()
            else:
                input_count -= 1

        if element_exists(self.options_container_x_path):
            raise Exception(
                f"Couldn't proceed on following search field {self.category} for "
                f"{self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )

        self.is_component_functional = True
        return

    @property
    def answer(self):
        if self._answer is not None:
            return self._answer

        answer = ApplicationField.get_field_value(
            field_category=self.category,
            user=self.parent_application_page.parent_job.user,
        )
        if not answer:
            answer = ApplicationField.extract_field_answer(
                job_title=self.parent_application_page.parent_job.title,
                job_url=self.parent_application_page.url,
                company_name=self.parent_application_page.parent_job.company,
                question=self.title,
                answer_type="text",
                parsed_resume=self.parent_application_page.parent_job.user.parsed_resume,
            )

        self._answer = answer
        return self._answer

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "x_path": self.x_path,
            "title": self.title,
            "category": self.category,
            "options_container_x_path": self.options_container_x_path,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            title=input_dict["title"],
            category=input_dict["category"],
            parent_application_page=parent_application_page,
        )

        instance.options_container_x_path = input_dict["options_container_x_path"]
        instance.is_component_functional = True

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


class DropDown(PageComponent):
    def __init__(self, x_path, title, category, parent_application_page):
        self.x_path = x_path
        self.title = title
        self.category = category
        self.parent_application_page = parent_application_page
        self.dropdown_button = Button(
            x_path=self.x_path,
            button_type="dropdown",
            parent_application_page=self.parent_application_page,
        )

        self.options = []
        self.options_container_x_path = None

        self.is_component_functional = False

        self.next = None
        self.prev = None

    def proceed(self):
        global driver

        option = None
        while (option is None) or element_exists(self.options_container_x_path):
            if option is None:
                if not self.options:
                    self._extract_dropdown_options()
                else:
                    self.dropdown_button.proceed()

                options = self.options
            else:
                if not option.get("children"):
                    self._extract_dropdown_options(parent_option=option)

                options = option["children"]

            answer = ApplicationField.get_field_value(
                field_category=self.category,
                user=self.parent_application_page.parent_job.user,
            )
            answer = (
                answer
                if [option for option in options if option["text"] == answer]
                else None
            )

            if answer is None:
                answer = ApplicationField.extract_field_answer(
                    job_title=self.parent_application_page.parent_job.title,
                    job_url=self.parent_application_page.url,
                    company_name=self.parent_application_page.parent_job.company,
                    question=self.title,
                    answer_type="enum",
                    options=[option["text"] for option in options],
                    parsed_resume=self.parent_application_page.parent_job.user.parsed_resume,
                )

            option = [option for option in options if option["text"] == answer][0]
            option_element = driver.find_element(By.XPATH, option["x_path"])
            option_element.click()

        self.is_component_functional = True

        return

    def _extract_dropdown_options(self, parent_option=None):
        global driver

        if not self.options_container_x_path:
            start_dom_mutation_observer()
            self.dropdown_button.proceed()
            options_container = get_observed_element()
            self.options_container_x_path = get_element_xpath(options_container)

        options = DropDown.extract_dropdown_options(
            job_title=self.parent_application_page.parent_job.title,
            job_url=self.parent_application_page.url,
            question=self.title,
            options_container_x_path=self.options_container_x_path,
        )

        if parent_option:
            parent_option["children"] = options
        else:
            self.options = options

        return

    @classmethod
    def extract_dropdown_options(
        cls, job_title, job_url, question, options_container_x_path, retry=False
    ):
        global driver

        options_container = driver.find_element(By.XPATH, options_container_x_path)

        user_prompt = (
            f"Following HTML page is job application webpage for {job_title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"There is a dropdown/menu options on this page with title as following -\n{question}\n"
            f"I am using javascript mutation observer to observer DOM changes. When I clicked the dropdown/menu options"
            f", the observer observed that following element was added to the DOM -\n"
            f"{options_container.get_attribute('outerHTML')}\n"
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
            return [
                {"text": option.text, "x_path": option.x_path} for option in options
            ]
        else:
            if not retry:
                return DropDown.extract_dropdown_options(
                    job_title=job_title,
                    job_url=job_url,
                    question=question,
                    options_container_x_path=options_container_x_path,
                    retry=True,
                )

            raise Exception(
                f"Couldn't extract dropdown fields for {job_title}. URL - {job_url}"
            )

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "x_path": self.x_path,
            "title": self.title,
            "category": self.category,
            "options": self.options,
            "options_container_x_path": self.options_container_x_path,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            title=input_dict["title"],
            category=input_dict["category"],
            parent_application_page=parent_application_page,
        )

        instance.options = input_dict["options"]
        instance.options_container_x_path = input_dict["options_container_x_path"]
        instance.is_component_functional = True

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


class ApplicationField:
    def __init__(self, parent_application_page, title, category):
        self.parent_application_page = parent_application_page
        self.title = title
        self.category = category

        self.field_type = None
        self.x_path = None

    def _identify(self, retry=False):
        global driver
        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"The webpage has following application field for applying to the job -\n"
            f"Field title - {self.title}\n"
            f"Field category - {self.category.value}\n"
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
            self.field_type = application_field.field_type.value
            self.x_path = application_field.x_path
        elif not retry:
            self._identify(retry=True)
        else:
            raise Exception(
                f"Couldn't extract following application field {self.category} for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

    def get_field_component(self):
        self._identify()

        self.field_type = self.revalidate_field_type(
            field_type=self.field_type, x_path=self.x_path, field_title=self.title
        )

        if self.field_type == "text_box":
            return TextInput(
                x_path=self.x_path,
                input_type=self.category,
                parent_application_page=self.parent_application_page,
            )
        elif self.field_type == "dropdown":
            return DropDown(
                x_path=self.x_path,
                title=self.title,
                category=self.category,
                parent_application_page=self.parent_application_page,
            )
        elif self.field_type == "search_field":
            return SearchField(
                x_path=self.x_path,
                title=self.title,
                category=self.category,
                parent_application_page=self.parent_application_page,
            )

    @classmethod
    def revalidate_field_type(cls, field_type, x_path, field_title):
        if field_type == "text_box":
            is_search_field = SearchField.validate_search_field(x_path, field_title)
            if is_search_field:
                return "search_field"

            start_dom_mutation_observer()
            element = driver.find_element(By.XPATH, x_path)
            element.click()
            observed_element = get_observed_element()
            if observed_element is None:
                return "text_box"
            else:
                simulate_empty_area_click(field_title)
                return "dropdown"

        return field_type

    @classmethod
    def get_field_value(cls, field_category, user):
        if field_category == "first_name":
            return user.first_name
        elif field_category == "last_name":
            return user.last_name
        elif field_category == "email":
            return user.email
        elif field_category == "password":
            return user.password
        elif field_category == "salutation_prefix":
            return user.parsed_resume.get("personal_details", {}).get("salutation")
        elif field_category == "phone_country_code":
            return (
                user.parsed_resume.get("personal_details", {})
                .get("phone", {})
                .get("country_code")
            )

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
