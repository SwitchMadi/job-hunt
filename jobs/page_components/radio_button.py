from selenium.webdriver.common.by import By

from jobs import ApplicationField
from jobs.page_components import PageComponent, get_page_component_class_name
from jobs.page_components.button import Button
from utilities.selenium import (
    get_selenium_driver,
    get_unique_element_by_xpath,
    get_element_xpath,
)


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class RadioButton(PageComponent):
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
        answer = ApplicationField.get_field_value(
            field_category=self.category,
            user=self.parent_application_page.parent_job.user,
        )
        answer = (
            answer
            if [option for option in self.options if option["text"] == answer]
            else None
        )

        if answer is None:
            answer, _ = ApplicationField.extract_field_answer(
                job_title=self.parent_application_page.parent_job.title,
                job_url=self.parent_application_page.url,
                company_name=self.parent_application_page.parent_job.company,
                field_title=self.title,
                question=self.question,
                answer_type="enum",
                options=[option["text"] for option in self.options],
                parsed_resume=self.parent_application_page.parent_job.user.parsed_resume,
            )

        option = [option for option in self.options if option["text"] == answer][0]

        option_element = get_unique_element_by_xpath(option["x_path"], self.title)
        if (
            option_element.tag_name == "input"
            and option_element.get_attribute("type") == "radio"
            and option_element.is_selected()
        ):
            pass
        else:
            option_element = Button(
                x_path=get_element_xpath(option_element),
                button_type="radio",
                parent_application_page=None,
            )
            option_element.proceed()

        # store the response
        if self.parent_application_page:
            self.parent_application_page.save_field_response(
                question=self.question,
                response=option["text"],
            )

        self.is_component_functional = True
        return

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
