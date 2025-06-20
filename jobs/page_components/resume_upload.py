from pydantic import BaseModel, Field
import dotenv
import yaml
import os

from jobs.page_components import (
    PageComponent,
    get_page_component_class_name,
    ApplicationField,
    logger,
)
from jobs.page_components.upload import Upload
from utilities import constants
from utilities.gpt import get_gpt_response
from utilities.selenium import (
    get_selenium_driver,
    element_exists,
    minify_html_for_gpt_prompt,
)
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

    def _identify(self, retry=False, prev_x_path=None):
        global driver

        title_prompt = f"Field title - {self.title}\n" if self.title else ""

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"There is following field on this webpage to upload resume -\n"
            f"{title_prompt}"
            f"I need to find XPath of upload resume button so that I can upload the resume. Keep in "
            f"mind following -\n"
            f"1. Be pragmatic — if a simple XPath like `//input[@type='file']` or a visible button works, prefer it. "
            f"Do not overcomplicate.\n"
            f"2. If text is not directly inside an element (e.g. wrapped in spans), prefer using `contains(., '...')` "
            f"or `normalize-space(.)` over `text()` for better accuracy.\n"
            f"3. Ensure the XPath will remain stable across small HTML or CSS changes by avoiding overly specific "
            f"classes or sibling positions when possible.\n"
            f"4. Be accurate but don’t overthink obvious cases."
        )

        if retry and prev_x_path:
            user_prompt += (
                f"\n\nIn previous try you gave following x_path and the button couldn't be found using that. So, find "
                f"correct x_path for the button.\n"
                f"Previous x_path - {prev_x_path}\n"
            )

        class UploadResumeButton(BaseModel):
            x_path: str = Field(
                ...,
                description="XPath of the button to upload the resume which can be used in selenium chrome driver to "
                "search the button. Don't use HTML hierarchy to construct XPath.",
            )
            another_file_already_uploaded: bool = Field(
                False,
                description="If True, it means that based on HTML there seems to be another file already uploaded for "
                "the upload button with the extracted x_path.",
            )

        button_found, button = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=UploadResumeButton,
        )

        if button_found:
            if button.another_file_already_uploaded:
                logger.warning(
                    f"Another file/resume seems to be already uploaded for job "
                    f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                )
                return

            if not element_exists(button.x_path):
                prompt = "The x_path that we are trying to extract is of resume upload button."
                correct_x_path = ApplicationField.extract_correct_x_path(
                    prev_x_path=button.x_path,
                    prompt=prompt,
                    job_title=self.parent_application_page.parent_job.title,
                    job_url=self.parent_application_page.url,
                )
                if not correct_x_path:
                    raise Exception(
                        f"Couldn't extract resume upload button XPath for "
                        f"{self.parent_application_page.parent_job.title}. "
                        f"URL - {self.parent_application_page.parent_job.url}"
                    )
                else:
                    button.x_path = correct_x_path

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

        success = s3.fetch_data(
            file_s3_path=self.parent_application_page.parent_job.user.resume,
            file_local_path=file_local_path,
        )

        if success and os.path.exists(file_local_path):
            self._resume_file_path = file_local_path
        else:
            raise Exception(
                f"Couldn't fetch resume file from S3 for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )

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
