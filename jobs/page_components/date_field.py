from selenium.webdriver.common.by import By
from pydantic import BaseModel, Field
from typing import Optional

from jobs import ApplicationField
from jobs.page_components import PageComponent, logger, get_page_component_class_name
from utilities.selenium import (
    get_selenium_driver,
    clear_text_field,
    simulate_typing,
    simulate_empty_area_click,
    start_dom_mutation_observer,
    get_observed_element,
)
from utilities import minify_html_for_gpt_prompt, constants
from utilities.gpt import get_gpt_response


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class DateField(PageComponent):
    def __init__(
        self,
        x_path,
        title,
        question,
        date_format,
        category,
        parent_application_page,
        input_text=None,
        persist_question=True,
    ):
        global driver
        self.x_path = x_path
        self.title = title
        self.question = question
        self.date_format = date_format
        self.category = category
        self.parent_application_page = parent_application_page
        self._answer = input_text
        self.persist_question = persist_question

        self.is_component_functional = False

        self.next = None
        self.prev = None

    def proceed(self):
        global driver

        if not self.date_format:
            self._identify_date_format()

        try:
            element = driver.find_element(By.XPATH, self.x_path)
            clear_text_field(self.x_path)
            element.send_keys(self.answer)

            current_value = element.get_attribute("value")
            if current_value != self.answer:
                date_filled = simulate_typing(self.x_path, self.answer)
            else:
                date_filled = True

            if not date_filled:
                logger.exception(
                    f"Could not fill date in DateField component. DateField instance - {vars(self)}"
                )
            else:
                self.is_component_functional = True

            simulate_empty_area_click(text_to_click=self.title)
        except Exception as e:
            logger.exception(
                f"Unexpected error occurred in class DateField's proceed method.\n{e}\n"
                f"DateField instance - {vars(self)}"
            )

        return

    def _identify_date_format(self):
        date_field = driver.find_element(By.XPATH, self.x_path)

        start_dom_mutation_observer()
        date_field.click()
        observed_element = get_observed_element()

        if not observed_element:
            date_picker_x_path = self._identify_calendar_button()
        else:
            date_picker_x_path = self.x_path
            simulate_empty_area_click(text_to_click=self.title)

        if date_picker_x_path:
            self._select_date(date_picker_x_path)

            date_field = driver.find_element(By.XPATH, self.x_path)
            current_value = date_field.get_attribute("value")

            if current_value:
                self.date_format = current_value
                return

        raise Exception(
            f"Couldn't extract date format for {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}"
        )

    def _identify_calendar_button(self, retry=False):
        global driver

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"I have to enter date in following date field -\n"
            f"Field title - {self.title}\n"
            f"Field XPath - {self.question}\n"
            f"In order to do that I need to click open date picker and choose my date. Give me XPath of calendar / date"
            f" picker button if there is any. If there is no such button then don't return anything."
        )

        class DatePicker(BaseModel):
            x_path: Optional[str] = Field(
                ..., description="XPath of the date picker / calendar widget"
            )

        date_picker_found, date_picker = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=DatePicker,
        )
        if date_picker_found:
            return date_picker.x_path
        else:
            if not retry:
                return self._identify_calendar_button(retry=True)

            raise Exception(
                f"Couldn't extract calendar button for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )

    def _select_date(self, date_picker_x_path, retry=False):
        global driver

        date_picker_button = driver.find_element(By.XPATH, date_picker_x_path)

        start_dom_mutation_observer()
        date_picker_button.click()
        date_picker = get_observed_element()

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"I have to enter date in following date field -\n"
            f"Field title - {self.title}\n"
            f"Field XPath - {self.question}\n"
            f"Date picker button XPath - {date_picker_x_path}\n"
            f"In order to do that I need to click open the date picker and choose my date. I am using javascript "
            f"mutation observer to observer DOM changes. When I clicked the date picker button"
            f", the observer observed that following element was added to the DOM -\n"
            f"{date_picker.get_attribute('outerHTML')}\n"
            f"I need to select 27th date of the month currently visible in the date picker. Give me XPath of the button"
            f" clicking which I can select 27th."
        )

        class Date(BaseModel):
            x_path: str = Field(
                ...,
                description="XPath of the 27th date of the month currently visible in the date picker which can be used"
                " in selenium chrome driver to search the 27th date. Don't use HTML hierarchy to construct "
                "XPath.",
            )

        date_found, date = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=Date,
        )
        if date_found:
            date = driver.find_element(By.XPATH, date.x_path)
            date.click()
            return
        else:
            if not retry:
                return self._select_date(date_picker_x_path, retry=True)

            raise Exception(
                f"Couldn't extract 27th date button for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )

    def to_dict(self):
        output = {
            "class": self.__class__.__name__,
            "x_path": self.x_path,
            "title": self.title,
            "date_format": self.date_format,
            "category": self.category,
            "next": self.next.to_dict() if self.next else None,
        }
        if self.persist_question:
            output["question"] = self.question

        return output

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            title=input_dict["title"],
            question=input_dict.get("question"),
            date_format=input_dict["date_format"],
            category=input_dict["category"],
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

    @property
    def answer(self):
        if self._answer is not None:
            return self._answer

        answer = ApplicationField.get_field_value(
            field_category=self.category,
            user=self.parent_application_page.parent_job.user,
        )
        answer = ApplicationField.extract_field_answer(
            job_title=self.parent_application_page.parent_job.title,
            job_url=self.parent_application_page.url,
            company_name=self.parent_application_page.parent_job.company,
            field_title=self.title or self.category,
            question=self.question,
            answer_format=self.date_format,
            answer_type="text",
            closest_answer=answer,
            parsed_resume=self.parent_application_page.parent_job.user.parsed_resume,
        )

        self._answer = answer
        return self._answer
