from pydantic import BaseModel, Field
from selenium.webdriver.common.by import By

from jobs.page_components import (
    PageComponent,
    ApplicationField,
    get_page_component_class_name,
)
from jobs.page_components.button import Button, logger
from utilities import constants
from utilities.gpt import get_gpt_response
from utilities.selenium import (
    get_selenium_driver,
    element_exists,
    start_dom_mutation_observer,
    get_observed_element,
    get_element_xpath,
    minify_html_for_gpt_prompt,
    simulate_empty_area_click,
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

        self.options_container_x_path = None
        self.options_xpath_pattern = None

        self.is_component_functional = False

        self.next = None
        self.prev = None

    def proceed(self, retry=False):
        global driver

        option = None
        while (option is None) or element_exists(self.options_container_x_path):
            self.dropdown_button.proceed()
            options = self._extract_dropdown_options()
            if not options:
                simulate_empty_area_click()
                continue

            answer = ApplicationField.get_field_value(
                field_category=self.category,
                user=self.parent_application_page.parent_job.user,
            )
            answer = (
                answer if [opt for opt in options if opt["text"] == answer] else None
            )

            if answer is None:
                answer = ApplicationField.extract_field_answer(
                    job_title=self.parent_application_page.parent_job.title,
                    job_url=self.parent_application_page.url,
                    company_name=self.parent_application_page.parent_job.company,
                    field_title=self.title,
                    question=self.question,
                    answer_type="enum",
                    options=[opt["text"] for opt in options],
                    parsed_resume=self.parent_application_page.parent_job.user.parsed_resume,
                )

            option = [opt for opt in options if opt["text"] == answer][0]

            # Get the clickable parent xpath for this option
            clickable_xpath = self._find_clickable_parent_xpath(
                option["x_path"], option["text"]
            )

            # Create a Button instance for the clickable element
            option_button = Button(
                x_path=clickable_xpath,
                button_type="dropdown_option",
                parent_application_page=self.parent_application_page,
            )
            option_button.proceed()

        self.is_component_functional = True
        return

    def _extract_dropdown_options(self):
        global driver

        if not self.options_container_x_path:
            simulate_empty_area_click(self.title)
            start_dom_mutation_observer()
            self.dropdown_button.proceed()
            options_container = get_observed_element()
            if not options_container:
                logger.error(
                    f"Couldn't find dropdown options container for job - "
                    f"{self.parent_application_page.parent_job.title}, url - {self.parent_application_page.url}"
                )
                return []

            self.options_container_x_path = get_element_xpath(options_container)

        if not self.options_xpath_pattern:
            self.options_xpath_pattern = DropDown.extract_options_xpath_pattern(
                job_title=self.parent_application_page.parent_job.title,
                job_url=self.parent_application_page.url,
                field_title=self.title,
                question=self.question,
                options_container_x_path=self.options_container_x_path,
            )

        return DropDown.build_options_list(self.options_xpath_pattern)

    @classmethod
    def extract_options_xpath_pattern(
        cls,
        job_title,
        job_url,
        field_title,
        options_container_x_path,
        question=None,
        retry=False,
    ):
        """Extract XPath pattern to find all dropdown options"""
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
            f"Return a single XPath pattern that will match ALL option elements in this dropdown. "
            f"The XPath pattern should:\n"
            f"1. Be usable with selenium webdriver find_elements(By.XPATH, pattern)\n"
            f"2. Not rely on HTML hierarchy\n"
            f"3. Use attributes like id, class, role, or data-* attributes instead\n"
            f"4. Return ONLY the actual clickable elements that handle option selection\n"
            f"5. For custom dropdowns, find the outermost clickable element that contains the option text\n"
            f"6. Look for elements with click handlers"
        )

        class OptionsXPath(BaseModel):
            xpath_pattern: str = Field(
                ...,
                description="XPath pattern that matches all option elements in the dropdown",
            )

        pattern_found, pattern_result = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=OptionsXPath,
        )

        if pattern_found:
            return pattern_result.xpath_pattern
        else:
            if not retry:
                return DropDown.extract_options_xpath_pattern(
                    job_title=job_title,
                    job_url=job_url,
                    field_title=field_title,
                    question=question,
                    options_container_x_path=options_container_x_path,
                    retry=True,
                )

            raise Exception(
                f"Couldn't extract dropdown options XPath for {job_title}. URL - {job_url}"
            )

    @classmethod
    def build_options_list(cls, xpath_pattern):
        """Build list of options using the XPath pattern"""
        global driver
        options = []
        option_elements = driver.find_elements(By.XPATH, xpath_pattern)
        for element in option_elements:
            options.append({"text": element.text, "x_path": get_element_xpath(element)})
        return options

    @classmethod
    def validate_observed_element_for_dropdown(
        cls, job_title, element_x_path, field_title, observed_element
    ):
        global driver

        class DropdownValidation(BaseModel):
            is_dropdown: bool = Field(
                ...,
                description="Whether the observed element is a dropdown/menu container for the clicked element",
            )

        user_prompt = (
            f"Following HTML page is job application webpage for {job_title}. "
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"There is a field with title {field_title} at XPath {element_x_path}.\n"
            f"When I clicked the field, javascript mutation observer observed that following element was added to the "
            f"DOM:\n"
            f"{observed_element.get_attribute('outerHTML')}\n"
            f"Determine if this observed element is likely to be a dropdown/menu container that appeared because "
            f"of clicking the element. Consider factors like:\n"
            f"1. Element's structure and attributes (class names, ARIA roles etc.)\n"
            f"2. Positioning and visibility attributes\n"
            f"3. Whether it contains clickable options/menu items\n"
            f"4. If the field title or similar text appears in the observed element\n"
        )

        validation_found, validation = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=DropdownValidation,
        )

        if validation_found:
            return validation.is_dropdown

        return False

    def _find_clickable_parent_xpath(self, element_xpath, original_text):
        """Find the outermost clickable parent element that maintains the same text content."""
        global driver

        element = driver.find_element(By.XPATH, element_xpath)
        target_element = element
        parent = element

        while parent:
            try:
                # Check if parent element is clickable
                if parent.is_enabled() and parent.is_displayed():
                    # Verify text hasn't changed
                    if parent.text == original_text:
                        target_element = parent
                    else:
                        break

                # Try next parent
                parent = parent.find_element(By.XPATH, "./..")
            except:
                break

        return get_element_xpath(target_element)

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "x_path": self.x_path,
            "title": self.title,
            "question": self.question,
            "category": self.category,
            "options_xpath_pattern": self.options_xpath_pattern,
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

        instance.options_container_x_path = input_dict["options_container_x_path"]
        instance.options_xpath_pattern = input_dict["options_xpath_pattern"]
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
