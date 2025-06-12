import time
from pydantic import BaseModel, Field
from enum import Enum
import json

from utilities import constants, generate_hash, retry
from utilities.selenium import (
    get_selenium_driver,
    extract_iframe_urls,
    disable_browser_alerts,
    minify_html_for_gpt_prompt,
)
from utilities.gpt import get_gpt_response
from utilities.logging import get_logger
from utilities.sql import get_sql_query_output, execute_sql_query
from jobs.page_components import ApplicationField
from jobs.page_components.application_data_source import ApplicationDataSource
from jobs.page_components.cookies_consent import CookiesConsent
from jobs.page_components.terms_and_conditions import TermsAndConditions
from jobs.page_components.login import Login, VerifyAccount
from jobs.page_components.start_application import StartApplication
from jobs.page_components.next_page import NextPage
from jobs.page_components.work_experience_section import WorkExperienceSection
from jobs.page_components.phone_info import PhoneInfo
from jobs.page_components.education_section import EducationSection
from jobs.page_components.resume_upload import ResumeUpload
from jobs.page_components.submit_application import SubmitApplication
from jobs.page_components.button import Button
from jobs.page_components.check_box import CheckBox
from jobs.page_components.date_field import DateField
from jobs.page_components.drop_down import DropDown
from jobs.page_components.radio_button import RadioButton
from jobs.page_components.search_field import SearchField
from jobs.page_components.popup import Popup


logger = get_logger(name="job")
driver = get_selenium_driver()
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
        self.is_active = job["is_active"]

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

        self.steps_identified = False
        self.is_application_feasible = True
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

            self.steps_identified = application_steps["is_identification_complete"]
            self.is_application_feasible = application_steps["is_application_feasible"]

            return True
        else:
            return False

    def save_application_steps(self):
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

    def update_steps(self, step, inplace=False):
        if step.is_component_functional:
            if self.head_step is None:
                self.head_step = step
                self.tail_step = step
            elif inplace:
                # Try to find and replace an existing step of the same class
                cur_step = self.head_step
                replaced = False
                while cur_step:
                    if cur_step.__class__ == step.__class__:
                        step.prev = cur_step.prev
                        step.next = cur_step.next

                        if cur_step.prev:
                            cur_step.prev.next = step
                        else:
                            self.head_step = step  # cur_step was head

                        if cur_step.next:
                            cur_step.next.prev = step
                        else:
                            self.tail_step = step  # cur_step was tail

                        replaced = True
                        break
                    cur_step = cur_step.next

                if not replaced:
                    self.tail_step.next = step
                    step.prev = self.tail_step
                    self.tail_step = step
            else:
                self.tail_step.next = step
                step.prev = self.tail_step
                self.tail_step = step

            self.save_application_steps()

        return

    @property
    def original_application_page_identified(self):
        return isinstance(self.original_application_page, ApplicationPage)

    @property
    def start_application_button_identified(self):
        cur_application_step = self.head_step
        while cur_application_step:
            if isinstance(cur_application_step, StartApplication):
                return True
            cur_application_step = cur_application_step.next

        return False

    @property
    def work_experience_section_identified(self):
        cur_application_step = self.head_step
        while cur_application_step:
            if isinstance(cur_application_step, WorkExperienceSection):
                return True
            cur_application_step = cur_application_step.next

        return False

    @property
    def education_section_identified(self):
        cur_application_step = self.head_step
        while cur_application_step:
            if isinstance(cur_application_step, EducationSection):
                return True
            cur_application_step = cur_application_step.next

        return False

    @property
    def phone_info_identified(self):
        curr_application_step = self.head_step
        while curr_application_step:
            if isinstance(curr_application_step, PhoneInfo):
                return True
            curr_application_step = curr_application_step.next
        return False

    @property
    def resume_upload_identified(self):
        cur_application_step = self.head_step
        while cur_application_step:
            if isinstance(cur_application_step, ResumeUpload):
                return True
            cur_application_step = cur_application_step.next

        return False

    def component_x_path_exists(self, x_path, skip_check=True):
        if skip_check:
            return False

        cur_application_step = self.head_step
        while cur_application_step:
            # if identified_fields exists as attribute then loop over it to check for existing xpath match
            if hasattr(cur_application_step, "identified_fields"):
                for field in cur_application_step.identified_fields:
                    component_x_paths = [
                        getattr(field, attr) for attr in dir(field) if "x_path" in attr
                    ]
                    if x_path in component_x_paths:
                        return True

            component_x_paths = [
                getattr(cur_application_step, attr)
                for attr in dir(cur_application_step)
                if "x_path" in attr
            ]
            if x_path in component_x_paths:
                return True

            cur_application_step = cur_application_step.next

        return False

    def identify_original_application_page(self):
        global driver
        driver.get(self.url)
        disable_browser_alerts()
        time.sleep(2)

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
            time.sleep(2)
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

    def run_steps(self, stop_step=None):
        logger.info("Re-doing all steps...")
        driver.get(self.url)
        disable_browser_alerts()
        time.sleep(2)

        next_step = self.head_step
        while True:

            @retry(raise_exception=False)
            def _():
                return next_step.proceed()

            _()

            next_step = next_step.next

            if next_step is None or next_step is stop_step:
                break

        return

    def apply(self):
        # Check if job was already successfully applied
        check_existing_query = f"""
            SELECT id, application_status
            FROM users.job_applications
            WHERE user_id = {self.parent_job.user.id}
            AND job_id = {self.parent_job.id}
            AND application_status = 'submitted';
        """
        existing_application = get_sql_query_output(check_existing_query)
        if existing_application:
            logger.warn(
                f"Already successfully applied for job {self.parent_job.id} - {self.parent_job.title} by user "
                f"{self.parent_job.user.id}"
            )
            return True

        # Create job application entry
        insert_application_query = f"""
            INSERT INTO users.job_applications
            (user_id, job_id, application_status)
            VALUES ({self.parent_job.user.id}, {self.parent_job.id}, 'initiated')
            RETURNING id;
        """
        result = execute_sql_query(insert_application_query, return_result=True)
        if not result:
            logger.error(
                f"Failed to create application entry for user {self.parent_job.user.id} "
                f"for job {self.parent_job.id} - {self.parent_job.title}"
            )
            return None

        application_id = result["id"]

        if not self.is_application_feasible:
            logger.warn(
                f"Application is not possible for job {self.parent_job.title}. URL - {self.url}"
            )
            self._update_application_status(application_id, "failed")
            return

        try:
            if not self.steps_identified:
                self.steps_identified = self._identify_application_steps()

                application_steps_query = f"""
                                                select *
                                                from jobs.application_steps
                                                where job_id = {self.parent_job.id}
                                                and is_active;
                                           """
                current_application_steps = get_sql_query_output(
                    application_steps_query
                )
                if current_application_steps:
                    query = f"""
                                update jobs.application_steps
                                set is_identification_complete = true,
                                    is_application_feasible = {"true" if self.steps_identified else "false"}
                                where job_id = {self.parent_job.id}
                                and is_active;
                             """
                else:
                    query = f"""
                                INSERT INTO jobs.application_steps
                                (job_id, is_identification_complete, is_application_feasible)
                                VALUES ({self.parent_job.id}, true, {"true" if self.steps_identified else "false"});
                             """

                execute_sql_query(query)

                if not self.steps_identified:
                    logger.exception(
                        f"Could not identify application steps for job {self.parent_job.title}. URL - {self.url}"
                    )
                    self._update_application_status(application_id, "failed")
                    return
            else:
                self.run_steps()

            # Verify submission status and update application
            application_submitted = self._verify_application_submission()
            if application_submitted is None:
                self._update_application_status(application_id, "unknown")
                return None

            status = "submitted" if application_submitted else "failed"
            self._update_application_status(application_id, status)
            return application_submitted
        except Exception as e:
            logger.exception(
                f"Error while applying for user {self.parent_job.user.id} for job {self.parent_job.id} - "
                f"{self.parent_job.title}. Error - {e}"
            )
            self._update_application_status(application_id, "failed")
            return None
        finally:
            # Close the driver after application
            global driver
            if driver:
                driver.quit()

            driver = None

    @staticmethod
    def _update_application_status(application_id, status):
        """Update job application status in database"""
        query = f"""
            UPDATE users.job_applications
            SET application_status = '{status}'
            WHERE id = {application_id};
        """
        execute_sql_query(query)

    def _verify_application_submission(self):
        """Verify if job application was successfully submitted by analyzing the page content"""
        global driver
        time.sleep(2)  # Wait for page to load completely

        user_prompt = (
            f"Following HTML page is shown after submitting job application for {self.parent_job.title} "
            f"at a company called {self.parent_job.company}.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Analyse the whole HTML very carefully to determine if application was submitted successfully."
        )

        class SubmissionStatus(Enum):
            true = True
            false = False

        class ApplicationSubmission(BaseModel):
            is_submitted: SubmissionStatus = Field(
                ...,
                description="Page content mentions / suggests that the job application submission was successful",
            )

        submission_found, submission = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=ApplicationSubmission,
        )

        if submission_found:
            submitted = submission.is_submitted.value
            if submitted:
                logger.info(
                    f"Successfully submitted application for user {self.parent_job.user.id} "
                    f"for job {self.parent_job.id} - {self.parent_job.title}"
                )
            else:
                logger.error(
                    f"Failed to submit application for user {self.parent_job.user.id} for job {self.parent_job.id} - "
                    f"{self.parent_job.title}"
                )
            return submitted
        else:
            logger.error(
                f"Could not verify submission status for user {self.parent_job.user.id} for job {self.parent_job.id} - "
                f"{self.parent_job.title}"
            )
            return None

    # Identify job page components
    def _identify_application_steps(self):
        global driver
        driver.get(self.url)
        disable_browser_alerts()
        time.sleep(2)

        if self.head_step:
            self.run_steps()

        while True:
            elements = self._identify_current_page_elements()
            if elements:
                elements_processed = self._act_on_current_page_elements(elements)
                if elements_processed is not None:
                    return elements_processed
            else:
                return False

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
                description="There is button to start applying to the job. It should have word like start or something"
                " similar to start. It can be just one word like 'Apply' as well also but definitely not "
                "'Apply with <some_platform>' kind of text. It's not next step or submit application button"
                " or some other button.",
            )
            next_button: IsElementPresent = Field(
                ...,
                description="There is button to go to next section of application. Don't consider submit application "
                "button as next button.",
            )
            submit_application_button: IsElementPresent = Field(
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
                description="Page suggests that user has already applied to the job previously.",
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
                description="Job page has sections which are in collapsed form (arrow, + buttons etc.) and need to be "
                "expanded to fill data into job fields",
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
            self.parent_job.is_active = False

            update_query = f"""
                update jobs.jobs
                set is_active = false
                where id = {self.parent_job.id};
            """
            execute_sql_query(update_query)

            return False

        if elements.captcha.value:
            logger.warn(f"There is captcha on the page so cannot move forward.")
            self.is_application_feasible = False

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
                            set is_application_feasible = false, is_identification_complete = true
                            where job_id = {self.parent_job.id}
                            and is_active;
                         """
            else:
                query = f"""
                            INSERT INTO jobs.application_steps
                            (job_id, is_application_feasible, is_identification_complete)
                            VALUES ({self.parent_job.id}, false, true);
                         """

            execute_sql_query(query)

            return False

        if elements.cookies_prompt.value:
            self._identify_cookies_consent()

        if elements.mandatory_account_login_signup.value:
            is_login_functional = self._extract_login_step_details()

            if is_login_functional:
                latest_elements = self._identify_current_page_elements()
                if latest_elements:
                    return self._act_on_current_page_elements(latest_elements)

                return

        if elements.account_verification.value:
            is_verify_email_field_functional = self._identify_verify_email_field()

            if is_verify_email_field_functional:
                latest_elements = self._identify_current_page_elements()
                if latest_elements:
                    return self._act_on_current_page_elements(latest_elements)

                return

        if (
            elements.start_application_button.value
            and not self.start_application_button_identified
        ):
            is_start_application_functional = self._identify_start_application_button()

            if is_start_application_functional:
                latest_elements = self._identify_current_page_elements()
                if latest_elements:
                    return self._act_on_current_page_elements(latest_elements)

                return

        if elements.select_application_data_source.value:
            is_manual_input_functional = (
                self._extract_application_data_source_options_details()
            )

            if is_manual_input_functional:
                latest_elements = self._identify_current_page_elements()
                if latest_elements:
                    return self._act_on_current_page_elements(latest_elements)

                return

        if elements.expand_collapse_section.value:
            pass

        if elements.application_fields.value:
            job_fields = self._identify_application_fields()
            self._act_on_job_fields(job_fields)

            # Fetch fields again and remove duplicates based on title
            additional_fields = self._identify_application_fields()
            if additional_fields:
                # Remove duplicates based on field title (case-insensitive)
                existing_titles = set()
                for field in job_fields:
                    if hasattr(field, "field_title"):
                        existing_titles.add(field.field_title.lower().strip())

                unique_additional_fields = []
                for field in additional_fields:
                    field_title_lower = field.field_title.lower().strip()
                    if field_title_lower not in existing_titles:
                        unique_additional_fields.append(field)
                        existing_titles.add(field_title_lower)

                if unique_additional_fields:
                    logger.info(
                        f"Found {len(unique_additional_fields)} additional unique fields for {self.parent_job.title}. "
                        f"URL - {self.url}"
                    )
                    self._act_on_job_fields(unique_additional_fields)

        # last action after all on page components
        if elements.next_button.value:
            is_next_page_button_functional = self._identify_next_page_button()

            if is_next_page_button_functional:
                latest_elements = self._identify_current_page_elements()
                if latest_elements:
                    return self._act_on_current_page_elements(latest_elements)

                return

        if elements.submit_application_button.value:
            self._identify_submit_application_button()

            return True

    # Identify application fields
    def _identify_application_fields(
        self,
        identify_only_errors=False,
    ):
        global driver

        if identify_only_errors:
            prompt_part = (
                "While filling job application I clicked submit / next section button. There might or might not be any "
                "errors on the page / around job fields. Analyse the whole HTML very carefully for extracting all the "
                "application fields which are definitely having an error. Strictly ignore the fields where there is no "
                "error for sure."
            )
        else:
            prompt_part = (
                "The webpage has job application related fields. Analyse the whole HTML very carefully for "
                "extracting all the application fields."
            )

        class FieldCategory(Enum):
            first_name = "first_name"
            middle_name = "middle_name"
            last_name = "last_name"
            full_name = "full_name"
            salutation_prefix = "salutation_prefix"
            email = "email"
            phone_country_code = "phone_country_code"
            phone_number_without_country_code = "phone_number_without_country_code"
            password = "password"
            tnc = "tnc"
            work_experience = "work_experience"
            education = "education"
            resume_upload = "resume_upload"
            cover_letter = "cover_letter"
            other = "other"

        if identify_only_errors:

            class ApplicationFieldInfo(BaseModel):
                field_title: str = Field(
                    ...,
                    description="Application field's exact title / question mentioned on the webpage, without any "
                    "modification.",
                )
                field_question: str = Field(
                    ...,
                    description="Field title on its own may not be self explanatory so modify it, if needed, so that it "
                    "makes sense as a question. Otherwise respond same as field title.",
                )
                field_category: FieldCategory = Field(
                    ...,
                    description="Application field category like email, work_experience, education, city etc.",
                )
                is_error_present: bool = Field(
                    ...,
                    description="Whether this field has any validation/requirement errors.",
                )
                error: str | None = Field(
                    None,
                    description="The error message shown for this field if it has validation/requirement errors.",
                )

        else:

            class ApplicationFieldInfo(BaseModel):
                field_title: str = Field(
                    ...,
                    description="Application field's exact title / question mentioned on the webpage, without any "
                    "modification.",
                )
                field_question: str = Field(
                    ...,
                    description="Field title on its own may not be self explanatory so modify it, if needed, so that it "
                    "makes sense as a question. Otherwise respond same as field title.",
                )
                field_category: FieldCategory = Field(
                    ...,
                    description="Application field category like email, work_experience, education, city etc.",
                )

        class JobFields(BaseModel):
            job_fields: list[ApplicationFieldInfo]

        # Helper function to get fields using GPT with consistent prompt structure
        def _get_fields_from_gpt(prompt_part_text):
            user_prompt_text = (
                f"Following HTML page is job application webpage for {self.parent_job.title} at a company called "
                f"{self.parent_job.company}.\n"
                f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
                f"{prompt_part_text}"
            )

            job_fields_found, job_fields = get_gpt_response(
                constants.gpt["system_prompts"]["application_step_identification"],
                user_prompt_text,
                response_format=JobFields,
            )
            if job_fields_found:
                return job_fields.job_fields
            else:
                return []

        # Initial GPT call to identify fields
        initial_fields = _get_fields_from_gpt(prompt_part)

        if not initial_fields:
            logger.error(
                f"Couldn't extract job fields for {self.parent_job.title}. URL - {self.url}"
            )
            return []

        return initial_fields

    def _act_on_job_fields(self, job_fields):
        for job_field in job_fields:
            # Handle phone number/code fields together
            if job_field.field_category.value in [
                "phone_country_code",
                "phone_number_without_country_code",
            ]:
                if not self.phone_info_identified:
                    self._identify_phone_fields(job_field.field_title)
            elif job_field.field_category.value == "tnc":
                self._identify_tnc_field(job_field)
            elif job_field.field_category.value == "work_experience":
                if self.work_experience_section_identified:
                    continue

                self._identify_work_experience_section()
            elif job_field.field_category.value == "education":
                if self.education_section_identified:
                    continue

                self._identify_education_section()
            elif job_field.field_category.value == "cover_letter":
                pass
            elif job_field.field_category.value == "resume_upload":
                if self.resume_upload_identified:
                    continue

                self._identify_resume_upload_field(job_field.field_title)
            else:
                self._complete_application_field_identification(job_field)

    # Identifying individual components
    @retry()
    def _identify_cookies_consent(self):
        cookies_field = CookiesConsent(parent_application_page=self)
        cookies_field.proceed()
        self.update_steps(cookies_field)

    @retry()
    def _identify_start_application_button(self):
        start_application_field = StartApplication(parent_application_page=self)
        start_application_field.proceed()
        self.update_steps(start_application_field)

        return start_application_field.is_component_functional

    @retry()
    def _extract_application_data_source_options_details(self):
        application_data_source_field = ApplicationDataSource(
            parent_application_page=self
        )
        application_data_source_field.proceed()
        self.update_steps(application_data_source_field)

        return application_data_source_field.is_component_functional

    @retry()
    def _extract_login_step_details(self):
        login_step = Login(parent_application_page=self)
        login_step.proceed()
        self.update_steps(login_step)

        return login_step.is_component_functional

    @retry()
    def _identify_tnc_field(self, job_field):
        tnc_field_step = TermsAndConditions(
            parent_application_page=self, field_info=job_field
        )
        tnc_field_step.proceed()
        self.update_steps(tnc_field_step)

    @retry()
    def _identify_next_page_button(self):
        next_page_button = NextPage(parent_application_page=self)
        next_page_button.proceed()
        self.update_steps(next_page_button)

        return next_page_button.is_component_functional

    @retry()
    def _identify_verify_email_field(self):
        verify_account_component = VerifyAccount(parent_application_page=self)
        verify_account_component.proceed()
        self.update_steps(verify_account_component)

        return verify_account_component.is_component_functional

    @retry()
    def _complete_application_field_identification(self, job_field):
        application_field = ApplicationField(
            parent_application_page=self,
            title=job_field.field_title,
            question=job_field.field_question,
            category=job_field.field_category.value,
        )
        application_field_component = application_field.get_field_component()

        if not application_field_component:
            return

        application_field_component.proceed()
        self.update_steps(application_field_component)

    def _identify_work_experience_section(self):
        work_experience_section = WorkExperienceSection(parent_application_page=self)
        work_experience_section.proceed()
        self.update_steps(work_experience_section)

    def _identify_education_section(self):
        education_section = EducationSection(parent_application_page=self)
        education_section.proceed()
        self.update_steps(education_section)

    @retry()
    def _identify_resume_upload_field(self, title):
        resume_upload_button = ResumeUpload(title=title, parent_application_page=self)
        resume_upload_button.proceed()
        self.update_steps(resume_upload_button)

        self._identify_popup()

    @retry()
    def _identify_popup(self):
        popup = Popup(previous_step="resume_upload", parent_application_page=self)
        popup.proceed()
        self.update_steps(popup)

    @retry()
    def _identify_phone_fields(self, title):
        """Identify and handle phone number related fields"""
        phone_info = PhoneInfo(title=title, parent_application_page=self)
        phone_info.proceed()
        self.update_steps(phone_info)

    def _identify_submit_application_button(self):
        submit_application_button = SubmitApplication(parent_application_page=self)
        submit_application_button.proceed()

        if submit_application_button.is_component_functional:
            error_fields = self._identify_application_fields(identify_only_errors=True)
            # Filter out fields that don't have errors
            error_fields = [
                field
                for field in error_fields
                if field.is_error_present and field.error
            ]
            if error_fields:
                logger.warn(
                    f"Errors in job application fields for {self.parent_job.title}. URL - {self.url}"
                )
                self._act_on_job_fields(error_fields)

            self.update_steps(submit_application_button)
