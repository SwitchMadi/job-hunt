from pydantic import BaseModel, Field

from jobs.page_components import (
    PageComponent,
    get_page_component_class_name,
    logger,
    ApplicationField,
)
from jobs.page_components.button import Button
from utilities import constants
from utilities.gpt import get_gpt_response
from utilities.selenium import (
    get_selenium_driver,
    minify_html_for_gpt_prompt,
    is_element_visible,
    find_input_block_for_title,
)

driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class TermsAndConditions(PageComponent):
    def __init__(self, parent_application_page, field_info=None):
        self.parent_application_page = parent_application_page
        self.field_info = field_info

        self.field_component = None
        self.component_identified = False

        self.next = None
        self.prev = None
        self.is_component_functional = False

    def proceed(self, retry=False):
        if not self.component_identified:
            return self._identify()

        self.field_component.proceed()

    def _identify(self, retry=False):
        global driver

        user_input_element = None
        try:
            element_identified, user_input_element = find_input_block_for_title(
                self.field_info.field_title
            )
            if not element_identified:
                logger.warn(
                    f"Input block for title {self.field_info.field_title} not identified in job "
                    f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                )
        except Exception as e:
            logger.warn(
                f"Error while finding input block for title {self.field_info.field_title} in job "
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
            f"The webpage has TnC field for applying to the job. Following is info about the TnC field -\n"
            f"Field title - {self.field_info.field_title}\n"
            f"Field category - {self.field_info.field_category}\n"
            f"Analyse the whole HTML very carefully for extracting XPath of the TnC field. It is usually a checkbox "
            f"or a button."
        )

        class TnCField(BaseModel):
            x_path: str = Field(
                ...,
                description="XPath of TnC field which can be used in selenium chrome driver to search the field. Don't "
                "use HTML hierarchy to construct XPath.",
            )

        tnc_field_found, tnc_field = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=TnCField,
        )
        if tnc_field_found:
            if not is_element_visible(tnc_field.x_path):
                prompt = "The x_path that we are trying to extract is of T&C field checkbox / button."
                correct_x_path = ApplicationField.extract_correct_x_path(
                    prev_x_path=tnc_field.x_path,
                    prompt=prompt,
                    job_title=self.parent_application_page.parent_job.title,
                    job_url=self.parent_application_page.url,
                )
                if not correct_x_path:
                    raise Exception(
                        f"Couldn't extract T&C field XPath for "
                        f"{self.parent_application_page.parent_job.title}. "
                        f"URL - {self.parent_application_page.parent_job.url}"
                    )
                else:
                    tnc_field.x_path = correct_x_path

            if self.parent_application_page.component_x_path_exists(tnc_field.x_path):
                logger.warn(
                    f"Page component with following x_path already exists - {tnc_field.x_path}"
                )
                return

            self.field_component = Button(
                x_path=tnc_field.x_path,
                button_type="tnc_consent",
                parent_application_page=self.parent_application_page,
            )

            self.field_component.proceed()
            if self.field_component.is_component_functional:
                self.is_component_functional = True
                self.component_identified = True
            else:
                raise Exception(
                    f"Couldn't extract TnC field for {self.parent_application_page.parent_job.title}. "
                    f"URL - {self.parent_application_page.url}"
                )
        else:
            raise Exception(
                f"Couldn't extract TnC field for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "field_component": self.field_component.to_dict(),
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            parent_application_page=parent_application_page,
        )

        field_component_class = get_page_component_class_name(
            class_name=input_dict["field_component"]["class"]
        )
        instance.field_component = field_component_class.from_dict(
            input_dict=input_dict["field_component"],
            parent_application_page=parent_application_page,
        )

        instance.component_identified = True

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
