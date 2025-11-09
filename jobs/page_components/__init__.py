import time
from abc import ABC, abstractmethod
import re
import importlib
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, List
from selenium.common import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    NoSuchElementException,
)
from selenium.webdriver.common.by import By

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
)
from utilities.logging import get_logger
from utilities import pascal_to_snake_casing, retry
from utilities import constants
from utilities.gpt import get_gpt_response


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
    ):
        self.parent_application_page = parent_application_page
        self.title = title
        self.title_to_click = title_to_click or title
        self.question = question
        self.category = category
        self.x_path = x_path

        self.field_type = None
        self.html_type = None
        self.format = None
        self.options = []

    def _identify_x_path(self, retry=False, prev_x_path=None):
        global driver

        logger.info(
            f"Identifying x_path for application field {self.title} & {self.category}..."
        )

        user_input_element = None
        try:
            element_identified, user_input_element = find_input_block_for_title(
                self.title
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

        class Option(BaseModel):
            text: str = Field(
                ...,
                description="Exact text of the checkbox / radio button / normal option",
            )
            x_path: str = Field(
                ...,
                description="XPath of the clickable checkbox / radio button which can be used in selenium "
                "chrome driver to search & click the checkbox / radio button. If checkbox / radio button is "
                "different from option text then give xpath of the clickable checkbox / radio button element",
            )

        if user_input_element:

            class ApplicationFieldInfo(BaseModel):
                x_path: Optional[str] = Field(
                    ...,
                    description="XPath of the application field which can be used in selenium chrome driver to search the "
                    "application field. Don't use HTML hierarchy to construct XPath. XPath of the first field "
                    "if there are many.",
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
                options: Optional[List[Option]] = Field(
                    ...,
                    description="Clickable options to select from if the field_type is either checkbox or radio button",
                )
                format: Optional[str] = Field(
                    ...,
                    description="Format of field answer if the field requires its answer to be in some specific format. "
                    "e.g. date format etc.",
                )

        else:

            class ApplicationFieldInfo(BaseModel):
                x_path: Optional[str] = Field(
                    ...,
                    description="XPath of the application field which can be used in selenium chrome driver to search the "
                    "application field. Don't use HTML hierarchy to construct XPath. XPath of the first field "
                    "if there are many.",
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
                options: Optional[List[Option]] = Field(
                    ...,
                    description="Clickable options to select from if the field_type is either checkbox or radio button",
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

        application_field_found, application_field = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=ApplicationFieldInfo,
        )
        if application_field_found:
            if not application_field.is_field_match_confident:
                logger.warn(
                    f"Field match is not confident for {self.title} & {self.category} in "
                    f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                )
                return None

            if (
                application_field.x_path.startswith("/")
                and not application_field.x_path.startswith("//")
                and not element_exists(application_field.x_path)
            ):
                application_field.x_path = "/" + application_field.x_path

            if (
                (application_field.field_type.value != "date_field")
                and not (
                    application_field.html_type != "dropdown"
                    and application_field.options
                )
                and not element_exists(application_field.x_path)
            ):
                logger.warn(
                    f"Element with x_path {application_field.x_path} doesn't exist for "
                    f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                )
                prompt = (
                    f"The x_path that we are trying to extract is of following application field -\n"
                    f"Field title - {self.title}\n"
                    f"Field category - {self.category}\n"
                )
                correct_x_path = self.extract_correct_x_path(
                    prev_x_path=application_field.x_path,
                    prompt=prompt,
                    job_title=self.parent_application_page.parent_job.title,
                    job_url=self.parent_application_page.url,
                    html=minified_html,
                )
                if not correct_x_path:
                    return None
                else:
                    application_field.x_path = correct_x_path

            if self.parent_application_page.component_x_path_exists(
                application_field.x_path
            ):
                logger.warn(
                    f"Page component with following x_path already exists - {application_field.x_path}"
                )
                return

            self.x_path = application_field.x_path
            self.field_type = application_field.field_type.value
            self.html_type = application_field.html_type.value
            self.format = application_field.format

            if not user_input_element:
                self.title = application_field.exact_field_title or self.title

            if application_field.options:
                self.options = [
                    {"text": option.text, "x_path": option.x_path}
                    for option in application_field.options
                ]
                self.options = self._validate_options_xpaths(
                    self.options, minified_html
                )
        elif not retry:
            self._identify_x_path(retry=True)
        else:
            raise Exception(
                f"Couldn't extract following application field {self.category} for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

        return None

    def _validate_options_xpaths(self, options, html):
        all_xpaths_valid = True
        for option in options:
            if not element_exists(option["x_path"]):
                all_xpaths_valid = False
                break

        if all_xpaths_valid:
            return options

        xpath_prompt = (
            f"The x_path that we are trying to find is of an option under following title - \n"
            f"Field title - {self.title}\n"
            f"The option is following - \n"
            f"Option text - {option['text']}"
        )

        correct_xpath = ApplicationField.extract_correct_x_path(
            prev_x_path=option["x_path"],
            prompt=xpath_prompt,
            job_title=self.parent_application_page.parent_job.title,
            job_url=self.parent_application_page.url,
            html=html,
            xpath_count=20,
        )
        if not correct_xpath:
            raise Exception(
                f"Couldn't extract correct x_path for the option {option['text']} under title {option['x_path']} for "
                f"url {self.parent_application_page.parent_job.url}."
            )

        options_prompt = "\n".join(f"- {option['text']}" for option in options)
        user_prompt = (
            f"Following HTML is of job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {html}\n"
            f"The webpage has following application field for applying to the job -\n"
            f"Field title - {self.title}\n"
            f"Field category - {self.category}\n"
            f"The field has following options - \n"
            f"{options_prompt}\n"
            f"For the option with text as {option['text']}, following is the correct xpath - {correct_xpath}\n"
            f"Fetch the xpath for all above given options, in strictly same pattern as the above given xpath."
        )

        class Option(BaseModel):
            text: str = Field(..., description="Exact text of the option")
            x_path: str = Field(
                ...,
                description=f"XPath of the option using following pattern - {correct_xpath}",
            )

        class Options(BaseModel):
            options: List[Option] = Field(
                ...,
                description="Options with text and x_paths",
            )

        options_xpaths_found, options = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=Options,
        )
        if options_xpaths_found:
            return [
                {"text": option.text, "x_path": option.x_path}
                for option in options.options
            ]
        else:
            raise Exception(
                f"Couldn't extract correct x_paths for the options under title {self.title} for "
                f"url {self.parent_application_page.parent_job.url}."
            )

    def get_field_component(self):
        if not self.x_path:
            self._identify_x_path()

        if self.field_type == "date_field":
            from jobs.page_components.date_field import DateField

            return DateField(
                title=self.title,
                question=self.question,
                category=self.category,
                parent_application_page=self.parent_application_page,
            )

        if self.x_path:
            self.html_type, container_x_path = self.revalidate_component_type(
                x_path=self.x_path,
                html_type=self.html_type,
                field_title=self.title,
                job_title=self.parent_application_page.parent_job.title,
                options=self.options,
            )

            if self.html_type == "text_box":
                from jobs.page_components.text_input import TextInput

                return TextInput(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    parent_application_page=self.parent_application_page,
                )
            elif self.html_type == "dropdown" or self.html_type == "dropdown_button":
                from jobs.page_components.drop_down import DropDown

                return DropDown(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    options_container_x_path=container_x_path,
                    parent_application_page=self.parent_application_page,
                )
            elif self.html_type == "search_field":
                from jobs.page_components.search_field import SearchField

                return SearchField(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    parent_application_page=self.parent_application_page,
                )
            elif self.html_type == "radio_button":
                from jobs.page_components.radio_button import RadioButton

                return RadioButton(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    options=self.options,
                    parent_application_page=self.parent_application_page,
                )
            elif self.html_type == "check_box":
                from jobs.page_components.check_box import CheckBox

                return CheckBox(
                    x_path=self.x_path,
                    title=self.title,
                    question=self.question,
                    category=self.category,
                    options=self.options,
                    parent_application_page=self.parent_application_page,
                )
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
        self, x_path, html_type, field_title, job_title, options=[]
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

            is_search_field = SearchField.validate_search_field(x_path, field_title)
            if is_search_field:
                return "search_field", None

            is_calendar_widget_present = self.validate_calendar_widget(
                x_path, field_title, text_to_click=self.title_to_click
            )
            if is_calendar_widget_present:
                return "date_field", None

            is_container_present, container_x_path = self.validate_options_container(
                x_path, field_title, job_title, text_to_click=self.title_to_click
            )
            if is_container_present and container_x_path:
                return "dropdown", container_x_path

            # try once more if there is any button inside the text box element
            element_identified, user_input_element = find_input_block_for_title(
                field_title
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
                        )
                    )
                    if is_container_present and container_x_path:
                        self.x_path = button_x_path
                        return "dropdown", container_x_path
                except NoSuchElementException:
                    pass

            return "text_box", None

        elif (html_type == "check_box") or ((html_type == "button") and options):
            from jobs.page_components.check_box import CheckBox

            multiple_correct = CheckBox.validate_checkbox(options, field_title)
            if not multiple_correct:
                return "radio_button", None
            else:
                return "check_box", None

        elif html_type == "dropdown" or html_type == "dropdown_button":
            is_container_present, container_x_path = self.validate_options_container(
                x_path, field_title, job_title, text_to_click=self.title_to_click
            )
            if is_container_present:
                return "dropdown", container_x_path

        return html_type, None

    @classmethod
    def validate_options_container(
        cls, x_path, field_title, job_title, text_to_click=None
    ):
        dropdown_element = get_unique_element_by_xpath(x_path, title=field_title)
        dropdown_type = ApplicationField.identify_options_container_type(
            dropdown_element
        )
        if dropdown_type == "select-option":
            return True, None

        simulate_empty_area_click(text_to_click=text_to_click or field_title)

        start_dom_mutation_observer()

        from jobs import Button

        try:
            element_button = Button(
                x_path=x_path,
                button_type="dropdown",
                title=field_title,
                parent_application_page=None,
            )
            element_button.proceed()
        except (ElementClickInterceptedException, ElementNotInteractableException):
            element_button = Button(
                x_path=find_clickable_parent_xpath(x_path),
                button_type="dropdown",
                title=field_title,
                parent_application_page=None,
            )
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
                simulate_empty_area_click(text_to_click=text_to_click or field_title)
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
                        text_to_click=text_to_click or field_title
                    )
                    if is_element_visible(container_x_path):
                        simulate_empty_area_click()
                    return True, container_x_path

        simulate_empty_area_click(text_to_click=text_to_click or field_title)
        return False, None

    @classmethod
    def validate_calendar_widget(cls, x_path, field_title, text_to_click=None):
        simulate_empty_area_click(text_to_click=text_to_click or field_title)

        start_dom_mutation_observer()

        from jobs import Button

        try:
            element_button = Button(
                x_path=x_path,
                button_type="calendar",
                title=field_title,
                parent_application_page=None,
            )
            element_button.proceed()
        except (ElementClickInterceptedException, ElementNotInteractableException):
            element_button = Button(
                x_path=find_clickable_parent_xpath(x_path),
                button_type="calendar",
                title=field_title,
                parent_application_page=None,
            )
            element_button.proceed()

        observed_elements = get_observed_elements()

        is_calendar_widget_present = False
        if observed_elements:
            from jobs.page_components.date_field import DateField

            is_calendar_widget_present = DateField.identify_calendar_using_regex(
                observed_elements
            )

        simulate_empty_area_click(text_to_click=text_to_click or field_title)
        return is_calendar_widget_present

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
                return info.get("responsibilities")
        elif "_achievements__" in field_category and re.search(r"\d$", field_category):
            entry_no = int(field_category.split("__")[-1])
            info = user.parsed_resume.get("work_experience", [])
            if entry_no < len(info):
                info = info[entry_no - 1]
                return info.get("achievements")
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

        user_prompt += "Give me correct answer for the question."

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
        cls, prev_x_path, prompt, job_title, job_url, html=None, xpath_count=10
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
            f"{prompt}\n"
        )

        class CorrectXPath(BaseModel):
            possible_x_paths: List[str] = Field(
                ...,
                description=f"{xpath_count} Possible correct XPaths of the element which can be used in selenium chrome driver to "
                "search the element. Try to give short & simple XPaths which point to desired element. Avoid long "
                "ancestor chains, multiple contains(@class,…) filters, or deep nesting because long XPaths can be brittle.",
            )

        correct_x_path_found, correct_x_path = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=CorrectXPath,
        )
        if correct_x_path_found:
            x_paths = "\n".join(
                f"{i + 1}. {x_path}"
                for i, x_path in enumerate(correct_x_path.possible_x_paths)
            )
            logger.info(
                f"Found {len(correct_x_path.possible_x_paths)} possible correct XPaths for the element.\n"
                f"Possible XPaths -\n{x_paths}"
            )

            for x_path in correct_x_path.possible_x_paths:
                if element_exists(x_path):
                    logger.info(f"Found correct x_path - {x_path}")
                    return x_path

        logger.error(
            f"Correct x_path couldn't be found for {job_title}. URL - {job_url}"
        )
        return None
