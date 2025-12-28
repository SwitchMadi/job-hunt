import time
from abc import ABC, abstractmethod
import re
import importlib
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, List, Annotated
from selenium.common import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    NoSuchElementException,
    InvalidSelectorException,
)
from selenium.webdriver.common.by import By
import yaml

from utilities.selenium import (
    get_selenium_driver,
    start_dom_mutation_observer,
    get_observed_elements,
    simulate_empty_area_click,
    element_exists,
    minify_html_for_gpt_prompt,
    is_stale,
    find_clickable_parent_xpath,
    is_element_visible,
    get_element_xpath,
    find_input_block_for_title,
    get_unique_element_by_xpath,
    get_interactive_elements_in_container,
)
from utilities.logging import get_logger
from utilities import pascal_to_snake_casing, retry, constants
from utilities.gpt import get_gpt_response


config = yaml.safe_load(open("config.yml"))
logger = get_logger(name="job")
driver = get_selenium_driver()
driver.set_page_load_timeout(15)


def get_page_component_class_name(class_name):
    module_name = pascal_to_snake_casing(class_name)
    if class_name == "VerifyAccount":
        module_name = "login"
    elif class_name == "WorkExperience":
        module_name = "work_experience_section"
    elif class_name == "Education":
        module_name = "education_section"
    elif class_name.endswith("State") and not class_name.startswith("Login"):
        # Login state classes (e.g., StartState, SignInFormState)
        # Map to login subfolder - module_name already has _state suffix, so we're good
        module_name = f"jobs.page_components.login.{module_name}"

    try:
        return globals()[class_name]
    except KeyError:
        # Use importlib for nested module imports (e.g., login.account_creation_form_state)
        try:
            module = importlib.import_module(module_name)
            return getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            # Fallback to eval for backward compatibility
            try:
                return eval(f'globals()["{module_name}"].{class_name}')
            except Exception:
                raise ImportError(
                    f"Could not import {class_name} from {module_name}: {e}"
                )


class PageComponent(ABC):
    @abstractmethod
    def proceed(self, retry=False):
        pass

    @abstractmethod
    def to_dict(self):
        pass

    @abstractmethod
    def from_dict(self, input_dict, parent_application_page):
        pass


class ApplicationField:
    def __init__(
        self,
        parent_application_page,
        title,
        question,
        category,
        x_path=None,
        title_to_click=None,
        container_x_path=None,
    ):
        self.parent_application_page = parent_application_page
        self.title = title
        self.title_to_click = title_to_click or title
        self.question = question
        self.category = category
        self.x_path = x_path
        self.container_x_path = container_x_path

        self.field_type = None
        self.html_type = None
        self.format = None
        self.options_container_x_path = None
        self.options_xpath_pattern = None

    @retry(times=2, delay=5, exceptions=InvalidSelectorException)
    def _identify_x_path(self, retry=False, prev_x_path=None, retry_with_complex=False):
        global driver

        logger.info(
            f"Identifying x_path for application field {self.title} & {self.category}..."
        )

        user_input_element = None
        computed_container_xpath = None
        try:
            element_identified, user_input_element, computed_container_xpath = (
                find_input_block_for_title(
                    self.title, container_xpath=self.container_x_path
                )
            )
            if not element_identified:
                logger.warn(
                    f"Input block for title {self.title} not identified in job "
                    f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                )
        except Exception as e:
            logger.warn(
                f"Error while finding input block for title {self.title} in job "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}. "
                f"Error: {e.msg if hasattr(e, 'msg') else str(e)}"
            )

        if user_input_element:
            minified_html = minify_html_for_gpt_prompt(
                user_input_element.get_attribute("outerHTML")
            )
            if (not self.container_x_path) and computed_container_xpath:
                self.container_x_path = computed_container_xpath
        elif self.container_x_path and element_exists(self.container_x_path):
            logger.info(
                f"User input element not found so using container_x_path for HTML extraction for "
                f"field {self.title} & {self.category}..."
            )
            container_element = driver.find_element(By.XPATH, self.container_x_path)
            minified_html = minify_html_for_gpt_prompt(
                container_element.get_attribute("outerHTML")
            )
        else:
            minified_html = minify_html_for_gpt_prompt(driver.page_source)

        user_prompt = (
            f"Following HTML is of job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minified_html}\n"
            f"The webpage has following application field for applying to the job -\n"
            f"Field title - {self.title}\n"
            f"Field category - {self.category}\n"
            f"Analyse the whole HTML very carefully for extracting XPath and other info of the interactive application "
            f"field for above given field title and category.\n"
            f"Please keep in mind following -\n"
            f"1. Get XPath of the application field which is interactive in nature. Don't get XPath of the field which"
            f" is not interactive. \n"
            f"2. Sometimes under one field title there can be multiple fields as in same vicinity or under same parent."
            f" In that case, get XPath of the field which is most relevant to the field title & category.\n"
            f"3. XPath should be of one interactive element only. Don't get XPath for element which has multiple "
            f"interactive elements in it (except for checkboxes and radio buttons) and the element is not interactive "
            f"itself.\n"
            f"4. When identifying html_type, carefully analyze the element's behavior and HTML structure. If you see a "
            f"button element that displays a selected value and opens a menu/list of options when clicked (indicated by "
            f"attributes like aria-haspopup, aria-expanded, or presence of dropdown icons), classify it as 'dropdownButton'. "
            f"Only use 'button' for elements that perform actions (submit, cancel, add entry) without opening selection menus.\n"
            f"5. If the field_type is checkbox or radio button, extract options_container_x_path (XPath of the parent element "
            f"containing all checkbox/radio options) and options_xpath_pattern (XPath pattern that matches all individual "
            f"option elements). The options_xpath_pattern will be used relative to the container element (i.e., "
            f"container_element.find_elements(By.XPATH, pattern)), so it should be a relative XPath pattern. "
            f"Both XPaths should avoid alphanumeric strings that may change on page reload.\n"
        )

        if self.category in ["phone_country_code", "phone_number_without_country_code"]:
            user_prompt += (
                f"\nAdditionally Put extra effort to understand HTML hierarchy and don't confuse yourself between country code "
                f"field and phone number field. They may be different fields or same field. If they seem to be "
                f"different fields then very carefully return XPath of the interactive element for {self.category} "
                f"field. Focus on HTML hierarchy, elements grouping and different attributes of the elements, "
                f"to identify & distinguish correctly."
            )

        if retry and prev_x_path:
            user_prompt += (
                f"\n\nIn previous try you gave following x_path and the element couldn't be found using that. So, find "
                f"correct x_path for the same field.\n"
                f"Previous x_path - {prev_x_path}\n"
            )

        class FieldHtmlType(Enum):
            textBox = "text_box"
            checkBox = "check_box"
            radioButton = "radio_button"
            dropdown = "dropdown"
            dropdownButton = "dropdown_button"
            button = "button"

        class FieldType(Enum):
            addButton = "add_button"
            upload = "upload"
            date_field = "date_field"
            expand = "expand"
            collapse = "collapse"
            text_field = "text_field"
            multiple_choice = "multiple_choice"
            other = "other"

        class XPathInfo(BaseModel):
            x_path: Optional[str] = Field(
                ...,
                description="XPath of the application field which can be used in selenium chrome driver to search the "
                "application field. Don't use HTML hierarchy to construct XPath. XPath of the first field "
                "if there are many.",
            )
            uses_alphanumeric: bool = Field(
                ...,
                description="Whether this XPath uses alphanumeric strings (like 'id-123abc', 'element-456xyz', "
                "or any attribute values containing random alphanumeric characters) that may change when the page reloads. "
                "Set to True if the XPath contains such patterns, False otherwise.",
            )

        if user_input_element:

            class ApplicationFieldInfo(BaseModel):
                x_path_info: XPathInfo = Field(
                    ...,
                    description="XPath information of the application field, including the xpath string and whether it uses alphanumeric IDs.",
                )
                is_field_match_confident: bool = Field(
                    ...,
                    description="Very carefully assess whether the extracted x_path element matches with the given title and category with great"
                    " confidence or not. If true then field is correct and should be used. If false then extracted field info "
                    "is not reliable enough and should not be used. Be very strict for assessing the confidence.",
                )
                field_type: FieldType = Field(
                    ...,
                    description="Application sub-field type like date, addButton, upload etc.",
                )
                html_type: FieldHtmlType = Field(
                    ...,
                    description="Application field html type like textbox, checkbox, dropdown, dropdownButton etc.",
                )
                options_container_x_path: Optional[str] = Field(
                    default=None,
                    description="XPath of the container element containing all checkbox/radio options. Should be provided only if html_type is check_box or radio_button.",
                )
                options_xpath_pattern: Optional[str] = Field(
                    default=None,
                    description="XPath pattern that matches all individual checkbox/radio option elements. This pattern will be used relative to the container element (i.e., container_element.find_elements(By.XPATH, pattern)), so it should be a relative XPath pattern. Should be provided only if html_type is check_box or radio_button.",
                )
                format: Optional[str] = Field(
                    ...,
                    description="Format of field answer if the field requires its answer to be in some specific format. "
                    "e.g. date format etc.",
                )

        else:

            class ApplicationFieldInfo(BaseModel):
                x_path_info: XPathInfo = Field(
                    ...,
                    description="XPath information of the application field, including the xpath string and whether it uses alphanumeric IDs.",
                )
                is_field_match_confident: bool = Field(
                    ...,
                    description="Very carefully assess whether the extracted x_path element matches with the given title and category with great"
                    " confidence or not. If true then field is correct and should be used. If false then extracted field info "
                    "is not reliable enough and should not be used. Be very strict for assessing the confidence.",
                )
                field_type: FieldType = Field(
                    ...,
                    description="Application sub-field type like date, addButton, upload etc.",
                )
                html_type: FieldHtmlType = Field(
                    ...,
                    description="Application field html type like textbox, checkbox, dropdown, dropdownButton etc.",
                )
                options_container_x_path: Optional[str] = Field(
                    default=None,
                    description="XPath of the container element containing all checkbox/radio options. Should be "
                    "provided only if html_type is check_box or radio_button.",
                )
                options_xpath_pattern: Optional[str] = Field(
                    default=None,
                    description="XPath pattern that matches all individual checkbox/radio option elements. This pattern"
                    " will be used relative to the container element "
                    "(i.e., container_element.find_elements(By.XPATH, pattern)), so it should be a relative"
                    " XPath pattern. Should be provided only if html_type is check_box or radio_button.",
                )
                format: Optional[str] = Field(
                    ...,
                    description="Format of field answer if the field requires its answer to be in some specific format. "
                    "e.g. date format etc.",
                )
                exact_field_title: Optional[str] = Field(
                    ...,
                    description="Exact field title as shown on page without any modification whatsoever, even if exact "
                    "title is too long.",
                )

        model = "complex" if retry_with_complex else "intermediate"
        application_field_found, application_field = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=ApplicationFieldInfo,
            model=model,
            timeout=60 if model == "intermediate" else None,
        )
        if application_field_found:
            if not application_field.is_field_match_confident:
                if not retry_with_complex:
                    logger.info(
                        f"Field match is not confident for {self.title} & {self.category} in "
                        f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}. "
                        f"Retrying with complex model..."
                    )
                    return self._identify_x_path(
                        retry=retry,
                        prev_x_path=prev_x_path,
                        retry_with_complex=True,
                    )
                else:
                    logger.warn(
                        f"Field match is not confident for {self.title} & {self.category} in "
                        f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url} "
                        f"even after retrying with complex model."
                    )
                    return None

            if (
                application_field.x_path_info.x_path
                and application_field.x_path_info.x_path.startswith("/")
                and not application_field.x_path_info.x_path.startswith("//")
                and not element_exists(application_field.x_path_info.x_path)
            ):
                application_field.x_path_info.x_path = (
                    "/" + application_field.x_path_info.x_path
                )

            # Try replacing contains(text(), ...) with contains(., ...) if element not found
            # This helps when HTML is minified and text nodes might be trimmed
            if application_field.x_path_info.x_path and not element_exists(
                application_field.x_path_info.x_path
            ):
                contains_text_pattern = r"contains\(text\(\),\s*(['\"])([^'\"]+)\1\)"
                match = re.search(
                    contains_text_pattern, application_field.x_path_info.x_path
                )
                if match:
                    quote_char = match.group(1)
                    text_content = match.group(2)
                    modified_xpath = re.sub(
                        contains_text_pattern,
                        f"contains(., {quote_char}{text_content}{quote_char})",
                        application_field.x_path_info.x_path,
                    )
                    if element_exists(modified_xpath):
                        logger.info(
                            f"Element found after replacing contains(text(), ...) with contains(., ...) "
                            f"for {self.title} & {self.category} in "
                            f"{self.parent_application_page.parent_job.title}. "
                            f"Original xpath: {application_field.x_path_info.x_path}, Modified xpath: {modified_xpath}"
                        )
                        application_field.x_path_info.x_path = modified_xpath

            # Form xpath from container if conditions are met
            if (
                application_field.html_type.value
                in ["text_box", "dropdown", "dropdown_button"]
                and application_field.field_type.value in ["text_field", "other"]
                and (
                    not application_field.x_path_info.x_path
                    or not element_exists(application_field.x_path_info.x_path)
                    or application_field.x_path_info.uses_alphanumeric
                )
                and self.container_x_path
            ):
                formed_xpath = self._form_xpath_from_container(self.container_x_path)
                if formed_xpath:
                    logger.info(
                        f"Replacing xpath {'(has alphanumeric IDs)' if application_field.x_path_info.uses_alphanumeric else ''} "
                        f"with container-based xpath for {self.title} & {self.category} in "
                        f"{self.parent_application_page.parent_job.title}. "
                        f"Original xpath: {application_field.x_path_info.x_path}, Container based xpath: {formed_xpath}"
                    )
                    application_field.x_path_info.x_path = formed_xpath
                    application_field.x_path_info.uses_alphanumeric = False

            if (
                (application_field.field_type.value != "date_field")
                and not (
                    application_field.html_type.value != "dropdown"
                    and (
                        application_field.options_container_x_path
                        or application_field.options_xpath_pattern
                    )
                )
                and application_field.x_path_info.x_path
                and not element_exists(application_field.x_path_info.x_path)
            ):
                logger.warn(
                    f"Element with x_path {application_field.x_path_info.x_path} doesn't exist for "
                    f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                )
                prompt = (
                    f"The x_path that we are trying to extract is of following application field -\n"
                    f"Field title - {self.title}\n"
                    f"Field category - {self.category}\n"
                )
                correct_x_path = self.extract_correct_x_path(
                    prev_x_path=application_field.x_path_info.x_path,
                    prompt=prompt,
                    job_title=self.parent_application_page.parent_job.title,
                    job_url=self.parent_application_page.url,
                    html=minified_html,
                    container_x_path=self.container_x_path,
                )
                if not correct_x_path:
                    return None
                else:
                    application_field.x_path_info.x_path = correct_x_path

            # Check if container exists and xpath is not unique (exists more than once)
            if (
                application_field.html_type.value
                in ["text_box", "dropdown", "dropdown_button"]
                and application_field.field_type.value in ["text_field", "other"]
                and self.container_x_path
                and element_exists(self.container_x_path)
                and application_field.x_path_info.x_path
                and element_exists(application_field.x_path_info.x_path)
            ):
                try:
                    elements = driver.find_elements(
                        By.XPATH, application_field.x_path_info.x_path
                    )
                    if len(elements) > 1:
                        logger.warn(
                            f"Element with x_path {application_field.x_path_info.x_path} exists {len(elements)} times on the page "
                            f"for {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}. "
                            f"Container exists, attempting to extract a more specific xpath..."
                        )
                        prompt = (
                            f"The x_path that we are trying to extract is of following application field -\n"
                            f"Field title - {self.title}\n"
                            f"Field category - {self.category}\n"
                            f"CRITICAL: The current x_path exists {len(elements)} times on the page, which means it's not unique. "
                            f"Since a container element exists with XPath: {self.container_x_path}, please extract a more specific "
                            f"x_path that targets the element within this container. The x_path should be unique within the page "
                            f"or be constructed relative to the container to ensure it targets the correct element."
                        )
                        correct_x_path = self.extract_correct_x_path(
                            prev_x_path=application_field.x_path_info.x_path,
                            prompt=prompt,
                            job_title=self.parent_application_page.parent_job.title,
                            job_url=self.parent_application_page.url,
                            html=minified_html,
                            container_x_path=self.container_x_path,
                        )
                        if correct_x_path:
                            application_field.x_path_info.x_path = correct_x_path
                except Exception as e:
                    logger.warn(
                        f"Error checking uniqueness of x_path {application_field.x_path_info.x_path} for "
                        f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}. "
                        f"Error: {str(e)}"
                    )

            if (
                application_field.x_path_info.x_path
                and self.parent_application_page.component_x_path_exists(
                    application_field.x_path_info.x_path
                )
            ):
                logger.warn(
                    f"Page component with following x_path already exists - {application_field.x_path_info.x_path}"
                )
                return

            self.x_path = application_field.x_path_info.x_path
            self.field_type = application_field.field_type.value
            self.html_type = application_field.html_type.value
            self.format = application_field.format

            if not user_input_element:
                self.title = application_field.exact_field_title or self.title

            # Handle checkbox/radio option patterns
            if application_field.html_type.value in ["check_box", "radio_button"]:
                # For checkbox/radio, we need both container and pattern
                self.options_container_x_path = (
                    application_field.options_container_x_path
                )
                self.options_xpath_pattern = application_field.options_xpath_pattern
                # Always validate - _validate_mcq_options_pattern handles missing fields
                self.options_container_x_path, self.options_xpath_pattern = (
                    self._validate_mcq_options_pattern(
                        self.options_container_x_path, self.options_xpath_pattern
                    )
                )
            elif (
                application_field.options_container_x_path
                or application_field.options_xpath_pattern
            ):
                # Non-checkbox/radio but has options (edge case - shouldn't happen per spec)
                self.options_container_x_path = (
                    application_field.options_container_x_path
                )
                self.options_xpath_pattern = application_field.options_xpath_pattern
        elif not retry:
            self._identify_x_path(retry=True)
        else:
            raise Exception(
                f"Couldn't extract following application field {self.category} for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

        return None

    def _validate_mcq_options_pattern(
        self, options_container_x_path, options_xpath_pattern
    ):
        """Validate and fix options container XPath and pattern XPath if needed"""
        global driver

        # Both container and pattern are required
        if not options_container_x_path or not options_xpath_pattern:
            logger.warning(
                f"Missing container or pattern XPath for {self.title}. "
                f"Container: {options_container_x_path}, Pattern: {options_xpath_pattern}"
            )
            return self._extract_options_pattern_using_llm(
                prev_options_container_x_path=options_container_x_path,
                prev_options_xpath_pattern=options_xpath_pattern,
                failed_part=(
                    "both"
                    if not options_container_x_path and not options_xpath_pattern
                    else ("container" if not options_container_x_path else "pattern")
                ),
                question=self.question,
            )

        # Validate container XPath exists
        if not element_exists(options_container_x_path):
            logger.warning(
                f"Container XPath {options_container_x_path} not found for {self.title}. "
                f"Attempting to extract correct pattern..."
            )
            # Try to extract pattern using LLM
            return self._extract_options_pattern_using_llm(
                prev_options_container_x_path=options_container_x_path,
                prev_options_xpath_pattern=options_xpath_pattern,
                failed_part="container",
                question=self.question,
            )

        # Validate pattern matches at least one element (scoped to container)
        container_element = driver.find_element(By.XPATH, options_container_x_path)
        elements = container_element.find_elements(By.XPATH, options_xpath_pattern)
        if not elements:
            logger.warning(
                f"Pattern {options_xpath_pattern} matches no elements within container {options_container_x_path} for {self.title}. "
                f"Attempting to extract correct pattern..."
            )
            # Try to extract pattern using LLM
            return self._extract_options_pattern_using_llm(
                prev_options_container_x_path=options_container_x_path,
                prev_options_xpath_pattern=options_xpath_pattern,
                failed_part="pattern",
                question=self.question,
            )

        return options_container_x_path, options_xpath_pattern

    def _form_xpath_from_container(self, container_xpath):
        """
        Form xpath relative to container xpath if there's exactly one interactive element.

        Args:
            container_xpath: XPath of the container element

        Returns:
            str or None: XPath relative to container (e.g., container_xpath//input) if exactly
                        one interactive element found, None otherwise
        """
        global driver

        try:
            interactive_elements, tag_counts = get_interactive_elements_in_container(
                container_xpath
            )

            # Only form xpath if there's exactly one interactive element
            if len(interactive_elements) != 1:
                logger.info(
                    f"Container {container_xpath} has {len(interactive_elements)} interactive elements, "
                    f"not forming xpath from container for field {self.title}"
                )
                return None

            # Get the tag name of the single interactive element
            tag_name = interactive_elements[0].tag_name.lower()

            # Form xpath relative to container: container_xpath//tag_name
            relative_xpath = f"{container_xpath}//{tag_name}"

            logger.info(
                f"Formed xpath from container for field {self.title}: {relative_xpath}"
            )

            return relative_xpath
        except Exception as e:
            logger.warning(
                f"Error forming xpath from container {container_xpath} for field {self.title}: {e}"
            )
            return None

    def _extract_options_pattern_using_llm(
        self,
        prev_options_container_x_path=None,
        prev_options_xpath_pattern=None,
        failed_part=None,
        question=None,
    ):
        """Extract options container and pattern using LLM"""
        global driver

        if question:
            question_prompt = (
                f"There is a checkbox/radio button field on this page asking following question under the "
                f"title {self.title}\nQuestion - {question}"
            )
        else:
            question_prompt = f"There is a checkbox/radio button field on this page with title as following -\n{self.title}"

        # Try to find input block for title
        element_identified, user_input_element, computed_container_xpath = (
            find_input_block_for_title(
                self.title, container_xpath=self.container_x_path
            )
        )
        if user_input_element:
            container_html = user_input_element.get_attribute("outerHTML")
        else:
            container_html = minify_html_for_gpt_prompt(driver.page_source)

        user_prompt = (
            f"I have HTML of job application webpage for {self.parent_application_page.parent_job.title}."
            f"{question_prompt}\n"
            f"Following is the HTML containing the checkbox/radio button options:\n"
            f"{minify_html_for_gpt_prompt(container_html)}\n"
        )

        if prev_options_container_x_path or prev_options_xpath_pattern:
            user_prompt += f"\nIn previous attempt, I tried following XPaths but they didn't work:\n"
            if prev_options_container_x_path:
                user_prompt += f"Container XPath: {prev_options_container_x_path}\n"
            if prev_options_xpath_pattern:
                user_prompt += f"Pattern XPath: {prev_options_xpath_pattern}\n"

            if failed_part:
                if failed_part == "container":
                    user_prompt += (
                        f"The container XPath failed (element not found). Please provide a correct container XPath. "
                        f"The pattern XPath may be correct, but verify it works with the new container.\n"
                    )
                elif failed_part == "pattern":
                    user_prompt += (
                        f"The pattern XPath failed (no elements found when used within the container). "
                        f"The container XPath is correct. Please provide a correct pattern XPath that will find "
                        f"option elements within the container.\n"
                    )
                elif failed_part == "both":
                    user_prompt += f"Both container and pattern XPaths are missing or incorrect. Please provide correct XPaths.\n"
            else:
                user_prompt += f"Please provide correct XPaths that will work.\n"

        user_prompt += (
            f"Return the container XPath (parent element containing all options) and XPath pattern that will match ALL "
            f"option elements. IMPORTANT: The options_xpath_pattern will be used relative to the container element "
            f"(i.e., container_element.find_elements(By.XPATH, pattern)), so it must be a relative XPath pattern. "
            f"The XPath pattern should:\n"
            f"1. Be a relative XPath that works when used with container_element.find_elements(By.XPATH, pattern)\n"
            f"2. Not rely on HTML hierarchy\n"
            f"3. Use attributes like class, role, data-* attributes instead (avoid alphanumeric strings)\n"
            f"4. Return ONLY the actual clickable elements that handle option selection\n"
            f"5. For custom implementations, find the outermost clickable element that contains the option text\n"
            f"6. Look for elements with click handlers\n"
            f"7. The pattern should be relative to the container element, not an absolute XPath from the document root"
        )

        class OptionsPattern(BaseModel):
            options_container_x_path: str = Field(
                ...,
                description="XPath of the container element containing all checkbox/radio options",
            )
            options_xpath_pattern: str = Field(
                ...,
                description="XPath pattern that matches all individual option elements. This pattern will be used relative to the container element (i.e., container_element.find_elements(By.XPATH, pattern)), so it should be a relative XPath pattern.",
            )

        pattern_found, pattern_result = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=OptionsPattern,
        )

        if pattern_found:
            # Validate the extracted pattern (pattern must be scoped to container)
            container_xpath = pattern_result.options_container_x_path
            pattern_xpath = pattern_result.options_xpath_pattern
            if element_exists(container_xpath):
                container_element = driver.find_element(By.XPATH, container_xpath)
                elements = container_element.find_elements(By.XPATH, pattern_xpath)
                if elements:
                    return (
                        container_xpath,
                        pattern_xpath,
                    )

        raise Exception(
            f"Couldn't extract options pattern for {self.title} at "
            f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
        )

    def get_field_component(self):
        if not self.x_path:
            self._identify_x_path()

        if self.field_type == "date_field":
            from jobs.page_components.date_field import DateField

            component = DateField(
                title=self.title,
                question=self.question,
                category=self.category,
                parent_application_page=self.parent_application_page,
            )
            component.container_x_path = self.container_x_path
            return component

        if self.x_path:
            self.html_type, container_x_path = self.revalidate_component_type(
                x_path=self.x_path,
                html_type=self.html_type,
                field_title=self.title,
                job_title=self.parent_application_page.parent_job.title,
                options_container_x_path=self.options_container_x_path,
                options_xpath_pattern=self.options_xpath_pattern,
            )

            if self.html_type == "text_box":
                from jobs.page_components.text_input import TextInput

                component = TextInput(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    parent_application_page=self.parent_application_page,
                )
                component.container_x_path = self.container_x_path
                return component
            elif self.html_type == "dropdown" or self.html_type == "dropdown_button":
                from jobs.page_components.drop_down import DropDown

                component = DropDown(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    options_container_x_path=container_x_path,
                    parent_application_page=self.parent_application_page,
                )
                component.container_x_path = self.container_x_path
                return component
            elif self.html_type == "search_field":
                from jobs.page_components.search_field import SearchField

                component = SearchField(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    parent_application_page=self.parent_application_page,
                )
                component.container_x_path = self.container_x_path
                return component
            elif self.html_type == "radio_button":
                from jobs.page_components.radio_button import RadioButton

                component = RadioButton(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    options_container_x_path=self.options_container_x_path,
                    options_xpath_pattern=self.options_xpath_pattern,
                    parent_application_page=self.parent_application_page,
                )
                component.container_x_path = self.container_x_path
                return component
            elif self.html_type == "check_box":
                from jobs.page_components.check_box import CheckBox

                component = CheckBox(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    options_container_x_path=self.options_container_x_path,
                    options_xpath_pattern=self.options_xpath_pattern,
                    parent_application_page=self.parent_application_page,
                )
                component.container_x_path = self.container_x_path
                return component
            elif self.html_type == "date_field":
                from jobs.page_components.date_field import DateField

                return DateField(
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    parent_application_page=self.parent_application_page,
                )

            return None
        else:
            logger.warn(
                f"Working Xpath couldn't be extracted.\nInstance - {vars(self)}"
            )
            return None

    def revalidate_component_type(
        self,
        x_path,
        html_type,
        field_title,
        job_title,
        options_container_x_path=None,
        options_xpath_pattern=None,
    ):
        if html_type == "text_box":
            if self.category in [
                "first_name",
                "middle_name",
                "last_name",
                "full_name",
                "email",
                "phone_number_without_country_code",
                "password",
            ]:
                return "text_box", None

            from jobs.page_components.search_field import SearchField

            is_search_field = SearchField.validate_search_field(
                x_path, field_title, container_xpath=self.container_x_path
            )
            if is_search_field:
                return "search_field", None

            is_calendar_widget_present = self.validate_calendar_widget(
                x_path,
                field_title,
                text_to_click=self.title_to_click,
                container_xpath=self.container_x_path,
            )
            if is_calendar_widget_present:
                return "date_field", None

            is_container_present, container_x_path = self.validate_options_container(
                x_path,
                field_title,
                job_title,
                text_to_click=self.title_to_click,
                container_xpath=self.container_x_path,
            )
            if is_container_present and container_x_path:
                return "dropdown", container_x_path

            # try once more if there is any button inside the text box element
            element_identified, user_input_element, computed_container_xpath = (
                find_input_block_for_title(
                    field_title, container_xpath=self.container_x_path
                )
            )
            if element_identified and user_input_element:
                try:
                    button = user_input_element.find_element(By.TAG_NAME, "button")
                    button_x_path = get_element_xpath(button, xpath_type="relative")

                    is_container_present, container_x_path = (
                        self.validate_options_container(
                            button_x_path,
                            field_title,
                            job_title,
                            text_to_click=self.title_to_click,
                            container_xpath=self.container_x_path,
                        )
                    )
                    if is_container_present and container_x_path:
                        self.x_path = button_x_path
                        return "dropdown", container_x_path
                except NoSuchElementException:
                    pass

            return "text_box", None

        elif (html_type == "check_box") or (
            (html_type == "button")
            and (options_container_x_path or options_xpath_pattern)
        ):
            from jobs.page_components.check_box import CheckBox

            multiple_correct = CheckBox.validate_checkbox(
                options_container_x_path,
                options_xpath_pattern,
                field_title,
                container_xpath=self.container_x_path,
            )
            if not multiple_correct:
                return "radio_button", None
            else:
                return "check_box", None

        elif html_type == "dropdown" or html_type == "dropdown_button":
            is_container_present, container_x_path = self.validate_options_container(
                x_path,
                field_title,
                job_title,
                text_to_click=self.title_to_click,
                container_xpath=self.container_x_path,
            )
            if is_container_present:
                return "dropdown", container_x_path

        return html_type, None

    @classmethod
    def validate_options_container(
        cls, x_path, field_title, job_title, text_to_click=None, container_xpath=None
    ):
        dropdown_element = get_unique_element_by_xpath(
            x_path, title=field_title, container_xpath=container_xpath
        )
        dropdown_type = ApplicationField.identify_options_container_type(
            dropdown_element
        )
        if dropdown_type == "select-option":
            return True, None

        simulate_empty_area_click(
            text_to_click=text_to_click or field_title, container_xpath=container_xpath
        )

        start_dom_mutation_observer()

        from jobs import Button

        try:
            element_button = Button(
                x_path=x_path,
                button_type="dropdown",
                title=field_title,
                parent_application_page=None,
            )
            element_button.container_x_path = container_xpath
            element_button.proceed()
        except (ElementClickInterceptedException, ElementNotInteractableException):
            element_button = Button(
                x_path=find_clickable_parent_xpath(x_path),
                button_type="dropdown",
                title=field_title,
                parent_application_page=None,
            )
            element_button.container_x_path = container_xpath
            element_button.proceed()

        observed_elements = get_observed_elements()

        if observed_elements:
            is_container_present, container_x_path = cls.identify_options_container(
                job_title=job_title,
                field_title=field_title,
                field_x_path=x_path,
                observed_elements=observed_elements,
                html_type="dropdown",
            )
            if is_container_present:
                simulate_empty_area_click(
                    text_to_click=text_to_click or field_title,
                    container_xpath=container_xpath,
                )
                if is_element_visible(container_x_path):
                    simulate_empty_area_click()
                return True, container_x_path

        if dropdown_element.tag_name.lower() == "input":
            start_dom_mutation_observer()

            # send vowels to trigger options loading for cases where just click is not enough
            for vowel in "aeiou":
                dropdown_element.send_keys(vowel)
                time.sleep(0.5)
                dropdown_element.send_keys("\ue003")  # Backspace key

            observed_elements = get_observed_elements()

            if observed_elements:
                is_container_present, container_x_path = cls.identify_options_container(
                    job_title=job_title,
                    field_title=field_title,
                    field_x_path=x_path,
                    observed_elements=observed_elements,
                    html_type="dropdown",
                )
                if is_container_present:
                    simulate_empty_area_click(
                        text_to_click=text_to_click or field_title,
                        container_xpath=container_xpath,
                    )
                    if is_element_visible(container_x_path):
                        simulate_empty_area_click()
                    return True, container_x_path

        simulate_empty_area_click(
            text_to_click=text_to_click or field_title, container_xpath=container_xpath
        )
        return False, None

    @classmethod
    def validate_calendar_widget(
        cls, x_path, field_title, text_to_click=None, container_xpath=None
    ):
        simulate_empty_area_click(
            text_to_click=text_to_click or field_title, container_xpath=container_xpath
        )

        start_dom_mutation_observer()

        from jobs import Button

        try:
            element_button = Button(
                x_path=x_path,
                button_type="calendar",
                title=field_title,
                parent_application_page=None,
            )
            element_button.container_x_path = container_xpath
            element_button.proceed()
        except (ElementClickInterceptedException, ElementNotInteractableException):
            element_button = Button(
                x_path=find_clickable_parent_xpath(x_path),
                button_type="calendar",
                title=field_title,
                parent_application_page=None,
            )
            element_button.container_x_path = container_xpath
            element_button.proceed()

        observed_elements = get_observed_elements()

        is_calendar_widget_present = False
        if observed_elements:
            from jobs.page_components.date_field import DateField

            is_calendar_widget_present = DateField.identify_calendar_using_regex(
                observed_elements
            )

        simulate_empty_area_click(
            text_to_click=text_to_click or field_title, container_xpath=container_xpath
        )
        return is_calendar_widget_present

    @staticmethod
    def _format_list_field(list_field):
        """Convert list/array to human-readable string format."""
        if not list_field:
            return None

        if isinstance(list_field, list):
            if len(list_field) == 0:
                return None
            return "\n".join(f"- {item}" for item in list_field if item)

        return list_field

    @classmethod
    def get_field_value(cls, field_category, user):
        if field_category == "first_name":
            return user.first_name
        elif field_category == "middle_name":
            return user.middle_name
        elif field_category == "last_name":
            return user.last_name
        elif field_category == "full_name":
            return user.name
        elif field_category in ["email", "username"]:
            return user.email
        elif field_category == "password":
            return user.password
        elif field_category == "salutation_prefix":
            return user.parsed_resume.get("personal_details", {}).get("salutation")
        elif field_category == "phone_country_code":
            return user.phone_country_code
        elif field_category == "phone_number_without_country_code":
            return user.phone_number
        elif field_category == "country":
            return user.country
        elif field_category == "city":
            return user.city
        elif field_category == "state":
            return user.state
        elif "_job_title__" in field_category and re.search(r"\d$", field_category):
            entry_no = int(field_category.split("__")[-1])
            info = user.parsed_resume.get("work_experience", [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                return info.get("job_title")
        elif "_company_name__" in field_category and re.search(r"\d$", field_category):
            entry_no = int(field_category.split("__")[-1])
            info = user.parsed_resume.get("work_experience", [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                return info.get("company_name")
        elif "_location__" in field_category and re.search(r"\d$", field_category):
            entry_no = int(field_category.split("__")[-1])
            category = field_category.split("__")[0]
            info = user.parsed_resume.get(category, [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                return info.get("location")
        elif "_start_date__" in field_category and re.search(r"\d$", field_category):
            entry_no = int(field_category.split("__")[-1])
            category = field_category.split("__")[0]
            info = user.parsed_resume.get(category, [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                return info.get("start_date")
        elif "_end_date__" in field_category and re.search(r"\d$", field_category):
            entry_no = int(field_category.split("__")[-1])
            category = field_category.split("__")[0]
            info = user.parsed_resume.get(category, [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                return info.get("end_date")
        elif "_responsibilities__" in field_category and re.search(
            r"\d$", field_category
        ):
            entry_no = int(field_category.split("__")[-1])
            info = user.parsed_resume.get("work_experience", [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                responsibilities = info.get("responsibilities")
                return cls._format_list_field(responsibilities)
        elif "_achievements__" in field_category and re.search(r"\d$", field_category):
            entry_no = int(field_category.split("__")[-1])
            info = user.parsed_resume.get("work_experience", [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                achievements = info.get("achievements")
                return cls._format_list_field(achievements)
        elif "_experience_related_url__" in field_category and re.search(
            r"\d$", field_category
        ):
            entry_no = int(field_category.split("__")[-1])
            info = user.parsed_resume.get("work_experience", [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                return info.get("experience_related_url")
        elif "_industry__" in field_category and re.search(r"\d$", field_category):
            entry_no = int(field_category.split("__")[-1])
            info = user.parsed_resume.get("work_experience", [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                return info.get("industry")
        elif "_employment_type__" in field_category and re.search(
            r"\d$", field_category
        ):
            entry_no = int(field_category.split("__")[-1])
            info = user.parsed_resume.get("work_experience", [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                return info.get("employment_type")
        elif "_degree__" in field_category and re.search(r"\d$", field_category):
            entry_no = int(field_category.split("__")[-1])
            info = user.parsed_resume.get("education", [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                return info.get("degree")
        elif "_details__" in field_category and re.search(r"\d$", field_category):
            entry_no = int(field_category.split("__")[-1])
            category = field_category.split("__")[0]
            info = user.parsed_resume.get(category, [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                return info.get("details")
        elif "_institution__" in field_category and re.search(r"\d$", field_category):
            entry_no = int(field_category.split("__")[-1])
            info = user.parsed_resume.get("education", [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                return info.get("institution")
        elif "_field_of_study__" in field_category and re.search(
            r"\d$", field_category
        ):
            entry_no = int(field_category.split("__")[-1])
            info = user.parsed_resume.get("education", [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                return info.get("field_of_study")

        return None

    @classmethod
    def identify_options_container(
        cls,
        field_title,
        field_x_path,
        observed_elements,
        html_type,
        job_title,
    ):
        """Identify if any observed element is an options container and return its XPath"""
        global driver

        observed_elements = [
            el
            for el in observed_elements
            if not is_stale(el) and is_element_visible(get_element_xpath(el))
        ]

        if not observed_elements:
            logger.warn(
                f"No observed elements found for field title {field_title} at XPath {field_x_path} "
                f"for job title {job_title}. This might be because the field is not interactive or "
                f"the page didn't load properly."
            )
            return False, None

        options_container_elements = cls._identify_options_container_using_regex(
            observed_elements
        )

        if not options_container_elements:
            return False, None
        elif len(options_container_elements) == 1:
            container_x_path = get_element_xpath(
                options_container_elements[0], xpath_type="relative"
            )
            return True, container_x_path
        else:
            logger.warn(
                f"Multiple options container elements found for field title {field_title} at XPath {field_x_path} "
                f"for job title {job_title}. Using LLM to identify the correct one."
            )
            return cls._identify_options_container_using_llm(
                field_title=field_title,
                field_x_path=field_x_path,
                observed_elements=observed_elements,
                html_type=html_type,
                job_title=job_title,
            )

    @staticmethod
    def _identify_options_container_using_regex(elements):
        options_containers = []
        for el in elements:
            container_type = ApplicationField.identify_options_container_type(el)
            if container_type:
                options_containers.append(el)

        return options_containers

    @classmethod
    def identify_options_container_type(cls, element):
        """Identify the type of options container based on its HTML structure"""
        try:
            outer_html = element.get_attribute("outerHTML")
        except Exception as e:
            logger.warn(f"Error getting outerHTML for element {element}. Error: {e}")
            return None

        if re.search(
            r"<select[^>]*>(?:\s*<option[^>]*>.*?</option>\s*)+</select>",
            outer_html,
            re.DOTALL | re.IGNORECASE,
        ):
            return "select-option"
        elif re.search(
            r"<ul[^>]*>(?:\s*<li[^>]*>.*?</li>\s*)+</ul>",
            outer_html,
            re.DOTALL | re.IGNORECASE,
        ):
            return "ul-li"
        elif re.search(
            r"<ol[^>]*>(?:\s*<li[^>]*>.*?</li>\s*)+</ol>",
            outer_html,
            re.DOTALL | re.IGNORECASE,
        ):
            return "ol-li"
        elif re.search(
            r'<(?P<outer_tag>\w+)[^>]*\srole=["\']listbox["\'][^>]*>'
            r'(?:.*?<\w+[^>]*\srole=["\']option["\'][^>]*>.*?</\w+>)+'
            r".*?</(?P=outer_tag)>",
            outer_html,
            re.DOTALL | re.IGNORECASE,
        ):
            return "listbox-option"
        elif re.search(
            r'<(?P<outer_tag>\w+)[^>]*\srole=["\']menu["\'][^>]*>'
            r'(?:.*?<\w+[^>]*\srole=["\']menuitem["\'][^>]*>.*?</\w+>)+'
            r".*?</(?P=outer_tag)>",
            outer_html,
            re.DOTALL | re.IGNORECASE,
        ):
            return "menu-menuitem"
        elif re.search(
            r'<div[^>]*class=["\'][^"\']*dropdown-container[^"\']*["\'][^>]*>'
            r'(?:.|\n)*?<div[^>]*class=["\'][^"\']*dropdown-results[^"\']*["\'][^>]*>'
            r'(?:.|\n)*?<div[^>]*class=["\'][^"\']*dropdown-location[^"\']*["\'][^>]*>.*?</div>',
            outer_html,
            re.DOTALL | re.IGNORECASE,
        ):
            return "custom-div-dropdown"
        else:
            return None

    @staticmethod
    def _identify_options_container_using_llm(
        field_title,
        field_x_path,
        observed_elements,
        html_type,
        job_title,
        retry=False,
        prev_xpath=None,
    ):
        global driver

        class ContainerValidation(BaseModel):
            is_options_container_present: bool = Field(
                ...,
                description=f"Whether any of the observed elements is an options / search suggestions container "
                f"strictly for the field title {field_title} and nothing else",
            )
            options_container_xpath: str | None = Field(
                default=None,
                description="XPath of the observed element that contains the options / search suggestions. Should be "
                "returned only if is_container is True.",
            )

        observed_elements_html = "\n".join(
            f"{i+1}. Element {i+1} - {minify_html_for_gpt_prompt(el.get_attribute('outerHTML'))}"
            for i, el in enumerate(observed_elements)
        )

        if not observed_elements_html.strip():
            return False, None

        # Generic prompts that work across different websites and HTML structures
        type_specific_prompts = {
            "dropdown": (
                f"1. Element appears to be a dropdown or list container strictly for the field title {field_title} and "
                f"nothing else\n"
                "2. Element has a container-like structure that holds selectable items. Contains only selectable items "
                "(all children look alike, like a menu of choices), and nothing else.\n"
                "3. Often has container or list-related attributes or styles. "
                "(e.g. <ul>/<li> or ARIA role='listbox'/role='option' etc.)\n"
            ),
            "search_field": (
                f"1. Element appears to be a suggestions or results container strictly for the field title "
                f"{field_title} and nothing else\n"
                "2. Element has a container-like structure that holds selectable items. Contains only selectable items "
                "(all children look alike, like a menu of choices), and nothing else.\n"
                "3. Often has attributes or styles related to suggestions/results display. "
                "(e.g. <ul>/<li> or ARIA role='listbox'/role='option' etc.)\n"
            ),
        }

        validation_prompt = type_specific_prompts[html_type]

        user_prompt = (
            f"In an HTML of job application webpage for {job_title} "
            f"there is a field with title {field_title} at XPath {field_x_path}.\n"
            f"When this field was clicked or typed in, javascript mutation observer observed that following elements "
            f"were added or modified in the DOM -\n{observed_elements_html}\n"
            f"A. Determine if any of the observed elements appears to be an options / search suggestions container "
            f"strictly for the field title {field_title} and nothing else. Consider:\n"
            f"{validation_prompt}\n"
            f"B. If it is an options / search suggestions container, identify which element number (1, 2, etc.) "
            f"contains the options / search suggestions. While identifying the container, very carefully look "
            f"for presence of options / search suggestions like elements inside the container.\n"
            f"If there is no strong signal then return false for is_options_container_present."
        )

        if retry and prev_xpath:
            user_prompt += (
                f"\n\nIn previous try you gave following XPath for the container but the element "
                f"couldn't be found / isn't visible using the XPath. So, find correct XPath for the container.\n"
                f"Previous XPath - {prev_xpath}\n"
            )

        validation_found, validation = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=ContainerValidation,
        )

        if validation_found:
            if validation.is_options_container_present:
                if validation.options_container_xpath and is_element_visible(
                    validation.options_container_xpath
                ):
                    return (
                        validation.is_options_container_present,
                        validation.options_container_xpath,
                    )
                elif not retry:
                    return ApplicationField._identify_options_container_using_llm(
                        field_title=field_title,
                        field_x_path=field_x_path,
                        observed_elements=observed_elements,
                        html_type=html_type,
                        job_title=job_title,
                        retry=True,
                        prev_xpath=validation.options_container_xpath,
                    )

        return False, None

    @classmethod
    def extract_field_answer(
        cls,
        job_title,
        job_url,
        company_name,
        field_title,
        answer_type,
        question=None,
        multiple_correct=False,
        closest_answer=None,
        answer_format=None,
        options=[],
        parsed_resume=None,
    ):
        if question:
            user_prompt = (
                f"While filling job application for {job_title} at a company called "
                f"{company_name}, I need you to help me answer following question under the field title - {field_title}"
                f"\nQuestion - {question}\n"
            )
        else:
            question = field_title
            user_prompt = (
                f"While filling job application for {job_title} at a company called "
                f"{company_name}, I need you to help me answer following question (field title) -\n{question}\n"
            )

        if answer_type == "enum":
            options_list = "\n".join(
                f"{i + 1}. {option}" for i, option in enumerate(options)
            )

            if closest_answer:
                user_prompt += (
                    f"Answer to the question is '{closest_answer}', but I have to select out of following "
                    f"options -\n{options_list}\n"
                )
            else:
                user_prompt += (
                    f"I have to select an option out of following options -\n{options_list}\n If based on "
                    f"the given context there is no answer that matches then pick the option which is "
                    f"safest from a candidate's point of view, meaning it should not prompt more questions."
                )

            FieldAnswerOptions = Enum(
                "FieldAnswerOptions",
                {
                    (
                        text
                        if text.isidentifier() and text
                        else text.replace(" ", "_") if text else f"Option_{i}"
                    ): text
                    for i, text in enumerate(options)
                },
            )

            if len(options) > 250:

                class FieldAnswer(BaseModel):
                    answer: str = Field(
                        ...,
                        description="Correct or most close but option out of the given options. Don't modify the option "
                        "text at all. Just return the option text strictly as it is. Keep in mind serial "
                        "number of the option is not important, just return the option text.",
                    )

            elif multiple_correct:

                class FieldAnswer(BaseModel):
                    answers: List[FieldAnswerOptions] = Field(
                        ...,
                        description="Correct options based on input",
                    )

            else:

                class FieldAnswer(BaseModel):
                    answer: FieldAnswerOptions = Field(
                        ...,
                        description="Correct option based on input",
                    )
                    # add boolean field to the class FieldAnswer to indicate if answer is found with great confidence. Add in this if block only
                    is_answer_found_with_great_confidence: bool = Field(
                        ...,
                        description="Indicates if the answer is found with great confidence. "
                        "If true then answer is correct and should be used. If false then answer is not "
                        "confident enough and should not be used.",
                    )

        elif answer_type == "text":
            user_prompt += (
                f"Answer should be precise and as short as you can write. Be very careful about following -\n"
                f"If field title is very short like one word or two then answer should also be of similar length. If "
                f"field title seems to be expecting bit elaborative answer then answer can be little verbose but not "
                f"too much. Also answer should reflect that these are my words, not Chat GPT's words. Answer like human"
                f" candidate and not a language model. I am going to feed your answer exactly same into the job "
                f"application so answer accordingly. If based on the given context there is no answer then don't "
                f"answer the question at all.\n"
            )

            if answer_format:
                user_prompt += (
                    f"Answer should strictly be in following format with no extra text except for what is "
                    f"mentioned in the format. Format - {answer_format}\n"
                )

                class FieldAnswer(BaseModel):
                    answer: Optional[str] = Field(
                        ...,
                        description=f"Correct answer based on user data. Answer should be precise and as short as you "
                        f"can write. Answer should strictly be in following format with no extra text "
                        f"except for what is mentioned in the format. Format - {answer_format}",
                    )

            else:

                class FieldAnswer(BaseModel):
                    answer: Optional[str] = Field(
                        ...,
                        description="Correct answer based on user data. Answer should be precise and as short as you "
                        "can write. Also answer should reflect that these are my words, not Chat GPT's "
                        "words.",
                    )

        else:
            raise Exception(f"Unknown parameter - {answer_type}")

        if closest_answer is None:
            user_prompt += (
                f"Following is context having user resume data using which you have to find answer -\n"
                f"{parsed_resume}\n"
            )
        else:
            user_prompt += f"Closest answer to the question is {closest_answer}.\n"

        user_prompt += f"""Following general information about the application - 
        1. Job source - LinkedIn
        2. If current user email is "{config['admin_email']}" and questions is if you are currently working or studying
         here then always answer as "No". If end date is asked for the same work experience or education qualification 
         then answer as per today's date.
        
        Now based on all above instructions, give me correct answer for the question.
        """

        field_answer_found, field_answer = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=FieldAnswer,
        )
        if field_answer_found:
            if answer_type == "text":
                return field_answer.answer, True
            elif (answer_type == "enum") and len(options) > 250:
                return re.sub(r"^\d+\.\s+", "", field_answer.answer), True
            elif multiple_correct:
                return [answer.value for answer in field_answer.answers], True
            else:
                return (
                    field_answer.answer.value,
                    field_answer.is_answer_found_with_great_confidence,
                )
        else:
            logger.error(
                f"Couldn't extract field answer for {job_title}. URL - {job_url}"
            )
            return None, False

    @classmethod
    def extract_correct_x_path(
        cls,
        prev_x_path,
        prompt,
        job_title,
        job_url,
        html=None,
        xpath_count=15,
        container_x_path=None,
    ):
        global driver

        logger.info(
            f"Extracting correct x_path for following incorrect x_path - {prev_x_path}\n"
            f"Job Title - {job_title}\n"
            f"Job URL - {job_url}"
        )

        user_prompt = (
            f"Following HTML page is job application webpage for {job_title}. "
            f"HTML: {html if html else minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"In my another GPT call you gave following x_path for a field / element but when I tried to find the "
            f"element using "
            f"that x_path, it couldn't be found. So, find correct x_path for the same field / element. After finding "
            f"correct "
            f"x_path, try to assess yourself if the x_path is correct or not. If it is not correct then try again to "
            f"find the correct x_path.\n"
            f"Previous x_path - {prev_x_path}\n"
        )

        if container_x_path:
            user_prompt += (
                f"CRITICAL: Ideally, the target element should exist within a container element with XPath: {container_x_path}. "
                f"When searching for the correct x_path, prioritize finding the element within this container.\n"
            )

        user_prompt += f"{prompt}\n"

        class XPathEntry(BaseModel):
            x_path: str = Field(
                ...,
                description=f"Possible correct XPath of the element which can be used in selenium chrome driver to "
                "search the element. Try to give short & simple XPaths which point to desired element. Avoid long "
                "ancestor chains, multiple contains(@class,…) filters, or deep nesting because long XPaths can be brittle.",
            )
            uses_alphanumeric: bool = Field(
                ...,
                description="Whether this XPath uses alphanumeric strings (like 'id-123abc', 'element-456xyz', "
                "or any attribute values containing random alphanumeric characters) that may change when the page reloads. "
                "Set to True if the XPath contains such patterns, False otherwise.",
            )

        class CorrectXPath(BaseModel):
            possible_x_paths: List[XPathEntry] = Field(
                ...,
                min_items=xpath_count,
                max_items=xpath_count,
                description=f"{xpath_count} Possible correct XPaths of the element. For each XPath, provide the x_path string "
                "and indicate whether it uses_alphanumeric patterns.",
            )

        correct_x_path_found, correct_x_path = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=CorrectXPath,
            model="complex",
        )
        if correct_x_path_found:
            # Helper function to check if element is inside container
            def is_in_container(x_path_entry):
                if not container_x_path:
                    return False
                try:
                    if not element_exists(x_path_entry.x_path) or not element_exists(
                        container_x_path
                    ):
                        return False
                    element = driver.find_element(By.XPATH, x_path_entry.x_path)
                    container_element = driver.find_element(By.XPATH, container_x_path)
                    is_contained = driver.execute_script(
                        "return arguments[0].contains(arguments[1]);",
                        container_element,
                        element,
                    )
                    return is_contained
                except Exception:
                    return False

            # Helper function to check if xpath exists only once on the page
            def is_unique_on_page(x_path_entry):
                try:
                    elements = driver.find_elements(By.XPATH, x_path_entry.x_path)
                    return len(elements) == 1
                except Exception:
                    return False

            # Sort: prioritize non-alphanumeric first, then prioritize in-container,
            # then prioritize unique (exists only once) when in container
            # Sort key: (uses_alphanumeric, not_in_container, in_container_and_not_unique)
            # - False (non-alphanumeric) comes before True (alphanumeric)
            # - False (in container) comes before True (not in container)
            # - False (unique when in container) comes before True (not unique when in container)
            if container_x_path:

                def sort_key(x):
                    in_container = is_in_container(x)
                    unique = is_unique_on_page(x)
                    # Only consider uniqueness when element is in container
                    # in_container_and_not_unique = True means it's in container but not unique
                    in_container_and_not_unique = in_container and not unique
                    return (
                        x.uses_alphanumeric,
                        not in_container,
                        in_container_and_not_unique,
                    )

                sorted_xpaths = sorted(correct_x_path.possible_x_paths, key=sort_key)
            else:
                sorted_xpaths = sorted(
                    correct_x_path.possible_x_paths, key=lambda x: x.uses_alphanumeric
                )

            x_paths = "\n".join(
                f"{i + 1}. {entry.x_path} "
                f"{'[uses alphanumeric]' if entry.uses_alphanumeric else '[no alphanumeric]'} "
                f"{'[in container]' if container_x_path and is_in_container(entry) else ''}"
                f"{' [unique on page]' if container_x_path and is_in_container(entry) and is_unique_on_page(entry) else ''}"
                for i, entry in enumerate(sorted_xpaths)
            )
            priority_note = "non-alphanumeric first"
            if container_x_path:
                priority_note += ", then prioritize in-container, then prioritize unique (exists only once) when in container"
            logger.info(
                f"Found {len(sorted_xpaths)} possible correct XPaths for the element.\n"
                f"Possible XPaths (prioritized: {priority_note}) -\n{x_paths}"
            )

            # Check xpaths in priority order
            for entry in sorted_xpaths:
                if element_exists(entry.x_path):
                    container_status = ""
                    if container_x_path:
                        in_container = is_in_container(entry)
                        unique = is_unique_on_page(entry)
                        container_status = f" {'(in container)' if in_container else '(not in container)'}"
                        if in_container and unique:
                            container_status += " (unique on page)"
                    logger.info(
                        f"Found correct x_path - {entry.x_path} "
                        f"{'(uses alphanumeric)' if entry.uses_alphanumeric else '(no alphanumeric)'}"
                        f"{container_status}"
                    )
                    return entry.x_path

        logger.error(
            f"Correct x_path couldn't be found for {job_title}. URL - {job_url}"
        )
        return None
