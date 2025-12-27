from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
from selenium.webdriver.common.by import By
from selenium.common.exceptions import InvalidSelectorException

from jobs.page_components import (
    PageComponent,
    get_page_component_class_name,
    logger,
    ApplicationField,
)
from utilities.selenium import (
    get_selenium_driver,
    minify_html_for_gpt_prompt,
    find_input_block_for_title,
)
from utilities.gpt import get_gpt_response
from utilities import constants

driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class PhoneInfo(PageComponent):
    def __init__(self, title, parent_application_page):
        self.title = title
        self.parent_application_page = parent_application_page
        self.identified_fields = []
        self.component_identified = False

        self.next = None
        self.prev = None
        self.is_component_functional = False

    @staticmethod
    def _find_best_parent_element(element, max_levels=3):
        """
        Find the best parent element by trying to traverse up the DOM tree.
        Reduces level by one if InvalidSelectorException occurs until no parent is left.

        Args:
            element: The starting element
            max_levels: Maximum number of levels to traverse up (default: 3)

        Returns:
            The best available parent element or the original element if no parent found
        """
        # Generate XPath patterns from highest to lowest level
        xpath_patterns = [
            f"./{'../' * i}".rstrip("/") for i in range(max_levels, -1, -1)
        ]

        for xpath in xpath_patterns:
            try:
                return element.find_element(By.XPATH, xpath)
            except InvalidSelectorException:
                continue
            except Exception:
                # Re-raise non-InvalidSelectorException errors
                raise

        # Fallback to original element if no parent found
        return element

    def proceed(self, retry=False):
        if not self.component_identified:
            return self._identify()

        for field in self.identified_fields:
            field.proceed()

    def _identify(self):
        global driver

        user_input_element = None
        try:
            element_identified, user_input_element, computed_container_xpath = (
                find_input_block_for_title(self.title)
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
            # since it's phone field, we'll consider parent elements up to 3 levels up to possibly capture
            # country code dropdowns etc.
            user_input_element = self._find_best_parent_element(user_input_element)
            minified_html = minify_html_for_gpt_prompt(
                user_input_element.get_attribute("outerHTML")
            )
        else:
            minified_html = minify_html_for_gpt_prompt(driver.page_source)

        user_prompt = (
            f"Following HTML is of job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minified_html}\n"
            f"Extract all phone information related fields on this page. These can include phone country code, "
            f"phone number etc. Return following info for each field -\n"
            f"1. Exact field title as shown on page\n"
            f"2. Field question - if field title alone doesn't make sense as a question then modify it to make "
            f"question\n"
            f"3. Field category - can be only phone_country_code, phone_number\n"
            f"If there are no phone related fields then return empty list."
        )

        class PhoneFieldCategory(Enum):
            phone_country_code = "phone_country_code"
            phone_number_without_country_code = "phone_number_without_country_code"

        class PhoneField(BaseModel):
            field_title: str = Field(
                ...,
                description="Phone field's exact title / question mentioned on the webpage, strictly without any "
                "modification whatsoever.",
            )
            field_question: Optional[str] = Field(
                ...,
                description="If field title alone doesn't make sense as a question then modify it to make it a "
                "question. Otherwise return None",
            )
            field_category: PhoneFieldCategory = Field(
                ..., description="Category of the phone information field"
            )

        class PhoneFields(BaseModel):
            phone_fields: List[PhoneField] = Field(
                ..., description="List of phone related fields found on the page"
            )

        fields_found, fields = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=PhoneFields,
        )

        if fields_found:
            if fields.phone_fields:
                for field in fields.phone_fields:
                    application_field = ApplicationField(
                        parent_application_page=self.parent_application_page,
                        title=field.field_title,
                        question=field.field_question,
                        category=field.field_category.value,
                        title_to_click=self.title,
                    )
                    field_component = application_field.get_field_component()
                    if field_component:
                        field_component.proceed()
                        self.identified_fields.append(field_component)

                self.is_component_functional = True
                self.component_identified = True
            else:
                logger.warn(
                    f"No phone fields found for {self.parent_application_page.parent_job.title}. "
                    f"Url: {self.parent_application_page.url}"
                )
                return

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "title": self.title,
            "identified_fields": [field.to_dict() for field in self.identified_fields],
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            title=input_dict["title"], parent_application_page=parent_application_page
        )
        instance.component_identified = True

        for field_dict in input_dict["identified_fields"]:
            field_class = get_page_component_class_name(class_name=field_dict["class"])
            field = field_class.from_dict(field_dict, parent_application_page)
            instance.identified_fields.append(field)

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
