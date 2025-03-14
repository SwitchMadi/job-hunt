import time
from pydantic import BaseModel, Field
from enum import Enum
import json

from utilities import minify_html_for_gpt_prompt, constants, generate_hash
from utilities.selenium import (
    get_selenium_driver,
    extract_iframe_urls,
    disable_browser_alerts,
)
from utilities.gpt import get_gpt_response
from utilities.logging import get_logger
from utilities.sql import get_sql_query_output, execute_sql_query
from jobs.page_components import Button, TextInput
from jobs.page_components.application_data_source import ApplicationDataSource
from jobs.page_components.cookies_consent import CookiesConsent
from jobs.page_components.terms_and_conditions import TermsAndConditions
from jobs.page_components.email import Email
from jobs.page_components.login import Login, VerifyAccount
from jobs.page_components.start_application import StartApplication
from jobs.page_components.next_page import NextPage

logger = get_logger(name="job")
driver = get_selenium_driver(headless=False)
driver.set_page_load_timeout(15)


class Job:
    def __init__(self, url, title=None, company=None, user=None):
        self.url = url

        job = Job.find_job_by_url(url)
        if job is None:
            self.hash_id = generate_hash(url)
            self.title = title
            self.company = company
            self.save_to_db()
            job = Job.find_job_by_url(url)

        self.id = job["id"]
        self.hash_id = job["job_hash_id"]
        self.title = job["title"]
        self.company = job["company"]

        self.user = user
        self.application_page = ApplicationPage(url=url, parent_job=self)

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
            (job_hash_id, job_url, title, company)
            values ('{self.hash_id}', '{self.url}', '{self.title}', '{self.company}')
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

        self.account_verification_otp = None

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

    @property
    def original_application_page_identified(self):
        return isinstance(self.original_application_page, ApplicationPage)

    @property
    def start_application_button_processed(self):
        cur_application_step = self.head_step
        while cur_application_step:
            if isinstance(self.head_step, StartApplication):
                return True
            cur_application_step = cur_application_step.next

        return False

    def identify_original_application_page(self):
        global driver
        driver.get(self.url)
        disable_browser_alerts()
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
            disable_browser_alerts()
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

    def redo_steps(self, stop_step=None):
        logger.info("Re-doing all steps...")
        driver.get(self.url)
        disable_browser_alerts()
        time.sleep(10)

        next_step = self.head_step
        while True:
            next_step.proceed()
            next_step = next_step.next

            if next_step is None or next_step is stop_step:
                break

        return

    # Identify job page components
    def identify_application_steps(self):
        global driver
        driver.get(self.url)
        disable_browser_alerts()
        time.sleep(10)

        if self.head_step:
            self.redo_steps()

        identification_completed = False
        while not identification_completed:
            elements = self._identify_current_page_elements()
            if elements:
                self._act_on_current_page_elements(elements)
            else:
                identification_completed = True

    def _identify_current_page_elements(self):
        global driver
        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Analyse the whole HTML very carefully for determining the elements present on the job page."
        )

        class IsElementPresent(Enum):
            true = True
            false = False

        class WebPageElements(BaseModel):
            mandatory_account_login_signup: IsElementPresent = Field(
                ...,
                description="Whether mandatory account login or signup step is there. If the page content suggests in "
                "anyway that login is not required then return false.",
            )
            account_verification: IsElementPresent = Field(
                ...,
                description="Whether current page is explicitly talking about verification via link or OTP?",
            )
            start_application_button: IsElementPresent = Field(
                ...,
                description="There is button to start applying to the job. It's not next step button.",
            )
            next_button: IsElementPresent = Field(
                ...,
                description="There is button to go to next section of application. Don't consider submit application "
                "button as next button.",
            )
            submit_button: IsElementPresent = Field(
                ...,
                description="There is button to go to submit the application. Button for going to next page is not "
                "submit button.",
            )
            select_application_data_source: IsElementPresent = Field(
                ...,
                description="Select application data source like Linkedin, Indeed, upload resume etc.",
            )
            already_applied_alert: IsElementPresent = Field(
                ...,
                description="Page suggests that user has already applied to the job",
            )
            application_fields: IsElementPresent = Field(
                ...,
                description="Job page has form fields to fill application like name, college, experience, email etc.",
            )
            job_not_available_alert: IsElementPresent = Field(
                ..., description="Page suggests that job is no longer available"
            )
            captcha: IsElementPresent = Field(
                ...,
                description="There is a mandatory captcha to proceed further. If it's dummy / empty html representing "
                "captcha then return false.",
            )
            expand_collapse_section: IsElementPresent = Field(
                ...,
                description="Job page has sections which are in collapsed form (arrow, + buttons etc. ) and need to be "
                "expanded to interact with",
            )
            cookies_prompt: IsElementPresent = Field(
                ...,
                description="Webpage has some prompt visible regarding cookies consent",
            )

        elements_found, elements = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=WebPageElements,
        )
        if elements_found:
            return elements
        else:
            logger.error(
                f"Couldn't identify current page elements for {self.parent_job.title}. URL - {self.url}"
            )
            return None

    def _act_on_current_page_elements(self, elements):
        if elements.already_applied_alert.value:
            logger.warn(f"User has already applied to the job.")
            return False

        if elements.job_not_available_alert.value:
            logger.warn(f"Job is not available anymore.")
            return False

        if elements.captcha.value:
            logger.warn(f"There is captcha on the page so cannot move forward.")
            return False

        if elements.cookies_prompt.value:
            self._identify_cookies_consent()

        if elements.mandatory_account_login_signup.value:
            pass

        if elements.account_verification.value:
            self._identify_verify_email_field()

        if (
            elements.start_application_button.value
            and not self.start_application_button_processed
        ):
            is_start_application_functional = self._identify_start_application_button()

            if is_start_application_functional:
                latest_elements = self._identify_current_page_elements()
                if latest_elements:
                    self._act_on_current_page_elements(latest_elements)

                return

        if elements.select_application_data_source.value:
            is_manual_input_functional = (
                self._extract_application_data_source_options_details()
            )

            if is_manual_input_functional:
                latest_elements = self._identify_current_page_elements()
                if latest_elements:
                    self._act_on_current_page_elements(latest_elements)

                return

        if elements.expand_collapse_section.value:
            pass

        if elements.application_fields.value:
            job_fields = self._identify_application_fields()
            self._act_on_job_fields(job_fields)

        # last action after all on page components
        if elements.next_button.value:
            self._identify_next_page_button()

    # Identify application fields
    def _identify_application_fields(self):
        global driver
        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_job.title} at a company called "
            f"{self.parent_job.company}.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"The webpage has job application related fields. Analyse the whole HTML very carefully for extracting all "
            f"the application fields."
        )

        class FieldCategory(Enum):
            first_name = "first_name"
            last_name = "last_name"
            name_prefix = "name_prefix"
            email = "email"
            phone_number = "phone_number"
            address = "address"
            password = "password"
            tnc = "tnc"
            work_permit = "work_permit"
            previous_association_with_the_company = (
                "previous_association_with_the_company"
            )
            work_experience = "work_experience"
            education = "education"
            resume_upload = "resume_upload"
            other = "other"

        class FieldType(Enum):
            textbox = "textbox"
            checkbox = "checkbox"
            dropdown = "dropdown"
            addButton = "addButton"
            upload = "upload"

        class ApplicationField(BaseModel):
            field_title: str = Field(
                ...,
                description="Application field title / question mentioned on the webpage",
            )
            field_category: FieldCategory = Field(
                ...,
                description="Application field category like email, work_experience, education, city etc.",
            )
            field_type: FieldType = Field(
                ...,
                description="Application field type like textbox, checkbox, dropdown etc.",
            )

        class JobFields(BaseModel):
            job_fields: list[ApplicationField]

        job_fields_found, job_fields = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=JobFields,
        )
        if job_fields_found:
            return job_fields.job_fields
        else:
            logger.error(
                f"Couldn't extract job fields for {self.parent_job.title}. URL - {self.url}"
            )
            return []

    def _act_on_job_fields(self, job_fields):
        for job_field in job_fields:
            if job_field.field_category.value == "email":
                self._identify_email_field(job_field)
            elif job_field.field_category.value == "tnc":
                self._identify_tnc_field(job_field)

    # Identifying individual components
    def _identify_cookies_consent(self):
        cookies_field = CookiesConsent(parent_application_page=self)
        cookies_field.proceed()
        self._update_steps(cookies_field)

    def _identify_start_application_button(self):
        start_application_field = StartApplication(parent_application_page=self)
        start_application_field.proceed()
        self._update_steps(start_application_field)

        return start_application_field.is_component_functional

    def _extract_application_data_source_options_details(self):
        application_data_source_field = ApplicationDataSource(
            parent_application_page=self
        )
        application_data_source_field.proceed()
        self._update_steps(application_data_source_field)

        return application_data_source_field.is_component_functional

    def _extract_login_step_details(self):
        login_step = Login(parent_application_page=self)
        login_step.proceed()
        self._update_steps(login_step)

    def _identify_email_field(self, job_field):
        email_field_step = Email(parent_application_page=self, field_info=job_field)
        email_field_step.proceed()
        self._update_steps(email_field_step)

    def _identify_tnc_field(self, job_field):
        tnc_field_step = TermsAndConditions(
            parent_application_page=self, field_info=job_field
        )
        tnc_field_step.proceed()
        self._update_steps(tnc_field_step)

    def _identify_next_page_button(self):
        next_page_button = NextPage(parent_application_page=self)
        next_page_button.proceed()
        self._update_steps(next_page_button)

    def _identify_verify_email_field(self):
        verify_account_component = VerifyAccount(parent_application_page=self)
        verify_account_component.proceed()
        self._update_steps(verify_account_component)
