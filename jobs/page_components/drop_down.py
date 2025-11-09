from pydantic import BaseModel, Field
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoSuchElementException
import time

from jobs.page_components import (
    PageComponent,
    ApplicationField,
    get_page_component_class_name,
    logger,
)
from jobs.page_components.button import Button
from utilities import constants, remove_emoji
from utilities.gpt import get_gpt_response
from utilities.selenium import (
    find_clickable_parent_xpath,
    get_selenium_driver,
    is_element_visible,
    get_element_xpath,
    simulate_empty_area_click,
    generalize_xpath_attributes,
    element_exists,
    get_unique_element_by_xpath,
)


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class DropDown(PageComponent):
    def __init__(
        self,
        x_path,
        title,
        question,
        category,
        options_container_x_path,
        parent_application_page,
    ):
        self.x_path = x_path
        self.title = title
        self.question = question
        self.category = category
        self.parent_application_page = parent_application_page
        self.options_container_x_path = options_container_x_path
        self.dropdown_button = Button(
            x_path=self.x_path,
            button_type="dropdown",
            title=title,
            parent_application_page=self.parent_application_page,
        )

        self.options_xpath_pattern = None

        self.is_component_functional = False

        self.next = None
        self.prev = None

    def _get_clickable_xpath_for_option(self, option_xpath, option_text):
        """
        Get the clickable xpath for an option, either directly or by scrolling to find it.

        :param option_xpath: XPath of the option element
        :param option_text: Text content of the option
        :return: Clickable xpath of the option element
        :raises: Exception if option cannot be found
        """
        global driver

        try:
            # Try to get clickable xpath directly
            clickable_xpath = find_clickable_parent_xpath(option_xpath, option_text)
            return clickable_xpath
        except NoSuchElementException:
            # Fallback strategy: scroll until we see the option
            # Since we're already at the end, scroll up (towards first element)
            logger.info(
                f"Option not found by xpath, scrolling up to find option: {option_text}"
            )
            same_first_element_count = 0
            first_element_xpath = None
            scroll_iteration = 0

            while True:
                scroll_iteration += 1
                # Get current visible options
                current_options = driver.find_elements(
                    By.XPATH, self.options_xpath_pattern
                )

                if not current_options:
                    break

                # Check if target option is visible
                for opt in current_options:
                    opt_text = remove_emoji(opt.text)
                    if opt_text == option_text:
                        # Found the option, return its clickable xpath
                        clickable_xpath = find_clickable_parent_xpath(
                            get_element_xpath(opt), option_text
                        )
                        logger.info(
                            f"Found option after scrolling (iteration {scroll_iteration})"
                        )
                        return clickable_xpath

                # Option not found in current view, scroll up (towards first element)
                first_option = current_options[0]
                current_first_xpath = get_element_xpath(first_option)
                if current_first_xpath == first_element_xpath:
                    same_first_element_count += 1
                    if same_first_element_count >= 3:
                        logger.warning(
                            f"Reached top of dropdown without finding option: {option_text}"
                        )
                        raise Exception(
                            f"Could not find option '{option_text}' after scrolling to top"
                        )
                else:
                    same_first_element_count = 0
                    first_element_xpath = current_first_xpath

                actions = ActionChains(driver)
                actions.move_to_element(first_option).perform()

    def proceed(self, retry=False):
        global driver

        dropdown_element = get_unique_element_by_xpath(self.x_path, title=self.title)
        dropdown_type = ApplicationField.identify_options_container_type(
            dropdown_element
        )
        if dropdown_type == "select-option":
            self.options_container_x_path = None

        if dropdown_type != "select-option":
            simulate_empty_area_click()
            self.dropdown_button.proceed()

            if (
                not element_exists(self.options_container_x_path)
                and dropdown_element.tag_name.lower() == "input"
            ):
                # send vowels to trigger options loading for cases where just click is not enough
                for vowel in "aeiou":
                    dropdown_element.send_keys(vowel)
                    time.sleep(0.5)
                    dropdown_element.send_keys("\ue003")  # Backspace key

            if not element_exists(self.options_container_x_path):
                logger.warning(
                    f"Element with dropdown container XPath {self.options_container_x_path} not found at url "
                    f"{self.parent_application_page.url}. Retrying with generalized XPath..."
                )
                self.options_container_x_path = generalize_xpath_attributes(
                    self.options_container_x_path
                )

            if not element_exists(self.options_container_x_path):
                raise Exception(
                    f"Element with generalized dropdown container XPath {self.options_container_x_path} not found at url "
                    f"{self.parent_application_page.url}"
                )
        else:
            driver.execute_script(
                """
                const element = arguments[0];
                const rect = element.getBoundingClientRect();
                const elementTop = rect.top + window.pageYOffset;
                const viewportHeight = window.innerHeight;
                const offsetToCenter = elementTop - (viewportHeight / 2) + (rect.height / 2) + 100;
                window.scrollTo({top: offsetToCenter, behavior: 'auto'});
            """,
                dropdown_element,
            )

        option = None
        max_empty_options_retries = 3
        empty_options_retry_count = 1
        max_iterations = 3
        iteration_count = 0
        while (
            (option is None) or is_element_visible(self.options_container_x_path)
        ) and iteration_count < max_iterations:
            iteration_count += 1
            if not self.options_xpath_pattern:
                self.options_xpath_pattern, options = self.get_dropdown_options(
                    job_title=self.parent_application_page.parent_job.title,
                    job_url=self.parent_application_page.url,
                    field_title=self.title,
                    question=self.question,
                    options_container_x_path=(
                        self.options_container_x_path
                        if dropdown_type != "select-option"
                        else self.x_path
                    ),
                    dropdown_type=dropdown_type,
                )
            else:
                options = self.build_options_list(
                    self.options_xpath_pattern, dropdown_type=dropdown_type
                )

            if not options:
                self.options_xpath_pattern = None

                if empty_options_retry_count >= max_empty_options_retries:
                    simulate_empty_area_click()
                    return
                empty_options_retry_count += 1

                continue

            answer = ApplicationField.get_field_value(
                field_category=self.category,
                user=self.parent_application_page.parent_job.user,
            )
            answer = (
                answer if [opt for opt in options if opt["text"] == answer] else None
            )

            if answer is None:
                answer, _ = ApplicationField.extract_field_answer(
                    job_title=self.parent_application_page.parent_job.title,
                    job_url=self.parent_application_page.url,
                    company_name=self.parent_application_page.parent_job.company,
                    field_title=self.title,
                    question=self.question,
                    answer_type="enum",
                    options=[opt["text"] for opt in options],
                    parsed_resume=self.parent_application_page.parent_job.user.parsed_resume,
                )

            option = [opt for opt in options if opt["text"] == answer]
            if option:
                option = option[0]
            else:
                logger.warning(
                    f"Couldn't find a matching option for {self.title} in the dropdown."
                )
                return

            if dropdown_type == "select-option":
                # Handle standard select dropdowns
                select_element = get_unique_element_by_xpath(
                    self.x_path, title=self.title
                )
                select = Select(select_element)
                select.select_by_visible_text(option["text"])
            else:
                # Get the clickable xpath for this option (with fallback scrolling if needed)
                clickable_xpath = self._get_clickable_xpath_for_option(
                    option["x_path"], option["text"]
                )

                # Create a Button instance for the clickable element
                option_button = Button(
                    x_path=clickable_xpath,
                    button_type="dropdown_option",
                    title=self.title,
                    parent_application_page=self.parent_application_page,
                )
                option_button.proceed()

        # Check if loop ended due to maximum iterations without completing successfully
        if iteration_count >= max_iterations:
            option_text = option["text"] if option else None
            dropdown_visible = False
            if self.options_container_x_path:
                try:
                    dropdown_visible = is_element_visible(self.options_container_x_path)
                except Exception:
                    dropdown_visible = "unknown"

            # Only raise exception if task didn't complete successfully
            # (option is None OR dropdown is still visible)
            if option is None or dropdown_visible:
                raise Exception(
                    f"Maximum iterations ({max_iterations}) reached for dropdown '{self.title}' "
                    f"at url {self.parent_application_page.url}. "
                    f"Option selected: {option_text}, "
                    f"Dropdown still visible: {dropdown_visible}"
                )

        # Store the response
        if option and self.parent_application_page:
            self.parent_application_page.save_field_response(
                question=self.question,
                response=option["text"],
            )

        self.is_component_functional = True
        return

    @classmethod
    def get_dropdown_options(
        cls,
        job_title,
        job_url,
        field_title,
        question,
        options_container_x_path,
        dropdown_type=None,
    ):
        """Get dropdown options pattern and list from container"""
        xpath_pattern = cls.extract_options_xpath_pattern(
            job_title=job_title,
            job_url=job_url,
            field_title=field_title,
            question=question,
            options_container_x_path=options_container_x_path,
        )
        options = cls.build_options_list(xpath_pattern, dropdown_type=dropdown_type)
        return xpath_pattern, options

    @classmethod
    def extract_options_xpath_pattern(
        cls,
        job_title,
        job_url,
        field_title,
        options_container_x_path,
        question=None,
    ):
        """Extract XPath pattern to find all dropdown options"""
        xpath_pattern = cls._extract_options_xpath_pattern_using_regex(
            options_container_x_path
        )
        if xpath_pattern:
            return xpath_pattern
        else:
            return cls._extract_options_xpath_pattern_using_llm(
                job_title=job_title,
                job_url=job_url,
                field_title=field_title,
                options_container_x_path=options_container_x_path,
                question=question,
            )

    @staticmethod
    def _extract_options_xpath_pattern_using_regex(options_container_x_path):
        container_element = driver.find_element(By.XPATH, options_container_x_path)
        dropdown_type = ApplicationField.identify_options_container_type(
            container_element
        )
        if dropdown_type == "select-option":
            return f"{options_container_x_path}//option"
        elif dropdown_type in ["ul-li", "ol-li"]:
            return f"{options_container_x_path}//li"
        elif dropdown_type == "listbox-option":
            return f"{options_container_x_path}//*[contains(@role, 'option')]"
        elif dropdown_type == "menu-menuitem":
            return f"{options_container_x_path}//*[contains(@role, 'menuitem')]"
        elif dropdown_type == "custom-div-dropdown":
            return (
                f"{options_container_x_path}//*[contains(@class, 'dropdown-location')]"
            )
        else:
            return None

    @staticmethod
    def _extract_options_xpath_pattern_using_llm(
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
            f"I have HTML of job application webpage for {job_title}."
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

        if pattern_found and is_element_visible(pattern_result.xpath_pattern):
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
    def build_options_list(cls, xpath_pattern, dropdown_type=None):
        """
        Scrolls through a dropdown container and collects all visible option elements.

        :param dropdown_type: Type of dropdown container (e.g., "select-option", "ul-li", "ol-li", etc.)
        :param xpath_pattern: XPath pattern for the dropdown options inside the container
        :return: List of all option dictionaries with text and x_path
        """
        global driver

        output_options = []
        option_texts = []

        if dropdown_type == "select-option":
            all_options = driver.find_elements(By.XPATH, xpath_pattern)
            all_options = [
                option for option in all_options if option.get_attribute("value")
            ]
            logger.info(f"Found {len(all_options)} select options")
            for option in all_options:
                clean_text = remove_emoji(option.text)
                if clean_text not in option_texts:
                    output_options.append(
                        {"text": clean_text, "x_path": get_element_xpath(option)}
                    )
                    option_texts.append(clean_text)
        else:
            # Scroll the container and collect options as we go
            last_element_xpath = None
            same_last_element_count = 0
            scroll_iteration = 0

            while True:
                scroll_iteration += 1
                options = driver.find_elements(By.XPATH, xpath_pattern)
                if not options:
                    logger.info(
                        f"No options found, stopping scroll at iteration {scroll_iteration}"
                    )
                    break

                # Process current options immediately to avoid stale elements
                new_options_count = 0
                for option in options:
                    clean_text = remove_emoji(option.text)
                    if clean_text not in option_texts:
                        output_options.append(
                            {"text": clean_text, "x_path": get_element_xpath(option)}
                        )
                        option_texts.append(clean_text)
                        new_options_count += 1

                if new_options_count > 0:
                    logger.info(
                        f"Scroll iteration {scroll_iteration}: Added {new_options_count} new options (total: {len(output_options)})"
                    )

                # Check if we've reached the end
                last_option = options[-1]
                current_last_xpath = get_element_xpath(last_option)
                if current_last_xpath == last_element_xpath:
                    same_last_element_count += 1
                    logger.info(
                        f"Same last element detected (count: {same_last_element_count}/3)"
                    )
                    if same_last_element_count >= 3:
                        logger.info(
                            f"Reached end of dropdown after {scroll_iteration} iterations"
                        )
                        break  # Same last element seen 3 times, stop scrolling
                else:
                    same_last_element_count = 0
                    last_element_xpath = current_last_xpath

                # Scroll to last option
                actions = ActionChains(driver)
                actions.move_to_element(last_option).perform()

        logger.info(
            f"Completed building options list: {len(output_options)} total options"
        )
        return output_options

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
            options_container_x_path=input_dict["options_container_x_path"],
            parent_application_page=parent_application_page,
        )

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
