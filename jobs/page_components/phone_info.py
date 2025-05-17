from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum

from jobs.page_components import (
    PageComponent,
    get_page_component_class_name,
    logger,
    ApplicationField,
)
from utilities.selenium import get_selenium_driver, minify_html_for_gpt_prompt
from utilities.gpt import get_gpt_response
from utilities import constants

driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class PhoneInfo(PageComponent):
    def __init__(self, parent_application_page):
        self.parent_application_page = parent_application_page
        self.identified_fields = []
        self.component_identified = False

        self.next = None
        self.prev = None
        self.is_component_functional = False

    def proceed(self, retry=False):
        if not self.component_identified:
            return self._identify()

        for field in self.identified_fields:
            field.proceed()

    def _identify(self):
        global driver
        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
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
                description="Phone field's exact title / question mentioned on the webpage, without modification",
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
            "identified_fields": [field.to_dict() for field in self.identified_fields],
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(parent_application_page=parent_application_page)
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
