from selenium.webdriver.common.by import By
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

from jobs import ApplicationField, Button
from jobs.page_components import PageComponent, logger, get_page_component_class_name
from jobs.page_components import ApplicationField
from utilities.selenium import (
    get_selenium_driver,
    clear_text_field,
    simulate_typing,
    simulate_empty_area_click,
    start_dom_mutation_observer,
    get_observed_elements,
    minify_html_for_gpt_prompt,
    is_stale,
    element_exists,
)
from utilities import constants
from utilities.gpt import get_gpt_response


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class DateField(PageComponent):
    def __init__(
        self,
        title,
        question,
        date_format,
        category,
        parent_application_page,
        persist_question=True,
    ):
        global driver
        self.title = title
        self.question = question
        self.date_format = date_format
        self.category = category
        self.parent_application_page = parent_application_page
        self.persist_question = persist_question

        self._answer = None
        self.input_method_identified = False
        self.input_method_details_identified = False
        self.has_calendar_button = False
        self.has_separate_components = False
        self.components = {
            "calendar": None,  # Will store: {'xpath': str, 'html_type': str, 'class_name': str}
            "month": None,
            "day": None,
            "year": None,
            "date": None,
        }
        self.is_component_functional = False

        self.next = None
        self.prev = None

    def proceed(self, retry=False):
        """Fill the date field following whiteboard flow logic"""
        global driver

        try:
            if not self.input_method_details_identified:
                # Try calendar widget first
                if self.has_calendar_button or self.components.get("date"):
                    try:
                        click_xpath = (
                            self.components.get("calendar", {}).get("xpath")
                            or self.components["date"]["xpath"]
                        )

                        start_dom_mutation_observer()
                        button = Button(
                            x_path=click_xpath,
                            button_type="date",
                            parent_application_page=self.parent_application_page,
                        )
                        button.proceed()

                        observed_elements = get_observed_elements()
                        if observed_elements:
                            user_prompt = (
                                f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
                                f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
                                f"When date field was clicked, following elements were observed -\n"
                                + "\n".join(
                                    f"{i + 1}. Element {i + 1} - {minify_html_for_gpt_prompt(el.get_attribute('outerHTML'))}"
                                    for i, el in enumerate(observed_elements)
                                    if not is_stale(el)
                                )
                                + f"\nIf these elements contain a calendar widget, find XPath of date 27 that can be clicked."
                            )

                            class DateInfo(BaseModel):
                                has_calendar: bool = Field(
                                    ...,
                                    description="Whether elements contain a calendar widget",
                                )
                                date_xpath: Optional[str] = Field(
                                    None,
                                    description="XPath of clickable date 27 if calendar exists",
                                )

                            date_info_found, date_info = get_gpt_response(
                                constants.gpt["system_prompts"][
                                    "application_step_identification"
                                ],
                                user_prompt,
                                response_format=DateInfo,
                            )

                            if (
                                date_info_found
                                and date_info.has_calendar
                                and date_info.date_xpath
                            ):
                                date_button = Button(
                                    x_path=date_info.date_xpath,
                                    button_type="date",
                                    parent_application_page=self.parent_application_page,
                                )
                                date_button.proceed()

                                # Get format from field value after selecting 27th
                                field = driver.find_element(
                                    By.XPATH, self.components["date"]["xpath"]
                                )
                                if field_value := field.get_attribute("value"):
                                    self.date_format = field_value
                                    self.input_method_details_identified = True
                                    logger.debug(
                                        f"Successfully extracted date format: {field_value}"
                                    )
                    except Exception as e:
                        logger.debug(f"Calendar widget interaction failed: {e}")
                    finally:
                        simulate_empty_area_click()  # Always cleanup widgets

                # If calendar didn't work and still not identified, try separate components
                if (
                    not self.input_method_details_identified
                    and self.has_separate_components
                ):
                    all_components_valid = True
                    for component_type, component in [
                        ("month", self.components.get("month")),
                        ("day", self.components.get("day")),
                        ("year", self.components.get("year")),
                    ]:
                        if component:  # Only process if component exists
                            field = ApplicationField(
                                parent_application_page=self.parent_application_page,
                                title=f"{self.title} - {component_type.title()}",
                                question=None,
                                category=component_type,
                                x_path=component["xpath"],
                            )
                            field.html_type = component["html_type"]

                            # Get component object and its class
                            component_obj = field.get_field_component()
                            if component_obj:
                                # Add class name to component dict
                                self.components[component_type][
                                    "class_name"
                                ] = component_obj.__class__.__name__
                                logger.debug(
                                    f"Identified {component_type} component as {component_obj.__class__.__name__} "
                                    f"with html_type: {component['html_type']}"
                                )
                            else:
                                all_components_valid = False
                                logger.debug(
                                    f"Failed to get component for {component_type}"
                                )

                    if all_components_valid:
                        self.input_method_details_identified = True

        except Exception as e:
            logger.exception(
                f"Unexpected error occurred in class DateField's proceed method.\n{e}\n"
                f"DateField instance - {vars(self)}"
            )

        return

    def _identify_input_method(self, retry=False, prev_xpaths=None):
        """Identifies input methods and xpaths of interactive elements for date field"""
        global driver

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"I need to enter date in following date field -\n"
            f"Field title - {self.title}\n"
            f"Field category - {self.category}\n"
            f"Please analyze the HTML to identify how date can be entered and return following info -\n"
            f"1. Whether there is a calendar widget button present\n"
            f"2. If date components (month, day, year) have separate interactive input elements\n"
            f"3. XPath of calendar button if present\n"
            f"4. XPaths of separate date component interactive input elements if present\n"
            f"5. XPath of date input element if separate components are not present\n"
        )

        if retry and prev_xpaths:
            prev_xpaths_str = "\n".join(
                [f"{k}: {v}" for k, v in prev_xpaths.items() if v]
            )
            user_prompt += (
                f"\nIn previous try you gave following XPaths but they couldn't be found on the page. "
                f"Please provide correct XPaths:\n{prev_xpaths_str}"
            )

        class FieldHtmlType(Enum):
            textBox = "text_box"
            checkBox = "check_box"
            radioButton = "radio_button"
            dropdown = "dropdown"
            button = "button"

        class DateComponent(BaseModel):
            xpath: str = Field(
                ...,
                description="XPath of the interactive input element to be used in selenium chrome driver",
            )
            html_type: FieldHtmlType = Field(
                ...,
                description="HTML type of the interactive input element (textBox, checkBox, radioButton, dropdown, button)",
            )

        class DateInputMethod(BaseModel):
            has_calendar_button: bool = Field(
                ...,
                description="Whether there is an interactive button present to open calendar widget",
            )
            has_separate_components: bool = Field(
                ...,
                description="Whether date field has separate interactive input elements for date components",
            )
            calendar_button_xpath: Optional[str] = Field(
                None,
                description="XPath of interactive button that opens calendar widget. Only provide if has_calendar_button is True",
            )
            date_format: Optional[str] = Field(
                None,
                description="Date format hint found in labels, placeholders or example values (e.g. MM/DD/YYYY)",
            )
            day_component: Optional[DateComponent] = Field(
                None,
                description="Interactive day input component if separate components exist",
            )
            month_component: Optional[DateComponent] = Field(
                None,
                description="Interactive month input component if separate components exist",
            )
            year_component: Optional[DateComponent] = Field(
                None,
                description="Interactive year input component if separate components exist",
            )
            date_field: Optional[DateComponent] = Field(
                None,
                description="Interactive single date field component if separate components don't exist",
            )

        input_found, input_data = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=DateInputMethod,
        )

        if input_found:
            # Validate calendar button xpath if provided
            if input_data.has_calendar_button and input_data.calendar_button_xpath:
                if not element_exists(input_data.calendar_button_xpath):
                    if not retry:
                        return self._identify_input_method(
                            retry=True,
                            prev_xpaths={
                                "calendar_button": input_data.calendar_button_xpath
                            },
                        )
                    else:
                        raise Exception(
                            f"Couldn't identify calendar button for {self.parent_application_page.parent_job.title}. "
                            f"URL - {self.parent_application_page.url}"
                        )

            # Validate separate component xpaths if provided
            if input_data.has_separate_components:
                invalid_xpaths = {}
                for component, xpath in [
                    ("month", input_data.month_xpath),
                    ("year", input_data.year_xpath),
                    ("day", input_data.day_xpath),
                ]:
                    if xpath and not element_exists(xpath):
                        invalid_xpaths[component] = xpath

                if invalid_xpaths and not retry:
                    return self._identify_input_method(
                        retry=True, prev_xpaths=invalid_xpaths
                    )
                elif invalid_xpaths:
                    raise Exception(
                        f"Couldn't identify separate date components for {self.parent_application_page.parent_job.title}. "
                        f"URL - {self.parent_application_page.url}"
                    )
            elif input_data.date_xpath and not element_exists(input_data.date_xpath):
                if not retry:
                    return self._identify_input_method(
                        retry=True, prev_xpaths={"date": input_data.date_xpath}
                    )
                else:
                    raise Exception(
                        f"Couldn't identify date input element for {self.parent_application_page.parent_job.title}. "
                        f"URL - {self.parent_application_page.url}"
                    )

            # Store component details after validation
            if input_data.has_calendar_button and input_data.calendar_button_xpath:
                self.has_calendar_button = True
                self.components["calendar"] = {
                    "xpath": input_data.calendar_button_xpath,
                    "html_type": "button",
                    "class_name": "Button",
                }

            if input_data.has_separate_components:
                self.has_separate_components = True
                if input_data.month_component:
                    self.components["month"] = {
                        "xpath": input_data.month_component.xpath,
                        "html_type": input_data.month_component.html_type,
                    }
                if input_data.day_component:
                    self.components["day"] = {
                        "xpath": input_data.day_component.xpath,
                        "html_type": input_data.day_component.html_type,
                    }
                if input_data.year_component:
                    self.components["year"] = {
                        "xpath": input_data.year_component.xpath,
                        "html_type": input_data.year_component.html_type,
                    }
            elif input_data.date_field:
                self.components["date"] = {
                    "xpath": input_data.date_field.xpath,
                    "html_type": input_data.date_field.html_type,
                }

            # Get date format from GPT response
            if input_data.date_format:
                self.date_format = input_data.date_format

            self.input_method_identified = True
            return True

        elif not retry:
            return self._identify_input_method(retry=True)
        else:
            raise Exception(
                f"Couldn't identify date input method for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )

    def to_dict(self):
        output = {
            "class": self.__class__.__name__,
            "title": self.title,
            "date_format": self.date_format,
            "category": self.category,
            "components": self.components,
            "has_calendar_button": self.has_calendar_button,
            "has_separate_components": self.has_separate_components,
            "input_method_identified": self.input_method_identified,
            "input_method_details_identified": self.input_method_details_identified,
            "next": self.next.to_dict() if self.next else None,
        }
        if self.persist_question:
            output["question"] = self.question
        return output

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            title=input_dict["title"],
            question=input_dict.get("question"),
            date_format=input_dict["date_format"],
            category=input_dict["category"],
            parent_application_page=parent_application_page,
        )

        # Restore component info and state
        if input_dict.get("components"):
            instance.components = input_dict["components"]
            instance.has_calendar_button = input_dict["has_calendar_button"]
            instance.has_separate_components = input_dict["has_separate_components"]
            instance.input_method_identified = input_dict["input_method_identified"]
            instance.input_method_details_identified = input_dict[
                "input_method_details_identified"
            ]

        # Handle next component
        if input_dict.get("next"):
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
        answer = ApplicationField.extract_field_answer(
            job_title=self.parent_application_page.parent_job.title,
            job_url=self.parent_application_page.url,
            company_name=self.parent_application_page.parent_job.company,
            field_title=self.title or self.category,
            question=self.question,
            answer_format=self.date_format,
            answer_type="text",
            closest_answer=answer,
            parsed_resume=self.parent_application_page.parent_job.user.parsed_resume,
        )

        self._answer = answer
        return self._answer

    @answer.setter
    def answer(self, value):
        self._answer = value
