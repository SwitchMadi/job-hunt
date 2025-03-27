from selenium.webdriver import Keys
from selenium.webdriver.common.by import By

from jobs import ApplicationField
from jobs.page_components import PageComponent, logger, get_page_component_class_name
from utilities.selenium import get_selenium_driver


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class TextInput(PageComponent):
    def __init__(
        self,
        x_path,
        category,
        parent_application_page,
        input_text=None,
    ):
        global driver
        self.x_path = x_path
        self.category = category
        self._answer = input_text
        self.parent_application_page = parent_application_page

        self.is_component_functional = True

        self.next = None
        self.prev = None

    def proceed(self):
        global driver

        try:
            element = driver.find_element(By.XPATH, self.x_path)
            if self.category == "otp_textbox":
                element.click()
                for otp_digit in str(self.answer):
                    active_element = driver.switch_to.active_element
                    active_element.send_keys(f"{otp_digit}")
            else:
                element.send_keys(self.answer)
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
            "category": self.category,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
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
        if not answer:
            answer = ApplicationField.extract_field_answer(
                job_title=self.parent_application_page.parent_job.title,
                job_url=self.parent_application_page.url,
                company_name=self.parent_application_page.parent_job.company,
                question=self.category,
                answer_type="text",
                parsed_resume=self.parent_application_page.parent_job.user.parsed_resume,
            )

        self._answer = answer
        return self._answer
