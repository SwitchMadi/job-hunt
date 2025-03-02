from pydantic import BaseModel, Field

from jobs.page_components import PageComponent, Button, get_page_component_class_name
from utilities import minify_html_for_gpt_prompt, constants
from utilities.gpt import get_gpt_response
from utilities.selenium import get_selenium_driver


driver = get_selenium_driver(headless=False)
driver.set_page_load_timeout(15)


class ApplicationDataSource(PageComponent):
    def __init__(self, parent_application_page):
        self.parent_application_page = parent_application_page

        self.field_component = None
        self.component_identified = False

        self.next = None
        self.prev = None
        self.is_component_functional = False

    def proceed(self):
        if not self.component_identified:
            return self._identify()

        self.field_component.proceed()

    def _identify(self, retry=False):
        global driver

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"As the next step in the job application, I have to select how I want to insert data in the application "
            f"fields. Priority is as follows -\n"
            f"1. Manually insert data\n"
            f"2. Autofill with resume\n"
            f"Based on above priority give me XPath of just 1 UI element clicking which I can select data "
            f"input strategy for the job application."
        )

        class DataInputOption(BaseModel):
            x_path: str = Field(
                ..., description="XPath of the UI element to start the job application"
            )
            strategy: str = Field(..., description="selected data input strategy")

        data_input_option_found, data_input_option = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=DataInputOption,
        )

        if data_input_option_found:
            self.field_component = Button(
                x_path=data_input_option.x_path,
                button_type="select_application_data_source",
                parent_application_page=self,
                click_result=data_input_option.strategy,
            )

            self.field_component.proceed()
            if self.field_component.is_component_functional:
                self.is_component_functional = True
                self.component_identified = True
            elif not retry:
                self._identify(retry=True)
            else:
                raise Exception(
                    f"Data input option not found / identified for {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                )
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
