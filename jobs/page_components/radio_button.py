from selenium.webdriver.common.by import By

from jobs import ApplicationField
from jobs.page_components import PageComponent, get_page_component_class_name, logger
from jobs.page_components.button import Button
from utilities.selenium import (
    get_selenium_driver,
    get_unique_element_by_xpath,
    get_element_xpath,
    element_exists,
)
from utilities import remove_emoji


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class RadioButton(PageComponent):
    def __init__(
        self,
        x_path,
        title,
        question,
        category,
        options_container_x_path,
        options_xpath_pattern,
        parent_application_page,
    ):
        self.options = []
        self.x_path = x_path
        self.title = title
        self.question = question
        self.category = category
        self.options_container_x_path = options_container_x_path
        self.options_xpath_pattern = options_xpath_pattern
        self.parent_application_page = parent_application_page

        self.is_component_functional = False

        self.next = None
        self.prev = None

    def _build_options_list(self):
        """Build options list from XPath pattern, scoped to container"""
        global driver

        if not self.options_xpath_pattern:
            logger.warning(f"No options_xpath_pattern provided for {self.title}")
            return []

        if not self.options_container_x_path:
            logger.warning(f"No options_container_x_path provided for {self.title}")
            return []

        if not element_exists(self.options_container_x_path):
            logger.warning(
                f"Container XPath {self.options_container_x_path} not found for {self.title}"
            )
            return []

        output_options = []
        option_texts = []

        # Pattern must always be scoped to container
        container_element = driver.find_element(By.XPATH, self.options_container_x_path)
        options = container_element.find_elements(By.XPATH, self.options_xpath_pattern)

        logger.info(
            f"Found {len(options)} options using pattern {self.options_xpath_pattern} within container {self.options_container_x_path}"
        )

        for option in options:
            clean_text = remove_emoji(option.text)
            if clean_text and clean_text not in option_texts:
                output_options.append(
                    {"text": clean_text, "x_path": get_element_xpath(option)}
                )
                option_texts.append(clean_text)

        logger.info(
            f"Completed building options list: {len(output_options)} total options for {self.title}"
        )
        return output_options

    def proceed(self, retry=False):
        # Build options list from pattern
        self.options = self._build_options_list()

        if not self.options:
            logger.warning(f"No options found for {self.title}")
            return
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
            "options_container_x_path": self.options_container_x_path,
            "options_xpath_pattern": self.options_xpath_pattern,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            title=input_dict["title"],
            question=input_dict["question"],
            category=input_dict["category"],
            options_container_x_path=input_dict.get("options_container_x_path"),
            options_xpath_pattern=input_dict.get("options_xpath_pattern"),
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
