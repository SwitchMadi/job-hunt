from pydantic import BaseModel, Field
from selenium.webdriver.common.by import By

from jobs import ApplicationField
from jobs.page_components import PageComponent, get_page_component_class_name, logger
from jobs.page_components.button import Button
from utilities.selenium import (
    get_selenium_driver,
    get_unique_element_by_xpath,
    get_element_xpath,
    find_input_block_for_title,
    minify_html_for_gpt_prompt,
    element_exists,
)
from utilities import constants, remove_emoji
from utilities.llm import create_llm_service

_llm_service = create_llm_service(provider="openai")


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class CheckBox(PageComponent):
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
        self.is_boolean = False
        self.container_x_path = None

        self.next = None
        self.prev = None

    @property
    def is_checked(self):
        """Check if the boolean checkbox is currently selected. Only works for boolean type."""
        global driver

        if not self.is_boolean:
            logger.warning(
                f"is_checked property is only applicable for boolean checkboxes. "
                f"Field {self.title} is not a boolean checkbox."
            )
            return None

        if not self.options_container_x_path or not self.options_xpath_pattern:
            logger.warning(
                f"Container or pattern XPath missing for boolean question {self.title}"
            )
            return None

        if not element_exists(self.options_container_x_path):
            logger.warning(
                f"Container XPath {self.options_container_x_path} not found for {self.title}"
            )
            return None

        container_element = driver.find_element(By.XPATH, self.options_container_x_path)
        option_elements = container_element.find_elements(
            By.XPATH, self.options_xpath_pattern
        )

        if not option_elements:
            logger.warning(
                f"No option elements found using pattern {self.options_xpath_pattern} for {self.title}"
            )
            return None

        checkbox_element = option_elements[0]
        return (
            checkbox_element.tag_name == "input"
            and checkbox_element.get_attribute("type") == "checkbox"
            and checkbox_element.is_selected()
        )

    def _find_text_containing_parent(
        self, option_element, all_option_elements, container_element
    ):
        """
        Traverse up the DOM from option element to find the highest parent that:
        1. Has non-empty text
        2. Doesn't contain other option elements (stop when other options become visible)

        Args:
            option_element: The option element to start from
            all_option_elements: List of all option elements found by the pattern
            container_element: The container element (stop traversing if we reach this)

        Returns:
            The parent element with text, or the option element itself if no suitable parent found
        """
        global driver
        current = option_element
        best_parent = option_element

        while current:
            try:
                # Check if we've reached the container (stop traversing)
                if current == container_element:
                    break

                # Get parent
                try:
                    parent = current.find_element(By.XPATH, "./..")
                except:
                    break

                # Check if parent has text
                parent_text = parent.text.strip() if hasattr(parent, "text") else ""

                if parent_text:
                    # Check if other options have become visible in this parent
                    other_options_visible = False
                    for other_option in all_option_elements:
                        if other_option != option_element:
                            # Check if other_option is within parent's subtree
                            try:
                                is_contained = driver.execute_script(
                                    "return arguments[0].contains(arguments[1]);",
                                    parent,
                                    other_option,
                                )
                                if is_contained:
                                    other_options_visible = True
                                    break
                            except:
                                pass

                    # If other options are visible, we've gone too high - stop here
                    if other_options_visible:
                        break

                    # This parent has text and doesn't show other options yet - use it
                    best_parent = parent

                current = parent
            except:
                break

        return best_parent

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
        option_elements = container_element.find_elements(
            By.XPATH, self.options_xpath_pattern
        )

        logger.info(
            f"Found {len(option_elements)} option elements using pattern {self.options_xpath_pattern} within container {self.options_container_x_path}"
        )

        # Check if this is a boolean (yes/no) question with only one option
        if len(option_elements) == 1:
            self.is_boolean = True
            logger.info(
                f"Detected boolean question for {self.title} - returning Yes/No options"
            )
            return [{"text": "Yes", "x_path": None}, {"text": "No", "x_path": None}]

        for option_element in option_elements:
            # Find the parent element that contains the text
            text_element = self._find_text_containing_parent(
                option_element, option_elements, container_element
            )

            # Extract text from the text element (parent that contains the label)
            clean_text = (
                remove_emoji(text_element.text.strip())
                if hasattr(text_element, "text")
                else ""
            )

            if clean_text and clean_text not in option_texts:
                # Use option element's XPath for clicking/interaction
                # Text is extracted from parent, but we interact with the option element
                option_xpath = get_element_xpath(option_element)

                output_options.append({"text": clean_text, "x_path": option_xpath})
                option_texts.append(clean_text)

        logger.info(
            f"Completed building options list: {len(output_options)} total options for {self.title}"
        )
        return output_options

    def _save_response(self, response_text):
        """Save field response to application page"""
        if response_text and self.parent_application_page:
            self.parent_application_page.save_field_response(
                question=self.question,
                response=response_text,
            )

    def _handle_boolean_question(self, answer):
        """Handle boolean (Yes/No) checkbox question"""
        global driver

        # Use container and pattern xpaths to find the checkbox element
        if not self.options_container_x_path or not self.options_xpath_pattern:
            logger.warning(
                f"Container or pattern XPath missing for boolean question {self.title}"
            )
            self.is_component_functional = False
            return None

        if not element_exists(self.options_container_x_path):
            logger.warning(
                f"Container XPath {self.options_container_x_path} not found for {self.title}"
            )
            self.is_component_functional = False
            return None

        container_element = driver.find_element(By.XPATH, self.options_container_x_path)
        option_elements = container_element.find_elements(
            By.XPATH, self.options_xpath_pattern
        )

        if not option_elements:
            logger.warning(
                f"No option elements found using pattern {self.options_xpath_pattern} for {self.title}"
            )
            self.is_component_functional = False
            return None

        checkbox_element = option_elements[0]
        checkbox_xpath = get_element_xpath(checkbox_element)

        if answer == "Yes":
            # Check the checkbox
            checkbox_button = Button(
                x_path=checkbox_xpath,
                button_type="checkbox",
                parent_application_page=None,
                title=self.title,
            )
            checkbox_button.container_x_path = self.container_x_path
            checkbox_button.proceed()
            return ["Yes"]
        else:
            # Ensure checkbox is unchecked
            if (
                checkbox_element.tag_name == "input"
                and checkbox_element.get_attribute("type") == "checkbox"
                and checkbox_element.is_selected()
            ):
                driver.execute_script("arguments[0].checked = false;", checkbox_element)
            return ["No"]

    def _handle_multi_option_checkboxes(self, answers):
        """Handle multi-option checkbox selection - only selected answers are checked, rest are unchecked"""
        global driver
        selected_options_text = []

        for option in self.options:
            option_element = get_unique_element_by_xpath(
                option["x_path"], self.title, container_xpath=self.container_x_path
            )
            should_be_selected = option["text"] in answers
            is_currently_selected = (
                option_element.tag_name == "input"
                and option_element.get_attribute("type") == "checkbox"
                and option_element.is_selected()
            )

            if should_be_selected:
                # Check if not already selected
                if not is_currently_selected:
                    option_button = Button(
                        x_path=get_element_xpath(option_element),
                        button_type="checkbox",
                        parent_application_page=None,
                        title=self.title,
                    )
                    option_button.container_x_path = self.container_x_path
                    option_button.proceed()
                selected_options_text.append(option["text"])
            else:
                # Uncheck if currently selected
                if is_currently_selected:
                    driver.execute_script(
                        "arguments[0].checked = false;", option_element
                    )

        return selected_options_text

    def proceed(self, retry=False):
        # Build options list from pattern
        self.options = self._build_options_list()

        if not self.options:
            logger.warning(f"No options found for {self.title}")
            return

        info = ApplicationField.get_field_value(
            field_category=self.category,
            user=self.parent_application_page.parent_job.user,
        )

        # Extract answer once for both boolean and multi-option cases
        extracted_answer, _ = ApplicationField.extract_field_answer(
            job_title=self.parent_application_page.parent_job.title,
            job_url=self.parent_application_page.url,
            company_name=self.parent_application_page.parent_job.company,
            field_title=self.title,
            question=self.question,
            answer_type="enum",
            multiple_correct=not self.is_boolean,
            options=[option["text"] for option in self.options],
            closest_answer=info if info else None,
            parsed_resume=self.parent_application_page.parent_job.user.parsed_resume,
        )

        # Handle boolean (Yes/No) questions
        if self.is_boolean:
            # Assume answer is definitely "Yes" or "No"
            answer = extracted_answer if extracted_answer else "No"
            response_text = self._handle_boolean_question(answer)
        else:
            # Handle multi-option checkboxes
            response_text = self._handle_multi_option_checkboxes(extracted_answer)

        # Save response once
        if response_text:
            self._save_response(response_text)
            self.is_component_functional = True

    @classmethod
    def validate_checkbox(
        cls,
        options_container_x_path,
        options_xpath_pattern,
        title,
        container_xpath=None,
    ):
        """Validate if checkbox allows multiple selections by building options and testing"""
        multiple_correct = False

        # Both container and pattern are required
        if not options_container_x_path or not options_xpath_pattern:
            return cls._validate_checkbox_using_llm(
                title, container_xpath=container_xpath
            )

        if not element_exists(options_container_x_path):
            return cls._validate_checkbox_using_llm(
                title, container_xpath=container_xpath
            )

        # Pattern must always be scoped to container
        container_element = driver.find_element(By.XPATH, options_container_x_path)
        options = container_element.find_elements(By.XPATH, options_xpath_pattern)

        # If there are no options or only one option, we can consider it valid
        if len(options) <= 1:
            return True

        # Get first two options for testing
        option_1_xpath = get_element_xpath(options[0])
        option_2_xpath = get_element_xpath(options[1])

        option_1 = get_unique_element_by_xpath(
            xpath=option_1_xpath, title=title, container_xpath=container_xpath
        )
        if not option_1:
            raise Exception(f"Unique element not found for x_path - {option_1_xpath}")

        if (
            option_1.tag_name == "input"
            and option_1.get_attribute("type") == "checkbox"
        ):
            driver.execute_script("arguments[0].checked = false;", option_1)
        else:
            return cls._validate_checkbox_using_llm(
                title, container_xpath=container_xpath
            )

        option_button_1 = Button(
            x_path=get_element_xpath(option_1),
            button_type="checkbox",
            parent_application_page=None,
            title=title,
        )
        option_button_1.container_x_path = container_xpath
        option_button_1.proceed()

        option_2 = get_unique_element_by_xpath(
            xpath=option_2_xpath, title=title, container_xpath=container_xpath
        )
        if not option_2:
            raise Exception(f"Unique element not found for x_path - {option_2_xpath}")
        driver.execute_script("arguments[0].checked = false;", option_2)

        option_button_2 = Button(
            x_path=get_element_xpath(option_2),
            button_type="checkbox",
            parent_application_page=None,
            title=title,
        )
        option_button_2.container_x_path = container_xpath
        option_button_2.proceed()

        if option_1.is_selected() and option_2.is_selected():
            multiple_correct = True

        driver.execute_script("arguments[0].checked = false;", option_1)
        driver.execute_script("arguments[0].checked = false;", option_2)

        return multiple_correct

    @staticmethod
    def _validate_checkbox_using_llm(title, container_xpath=None):
        global driver

        element_identified, user_input_element, computed_container_xpath = (
            find_input_block_for_title(title, container_xpath=container_xpath)
        )
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

        checkbox_validation_done, checkbox_validation = _llm_service.chat(
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
            "options_container_x_path": self.options_container_x_path,
            "options_xpath_pattern": self.options_xpath_pattern,
            "is_boolean": self.is_boolean,
            "container_x_path": self.container_x_path,
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

        instance.container_x_path = input_dict.get("container_x_path")
        instance.is_component_functional = True
        instance.is_boolean = input_dict.get("is_boolean", False)

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
