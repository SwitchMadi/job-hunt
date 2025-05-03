from abc import ABC, abstractmethod
from selenium.webdriver.common.by import By
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, List

from utilities.selenium import (
    get_selenium_driver,
    start_dom_mutation_observer,
    get_observed_element,
    simulate_empty_area_click,
    element_exists,
    minify_html_for_gpt_prompt,
)
from utilities.logging import get_logger
from utilities import pascal_to_snake_casing
from utilities import constants
from utilities.gpt import get_gpt_response


logger = get_logger(name="job")
driver = get_selenium_driver()
driver.set_page_load_timeout(15)


def get_page_component_class_name(class_name):
    module_name = pascal_to_snake_casing(class_name)
    if class_name == "VerifyAccount":
        module_name = "login"
    elif class_name == "WorkExperience":
        module_name = "work_experience_section"
    elif class_name == "Education":
        module_name = "education_section"

    try:
        return globals()[class_name]
    except KeyError:
        return eval(f'globals()["{module_name}"].{class_name}')


class PageComponent(ABC):
    @abstractmethod
    def proceed(self, retry=False):
        pass

    @abstractmethod
    def to_dict(self):
        pass

    @abstractmethod
    def from_dict(self, input_dict, parent_application_page):
        pass


class ApplicationField:
    def __init__(self, parent_application_page, title, question, category):
        self.parent_application_page = parent_application_page
        self.title = title
        self.question = question
        self.category = category

        self.x_path = None
        self.field_type = None
        self.html_type = None
        self.format = None
        self.options = []

    def _identify(self, retry=False, prev_x_path=None):
        global driver
        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"The webpage has following application field for applying to the job -\n"
            f"Field title - {self.title}\n"
            f"Field category - {self.category}\n"
            f"Analyse the whole HTML very carefully for extracting XPath and other info of the application field."
        )

        if retry and prev_x_path:
            user_prompt += (
                f"\n\nIn previous try you gave following x_path and the element couldn't be found using that. So, find "
                f"correct x_path for the same field.\n"
                f"Previous x_path - {prev_x_path}\n"
            )

        class FieldHtmlType(Enum):
            textBox = "text_box"
            checkBox = "check_box"
            radioButton = "radio_button"
            dropdown = "dropdown"
            button = "button"

        class FieldType(Enum):
            addButton = "add_button"
            upload = "upload"
            date = "date"
            expand = "expand"
            collapse = "collapse"
            text_field = "text_field"
            multiple_choice = "multiple_choice"
            other = "other"

        class Option(BaseModel):
            text: str = Field(
                ..., description="Text of the checkbox / radio button option"
            )
            x_path: str = Field(
                ...,
                description="XPath of the checkbox / radio button which can be used in selenium "
                "chrome driver to search the checkbox / radio button. Don't use HTML "
                "hierarchy to construct XPath.",
            )

        class ApplicationFieldInfo(BaseModel):
            x_path: str = Field(
                ...,
                description="XPath of the application field which can be used in selenium chrome driver to search the "
                "application field. Don't use HTML hierarchy to construct XPath. XPath of the first field "
                "if there are many.",
            )
            field_type: FieldType = Field(
                ...,
                description="Application sub-field type like date, addButton, upload etc.",
            )
            html_type: FieldHtmlType = Field(
                ...,
                description="Application field html type like textbox, checkbox, dropdown etc.",
            )
            options: Optional[List[Option]] = Field(
                ...,
                description="Options to select from if the field_type is either checkbox or radio button",
            )
            format: Optional[str] = Field(
                ...,
                description="Format of field answer if the field requires its answer to be in some specific format. "
                "e.g. date format etc.",
            )

        application_field_found, application_field = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=ApplicationFieldInfo,
        )
        if application_field_found:
            if not element_exists(application_field.x_path):
                if not retry:
                    return self._identify(
                        retry=True, prev_x_path=application_field.x_path
                    )
                else:
                    return

            if self.parent_application_page.component_x_path_exists(
                application_field.x_path
            ):
                logger.warn(
                    f"Page component with following x_path already exists - {application_field.x_path}"
                )
                return

            self.x_path = application_field.x_path
            self.field_type = application_field.field_type.value
            self.html_type = application_field.html_type.value
            self.format = application_field.format

            if application_field.options:
                self.options = [
                    {"text": option.text, "x_path": option.x_path}
                    for option in application_field.options
                ]
        elif not retry:
            self._identify(retry=True)
        else:
            raise Exception(
                f"Couldn't extract following application field {self.category} for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

    def get_field_component(self):
        self._identify()

        if self.x_path:
            self.html_type = ApplicationField.revalidate_component_type(
                x_path=self.x_path,
                html_type=self.html_type,
                field_title=self.title,
                job_title=self.parent_application_page.parent_job.title,
                options=self.options,
            )

            if self.html_type == "text_box":
                from jobs.page_components.text_input import TextInput

                return TextInput(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    parent_application_page=self.parent_application_page,
                )
            elif self.html_type == "dropdown":
                from jobs.page_components.drop_down import DropDown

                return DropDown(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    parent_application_page=self.parent_application_page,
                )
            elif self.html_type == "search_field":
                from jobs.page_components.search_field import SearchField

                return SearchField(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    parent_application_page=self.parent_application_page,
                )
            elif self.html_type == "radio_button":
                from jobs.page_components.radio_button import RadioButton

                return RadioButton(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    options=self.options,
                    parent_application_page=self.parent_application_page,
                )
            elif self.html_type == "check_box":
                from jobs.page_components.check_box import CheckBox

                return CheckBox(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    options=self.options,
                    parent_application_page=self.parent_application_page,
                )
        else:
            logger.warn(
                f"Working Xpath couldn't be extracted.\nInstance - {vars(self)}"
            )

    @classmethod
    def revalidate_component_type(
        cls, x_path, html_type, field_title, job_title, options=[]
    ):
        if html_type == "text_box":
            from jobs.page_components.search_field import SearchField

            is_search_field = SearchField.validate_search_field(x_path, field_title)
            if is_search_field:
                return "search_field"

            start_dom_mutation_observer()
            element = driver.find_element(By.XPATH, x_path)
            element.click()
            observed_element = get_observed_element()

            if observed_element:
                from jobs.page_components.drop_down import DropDown

                is_observed_element_dropdown = (
                    DropDown.validate_observed_element_for_dropdown(
                        job_title=job_title,
                        element_x_path=x_path,
                        field_title=field_title,
                        observed_element=observed_element,
                    )
                )
                if is_observed_element_dropdown:
                    simulate_empty_area_click(field_title)
                    return "dropdown"

            return "text_box"

        elif html_type == "check_box":
            from jobs.page_components.check_box import CheckBox

            multiple_correct = CheckBox.validate_checkbox(options)
            if not multiple_correct:
                return "radio_button"

        return html_type

    @classmethod
    def get_field_value(cls, field_category, user):
        if field_category == "first_name":
            return user.first_name
        elif field_category == "last_name":
            return user.last_name
        elif field_category == "full_name":
            return user.name
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
        elif field_category.startswith("job_title"):
            experience_no = int(field_category.split("__")[-1])
            work_info = user.parsed_resume.get("work_experience", [])
            if experience_no < len(work_info):
                work_info = work_info[experience_no - 1]
                return work_info.get("job_title")

        elif field_category.startswith("company_name"):
            experience_no = int(field_category.split("__")[-1])
            work_info = user.parsed_resume.get("work_experience", [])
            if experience_no < len(work_info):
                work_info = work_info[experience_no - 1]
                return work_info.get("company_name")

        elif field_category.startswith("location"):
            experience_no = int(field_category.split("__")[-1])
            work_info = user.parsed_resume.get("work_experience", [])
            if experience_no < len(work_info):
                work_info = work_info[experience_no - 1]
                return work_info.get("location")

        elif field_category.startswith("start_date"):
            experience_no = int(field_category.split("__")[-1])
            work_info = user.parsed_resume.get("work_experience", [])
            if experience_no < len(work_info):
                work_info = work_info[experience_no - 1]
                return work_info.get("start_date")

        elif field_category.startswith("end_date"):
            experience_no = int(field_category.split("__")[-1])
            work_info = user.parsed_resume.get("work_experience", [])
            if experience_no < len(work_info):
                work_info = work_info[experience_no - 1]
                return work_info.get("end_date")

        elif field_category.startswith("responsibilities"):
            experience_no = int(field_category.split("__")[-1])
            work_info = user.parsed_resume.get("work_experience", [])
            if experience_no < len(work_info):
                work_info = work_info[experience_no - 1]
                return work_info.get("responsibilities")

        elif field_category.startswith("achievements"):
            experience_no = int(field_category.split("__")[-1])
            work_info = user.parsed_resume.get("work_experience", [])
            if experience_no < len(work_info):
                work_info = work_info[experience_no - 1]
                return work_info.get("achievements")

        elif field_category.startswith("experience_related_url"):
            experience_no = int(field_category.split("__")[-1])
            work_info = user.parsed_resume.get("work_experience", [])
            if experience_no < len(work_info):
                work_info = work_info[experience_no - 1]
                return work_info.get("experience_related_url")

        elif field_category.startswith("industry"):
            experience_no = int(field_category.split("__")[-1])
            work_info = user.parsed_resume.get("work_experience", [])
            if experience_no < len(work_info):
                work_info = work_info[experience_no - 1]
                return work_info.get("industry")

        elif field_category.startswith("employment_type"):
            experience_no = int(field_category.split("__")[-1])
            work_info = user.parsed_resume.get("work_experience", [])
            if experience_no < len(work_info):
                work_info = work_info[experience_no - 1]
                return work_info.get("employment_type")

        return None

    @classmethod
    def extract_field_answer(
        cls,
        job_title,
        job_url,
        company_name,
        field_title,
        answer_type,
        question=None,
        multiple_correct=False,
        closest_answer=None,
        answer_format=None,
        options=[],
        parsed_resume=None,
    ):
        if question:
            user_prompt = (
                f"While filling job application for {job_title} at a company called "
                f"{company_name}, I need you to help me answer following question under the field title - {field_title}"
                f"\nQuestion - {question}\n"
            )
        else:
            question = field_title
            user_prompt = (
                f"While filling job application for {job_title} at a company called "
                f"{company_name}, I need you to help me answer following question (field title) -\n{question}\n"
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

            if multiple_correct:

                class FieldAnswer(BaseModel):
                    answers: List[FieldAnswerOptions] = Field(
                        ...,
                        description="Correct options based on input",
                    )

            else:

                class FieldAnswer(BaseModel):
                    answer: FieldAnswerOptions = Field(
                        ...,
                        description="Correct option based on input",
                    )

        elif answer_type == "text":
            user_prompt += (
                f"Answer should be precise and as short as you can write. Be very careful about following -\n"
                f"If field title is very short like one word or two then answer should also be of similar length. If "
                f"field title seems to be expecting bit elaborative answer then answer can be little verbose but not "
                f"too much. Also answer should reflect that these are my words, not Chat GPT's words. Answer like human"
                f" candidate and not a language model. I am going to feed your answer exactly same into the job "
                f"application so answer accordingly. If based on the given context there is no answer then don't "
                f"answer the question at all.\n"
            )

            if answer_format:
                user_prompt += (
                    f"Answer should strictly be in following format with no extra text except for what is "
                    f"mentioned in the format. Format - {answer_format}\n"
                )

                class FieldAnswer(BaseModel):
                    answer: Optional[str] = Field(
                        ...,
                        description=f"Correct answer based on user data. Answer should be precise and as short as you "
                        f"can write. Answer should strictly be in following format with no extra text "
                        f"except for what is mentioned in the format. Format - {answer_format}",
                    )

            else:

                class FieldAnswer(BaseModel):
                    answer: Optional[str] = Field(
                        ...,
                        description="Correct answer based on user data. Answer should be precise and as short as you "
                        "can write. Also answer should reflect that these are my words, not Chat GPT's "
                        "words.",
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
            if answer_type == "text":
                return field_answer.answer
            elif multiple_correct:
                return [answer.value for answer in field_answer.answers]
            else:
                return field_answer.answer.value
        else:
            logger.error(
                f"Couldn't extract field answer for {job_title}. URL - {job_url}"
            )
            return None
