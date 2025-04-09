from selenium.webdriver.common.by import By

from jobs import ApplicationField
from jobs.page_components import PageComponent, get_page_component_class_name
from utilities.selenium import get_selenium_driver


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

        answers = ApplicationField.extract_field_answer(
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
            option_element = driver.find_element(By.XPATH, option["x_path"])
            option_element.click()

        self.is_component_functional = True
        return

    @classmethod
    def validate_checkbox(cls, options):
        multiple_correct = False

        if len(options) <= 1:
            return multiple_correct

        option_1 = driver.find_element(By.XPATH, options[0]["x_path"])
        option_1.click()

        option_2 = driver.find_element(By.XPATH, options[1]["x_path"])
        option_2.click()

        if option_1.is_selected() and option_2.is_selected():
            multiple_correct = True

        return multiple_correct

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
