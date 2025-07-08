from pydantic import BaseModel, Field
from enum import Enum

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
    disable_browser_alerts,
    switch_to_active_tab,
)

driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class ApplicationDataSource(PageComponent):
    def __init__(self, parent_application_page):
        self.parent_application_page = parent_application_page

        self.field_component = None
        self.component_identified = False

        self.next = None
        self.prev = None
        self.is_component_functional = False

    def proceed(self, retry=False):
        if not self.component_identified:
            return self._identify()

        self.field_component.proceed()

        switch_to_active_tab()
        disable_browser_alerts()

    def _identify(self, retry=False):
        global driver

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"On current page there is certain section where options are given to select application data source "
            f"strategy like Linkedin, Indeed, upload resume or manually input data etc. First identify the section and "
            f"then resolve following query strictly for the identified section only - \n"
            f"Out of the given application data source options in the identified section is there an explicit option to"
            f" choose data input strategy as manual input? If yes then give XPath of the button. The button must only "
            f"be for choosing data input strategy as manual, not to actually start inputting application data. If there"
            f" is no such button then return check if button for uploading resume is there. If it is there then return "
            f"true otherwise return false."
        )

        class IsElementPresent(Enum):
            true = True
            false = False

        class ManualDataInputOption(BaseModel):
            manual_data_input_option_present: IsElementPresent = Field(
                ...,
                description="Out of the given application data source options, is there an option to opt for manual "
                "data input as primary method? This button should only be for selecting data strategy. "
                "Return false if no such button found.",
            )
            manual_data_input_x_path: str = Field(
                ...,
                description="If the is option to select manual data input strategy then XPath of the button to opt for "
                "manually inputting application data which can be used in selenium chrome driver to search the button. "
                "Don't use HTML hierarchy to construct XPath.",
            )
            upload_resume_button_present: IsElementPresent = Field(
                ...,
                description="If there is no option to select manual data input strategy then check if there is an "
                "option to upload resume. If yes then return true, else return false.",
            )

        manual_data_input_option_searched, manual_data_input_option = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=ManualDataInputOption,
        )

        if manual_data_input_option_searched:
            if manual_data_input_option.manual_data_input_option_present.value:
                if self.parent_application_page.component_x_path_exists(
                    manual_data_input_option.manual_data_input_x_path
                ):
                    logger.warn(
                        f"Page component with following x_path already exists - {manual_data_input_option.manual_data_input_x_path}"
                    )
                    return

                if not is_element_visible(
                    manual_data_input_option.manual_data_input_x_path
                ):
                    prompt = (
                        "The x_path that we are trying to extract is of a button to opt for manually inputting "
                        "application data or selecting data input strategy as manual."
                    )
                    correct_x_path = ApplicationField.extract_correct_x_path(
                        prev_x_path=manual_data_input_option.manual_data_input_x_path,
                        prompt=prompt,
                        job_title=self.parent_application_page.parent_job.title,
                        job_url=self.parent_application_page.url,
                    )
                    if not correct_x_path:
                        raise Exception(
                            f"Couldn't extract XPath for selecting manual data input option for "
                            f"{self.parent_application_page.parent_job.title}. "
                            f"URL - {self.parent_application_page.parent_job.url}"
                        )
                    else:
                        manual_data_input_option.manual_data_input_x_path = (
                            correct_x_path
                        )

                self.field_component = Button(
                    x_path=manual_data_input_option.manual_data_input_x_path,
                    button_type="select_application_data_source",
                    parent_application_page=self.parent_application_page,
                )

                self.field_component.proceed()
                if self.field_component.is_component_functional:
                    self.is_component_functional = True
                    self.component_identified = True

                    switch_to_active_tab()
                    disable_browser_alerts()

                    return None
                else:
                    raise Exception(
                        f"Data input option not found / identified for {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                    )
            elif manual_data_input_option.upload_resume_button_present.value:
                return "resume_upload"
            else:
                return None
        else:
            raise Exception(
                f"Data input option not found / identified for {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
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
