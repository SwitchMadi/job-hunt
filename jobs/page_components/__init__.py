from abc import ABC, abstractmethod
from selenium.webdriver.common.by import By
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional

from jobs.page_components import SearchField
from jobs.page_components.button import Button
from jobs.page_components.drop_down import DropDown
from jobs.page_components.search_field import SearchField
from jobs.page_components.text_input import TextInput
from utilities.selenium import (
    get_selenium_driver,
    start_dom_mutation_observer,
    get_observed_element,
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
                category=self.category,
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
