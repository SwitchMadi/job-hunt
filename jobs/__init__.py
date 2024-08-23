import time

from utilities.selenium import get_selenium_driver, extract_iframe_urls
from utilities import minify_html_for_gpt_prompt
from utilities.gpt import get_gpt_response
from utilities.logging import get_logger
from utilities import constants


logger = get_logger(name="job", file_name="job-hunt")


class Job:
    def __init__(self, url, title):
        self.url = url
        self.title = title
        self.application_page = ApplicationPage

    @property
    def application_page_identified(self):
        return isinstance(self.application_page, ApplicationPage)

    def identify_application_page(self):
        driver = get_selenium_driver(headless=False)
        driver.set_page_load_timeout(15)
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

        user_prompt = f"""Out of of following htmls, which one is job application page for job title {self.title}.
            Answer should strictly be just the relevant key's name or "Cannot determine" -
            {html_prompt}"""

        job_application_page_key = get_gpt_response(
            constants["gpt"]["system_prompts"]["application_step_identification"],
            user_prompt,
        )

        for key, value in htmls.items():
            if key in job_application_page_key:
                self.application_page = ApplicationPage(
                    url=value["url"], page_source=value["page_source"], parent_job=self
                )
                break

        if not self.application_page_identified:
            logger.critical(
                f"""No application page identified.
                job_application_page_key - {job_application_page_key}
                main_page - {self.url}
                iframe_urls - {iframe_urls}
            """
            )

        return


class ApplicationPage:
    def __init__(self, url, page_source, parent_job: Job):
        self.url = url
        self.page_source = page_source
        self.parent_job = parent_job

    def identify_steps(self):
        pass
