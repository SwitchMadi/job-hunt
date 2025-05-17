from selenium.webdriver import Keys
from selenium.webdriver.common.by import By

from jobs import ApplicationField
from jobs.page_components import PageComponent, logger, get_page_component_class_name
from utilities.selenium import get_selenium_driver, clear_text_field


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class TextInput(PageComponent):
    def __init__(
        self,
        x_path,
        category,
        parent_application_page,
        title=None,
        question=None,
        hit_enter=False,
    ):
        global driver

        self.x_path = x_path
        self.title = title
        self.question = question
        self.category = category
        self.hit_enter = hit_enter
        self.parent_application_page = parent_application_page

        self._answer = None
        self.is_component_functional = False

        self.next = None
        self.prev = None

    def proceed(self, retry=False):
        global driver

        try:
            if not self.answer:
                return

            element = driver.find_element(By.XPATH, self.x_path)
            if self.category == "otp_textbox":
                element.click()
                for otp_digit in str(self.answer):
                    active_element = driver.switch_to.active_element
                    active_element.send_keys(f"{otp_digit}")
            else:
                clear_text_field(self.x_path)
                element.send_keys(self.answer)

                # Force check and set value if needed
                actual_value = element.get_attribute("value")
                if actual_value.strip().lower() != str(self.answer).strip().lower():
                    # Force set using JavaScript if value doesn't match
                    driver.execute_script(
                        "arguments[0].value = arguments[1]; "
                        "arguments[0].dispatchEvent(new Event('input', { bubbles: true })); "
                        "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
                        element,
                        str(self.answer),
                    )

            if self.hit_enter:
                element.send_keys(Keys.RETURN)

            self.is_component_functional = True
        except Exception as e:
            logger.exception(
                f"Unexpected error occurred in class TextInput's proceed method.\n{e}\n"
                f"TextInput instance - {vars(self)}"
            )
            raise e

        return

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "x_path": self.x_path,
            "category": self.category,
            "title": self.title,
            "question": self.question,
            "hit_enter": self.hit_enter,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            category=input_dict["category"],
            title=input_dict["title"],
            question=input_dict["question"],
            hit_enter=input_dict["hit_enter"],
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
                field_title=self.title or self.category,
                question=self.question,
                answer_type="text",
                parsed_resume=self.parent_application_page.parent_job.user.parsed_resume,
            )

        self._answer = answer
        return self._answer

    @answer.setter
    def answer(self, value):
        self._answer = value
