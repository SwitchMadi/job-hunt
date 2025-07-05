import time
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum
import json
import yaml
from selenium.webdriver.support.ui import WebDriverWait

from utilities import constants, generate_hash, retry, clean_text_edges, take_screenshot
from utilities.selenium import (
    get_selenium_driver,
    extract_iframe_urls,
    disable_browser_alerts,
    minify_html_for_gpt_prompt,
    close_selenium_driver,
    revoke_optional_permissions,
)
from utilities.gpt import get_gpt_response
from utilities.logging import get_logger
from utilities.sql import get_sql_query_output, execute_sql_query
from utilities.aws.s3 import S3Bucket
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
from jobs.page_components.text_input import TextInput
from jobs.page_components.check_box import CheckBox
from jobs.page_components.date_field import DateField
from jobs.page_components.drop_down import DropDown
from jobs.page_components.radio_button import RadioButton
from jobs.page_components.search_field import SearchField
from jobs.page_components.popup import Popup


config = yaml.safe_load(open("config.yml"))
logger = get_logger(name="job")

# TODO - driver should not be initialized at module level as importing this module will create a driver instance
driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class Job:
    def __init__(self, job_id=None, url=None, title=None, company=None, user=None):
        if job_id is not None:
            job = Job.find_job_by_id(job_id)
            if job is None:
                raise ValueError(f"Job with id {job_id} not found in database")
        elif url is not None:
            job = Job.find_job_by_url(url)
            if job is None:
                self.hash_id = generate_hash(url)
                self.title = title
                self.company = company
                self.url = url
                self.save_to_db()
                job = Job.find_job_by_url(url)

        self.id = job["id"]
        self.url = job["job_url"]
        self.hash_id = job["job_hash_id"]
        self.title = job["title"]
        self.company = job["company"]
        self.is_active = job["is_active"]

        self.user = user
        self.application_page = ApplicationPage(url=self.url, parent_job=self)

    @staticmethod
    def find_job_by_id(job_id):
        job_query = f"""
                        select *
                        from jobs.jobs
                        where id = '{job_id}'
                    """
        job = get_sql_query_output(job_query)
        if job:
            return job[0]
        else:
            return None

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
            if application_steps["steps"]:
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

        revoke_optional_permissions(self.url)
        driver.get(self.url)
        disable_browser_alerts()

        # Wait for page load to complete
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(5)

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
            revoke_optional_permissions(iframe_url)
            driver.get(iframe_url)
            disable_browser_alerts()

            # Wait for page load to complete
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            time.sleep(5)

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
        revoke_optional_permissions(self.url)
        driver.get(self.url)
        disable_browser_alerts()

        # Wait for page load to complete
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(5)

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

    @classmethod
    def get_non_feasible_domains(cls):
        non_feasible_domains_query = f"""
            select distinct CASE
                WHEN split_part(job_url, '/', 3) ~* '\.co\.uk$' THEN regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.(?:co\.uk))$', '\1')
                WHEN split_part(job_url, '/', 3) ~* '\.ac\.uk$' THEN regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.(?:ac\.uk))$', '\1')
                WHEN split_part(job_url, '/', 3) ~* '\.gov\.uk$' THEN regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.(?:gov\.uk))$', '\1')
                WHEN split_part(job_url, '/', 3) ~* '\.com\.au$' THEN regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.(?:com\.au))$', '\1')
                WHEN split_part(job_url, '/', 3) ~* '\.net\.au$' THEN regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.(?:net\.au))$', '\1')
                WHEN split_part(job_url, '/', 3) ~* '\.gov\.au$' THEN regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.(?:gov\.au))$', '\1')
                WHEN split_part(job_url, '/', 3) ~* '\.co\.in$' THEN regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.(?:co\.in))$', '\1')
                WHEN split_part(job_url, '/', 3) ~* '\.gov\.in$' THEN regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.(?:gov\.in))$', '\1')
                WHEN split_part(job_url, '/', 3) ~* '\.co\.jp$' THEN regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.(?:co\.jp))$', '\1')
                WHEN split_part(job_url, '/', 3) ~* '\.ne\.jp$' THEN regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.(?:ne\.jp))$', '\1')
                WHEN split_part(job_url, '/', 3) ~* '\.or\.jp$' THEN regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.(?:or\.jp))$', '\1')
                WHEN split_part(job_url, '/', 3) ~* '\.co\.nz$' THEN regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.(?:co\.nz))$', '\1')
                WHEN split_part(job_url, '/', 3) ~* '\.gov\.nz$' THEN regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.(?:gov\.nz))$', '\1')
                ELSE regexp_replace(split_part(job_url, '/', 3), '^.*?([^.]+\.[^.]+)$', '\1')
            END as "domain"
            from jobs.application_steps t1
            join jobs.jobs t2 
            on t1.job_id = t2.id
            where t1.remarks in ('Login required', 'Account verification required', 'Next page button present')
        """
        non_feasible_domains = get_sql_query_output(non_feasible_domains_query)
        if not non_feasible_domains:
            return []

        return [domain["domain"] for domain in non_feasible_domains]

    @classmethod
    def is_domain_automatable(cls, url):
        """Check if the job application URL is automatable"""
        if not url:
            return False

        # Check if URL is in non-automatable job boards
        for non_automatable_board in constants.non_automatable_job_boards:
            if non_automatable_board in url:
                return False

        # Check if URL is a valid job application page
        non_feasible_domains = cls.get_non_feasible_domains()
        for domain in non_feasible_domains:
            if domain in url:
                return False

        return True

    def apply(self):
        global driver

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
            close_selenium_driver()
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
            close_selenium_driver()
            return None

        application_id = result["id"]

        steps_identified_at_beginning = self.steps_identified

        if not self.is_application_feasible:
            logger.warn(
                f"Application is not possible for job {self.parent_job.title}. URL - {self.url}"
            )
            self._update_application_status(
                application_id, "failed", "Application not possible"
            )
            close_selenium_driver()
            return

        is_domain_automatable = self.is_domain_automatable(self.url)
        if not is_domain_automatable:
            logger.warn(
                f"Domain {self.url} is not automatable for job {self.parent_job.title}."
            )
            if not steps_identified_at_beginning:
                self.update_steps_identification_status(
                    job_id=self.parent_job.id,
                    is_application_feasible=False,
                    remarks="Domain not automatable",
                )

            close_selenium_driver()
            return

        try:
            if not self.steps_identified:
                try:
                    self.steps_identified, failure_reason = (
                        self._identify_application_steps()
                    )
                except Exception as e:
                    self.steps_identified = False
                    failure_reason = str(e).replace("'", "''")
                    raise e
                finally:
                    self.update_steps_identification_status(
                        job_id=self.parent_job.id,
                        is_application_feasible=self.steps_identified,
                        remarks=failure_reason,
                    )

                if not self.steps_identified:
                    logger.exception(
                        f"Could not identify application steps for job {self.parent_job.title}. URL - {self.url}"
                    )
                    self._update_application_status(
                        application_id, "failed", failure_reason
                    )
                    return
            else:
                self.run_steps()

            # Verify submission status and update application
            application_submitted, success_proof, failure_reason = (
                self._verify_application_submission()
            )
            if application_submitted is None:
                self._update_application_status(application_id, "unknown", None)
                return None

            status = "submitted" if application_submitted else "failed"
            remarks = success_proof if application_submitted else failure_reason
            self._update_application_status(application_id, status, remarks)

            if not application_submitted:
                logger.error(
                    f"Application for job {self.parent_job.title} failed. Reason - {failure_reason}"
                )

                if not steps_identified_at_beginning:
                    self.update_steps_identification_status(
                        job_id=self.parent_job.id,
                        is_application_feasible=False,
                        remarks=failure_reason,
                    )

            return application_submitted
        except Exception as e:
            logger.exception(
                f"Error while applying for user {self.parent_job.user.id} for job {self.parent_job.id} - "
                f"{self.parent_job.title}. Error - {e}"
            )
            remarks = str(e).replace("'", "''")
            self._update_application_status(application_id, "failed", remarks)

            if not steps_identified_at_beginning:
                self.update_steps_identification_status(
                    job_id=self.parent_job.id,
                    is_application_feasible=False,
                    remarks=remarks,
                )

            return None
        finally:
            # Upload screenshot to S3
            try:
                screenshot_filename = (
                    f"jobId-{self.parent_job.id}--userId-{self.parent_job.user.id}.png"
                )
                take_screenshot(filename=screenshot_filename)

                s3 = S3Bucket(bucket_name=config["s3_bucket"])
                file_s3_path = (
                    f"user_data/applications/screenshots/{screenshot_filename}"
                )
                s3.upload_data(
                    file_local_path=screenshot_filename, file_s3_path=file_s3_path
                )
            except Exception as e:
                logger.warn(
                    f"Failed to take / upload screenshot for job {self.parent_job.id} - "
                    f"{self.parent_job.title}. Error - {e}"
                )

            # Close the driver after application
            close_selenium_driver()

    @staticmethod
    def _update_application_status(application_id, status, remarks):
        """Update job application status in database"""
        query = f"""
            UPDATE users.job_applications
            SET application_status = '{status}',
                remarks = {"'" + remarks + "'" if remarks else "null"}
            WHERE id = {application_id};
        """
        execute_sql_query(query)

    @classmethod
    def update_steps_identification_status(
        cls, job_id, is_application_feasible, remarks=None
    ):
        application_steps_query = f"""
                                        select *
                                        from jobs.application_steps
                                        where job_id = {job_id}
                                        and is_active;
                                   """
        current_application_steps = get_sql_query_output(application_steps_query)
        if current_application_steps:
            query = f"""
                        update jobs.application_steps
                        set is_identification_complete = true,
                            is_application_feasible = {"true" if is_application_feasible else "false"},
                            remarks = {"'" + remarks + "'" if remarks else "null"}
                        where job_id = {job_id}
                        and is_active;
                     """
        else:
            query = f"""
                        INSERT INTO jobs.application_steps
                        (job_id, is_identification_complete, is_application_feasible, remarks)
                        VALUES (
                            {job_id},
                            true, 
                            {"true" if is_application_feasible else "false"},
                            {"'" + remarks + "'" if remarks else "null"}
                        );
                     """

        execute_sql_query(query)

    def _verify_application_submission(self):
        """Verify if job application was successfully submitted by analyzing the page content"""
        global driver
        time.sleep(3)  # Wait for page to load completely

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
            success_proof: Optional[str] = Field(
                ...,
                description="If is_submitted is true then what is proof of success in short, which you based your "
                "decision on",
            )
            failure_reason: Optional[str] = Field(
                ...,
                description="If is_submitted is false then what is reason for failure in short, which you based your "
                "decision on",
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
                    f"for job {self.parent_job.id} - {self.parent_job.title}.\nProof - {submission.success_proof}"
                )
            else:
                logger.error(
                    f"Failed to submit application for user {self.parent_job.user.id} for job {self.parent_job.id} - "
                    f"{self.parent_job.title}\nReason - {submission.failure_reason}"
                )
            return submitted, submission.success_proof, submission.failure_reason
        else:
            logger.error(
                f"Could not verify submission status for user {self.parent_job.user.id} for job {self.parent_job.id} - "
                f"{self.parent_job.title}"
            )
            return None, None, None

    # Identify job page components
    def _identify_application_steps(self):
        global driver

        revoke_optional_permissions(self.url)
        driver.get(self.url)
        disable_browser_alerts()

        # Wait for page load to complete
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(5)

        if self.head_step:
            self.run_steps()

        max_try = 5
        curr_try = 1
        while curr_try <= max_try:
            elements = self._identify_current_page_elements()
            if elements:
                elements_processed, failure_reason = self._act_on_current_page_elements(
                    elements
                )
                if elements_processed is not None:
                    return elements_processed, failure_reason
                else:
                    logger.warn(
                        f"No conclusion for identifying page elements after attempt {curr_try}/{max_try}\n"
                        f"Reason - {failure_reason}"
                    )
            else:
                return False, "Page elements not found"

            curr_try += 1

        return False, "No conclusion after multiple attempts"

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
            elements_present = [
                attr for attr in dict(elements) if getattr(elements, attr).value
            ]
            logger.info(
                f"Identified following current page elements for {self.parent_job.title}. URL - {self.url}-\n"
                f"{elements_present}"
            )
            return elements
        else:
            logger.error(
                f"Couldn't identify current page elements for {self.parent_job.title}. URL - {self.url}"
            )
            return None

    def _act_on_current_page_elements(self, elements):
        # Not feasible sections
        if elements.already_applied_alert.value:
            logger.warn(f"User has already applied to the job.")
            return False, "User already applied"

        if elements.job_not_available_alert.value:
            logger.warn(f"Job is not available anymore.")
            self.parent_job.is_active = False

            update_query = f"""
                update jobs.jobs
                set is_active = false
                where id = {self.parent_job.id};
            """
            execute_sql_query(update_query)

            return False, "Job not available"

        # if elements.mandatory_account_login_signup.value:
        #     return False, "Login required"
        #
        # if elements.account_verification.value:
        #     return False, "Account verification required"

        # Feasible sections
        if elements.captcha.value:
            logger.warn(
                f"Captcha is present on the page. Job title - {self.parent_job.url}. URL - {self.url}"
            )

        if elements.cookies_prompt.value:
            self._identify_cookies_consent()

        if elements.mandatory_account_login_signup.value:
            is_login_functional = self._extract_login_step_details()

            if is_login_functional:
                latest_elements = self._identify_current_page_elements()
                if latest_elements:
                    return self._act_on_current_page_elements(latest_elements)

                return None, "Page elements not found post login"

        if elements.account_verification.value:
            is_verify_email_field_functional = self._identify_verify_email_field()

            if is_verify_email_field_functional:
                latest_elements = self._identify_current_page_elements()
                if latest_elements:
                    return self._act_on_current_page_elements(latest_elements)

                return None, "Page elements not found post account verification"

        if (
            elements.start_application_button.value
            and not self.start_application_button_identified
        ):
            is_start_application_functional = self._identify_start_application_button()

            if is_start_application_functional:
                latest_elements = self._identify_current_page_elements()
                if latest_elements:
                    return self._act_on_current_page_elements(latest_elements)

                return None, "Page elements not found post starting application"

        # There are no application fields on the page and application data source is to be selected
        if (
            elements.select_application_data_source.value
            and not elements.application_fields.value
        ):
            is_manual_input_functional = (
                self._extract_application_data_source_options_details()
            )

            if is_manual_input_functional:
                latest_elements = self._identify_current_page_elements()
                if latest_elements:
                    return self._act_on_current_page_elements(latest_elements)

                return (
                    None,
                    "Page elements not found post application data source selection",
                )

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
                        existing_titles.add(clean_text_edges(field.field_title).lower())

                curr_node = self.head_step
                while curr_node:
                    if hasattr(curr_node, "title"):
                        existing_titles.add(clean_text_edges(curr_node.title).lower())
                    curr_node = curr_node.next

                unique_additional_fields = []
                for field in additional_fields:
                    field_title_lower = clean_text_edges(field.field_title).lower()

                    if len(field_title_lower) < 75:
                        if field_title_lower not in existing_titles:
                            unique_additional_fields.append(field)
                            existing_titles.add(field_title_lower)
                    else:
                        if not any(
                            (
                                (field_title_lower in existing_title)
                                or (existing_title in field_title_lower)
                            )
                            for existing_title in existing_titles
                        ):
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
                # return False, "Next page button present"

                latest_elements = self._identify_current_page_elements()
                if latest_elements:
                    return self._act_on_current_page_elements(latest_elements)

                return None, "Page elements not found post next page click"

        if elements.submit_application_button.value:
            self._identify_submit_application_button()

            return True, None

        return None, None

    # Identify application fields
    def _identify_application_fields(
        self,
        identify_only_errors=False,
    ):
        global driver

        if identify_only_errors:
            prompt_part = (
                "While filling job application I clicked submit / next section button. There may be some "
                "errors on the page / around job fields. Analyse the whole HTML very carefully for extracting all the "
                "errors & their fields. Strictly ignore the fields where there is no error. Very carefully note that "
                "if a field is required, that doesn't mean that it has an error. It should have some error message to "
                "be considered as error."
            )
        else:
            prompt_part = (
                "The webpage has job application related fields. Analyse the whole HTML very carefully for "
                "extracting all the application fields. While extracting field titles, strictly extract exact field "
                "titles as they are mentioned on the webpage, without any modification whatsoever."
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
                    "modification whatsoever. Just pick what's in HTML and respond as it is, not matter how long it is.",
                )
                field_question: str = Field(
                    ...,
                    description="If field title on its own is not self explanatory so modify it, so that it "
                    "makes sense as a question. Otherwise respond same as field title.",
                )
                field_category: FieldCategory = Field(
                    ...,
                    description="Application field category like email, work_experience, education, city etc. Note that "
                    "TnC field must be a checkbox kind of field, not expect any answer.",
                )
                error: str | None = Field(
                    None,
                    description="The error message shown for this field. Very carefully note that "
                    "if a field is required, that doesn't mean that it has an error. It should have some error message to "
                    "be considered as error.",
                )

        else:

            class ApplicationFieldInfo(BaseModel):
                field_title: str = Field(
                    ...,
                    description="Application field's exact title / question mentioned on the webpage, without any "
                    "modification whatsoever. Just pick what's in HTML and respond as it is, not matter how long it is.",
                )
                field_question: str = Field(
                    ...,
                    description="If field title on its own is not self explanatory so modify it, so that it "
                    "makes sense as a question. Otherwise respond same as field title.",
                )
                field_category: FieldCategory = Field(
                    ...,
                    description="Application field category like email, work_experience, education, city etc. Note that "
                    "TnC field must be a checkbox kind of field, not expect any answer.",
                )

        class JobFields(BaseModel):
            job_fields: list[ApplicationFieldInfo]

        # Helper function to get fields using GPT with consistent prompt structure
        def _get_fields_from_gpt(prompt_part_text):
            user_prompt_text = (
                f"Following HTML page is job application webpage for {self.parent_job.title} at a company called "
                f"{self.parent_job.company}.\n"
                f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
                f"{prompt_part_text}\n"
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
        resp = application_data_source_field.proceed()

        if resp == "resume_upload":
            self._identify_resume_upload_field()
            return True
        else:
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
    def _identify_resume_upload_field(self, title=None):
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
            error_fields = [field for field in error_fields if field.error]
            if error_fields:
                logger.warn(
                    f"Errors in job application fields for {self.parent_job.title}. URL - {self.url}"
                )
                self._act_on_job_fields(error_fields)

                submit_application_button.proceed()

            self.update_steps(submit_application_button)

            verification_functional = self._identify_verify_email_field()
            if verification_functional:
                submit_application_button = SubmitApplication(
                    parent_application_page=self
                )
                submit_application_button.proceed()
                self.update_steps(submit_application_button)
