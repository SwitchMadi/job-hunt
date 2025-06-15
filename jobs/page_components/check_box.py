from pydantic import BaseModel, Field

from jobs import ApplicationField
from jobs.page_components import PageComponent, get_page_component_class_name
from jobs.page_components.button import Button
from utilities.selenium import (
    get_selenium_driver,
    get_unique_element_by_xpath,
    get_element_xpath,
    find_input_block_for_title,
    minify_html_for_gpt_prompt,
)
from utilities import constants
from utilities.gpt import get_gpt_response


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class CheckBox(PageComponent):
    def __init__(
        self, x_path, title, question, category, options, parent_application_page
    ):
        self.x_path = x_path
        self.title = title
        self.question = question
        self.category = category
        self.options = options
        self.parent_application_page = parent_application_page

        self.is_component_functional = False

        self.next = None
        self.prev = None

    def proceed(self, retry=False):
        info = ApplicationField.get_field_value(
            field_category=self.category,
            user=self.parent_application_page.parent_job.user,
        )

        answers, _ = ApplicationField.extract_field_answer(
            job_title=self.parent_application_page.parent_job.title,
            job_url=self.parent_application_page.url,
            company_name=self.parent_application_page.parent_job.company,
            field_title=self.title,
            question=self.question,
            answer_type="enum",
            multiple_correct=True,
            options=[option["text"] for option in self.options],
            closest_answer=info if info else None,
            parsed_resume=self.parent_application_page.parent_job.user.parsed_resume,
        )
        options_to_select = [
            option for option in self.options if option["text"] in answers
        ]

        for option in options_to_select:
            option_element = get_unique_element_by_xpath(option["x_path"], self.title)
            if (
                (option_element.tag_name == "input")
                and (option_element.get_attribute("type") == "checkbox")
                and option_element.is_selected()
            ):
                continue

            option_element = Button(
                x_path=get_element_xpath(option_element),
                button_type="checkbox",
                parent_application_page=None,
            )
            option_element.proceed()

        self.is_component_functional = True
        return

    @classmethod
    def validate_checkbox(cls, options, title):
        multiple_correct = False

        # If there are no options or only one option, we can consider it valid
        if len(options) <= 1:
            return True

        option_1 = get_unique_element_by_xpath(xpath=options[0]["x_path"], title=title)
        if not option_1:
            raise Exception(
                f"Unique element not found for x_path - {options[0]['x_path']}"
            )

        if (
            option_1.tag_name == "input"
            and option_1.get_attribute("type") == "checkbox"
        ):
            driver.execute_script("arguments[0].checked = false;", option_1)
        else:
            return cls._validate_checkbox_using_llm(title)

        option_button_1 = Button(
            x_path=get_element_xpath(option_1),
            button_type="checkbox",
            parent_application_page=None,
        )
        option_button_1.proceed()

        option_2 = get_unique_element_by_xpath(xpath=options[1]["x_path"], title=title)
        if not option_2:
            raise Exception(
                f"Unique element not found for x_path - {options[1]['x_path']}"
            )
        driver.execute_script("arguments[0].checked = false;", option_2)

        option_button_2 = Button(
            x_path=get_element_xpath(option_2),
            button_type="checkbox",
            parent_application_page=None,
        )
        option_button_2.proceed()

        if option_1.is_selected() and option_2.is_selected():
            multiple_correct = True

        driver.execute_script("arguments[0].checked = false;", option_1)
        driver.execute_script("arguments[0].checked = false;", option_2)

        return multiple_correct

    @staticmethod
    def _validate_checkbox_using_llm(title):
        global driver

        element_identified, user_input_element = find_input_block_for_title(title)
        if user_input_element:
            minified_html = minify_html_for_gpt_prompt(
                user_input_element.get_attribute("outerHTML")
            )
        else:
            minified_html = minify_html_for_gpt_prompt(driver.page_source)

        user_prompt = (
            f"Following HTML is of job application webpage."
            f"HTML: {minified_html}\n"
            f"The webpage has following application field for applying to the job -\n"
            f"Field title - {title}\n"
            f"Please asses the HTML and determine if the field has possibility multiple correct answers or it can have "
            f"just 1 correct answer.\n"
        )

        class ApplicationFieldInfo(BaseModel):
            is_multiple_correct_answers_field: bool = Field(
                ...,
                description="Can the field can have multiple correct answers?",
            )

        checkbox_validation_done, checkbox_validation = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=ApplicationFieldInfo,
        )
        if checkbox_validation_done:
            return checkbox_validation.is_multiple_correct_answers_field
        else:
            return False

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "x_path": self.x_path,
            "title": self.title,
            "question": self.question,
            "category": self.category,
            "options": self.options,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            title=input_dict["title"],
            question=input_dict["question"],
            category=input_dict["category"],
            options=input_dict["options"],
            parent_application_page=parent_application_page,
        )

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
