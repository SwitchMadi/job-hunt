from pydantic import BaseModel, Field
from selenium.webdriver.common.by import By

from jobs.page_components import (
    PageComponent,
    ApplicationField,
    get_page_component_class_name,
)
from jobs.page_components.button import Button, logger
from utilities import minify_html_for_gpt_prompt, constants
from utilities.gpt import get_gpt_response
from utilities.selenium import (
    get_selenium_driver,
    element_exists,
    start_dom_mutation_observer,
    get_observed_element,
    get_element_xpath,
)


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class DropDown(PageComponent):
    def __init__(self, x_path, title, question, category, parent_application_page):
        self.x_path = x_path
        self.title = title
        self.question = question
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

    def proceed(self, retry=False):
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
                    field_title=self.title,
                    question=self.question,
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
            field_title=self.title,
            question=self.question,
            options_container_x_path=self.options_container_x_path,
        )

        if parent_option:
            parent_option["children"] = options
            logger.info(
                f"Updating dropdown field options in db for job - "
                f"{self.parent_application_page.parent_job.title}, url - {self.parent_application_page.url}"
            )
            self.parent_application_page.save_application_steps()
        else:
            self.options = options

        return

    @classmethod
    def extract_dropdown_options(
        cls,
        job_title,
        job_url,
        field_title,
        options_container_x_path,
        question=None,
        retry=False,
    ):
        global driver

        options_container = driver.find_element(By.XPATH, options_container_x_path)

        if question:
            question_prompt = (
                f"There is a dropdown/menu options on this page asking following question under the "
                f"title {field_title}\nQuestion - {question}"
            )
        else:
            question_prompt = f"There is a dropdown/menu options on this page with title as following -\n{field_title}"

        user_prompt = (
            f"Following HTML page is job application webpage for {job_title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"{question_prompt}\n"
            f"I am using javascript mutation observer to observe DOM changes. When I clicked the dropdown/menu options"
            f", the observer observed that following element was added to the DOM -\n"
            f"{options_container.get_attribute('outerHTML')}\n"
            f"Extract all options available in dropdown menu."
        )

        class Option(BaseModel):
            text: str = Field(..., description="Text shown in the dropdown option")
            x_path: str = Field(
                ...,
                description="XPath of the option which can be used in selenium chrome driver to "
                "search the option. Don't use HTML hierarchy to construct XPath.",
            )

        class DropdownOptions(BaseModel):
            options: list[Option]

        options_found, options = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=DropdownOptions,
        )
        if options_found:
            return [
                {"text": option.text, "x_path": option.x_path}
                for option in options.options
            ]
        else:
            if not retry:
                return DropDown.extract_dropdown_options(
                    job_title=job_title,
                    job_url=job_url,
                    field_title=field_title,
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
            "question": self.question,
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
            question=input_dict["question"],
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
