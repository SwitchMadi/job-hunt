import time
from pydantic import BaseModel, Field
from enum import Enum
import json

from utilities import minify_html_for_gpt_prompt, constants, generate_hash
from utilities.selenium import get_selenium_driver, extract_iframe_urls
from utilities.gpt import get_gpt_response
from utilities.logging import get_logger
from utilities.sql import get_sql_query_output, execute_sql_query
from jobs.page_components import Button, Login


logger = get_logger(name="job")
driver = get_selenium_driver(headless=False)
driver.set_page_load_timeout(15)


class Job:
    def __init__(self, url, title=None, user=None):
        self.url = url

        job = Job.find_job_by_url(url)
        if job is None:
            self.hash_id = generate_hash(url)
            self.title = title
            self.save_to_db()
            job = Job.find_job_by_url(url)

        self.id = job["id"]
        self.hash_id = job["job_hash_id"]
        self.title = job["title"]

        self.application_page = ApplicationPage(url=url, parent_job=self)
        self.user = user

    @staticmethod
    def find_job_by_url(url):
        job_hash_id = generate_hash(url)
        job_query = f"""
                        select *
                        from jobs.jobs
                        where job_hash_id = '{job_hash_id}'
                    """
        job = get_sql_query_output(job_query)
        if job:
            return job[0]
        else:
            return None

    def save_to_db(self):
        job_create_query = f"""
            insert into jobs.jobs
            (job_hash_id, job_url, title)
            values ('{self.hash_id}', '{self.url}', '{self.title}')
        """
        return execute_sql_query(job_create_query)


class ApplicationPage:
    def __init__(self, url, parent_job: Job, page_source=None):
        self.url = url
        self.page_source = page_source
        self.parent_job = parent_job

        self.original_application_page = ApplicationPage
        self.head_step = None
        self.tail_step = None

        self._get_application_steps()

    def _get_application_steps(self):
        application_steps_query = f"""
                                        select *
                                        from jobs.application_steps
                                        where job_id = {self.parent_job.id}
                                        and is_active;
                                   """
        application_steps = get_sql_query_output(application_steps_query)
        if application_steps:
            application_steps = application_steps[0]
            head_step_class = globals()[application_steps["steps"]["class"]]
            self.head_step = self.tail_step = head_step_class.from_dict(
                input_dict=application_steps["steps"], parent_application_page=self
            )

            next_step = self.head_step.next
            while next_step:
                self.tail_step = next_step
                next_step = next_step.next

            return True
        else:
            return False

    def _save_application_steps(self):
        application_steps_dict = json.dumps(self.head_step.to_dict()).replace("'", "''")

        application_steps_query = f"""
                                        select *
                                        from jobs.application_steps
                                        where job_id = {self.parent_job.id}
                                        and is_active;
                                   """
        current_application_steps = get_sql_query_output(application_steps_query)
        if current_application_steps:
            query = f"""
                        update jobs.application_steps
                        set steps = '{application_steps_dict}'
                        where job_id = {self.parent_job.id}
                        and is_active;
                    """
        else:
            query = f"""
                INSERT INTO jobs.application_steps
                (job_id, steps)
                VALUES ({self.parent_job.id}, '{application_steps_dict}');
            """
        return execute_sql_query(query)

    def _update_steps(self, step):
        if step.is_component_functional:
            if self.head_step is None:
                self.head_step = step
                self.tail_step = step
            else:
                self.tail_step.next = step
                step.prev = self.tail_step
                self.tail_step = step

            self._save_application_steps()

        return

    def identify_popups(self):
        global driver
        driver.get(self.url)
        time.sleep(10)

        user_prompt = (
            f"Analyze the following HTML page for any screen overlays or UI overlays such as cookie "
            f"consent banners, pop-ups which is strictly not related to job application, or any other similar "
            f"elements. For each overlay found, provide the XPath of one button to close the overlay."
            f"Carefully analyse each button based on its html, class names & text if it can close the overlay. If the "
            f"button doesn't seem to be closing the overlay then strictly ignore the overlay and do not give button in "
            f"response.\nI will click the XPaths in the order you provide, so ensure the sequence is correct and "
            f"can be clicked in that order.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}"
        )

        class OverlayActionButton(BaseModel):
            x_path: str = Field(
                ...,
                description="For the overlay found, XPath of one button to close the overlay.",
            )
            button_result: str = Field(
                ..., description="What will happen clicking this button?"
            )

        class OverlayActionButtons(BaseModel):
            buttons: list[OverlayActionButton]

        overlay_action_buttons_found, overlay_action_buttons = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=OverlayActionButtons,
        )
        if overlay_action_buttons_found:
            for overlay_action_button in overlay_action_buttons.buttons:
                close_overlay_button = Button(
                    x_path=overlay_action_button.x_path,
                    button_type="close_overlay",
                    parent_application_page=self,
                    click_result=overlay_action_button.button_result,
                )
                close_overlay_button.proceed()
                self._update_steps(close_overlay_button)
        else:
            logger.warn(
                f"GPT could/did not find overlay close buttons. Response - "
                f"{overlay_action_buttons}"
            )

        return

    @property
    def original_application_page_identified(self):
        return isinstance(self.original_application_page, ApplicationPage)

    def identify_original_application_page(self):
        global driver
        driver.get(self.url)
        time.sleep(10)

        # Get the total height of the page
        total_height = driver.execute_script("return document.body.scrollHeight")

        # Calculate the scroll amount (30% of the total height)
        scroll_amount = total_height * 0.3

        # Scroll down by the calculated amount
        driver.execute_script(f"window.scrollBy(0, {scroll_amount})")

        htmls = {"main_page": {"url": self.url, "page_source": driver.page_source}}

        iframe_urls = extract_iframe_urls(driver.page_source)
        iframe_urls = list(set(iframe_urls))
        for iframe_url in iframe_urls:
            driver.get(iframe_url)
            time.sleep(10)
            htmls[f"iframe_{iframe_urls.index(iframe_url)}"] = {
                "url": iframe_url,
                "page_source": driver.page_source,
            }

        html_prompt = ""
        for key, value in htmls.items():
            html_prompt += f"\nkey - {key}\nvalue - {minify_html_for_gpt_prompt(value['page_source'])}\n"

        user_prompt = f"""Out of of following htmls, which one is job application page for job title
            {self.parent_job.title}. Answer should strictly be just the relevant key's name or "Cannot determine" -
            {html_prompt}"""

        job_application_page_key = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
        )

        for key, value in htmls.items():
            if key in job_application_page_key:
                if value["url"] == self.url:
                    self.original_application_page = self
                    self.page_source = value["page_source"]
                else:
                    self.original_application_page = ApplicationPage(
                        url=value["url"],
                        page_source=value["page_source"],
                        parent_job=self.parent_job,
                    )
                break

        if not self.original_application_page_identified:
            logger.critical(
                f"""No application page identified.
                job_application_page_key - {job_application_page_key}
                main_page - {self.url}
                iframe_urls - {iframe_urls}
            """
            )

        return

    def identify_steps(self):
        global driver
        application_completed = False
        while not application_completed:
            user_prompt = (
                f"Following HTML page is job application page for {self.parent_job.title}. Analyse the whole HTML"
                f"very carefully for determining the immediate next step in job application. Respond with just 1 next "
                f"step, not any further than 1 step. Login can be the least priority for next step if possible.\n"
                f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}"
            )

            class JobApplicationStep(str, Enum):
                start_application = "start_application"
                select_application_data_source = "select_application_data_source"
                login = "login"
                job_application_completed = "job_application_completed"
                page_not_found_error = "page_not_found_error"

            class JobApplicationNextStep(BaseModel):
                step: JobApplicationStep = Field(
                    ...,
                    description="What is the immediate & mandatory next step in the job application, based on the "
                    "whole HTML.\n"
                    "start_application - I have to start job application process by clicking somewhere\n"
                    "select_application_data_source - The page is asking for selecting job application data input "
                    "source like autofill using resume, manual input, apply using linkedin etc.\n"
                    "login - If login is mandatory step before moving to any next step in job application.\n"
                    "job_application_completed - Job application has been completed.\n"
                    "page_not_found_error - HTML has error message saying page / job not found or expired",
                )

            next_step_found, next_step = get_gpt_response(
                constants.gpt["system_prompts"]["application_step_identification"],
                user_prompt,
                response_format=JobApplicationNextStep,
            )
            if next_step_found:
                if next_step.step == JobApplicationStep.page_not_found_error:
                    logger.critical(
                        f"Job has expired / not found. Title - {self.parent_job.title}"
                    )
                    return
                if next_step.step == JobApplicationStep.start_application:
                    self._extract_start_application_step_details()
                elif (
                    next_step.step == JobApplicationStep.select_application_data_source
                ):
                    self._extract_application_data_source_options_details()
                elif next_step.step == JobApplicationStep.login:
                    self._extract_login_step_details()
            else:
                application_completed = True

    def _extract_start_application_step_details(self):
        global driver

        user_prompt = (
            f"Following HTML page is job application page for {self.parent_job.title}. As a first step in "
            f"the job application, I have to start application by clicking some button. Give XPath of the"
            f"UI element clicking which I can start the job application.\n"
            f"HTML : {minify_html_for_gpt_prompt(driver.page_source)}"
        )

        class StartApplication(BaseModel):
            x_path: str = Field(
                ...,
                description="XPath of the UI element to start the job application",
            )

        start_application_button_found, start_application_button = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=StartApplication,
        )
        if start_application_button_found:
            start_application_button = Button(
                x_path=start_application_button.x_path,
                button_type="start_application",
                parent_application_page=self,
                click_result="Starts job application",
            )
            start_application_button.proceed()
            self._update_steps(start_application_button)
        else:
            logger.critical(
                f"Start application button not found.\nGPT response - {start_application_button}"
            )

    def _extract_application_data_source_options_details(self):
        global driver

        user_prompt = (
            f"Following HTML page is job application page for {self.parent_job.title}. As the next step in "
            f"the job application, I have to select how I want to insert data in the application fields."
            f"Priority is as follows -\n"
            f"1. Manually insert data\n"
            f"2. Autofill with resume\n"
            f"Based on above priority give me XPath of just 1 UI element clicking which I can select data "
            f"input strategy for the job application.\n"
            f"HTML : {minify_html_for_gpt_prompt(driver.page_source)}"
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
            data_input_option_button = Button(
                x_path=data_input_option.x_path,
                button_type="select_application_data_source",
                parent_application_page=self,
                click_result=data_input_option.strategy,
            )
            data_input_option_button.proceed()
            self._update_steps(data_input_option_button)
        else:
            logger.critical(
                f"Data input option not found / identified properly.\nGPT response - {data_input_option}"
            )

    def _extract_login_step_details(self):
        login_step = Login(parent_application_page=self)
        login_step.proceed()
        self._update_steps(login_step)
