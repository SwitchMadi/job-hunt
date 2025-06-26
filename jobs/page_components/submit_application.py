import time
from pydantic import BaseModel, Field
import os
from selenium.webdriver.support.ui import WebDriverWait

from jobs.page_components import (
    PageComponent,
    get_page_component_class_name,
    ApplicationField,
)
from jobs.page_components.button import Button
from jobs.page_components.resume_upload import ResumeUpload
from utilities import constants
from utilities.gpt import get_gpt_response
from utilities.selenium import (
    get_selenium_driver,
    minify_html_for_gpt_prompt,
    is_element_visible,
)

driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class SubmitApplication(PageComponent):
    def __init__(self, parent_application_page):
        self.parent_application_page = parent_application_page

        self.field_component = None
        self.component_identified = False

        self.next = None
        self.prev = None
        self.is_component_functional = False

    def proceed(self, retry=False):
        if not self.component_identified:
            self._identify()
        else:
            self.field_component.proceed()

        self._switch_to_active_tab()
        return

    def _identify(self, retry=False):
        global driver
        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"The webpage has submit application button clicking which user can submit the job application. Analyse "
            f"the whole HTML very carefully for extracting XPath of the submit application button. Don't confuse "
            f"yourself with any button to go to next page."
        )

        class SubmitApplicationButton(BaseModel):
            is_submit_button_present: bool = Field(
                ...,
                description="Whether submit application button is present on the page",
            )
            x_path: str = Field(
                ...,
                description="XPath of next submit application button which can be used in selenium chrome driver to "
                "search the button. Don't use HTML hierarchy to construct XPath.",
            )

        button_found, button = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=SubmitApplicationButton,
        )
        if button_found:
            if button.is_submit_button_present:
                if not is_element_visible(button.x_path):
                    prompt = "The x_path that we are trying to extract is of submit application button."
                    correct_x_path = ApplicationField.extract_correct_x_path(
                        prev_x_path=button.x_path,
                        prompt=prompt,
                        job_title=self.parent_application_page.parent_job.title,
                        job_url=self.parent_application_page.url,
                    )
                    if not correct_x_path:
                        raise Exception(
                            f"Couldn't extract submit application button XPath for "
                            f"{self.parent_application_page.parent_job.title}. "
                            f"URL - {self.parent_application_page.parent_job.url}"
                        )
                    else:
                        button.x_path = correct_x_path

                self.field_component = Button(
                    x_path=button.x_path,
                    button_type="submit_application",
                    parent_application_page=self.parent_application_page,
                )

                self.field_component.proceed()
                if self.field_component.is_component_functional:
                    self.is_component_functional = True
                    self.component_identified = True

                    # Wait for page load to complete
                    WebDriverWait(driver, 10).until(
                        lambda d: d.execute_script("return document.readyState")
                        == "complete"
                    )
                    time.sleep(5)

                    self._delete_downloaded_resume()

                elif not retry:
                    self._identify(retry=True)
                else:
                    raise Exception(
                        f"Couldn't extract submit application button for {self.parent_application_page.parent_job.title}. "
                        f"URL - {self.parent_application_page.url}"
                    )
            else:
                return
        else:
            raise Exception(
                f"Couldn't extract submit application button for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )

    @staticmethod
    def _switch_to_active_tab():
        global driver
        driver.switch_to.window(driver.window_handles[-1])

    def _delete_downloaded_resume(self):
        cur_application_step = self.parent_application_page.head_step
        while cur_application_step:
            if isinstance(cur_application_step, ResumeUpload):
                try:
                    os.remove(cur_application_step.resume_file_path)
                except FileNotFoundError:
                    pass

                return

            cur_application_step = cur_application_step.next

        return

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
