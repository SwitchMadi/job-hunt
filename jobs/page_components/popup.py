from pydantic import BaseModel, Field
from enum import Enum
import time

from jobs.page_components import PageComponent, get_page_component_class_name, logger
from jobs.page_components.button import Button
from utilities import constants
from utilities.gpt import get_gpt_response
from utilities.selenium import get_selenium_driver, minify_html_for_gpt_prompt

driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class Popup(PageComponent):
    def __init__(self, parent_application_page, previous_step=None):
        self.previous_step = previous_step
        self.parent_application_page = parent_application_page

        self.field_component = None
        self.component_identified = False

        self.next = None
        self.prev = None
        self.is_component_functional = False

    def proceed(self, retry=False):
        if not self.component_identified:
            self._identify()
            if self.previous_step == "resume_upload":
                time.sleep(10)
            return

        if self.field_component:
            self.field_component.proceed()

            if self.previous_step == "resume_upload":
                time.sleep(10)

    def _identify(self, retry=False):
        global driver

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"I need to determine if there is any popup or modal dialog visible on the page currently. If there is one, I "
            f"need to find the most appropriate button to close it in a way that won't prevent the job application from "
            f"proceeding. For example:\n"
            f"1. If it's a terms & conditions popup, find the accept/agree button rather than decline/close\n"
            f"2. If it's a cookies consent, find the accept button\n"
            f"3. If it's a general info popup with just OK/Close, that's fine to close\n"
            f"4. Any buttons that clearly prevent proceeding (like 'Cancel Application') should be avoided\n"
            "Analyze the HTML carefully and if there is a visible popup with an appropriate button to dismiss it, provide "
            "the button's XPath."
        )

        class IsPopupPresent(Enum):
            true = True
            false = False

        class PopupButton(BaseModel):
            popup_present: IsPopupPresent = Field(
                ...,
                description="Whether there is currently a popup/modal visible on the page that needs to be handled",
            )
            popup_button_x_path: str = Field(
                ...,
                description="XPath of the appropriate button to dismiss the popup which can be used in selenium chrome "
                "driver to search the button. Don't use HTML hierarchy to construct XPath. Return empty string if no "
                "popup is present.",
            )

        popup_button_found, popup_button = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=PopupButton,
        )

        if popup_button_found:
            if popup_button.popup_present.value and popup_button.popup_button_x_path:
                if self.parent_application_page.component_x_path_exists(
                    popup_button.popup_button_x_path
                ):
                    logger.warn(
                        f"Page component with following x_path already exists - {popup_button.popup_button_x_path}"
                    )
                    return

                self.field_component = Button(
                    x_path=popup_button.popup_button_x_path,
                    button_type="popup_button",
                    parent_application_page=self.parent_application_page,
                )

                self.field_component.proceed()
                if self.field_component.is_component_functional:
                    self.is_component_functional = True
                    self.component_identified = True
                elif not retry:
                    self._identify(retry=True)
                else:
                    raise Exception(
                        f"Couldn't interact with popup button for {self.parent_application_page.parent_job.title}. "
                        f"URL - {self.parent_application_page.url}"
                    )
            else:
                # No popup present, component still identified successfully
                self.component_identified = True
                self.is_component_functional = False
                return
        else:
            raise Exception(
                f"Couldn't analyze page for popups for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "previous_step": self.previous_step,
            "field_component": (
                self.field_component.to_dict() if self.field_component else None
            ),
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            previous_step=input_dict["previous_step"],
            parent_application_page=parent_application_page,
        )

        if input_dict.get("field_component"):
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
