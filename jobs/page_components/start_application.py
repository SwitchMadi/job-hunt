from pydantic import BaseModel, Field
from enum import Enum
from selenium.webdriver.common.by import By

from jobs.page_components import (
    PageComponent,
    get_page_component_class_name,
    ApplicationField,
    logger,
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
    element_exists,
    get_element_xpath,
)

driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class StartApplication(PageComponent):
    def __init__(self, parent_application_page):
        self.parent_application_page = parent_application_page

        self.field_component = None
        self.component_identified = False

        self._previous_start_button_x_paths = None

        self.next = None
        self.prev = None
        self.is_component_functional = False

    @property
    def previous_start_button_x_paths(self):
        global driver

        if self._previous_start_button_x_paths is not None:
            return self._previous_start_button_x_paths

        _previous_start_button_x_paths = []
        cur_application_step = self.parent_application_page.head_step
        while cur_application_step:
            if isinstance(cur_application_step, StartApplication):
                if (
                    hasattr(cur_application_step, "field_component")
                    and cur_application_step.field_component
                ):
                    curr_x_path = cur_application_step.field_component.x_path
                    if element_exists(curr_x_path):
                        # append the current x_path to the list
                        _previous_start_button_x_paths.append(curr_x_path)

                        # append full x_path of the element
                        elm = driver.find_element(By.XPATH, curr_x_path)
                        _previous_start_button_x_paths.append(get_element_xpath(elm))

            cur_application_step = cur_application_step.next

        self._previous_start_button_x_paths = _previous_start_button_x_paths
        return _previous_start_button_x_paths

    def proceed(self, retry=False):
        if not self.component_identified:
            self._identify()
        else:
            self.field_component.proceed()

        switch_to_active_tab()
        disable_browser_alerts()

        return

    def _identify(self, retry=False):
        global driver

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"As a first step in the job application, I have to start application by clicking some button. Give XPath "
            f"of the visible UI element clicking which I can start the job application. Be very careful about following "
            f"criteria -\n"
            f"The button should have word like start, apply or something similar clicking which can seemingly start the "
            f"job application . It can be just one word like 'Apply' as well also but definitely not 'Apply with "
            f"<some_platform_like_linkedin_etc>' kind of text. It's not next step or submit application button or some "
            f"other button also. If there is not any start application kind of button you can find then don't return "
            f"XPath. If there are multiple start application buttons then prioritize the visible button."
        )

        class IsStartApplicationButtonPresent(Enum):
            true = True
            false = False

        class StartApplicationButton(BaseModel):
            is_start_application_button_present: IsStartApplicationButtonPresent = (
                Field(
                    ...,
                    description="Does a visible start application button exist based on prompt criteria?",
                )
            )
            x_path: str = Field(
                ...,
                description="XPath of the visible button to start the job application which can be used in selenium "
                "chrome driver to search the button. Don't use HTML hierarchy to construct XPath.",
            )

        button_found, button = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=StartApplicationButton,
        )

        if button_found:
            if button.is_start_application_button_present.value:
                if not is_element_visible(button.x_path):
                    prompt = "The x_path that we are trying to extract is of start application button."
                    correct_x_path = ApplicationField.extract_correct_x_path(
                        prev_x_path=button.x_path,
                        prompt=prompt,
                        job_title=self.parent_application_page.parent_job.title,
                        job_url=self.parent_application_page.url,
                    )
                    if not correct_x_path:
                        raise Exception(
                            f"Couldn't extract start application button XPath for "
                            f"{self.parent_application_page.parent_job.title}. "
                            f"URL - {self.parent_application_page.parent_job.url}"
                        )
                    else:
                        button.x_path = correct_x_path

                # check if the same button was already identified in previous steps
                elm = driver.find_element(By.XPATH, button.x_path)
                full_x_path = get_element_xpath(elm)

                if (
                    button.x_path in self.previous_start_button_x_paths
                    or full_x_path in self.previous_start_button_x_paths
                ):
                    logger.warn(
                        f"Start application button already identified in previous steps for "
                        f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                    )
                    return

                element = driver.find_element(By.XPATH, button.x_path)
                element_text = element.text or ""

                if (
                    "submit" in button.x_path.lower()
                    or "submit" in element_text.strip().lower()
                ):
                    logger.warn(
                        f"Start application button actually seems to be submit button for "
                        f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                    )
                    return

                self.field_component = Button(
                    x_path=button.x_path,
                    button_type="start_application",
                    parent_application_page=self.parent_application_page,
                )

                self.field_component.proceed()
                if self.field_component.is_component_functional:
                    self.is_component_functional = True
                    self.component_identified = True
                else:
                    raise Exception(
                        f"Couldn't extract start application button for {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                    )
            else:
                return
        else:
            raise Exception(
                f"Couldn't extract start application button for {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
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
