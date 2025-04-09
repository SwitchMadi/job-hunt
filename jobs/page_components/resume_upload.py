from pydantic import BaseModel, Field
import dotenv
import yaml
import os
from enum import Enum

from jobs.page_components import PageComponent, get_page_component_class_name
from jobs.page_components.upload import Upload
from utilities import minify_html_for_gpt_prompt, constants
from utilities.gpt import get_gpt_response
from utilities.selenium import get_selenium_driver, element_exists
from utilities.aws.s3 import S3Bucket


driver = get_selenium_driver()
driver.set_page_load_timeout(15)

dotenv.load_dotenv()
config = yaml.safe_load(open("config.yml"))


class ResumeUpload(PageComponent):
    def __init__(self, title, parent_application_page):
        self.title = title

        self.parent_application_page = parent_application_page

        self.field_component = None
        self._resume_file_path = None
        self.component_identified = False

        self.next = None
        self.prev = None
        self.is_component_functional = False

    def proceed(self, retry=False):
        if not self.component_identified:
            return self._identify()

        self.field_component.file_path = self.resume_file_path
        self.field_component.proceed()

        return

    def _identify(self, retry=False):
        global driver

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"There is following field on this webpage to upload resume -\n"
            f"Field title - {self.title}\n"
            f"I need to find XPath of upload button so that I can upload the resume. Before uploading the resume, I "
            f"need to decide whether the above field is just another application field to upload resume or is it part "
            f"of data selection strategy for whole application. If the field is part of application data source "
            f"selection step or immediately surrounded by application data source options like LinkedIn, Indeed, "
            f"manual data input etc. then do not give XPath details of resume upload button as I want to insert data "
            f"manually. If field is just standalone upload resume button and there is no sign of it being one option "
            f"out of many application data input options only then give me XPath of the resume upload button."
        )

        class IsNotADataInputOption(Enum):
            true = True
            false = False

        class UploadResumeButton(BaseModel):
            is_not_a_data_input_option: IsNotADataInputOption = Field(
                ...,
                description="Is the field just a standalone upload resume button, with no indication that it's one "
                "option among many ways to input application data?",
            )
            x_path: str = Field(
                ...,
                description="XPath of the button to upload the resume which can be used in selenium chrome driver to "
                "search the button. Don't use HTML hierarchy to construct XPath.",
            )

        button_found, button = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=UploadResumeButton,
        )

        if button_found:
            if button.is_not_a_data_input_option.value:
                if not element_exists(button.x_path) and not retry:
                    return self._identify(retry=True)

                self.field_component = Upload(
                    x_path=button.x_path,
                    upload_type="resume_upload",
                    parent_application_page=self.parent_application_page,
                )

                self.field_component.file_path = self.resume_file_path
                self.field_component.proceed()

                if self.field_component.is_component_functional:
                    self.is_component_functional = True
                    self.component_identified = True

                    os.remove(self.resume_file_path)
                elif not retry:
                    self._identify(retry=True)
                else:
                    raise Exception(
                        f"Couldn't extract upload resume button for {self.parent_application_page.parent_job.title}. "
                        f"URL - {self.parent_application_page.url}"
                    )
            else:
                return
        else:
            raise Exception(
                f"Couldn't extract upload resume button for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )

    @property
    def resume_file_path(self):
        if self._resume_file_path:
            return self._resume_file_path

        s3 = S3Bucket(bucket_name=config["s3_bucket"])

        file_name = self.parent_application_page.parent_job.user.resume.split("/")[-1]
        file_local_path = f"{config['other_files_folder']}/{file_name}"

        s3.fetch_data(
            file_s3_path=self.parent_application_page.parent_job.user.resume,
            file_local_path=file_local_path,
        )

        self._resume_file_path = file_local_path

        return self._resume_file_path

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "title": self.title,
            "field_component": self.field_component.to_dict(),
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            title=input_dict["title"],
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
