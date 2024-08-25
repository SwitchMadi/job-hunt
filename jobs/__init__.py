import time
from abc import ABC, abstractmethod
from selenium.webdriver.common.by import By

from utilities.selenium import get_selenium_driver, extract_iframe_urls
from utilities import minify_html_for_gpt_prompt
from utilities.gpt import get_gpt_response
from utilities.logging import get_logger
from utilities import constants


logger = get_logger(name="job", file_name="job-hunt")
driver = get_selenium_driver(headless=False)
driver.set_page_load_timeout(15)


class Job:
    def __init__(self, url, title):
        self.url = url
        self.title = title
        self.application_page = ApplicationPage(url=url, parent_job=self)


class ApplicationPage:
    def __init__(self, url, parent_job: Job, page_source=None):
        self.url = url
        self.page_source = page_source
        self.parent_job = parent_job

        self.original_application_page = ApplicationPage
        self.application_steps = []

    def identify_popups(self, retry=False):
        global driver
        driver.get(self.url)
        time.sleep(10)

        user_prompt = (
            f"Analyze the following HTML page for any screen overlays or UI overlays such as cookie "
            f"consent banners, pop-ups which is strictly not related to job application, or any other similar "
            f"elements. For each overlay found, provide the XPath of one button to close the overlay."
            f"Analyse the button if it can close the overlay. If the button doesn't close the overlay "
            f"then strictly ignore the overlay and do not give button XPath in response.\n"
            f"Your response should be strictly a list of XPaths with reason, with no additional text or "
            f"explanation whatsoever. If no overlays are found, respond with an empty list.\n"
            f"Examples of valid responses: ['//button[@id=\"accept\"]', '//div[@class=\"popup\"]/button'], "
            f"[]\nI will click the XPaths in the order you provide, so ensure the sequence is correct and "
            f"can be clicked in that order.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}"
        )

        overlay_action_buttons = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
        )
        try:
            overlay_action_buttons = eval(overlay_action_buttons)
            for overlay_action_button in overlay_action_buttons:
                close_overlay_button = Button(
                    x_path=overlay_action_button,
                    action_type="close_overlay",
                    parent_application_page=self,
                )
                close_overlay_button.proceed()
                self.application_steps.append(close_overlay_button)
        except SyntaxError:
            logger.warn(
                f"GPT response to identify_popups prompt could not be converted to list. Response - "
                f"{overlay_action_buttons}"
            )
            if not retry:
                return self.identify_popups(retry=True)

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
        pass


class PageComponent(ABC):
    @abstractmethod
    def proceed(self):
        pass

    @abstractmethod
    def to_dict(self):
        pass


class Button(PageComponent):
    def __init__(self, x_path, action_type, parent_application_page: ApplicationPage):
        global driver
        self.x_path = x_path
        self.action_type = action_type
        self.parent_application_page = parent_application_page

    def proceed(self):
        global driver

        try:
            element = driver.find_element(By.XPATH, self.x_path)
            driver.execute_script("arguments[0].scrollIntoView(true);", element)
            element.click()
        except Exception as e:
            logger.error(
                f"Unexpected error occurred in proceed method.\n{e}\nButton instance - {vars(self)}"
            )

        return

    def to_dict(self):
        return {
            "class_name": self.__class__.__name__,
            "x_path": self.x_path,
            "action_type": self.action_type,
        }
