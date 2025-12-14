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
        self.container_x_path = None

        self.next = None
        self.prev = None

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

        option_element = get_unique_element_by_xpath(
            option["x_path"], self.title, container_xpath=self.container_x_path
        )
        if (
            option_element.tag_name == "input"
            and option_element.get_attribute("type") == "radio"
            and option_element.is_selected()
        ):
            pass
        else:
            option_button = Button(
                x_path=get_element_xpath(option_element),
                button_type="radio",
                parent_application_page=None,
            )
            option_button.container_x_path = self.container_x_path
            option_button.proceed()

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
