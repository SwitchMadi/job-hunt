import time
from abc import ABC, abstractmethod
from selenium.webdriver.common.by import By
from pydantic import BaseModel, Field

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
                self.application_steps.append(close_overlay_button)
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
        pass


class PageComponent(ABC):
    @abstractmethod
    def proceed(self):
        pass

    @abstractmethod
    def to_dict(self):
        pass


class Button(PageComponent):
    def __init__(
        self,
        x_path,
        button_type,
        parent_application_page: ApplicationPage,
        click_result=None,
    ):
        global driver
        self.x_path = x_path
        self.action_type = button_type
        self.parent_application_page = parent_application_page
        self.click_result = click_result

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
            "click_result": self.click_result,
        }
