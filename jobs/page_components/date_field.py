from selenium.webdriver.common.by import By
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

from jobs import ApplicationField, Button
from jobs.page_components import PageComponent, logger, get_page_component_class_name
from jobs.page_components.text_input import TextInput
from jobs.page_components.drop_down import DropDown
from utilities.selenium import (
    get_selenium_driver,
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
        category,
        parent_application_page,
        persist_context_fileds=True,
    ):
        global driver
        self.title = title
        self.question = question
        self.category = category
        self.parent_application_page = parent_application_page
        self.persist_context_fileds = persist_context_fileds

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
        self.date_format = None
        self.is_component_functional = False

        self.next = None
        self.prev = None

    def _handle_calendar_interaction(self, retry=False, prev_xpath=None):
        """Handle calendar widget or date field interaction.

        Steps:
        1. Get xpath from calendar button or date field
        2. Create Button instance and proceed()
        3. Monitor DOM changes with mutation observer
        4. If calendar appears, find xpath for date 27
        5. Click date 27 and extract format from field value
        6. Update input_method_details_identified if successful

        Side effects:
        - Updates self.date_format with field value after clicking 27
        - Sets input_method_details_identified to True on success
        - Always calls simulate_empty_area_click() for cleanup
        """
        # Clean up any existing open widgets
        simulate_empty_area_click()

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
                + f"\nIf these elements contain a calendar widget, find XPath of date 27, which is currently visible on"
                f" observed calendar element that can be clicked."
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

            if retry and prev_xpath:
                user_prompt += (
                    f"\nPrevious attempt to find date 27 with xpath '{prev_xpath}' failed. "
                    f"Please provide correct xpath for date 27 currently visible on the observed calendar element."
                )

            date_info_found, date_info = get_gpt_response(
                constants.gpt["system_prompts"]["application_step_identification"],
                user_prompt,
                response_format=DateInfo,
            )

            if date_info_found and date_info.has_calendar and date_info.date_xpath:
                if not element_exists(date_info.date_xpath):
                    if not retry:
                        return self._handle_calendar_interaction(
                            retry=True, prev_xpath=date_info.date_xpath
                        )
                    else:
                        simulate_empty_area_click()
                        logger.debug(
                            f"Date 27 xpath not found after retry: {date_info.date_xpath}"
                        )
                        return

                date_button = Button(
                    x_path=date_info.date_xpath,
                    button_type="date",
                    parent_application_page=self.parent_application_page,
                )
                date_button.proceed()

                # Get format from field value after selecting 27th
                field = driver.find_element(By.XPATH, self.components["date"]["xpath"])
                if field_value := field.get_attribute("value"):
                    simulate_empty_area_click()
                    self.date_format = field_value
                    self.input_method_details_identified = True
                    logger.debug(f"Successfully extracted date format: {field_value}")
                    return True

        simulate_empty_area_click()

    def _handle_separate_components(self):
        """Handle separate month/day/year components.

        Steps:
        1. For each component (month/day/year):
           - Create ApplicationField instance with component info
           - Set correct html_type from stored component data
           - Get proper component class using get_field_component()
           - Store component class name in components dict

        2. If all components are successfully processed:
           - Set input_method_details_identified to True

        Note: Only processes components that exist in self.components
        """
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
                    question=f"{self.question}\nFinal question for us to answer is - What is {component_type} part of the date in question here?",
                    category=f"{self.category} - {component_type.title()}",
                    x_path=component["xpath"],
                )
                field.html_type = component["html_type"]

                # Get component object and its class
                component_obj = field.get_field_component()
                if component_obj:
                    # Add class name to component dict
                    self.components[component_type] = component_obj
                    logger.debug(
                        f"Identified {component_type} component as {component_obj.__class__.__name__} "
                        f"with html_type: {field.html_type}"
                    )
                else:
                    all_components_valid = False
                    logger.debug(f"Failed to get component for {component_type}")

        if all_components_valid:
            self.input_method_details_identified = True

    def proceed(self, retry=False):
        """Fill the date field using identified input method"""
        global driver

        if not self.input_method_identified:
            self._identify_input_method()

        if not self.input_method_identified:
            raise Exception(
                f"Couldn't identify input method for date field {self.title} "
                f"on {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

        if not self.input_method_details_identified:
            # Try calendar widget first
            if self.has_calendar_button or self.components.get("date"):
                self._handle_calendar_interaction(retry=False)

            # If calendar didn't work and still not identified, try separate components
            if (
                not self.input_method_details_identified
                and self.has_separate_components
            ):
                self._handle_separate_components()

        if not self.input_method_details_identified:
            raise Exception(
                f"Couldn't identify input method for date field {self.title} "
                f"on {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

        # Proceed with filling the date field
        if self.date_format and components.get("date"):
            date_field = TextInput(
                x_path=self.components["date"]["xpath"],
                category="date_field",
                parent_application_page=self.parent_application_page,
            )
            date_field.answer = self.answer
            date_field.proceed()
        elif self.has_separate_components:
            # Process each component
            for component_type, component in [
                ("month", self.components.get("month")),
                ("day", self.components.get("day")),
                ("year", self.components.get("year")),
            ]:
                if component and isinstance(component, PageComponent):
                    if self.date_format:
                        date_component = self._get_date_component_in_format(
                            date=self.answer,
                            date_format=self.date_format,
                            date_component=component_type,
                        )
                        component.answer = date_component
                    elif isinstance(component, DropDown):
                        component.answer = self.answer

                    component.proceed()

                    if not self.persist_context_fileds:
                        component.question = None
                        component.category = None

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
            f"5. XPath of date input or date box (where selected date is / will be shown) element\n"
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
                description="Single date input or date box (where selected date is / will be shown) element",
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
                    ("month", input_data.month_component.xpath),
                    ("year", input_data.year_component.xpath),
                    ("day", input_data.day_component.xpath),
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
            elif input_data.date_field.xpath and not element_exists(
                input_data.date_field.xpath
            ):
                if not retry:
                    return self._identify_input_method(
                        retry=True, prev_xpaths={"date": input_data.date_field.xpath}
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

    def _get_date_component_in_format(self, date, date_format, date_component):
        user_prompt = (
            f"I have following date -\n{date}\n"
            f"Consider following date format -\n{date_format}\n"
            f"Please extract just the {date_component} part of the date in the date format {date_format}. "
            f"Strictly follow the date format and return only the {date_component} part."
        )
        class DateComponentFormat(BaseModel):
            date_component: str = Field(
                ...,
                description="Extracted date component in the specified format",
            )
        date_component_found, date_component_data = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=DateComponentFormat,
        )
        if date_component_found:
            return date_component_data.date_component
        else:
            raise Exception(
                f"Couldn't extract {date_component} component from date {date} in {date_format} format."
            )


    def to_dict(self):
        output = {
            "class": self.__class__.__name__,
            "title": self.title,
            "date_format": self.date_format,
            "category": self.category if self.persist_context_fileds else None,
            "components": {
                k: v.to_dict() if isinstance(v, PageComponent) else v
                for k, v in self.components.items()
                if v is not None
            },
            "has_calendar_button": self.has_calendar_button,
            "has_separate_components": self.has_separate_components,
            "input_method_identified": self.input_method_identified,
            "input_method_details_identified": self.input_method_details_identified,
            "question": self.question if self.persist_context_fileds else None,
            "persist_context_fileds": self.persist_context_fileds,
            "next": self.next.to_dict() if self.next else None,
        }
        return output

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            title=input_dict["title"],
            question=input_dict.get("question"),
            date_format=input_dict["date_format"],
            category=input_dict["category"],
            parent_application_page=parent_application_page,
            persist_context_fileds=input_dict.get("persist_context_fileds", True),
        )

        # Restore component info and state
        if input_dict.get("components"):
            instance.components = {}
            # Restore each component
            for comp_type, comp_data in input_dict["components"].items():
                if isinstance(comp_data, dict) and comp_data.get("class"):
                    # If it's a serialized PageComponent
                    comp_class = get_page_component_class_name(comp_data["class"])
                    instance.components[comp_type] = comp_class.from_dict(
                        comp_data, parent_application_page
                    )
                else:
                    # Regular dict data
                    instance.components[comp_type] = comp_data

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

        if self.date_format or answer is None:
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
