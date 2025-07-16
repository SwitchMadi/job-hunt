from selenium.webdriver.common.by import By
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
import re
from selenium.common.exceptions import NoSuchElementException
from datetime import date

from jobs import ApplicationField, Button
from jobs.page_components import PageComponent, logger, get_page_component_class_name
from jobs.page_components.text_input import TextInput
from utilities.selenium import (
    get_selenium_driver,
    simulate_empty_area_click,
    start_dom_mutation_observer,
    get_observed_elements,
    minify_html_for_gpt_prompt,
    is_stale,
    element_exists,
    get_element_xpath,
    find_input_block_for_title,
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
        persist_context_fields=True,
    ):
        global driver
        self.title = title
        self.question = question
        self.category = category
        self.parent_application_page = parent_application_page
        self.persist_context_fields = persist_context_fields

        self._answer = None
        self.input_method_identified = False
        self.input_method_details_identified = False
        self.has_calendar_button = False
        self.has_separate_components = False
        self.components = {
            "calendar": {},  # Will store: {'xpath': str, 'html_type': str, 'class_name': str}
            "month": {},
            "day": {},
            "year": {},
            "date": {},
        }
        self.date_format = None
        self.is_component_functional = False

        self.next = None
        self.prev = None

    def _handle_calendar_interaction(self):
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
        simulate_empty_area_click(text_to_click=self.title)

        click_xpath = self.components.get("calendar", {}).get(
            "xpath"
        ) or self.components.get("date", {}).get("xpath")

        if element_exists(click_xpath):
            date_format = self._extract_date_format_from_input_type_tag(click_xpath)
            if date_format:
                self.date_format = date_format
                self.input_method_details_identified = True
                return True

            start_dom_mutation_observer()
            button = Button(
                x_path=click_xpath,
                button_type="date",
                parent_application_page=self.parent_application_page,
            )
            button.proceed()

            observed_elements = get_observed_elements()
            observed_elements = [el for el in observed_elements if not is_stale(el)]

            # if no elements observed, retry clicking using date component xpath
            if not observed_elements and self.components.get("date", {}).get("xpath"):
                start_dom_mutation_observer()
                button = Button(
                    x_path=self.components["date"]["xpath"],
                    button_type="date",
                    parent_application_page=self.parent_application_page,
                )
                button.proceed()

                observed_elements = get_observed_elements()
                observed_elements = [el for el in observed_elements if not is_stale(el)]

            if observed_elements:
                is_regex_op_successful = DateField.identify_calendar_using_regex(
                    observed_elements
                )
                if not is_regex_op_successful:
                    simulate_empty_area_click(text_to_click=self.title)

                    start_dom_mutation_observer()
                    button.proceed()
                    observed_elements = get_observed_elements()
                    observed_elements = [
                        el for el in observed_elements if not is_stale(el)
                    ]

                    self._identify_calendar_using_llm(observed_elements)

        if self.components.get("date", {}).get("xpath") and element_exists(
            self.components.get("date", {}).get("xpath")
        ):
            # Get format from field value after selecting 27th or Jan month
            field = driver.find_element(
                By.XPATH, self.components.get("date", {}).get("xpath")
            )
            field_value = field.get_attribute("value") or field.text
            if field_value:
                self.date_format = field_value.strip()

                day, month, _ = self._get_date_values()
                self.date_format = self._replace_day_in_date(
                    date_str=self.date_format, day=day, month=month
                )

                self.input_method_details_identified = True
                logger.debug(f"Successfully extracted date format: {field_value}")

                simulate_empty_area_click(text_to_click=self.title)
                return True

        simulate_empty_area_click(text_to_click=self.title)
        return False

    @staticmethod
    def _replace_day_in_date(date_str: str, day: int, month: int) -> str:
        """
        Replace occurrences of `day` in `date_str` according to:

        1. If day == 1 and month == 1:
        a) Look for "01" as a whole number (not part of e.g. "2001").
            - If there's exactly one occurrence, replace it with "27" and return.
            - If there's more than one, do nothing and return original.
        b) If no "01" was found, look for "1" as a whole number.
            - If exactly one occurrence, replace it with "27"; else return original.
        2. If day != 1:
        a) First try with leading zero (e.g. "05" for day=5). Replace *all* such occurrences if found.
        b) Otherwise try without leading zero (e.g. "5"). Replace *all* such occurrences if found.
        c) If neither is found, return original.
        """

        # Case 1: day = 1, month = 1
        if day == 1 and month == 1:
            # a) leading-zero pattern
            p0 = r"(?<!\d)01(?!\d)"
            zero_hits = re.findall(p0, date_str)
            if len(zero_hits) > 1:
                return date_str
            if len(zero_hits) == 1:
                return re.sub(p0, "27", date_str)

            # b) no-leading-zero pattern
            p1 = r"(?<!\d)1(?!\d)"
            one_hits = re.findall(p1, date_str)
            if len(one_hits) == 1:
                return re.sub(p1, "27", date_str)
            return date_str

        # Case 2: day != 1
        # a) try with leading zero
        day_zero = f"{day:02d}"
        p0 = rf"(?<!\d){day_zero}(?!\d)"
        if re.search(p0, date_str):
            return re.sub(p0, "27", date_str)

        # b) try without leading zero
        p = rf"(?<!\d){day}(?!\d)"
        if re.search(p, date_str):
            return re.sub(p, "27", date_str)

        # c) nothing found
        return date_str

    @staticmethod
    def _element_has_day_numbers(el):
        """Check if the element contains all day numbers from 1 to 27."""
        DAY_NUMBERS = {str(i) for i in range(1, 28)}

        try:
            outer_html = el.get_attribute("outerHTML")
            # Extract and tokenize text
            text_content = re.sub(r"<.*?>", " ", outer_html)
            words = set(re.findall(r"\b\w+\b", text_content))
            if DAY_NUMBERS.issubset(words):
                return True
        except Exception as e:
            logger.warn(
                f"Error getting outerHTML for potential calendar widget element: {str(e)}"
            )
            return False

    @staticmethod
    def _element_has_month_names(el):
        """Check if the element contains all day months from Jan to Dec."""
        MONTH_NAMES = {
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        }

        try:
            outer_html = el.get_attribute("outerHTML")
            # Extract and tokenize text
            text_content = re.sub(r"<.*?>", " ", outer_html)
            words = set(re.findall(r"\b\w+\b", text_content))
            lower_words = {
                w[:3].capitalize() for w in words if w.isalpha() and len(w) >= 3
            }
            if MONTH_NAMES.issubset(lower_words):
                return True
        except Exception as e:
            logger.warn(
                f"Error getting outerHTML for potential calendar widget element: {str(e)}"
            )
            return False

    @staticmethod
    def _click_date_element(el, day):
        """Helper method to click on a specific date element."""
        try:
            specific_date = el.find_element(By.XPATH, ".//*[text()='27']")

            # finding calendar parent element with all days
            parent = specific_date.find_element(By.XPATH, "./..")
            while not DateField._element_has_day_numbers(parent):
                try:
                    parent = parent.find_element(By.XPATH, "./..")
                except Exception as e:
                    logger.warn(
                        f"Parent element of 27th date not found while traversing up - {str(e)}"
                    )
                    return False

            try:
                specific_date = el.find_element(By.XPATH, f".//*[text()='{day:02d}']")
            except NoSuchElementException:
                specific_date = el.find_element(By.XPATH, f".//*[text()='{day}']")

            specific_date.click()
            logger.info(f"Clicked on date {day}.")
            return True
        except NoSuchElementException:
            logger.warn(f"Date 27 or {day} not found in text.")
            return False
        except Exception as e:
            logger.warn(
                f"Error clicking date 27 or {day}: {e} but element found with text - {el.text}"
            )
            return True

    @staticmethod
    def _get_date_values():
        """Get the current date values for day and month."""
        today = date.today()
        day, month = today.day, today.month
        if day == month and day > 1:
            day -= 1

        month_name = today.strftime("%b").lower()

        return day, month, month_name

    @classmethod
    def identify_calendar_using_regex(cls, observed_elements):
        global driver

        day, month, month_name = cls._get_date_values()

        for el in observed_elements:
            # Case 1: All days 1–27 are found
            if cls._element_has_day_numbers(el):
                logger.info("All days 1–27 detected")
                return cls._click_date_element(el, day)

            # Case 2: All month names found
            if cls._element_has_month_names(el):
                logger.info("All months Jan–Dec detected")
                try:
                    month_el = el.find_element(
                        By.XPATH,
                        f".//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{month_name}')]",
                    )
                    month_el.click()
                    logger.info(f"Clicked on {month_name}.")
                except NoSuchElementException:
                    logger.warn(f"Month '{month_name}' not clickable.")
                    return False

                # After clicking month name, recheck for days
                if el.is_displayed() and cls._element_has_day_numbers(el):
                    return cls._click_date_element(el, day)
                else:
                    logger.warn("Days not detected after month selection.")
                    return False

        logger.info("No calendar widget identified.")
        return False

    def _identify_calendar_using_llm(
        self, observed_elements, retry=False, prev_xpath=None
    ):
        observed_elements_prompt = "\n".join(
            f"{i + 1}. Element {i + 1} - {minify_html_for_gpt_prompt(el.get_attribute('outerHTML'))}"
            for i, el in enumerate(observed_elements)
            if not is_stale(el)
        )
        if not observed_elements_prompt.strip():
            logger.debug("No elements observed after clicking date field.")
            self.has_calendar_button = False
            simulate_empty_area_click()
            return None

        day, _, _ = self._get_date_values()

        user_prompt = (
            f"There is a job application webpage for {self.parent_application_page.parent_job.title}. "
            f"When date field was clicked, following elements were observed -\n"
            f"{observed_elements_prompt}"
            f"\nIf these observed elements contain a calendar widget, then find XPath of date {day}, which is "
            f"currently visible on the observed calendar that can be clicked."
        )

        class DateInfo(BaseModel):
            has_calendar: bool = Field(
                ...,
                description="Whether any of the observed elements represents an open calendar widget. Answer it "
                "strictly from the observed elements. Multiple numeric dates must exist in the calendar widget for it to be considered a calendar.",
            )
            date_xpath: Optional[str] = Field(
                None,
                description=f"XPath of clickable date {day}, if calendar exists, visible on the observed calendar.",
            )

        if retry and prev_xpath:
            user_prompt += (
                f"\n\nIn previous try you gave following XPath for the container but the element couldn't be found "
                f"using that. So, find correct XPath for the date {day}.\n"
                f"Previous XPath - {prev_xpath}\n"
            )

        date_info_found, date_info = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=DateInfo,
        )

        if date_info_found and date_info.has_calendar and date_info.date_xpath:
            if not element_exists(date_info.date_xpath):
                if not retry:
                    return self._identify_calendar_using_llm(
                        observed_elements, retry=True, prev_xpath=date_info.date_xpath
                    )
                else:
                    simulate_empty_area_click()
                    logger.debug(
                        f"Date {day} xpath not found after retry: {date_info.date_xpath}"
                    )
                    return None

            date_button = Button(
                x_path=date_info.date_xpath,
                button_type="date",
                parent_application_page=self.parent_application_page,
            )
            date_button.proceed()

            return True
        elif date_info_found and not date_info.has_calendar:
            logger.debug(
                "No calendar widget found in observed elements after clicking date field."
            )
            self.has_calendar_button = False

        return False

    @staticmethod
    def _extract_date_format_from_input_type_tag(x_path):
        global driver

        element = driver.find_element(By.XPATH, x_path)
        outer_html = element.get_attribute("outerHTML")
        if re.search(
            r'<input\b[^>]*\btype=["\']date["\'][^>]*>', outer_html, re.IGNORECASE
        ):
            script = """
                    const date = new Date(arguments[0]);
                    return date.toLocaleDateString(navigator.language);
                """
            date_format = driver.execute_script(script, "2025-01-27")
            return date_format
        else:
            return None

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
                    title=self.title,
                    question=f"{self.question}\nFinal question for us to answer is - What is {component_type} part of "
                    f"the date in question here?",
                    category=f"{self.category} - {component_type}",
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
                self._handle_calendar_interaction()

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
        if self.date_format and self.components.get("date"):
            date_field = TextInput(
                x_path=self.components.get("date", {}).get("xpath"),
                category="date_field",
                parent_application_page=self.parent_application_page,
            )
            date_field.answer = self.answer
            date_field.proceed()

        if self.has_separate_components:
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

                    if not self.persist_context_fields:
                        component.question = (
                            f"{self.question}\nFinal question for us to answer is - What is "
                            f"{component_type} part of the date in question here?"
                        )
                        component.category = f"{self.category} - {component_type}"

                    component.proceed()

                    if not self.persist_context_fields:
                        component.question = None
                        component.category = None

        simulate_empty_area_click(self.title)
        return

    def _identify_input_method(self, retry=False):
        """Identifies input methods and xpaths of interactive elements for date field"""
        global driver

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
            f"I need to enter date in following date field -\n"
            f"Field title - {self.title}\n"
            f"Field category - {self.category}\n"
            f"Please analyze the HTML to help identify how date can be entered and return following info -\n"
            f"1. Whether there is a calendar widget button present\n"
            f"2. If date components (month or day or year or all) have separate interactive input elements\n"
            f"3. XPath of calendar button if present\n"
            f"4. XPaths of separate date component interactive input elements if present\n"
            f"5. XPath of date input or date box (where selected date is / will be shown) element\n"
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
                description="Give me the simplest unique XPath to select this interactive input element for use in "
                "Selenium ChromeDriver. Avoid long ancestor chains, multiple contains(@class,…) filters, or"
                " deep nesting as that usually leads to brittle XPaths.",
            )
            html_type: FieldHtmlType = Field(
                ...,
                description="HTML type of the interactive input element (textBox, checkBox, radioButton, dropdown, "
                "button)",
            )

        class DateInputMethod(BaseModel):
            has_calendar_button: bool = Field(
                ...,
                description=f"Whether there is an interactive button present to open calendar widget for field "
                f"{self.title}. Look for proofs where suggest that clicking this button opens a calendar widget.",
            )
            has_separate_components: bool = Field(
                ...,
                description=f"Whether date field has separate interactive input elements for date components for field "
                f"{self.title}",
            )
            calendar_button_xpath: Optional[str] = Field(
                None,
                description=f"XPath of interactive button that opens calendar widget for field {self.title}. Only "
                f"provide if has_calendar_button is True",
            )
            date_format: Optional[str] = Field(
                None,
                description=f"Date format hint found in labels, placeholders or example values (e.g. MM/DD/YYYY) for "
                f"field {self.title}. Provide this information only if you are confident about the format, "
                f"otherwise return None.",
            )
            month_component: Optional[DateComponent] = Field(
                None,
                description=f"Interactive month input component for field {self.title}. It may exist only if separate "
                f"components exist. Don't assume that it's present because has_separate_components is True."
                f" Look for solid proof of month field being present.",
            )
            year_component: Optional[DateComponent] = Field(
                None,
                description=f"Interactive year input component for field {self.title}. It may exist only if separate "
                f"components exist. Don't assume that it's present because has_separate_components is True."
                f" Look for solid proof of year field being present.",
            )
            day_component: Optional[DateComponent] = Field(
                None,
                description=f"Interactive day input component for field {self.title}. It may exist only if separate "
                f"components exist. Don't assume that it's present because has_separate_components is True."
                f" Look for solid proof of day field being present.",
            )
            date_field: Optional[DateComponent] = Field(
                None,
                description=f"Single date input or date box (where selected date is / will be shown) element for field "
                f"{self.title}.",
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
                    prompt = (
                        f"The x_path that we are trying to extract is of a button to open calendar for a field "
                        f"with title {self.title}."
                    )
                    input_data.calendar_button_xpath = (
                        ApplicationField.extract_correct_x_path(
                            prev_x_path=input_data.calendar_button_xpath,
                            prompt=prompt,
                            job_title=self.parent_application_page.parent_job.title,
                            job_url=self.parent_application_page.url,
                        )
                    )

                    if not input_data.calendar_button_xpath:
                        raise Exception(
                            f"Couldn't identify calendar button for {self.parent_application_page.parent_job.title}. "
                            f"URL - {self.parent_application_page.url}"
                        )

            # Validate separate component xpaths if provided
            if input_data.has_separate_components:
                for component, xpath in [
                    (
                        "month",
                        (
                            input_data.month_component.xpath
                            if input_data.month_component
                            else None
                        ),
                    ),
                    (
                        "year",
                        (
                            input_data.year_component.xpath
                            if input_data.year_component
                            else None
                        ),
                    ),
                    (
                        "day",
                        (
                            input_data.day_component.xpath
                            if input_data.day_component
                            else None
                        ),
                    ),
                ]:
                    if xpath and not element_exists(xpath):
                        prompt = (
                            f"The x_path that we are trying to extract is of {component} type interactive element for a"
                            f" field with title {self.title}."
                        )
                        xpath = ApplicationField.extract_correct_x_path(
                            prev_x_path=xpath,
                            prompt=prompt,
                            job_title=self.parent_application_page.parent_job.title,
                            job_url=self.parent_application_page.url,
                        )

                        if not xpath:
                            raise Exception(
                                f"Couldn't identify separate date components for "
                                f"{self.parent_application_page.parent_job.title}. "
                                f"URL - {self.parent_application_page.url}"
                            )

                        if component == "month":
                            input_data.month_component.xpath = xpath
                        elif component == "year":
                            input_data.year_component.xpath = xpath
                        elif component == "day":
                            input_data.day_component.xpath = xpath

            elif input_data.date_field.xpath and not element_exists(
                input_data.date_field.xpath
            ):
                prompt = (
                    f"The x_path that we are trying to extract is of single date input or date box (where selected "
                    f"date is / will be shown) element for a field with title {self.title}."
                )
                input_data.date_field.xpath = ApplicationField.extract_correct_x_path(
                    prev_x_path=input_data.date_field.xpath,
                    prompt=prompt,
                    job_title=self.parent_application_page.parent_job.title,
                    job_url=self.parent_application_page.url,
                )

                if not input_data.date_field.xpath:
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
                        "html_type": input_data.month_component.html_type.value,
                    }
                if input_data.day_component:
                    self.components["day"] = {
                        "xpath": input_data.day_component.xpath,
                        "html_type": input_data.day_component.html_type.value,
                    }
                if input_data.year_component:
                    self.components["year"] = {
                        "xpath": input_data.year_component.xpath,
                        "html_type": input_data.year_component.html_type.value,
                    }

                self._remove_duplicate_separate_components()

            if input_data.date_field:
                self.components["date"] = {
                    "xpath": input_data.date_field.xpath,
                    "html_type": input_data.date_field.html_type.value,
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

    def _remove_duplicate_separate_components(
        self,
    ):
        """Remove duplicate separate components from self.components."""

        global driver

        original_month_xpath = self.components.get("month", {}).get("xpath")
        original_year_xpath = self.components.get("year", {}).get("xpath")
        original_day_xpath = self.components.get("day", {}).get("xpath")

        # Get the unique xpaths for month, year and day components
        unique_month_xpath = (
            get_element_xpath(driver.find_element(By.XPATH, original_month_xpath))
            if original_month_xpath
            else None
        )
        unique_year_xpath = (
            get_element_xpath(driver.find_element(By.XPATH, original_year_xpath))
            if original_year_xpath
            else None
        )
        unique_day_xpath = (
            get_element_xpath(driver.find_element(By.XPATH, original_day_xpath))
            if original_day_xpath
            else None
        )

        # check if any of the x_paths are same
        if (
            unique_month_xpath == unique_year_xpath
            or unique_month_xpath == unique_day_xpath
            or unique_year_xpath == unique_day_xpath
        ):
            pass
        else:
            return

        # Prepare the user prompt for GPT
        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"I have following x_paths for month, year and day components from an HTML -\n"
            f"Month XPath: {original_month_xpath}\n"
            f"Year XPath: {original_year_xpath}\n"
            f"Day XPath: {original_day_xpath}\n"
            f"I have found that 2 or more of these x_paths point to the same element in the HTML. Based on the mapping "
            f"above and the x_paths themselves, I need your help to identify which components to keep and which seem to"
            f" be incorrectly mapped."
        )

        class ComponentsXPathCorrectness(BaseModel):
            is_month_xpath_correct: bool = Field(
                ...,
                description="Whether the month component XPath is correct and should be kept.",
            )
            is_year_xpath_correct: bool = Field(
                ...,
                description="Whether the year component XPath is correct and should be kept.",
            )
            is_day_xpath_correct: bool = Field(
                ...,
                description="Whether the day component XPath is correct and should be kept.",
            )

        components_found, components_data = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=ComponentsXPathCorrectness,
        )
        if components_found:
            # Remove components based on GPT response
            if not components_data.is_month_xpath_correct:
                self.components.month = {}
            if not components_data.is_year_xpath_correct:
                self.components.year = {}
            if not components_data.is_day_xpath_correct:
                self.components.day = {}

            logger.info(
                "Removed following duplicate components based on GPT response:\n"
                f"Month: {not components_data.is_month_xpath_correct}, "
                f"Year: {not components_data.is_year_xpath_correct}, "
                f"Day: {not components_data.is_day_xpath_correct}"
            )
        else:
            raise Exception(
                f"Couldn't identify which separate components to keep for date field {self.title} "
                f"on {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

    @staticmethod
    def _get_date_component_in_format(date, date_format, date_component):
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
            "category": self.category,
            "components": {
                k: v.to_dict() if isinstance(v, PageComponent) else v
                for k, v in self.components.items()
                if v is not None
            },
            "has_calendar_button": self.has_calendar_button,
            "has_separate_components": self.has_separate_components,
            "input_method_identified": self.input_method_identified,
            "input_method_details_identified": self.input_method_details_identified,
            "question": self.question,
            "persist_context_fields": self.persist_context_fields,
            "next": self.next.to_dict() if self.next else None,
        }
        return output

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            title=input_dict["title"],
            question=input_dict.get("question"),
            category=input_dict["category"],
            parent_application_page=parent_application_page,
            persist_context_fields=input_dict.get("persist_context_fields", True),
        )
        instance.date_format = input_dict["date_format"]

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
            answer, _ = ApplicationField.extract_field_answer(
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
