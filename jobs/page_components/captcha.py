import time
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from jobs.page_components import PageComponent, logger
from utilities import constants
from utilities.llm import create_llm_service
from utilities.selenium import (
    get_selenium_driver,
    is_element_visible,
    minify_html_for_gpt_prompt,
)

_llm_service = create_llm_service(provider="openai")

driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class CaptchaOpenState(str, Enum):
    open = "open"
    closed = "closed"


class CaptchaAssessment(BaseModel):
    captcha_state: CaptchaOpenState = Field(
        ...,
        description="Return open when a real captcha or security challenge is currently present and blocking on the page. Return closed otherwise.",
    )
    evidence: Optional[str] = Field(
        None,
        description="Short evidence from the HTML that supports the decision.",
    )


class CaptchaIframeSelection(BaseModel):
    iframe_numbers: List[int] = Field(
        ...,
        description="1-based iframe candidate numbers that are captcha-related. Return an empty array if none of the candidates are captcha iframes.",
    )
    evidence: Optional[str] = Field(
        None,
        description="Short evidence explaining why the selected iframe candidates are captcha-related.",
    )


class Captcha(PageComponent):
    def __init__(self, parent_application_page):
        self.parent_application_page = parent_application_page

        self.next = None
        self.prev = None
        self.is_component_functional = False

        self.evidence = None
        self.selected_iframe_candidates = []
        self.iframe_candidates = []
        self.last_assessment_target = "main_page"

    def proceed(self, retry=False):
        del retry

        self.evidence = None
        self.selected_iframe_candidates = []
        self.iframe_candidates = []
        self.last_assessment_target = "main_page"

        logger.info(
            f"Checking captcha presence for {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}"
        )

        try:
            driver.switch_to.default_content()

            self.iframe_candidates = self._get_visible_iframe_candidates()
            self.selected_iframe_candidates = self._identify_captcha_iframes(
                self.iframe_candidates
            )

            if self.selected_iframe_candidates:
                logger.info(
                    f"Captcha-related iframe candidates selected: "
                    f"{[candidate['candidate_number'] for candidate in self.selected_iframe_candidates]} "
                    f"for {self.parent_application_page.parent_job.title}. "
                    f"URL - {self.parent_application_page.url}"
                )
                for iframe_candidate in self.selected_iframe_candidates:
                    assessment = self._assess_captcha_iframe(iframe_candidate)
                    self.evidence = assessment.evidence
                    self.last_assessment_target = (
                        f"iframe_{iframe_candidate['candidate_number']}"
                    )

                    if assessment.captcha_state == CaptchaOpenState.open:
                        self.is_component_functional = True
                        logger.warning(
                            f"Open captcha detected in iframe candidate {iframe_candidate['candidate_number']} "
                            f"for {self.parent_application_page.parent_job.title}. "
                            f"URL - {self.parent_application_page.url}. Evidence - {self.evidence}"
                        )
                        return True

                self.is_component_functional = False
                logger.info(
                    f"No open captcha found after checking iframe candidates "
                    f"{[candidate['candidate_number'] for candidate in self.selected_iframe_candidates]} "
                    f"for {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}. "
                    f"Last evidence - {self.evidence}"
                )
                return False

            logger.info(
                f"No captcha-related iframe candidates selected. Falling back to main page HTML for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )
            assessment = self._assess_page_source_for_captcha(driver.page_source)
            self.evidence = assessment.evidence
            self.last_assessment_target = "main_page"
            self.is_component_functional = (
                assessment.captcha_state == CaptchaOpenState.open
            )

            if self.is_component_functional:
                logger.warning(
                    f"Open captcha detected on main page for {self.parent_application_page.parent_job.title}. "
                    f"URL - {self.parent_application_page.url}. Evidence - {self.evidence}"
                )
            else:
                logger.info(
                    f"No open captcha detected on main page for {self.parent_application_page.parent_job.title}. "
                    f"URL - {self.parent_application_page.url}. Evidence - {self.evidence}"
                )

            return self.is_component_functional
        except Exception as e:
            logger.exception(
                f"Failed to assess captcha for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}. Error - {e}"
            )
            raise
        finally:
            driver.switch_to.default_content()

    def _get_visible_iframe_candidates(self):
        iframe_elements = driver.find_elements(By.XPATH, "//body//iframe")
        iframe_candidates = []

        for body_iframe_number, iframe_element in enumerate(iframe_elements, start=1):
            if not is_element_visible(element=iframe_element):
                continue

            iframe_size = iframe_element.size or {}
            width = iframe_size.get("width", 0)
            height = iframe_size.get("height", 0)
            if width <= 0 or height <= 0:
                continue

            iframe_candidates.append(
                {
                    "candidate_number": len(iframe_candidates) + 1,
                    "body_iframe_number": body_iframe_number,
                    "width": width,
                    "height": height,
                    "outer_html": iframe_element.get_attribute("outerHTML") or "",
                    "x_path": f"(//body//iframe)[{body_iframe_number}]",
                }
            )

        logger.info(
            f"Found {len(iframe_candidates)} visible iframe candidates for captcha check "
            f"for {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
        )

        return iframe_candidates

    def _identify_captcha_iframes(self, iframe_candidates):
        if not iframe_candidates:
            self.evidence = "No visible body iframe candidates were found."
            return []

        iframe_prompt = ""
        for candidate in iframe_candidates:
            iframe_prompt += (
                f"\nCandidate {candidate['candidate_number']} "
                f"(body iframe {candidate['body_iframe_number']}, "
                f"width={candidate['width']}, height={candidate['height']})\n"
                f"{minify_html_for_gpt_prompt(candidate['outer_html'])}\n"
            )

        user_prompt = (
            f"Following iframe HTML snippets are from the body of webpage for {self.parent_application_page.parent_job.title}. "
            "Every iframe candidate listed below is visible on the main page and has non-zero dimensions. "
            "Identify all iframes that are related to a captcha or security challenge. "
            "Look for providers and patterns such as reCAPTCHA, hCaptcha, Cloudflare Turnstile, Arkose/FunCaptcha, GeeTest, checkbox verification, or challenge widgets. "
            "Multiple candidates can be eligible. Return an empty array only if none of the candidates are captcha-related."
            f"{iframe_prompt}"
        )

        selection_found, selection = _llm_service.chat(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=CaptchaIframeSelection,
        )

        if not selection_found:
            raise RuntimeError(
                f"Could not identify captcha iframes for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

        self.evidence = selection.evidence

        selected_candidates = []
        seen_candidate_numbers = set()

        for iframe_number in selection.iframe_numbers:
            if iframe_number in seen_candidate_numbers:
                continue
            seen_candidate_numbers.add(iframe_number)

            selected_candidate = next(
                (
                    candidate
                    for candidate in iframe_candidates
                    if candidate["candidate_number"] == iframe_number
                ),
                None,
            )

            if selected_candidate is None:
                raise RuntimeError(
                    f"LLM selected iframe candidate {iframe_number}, but that candidate does not exist."
                )

            selected_candidates.append(selected_candidate)

        logger.info(
            f"LLM selected {len(selected_candidates)} captcha-related iframe candidates for "
            f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}. "
            f"Evidence - {self.evidence}"
        )

        return selected_candidates

    def _assess_page_source_for_captcha(self, page_source):
        user_prompt = (
            f"Following HTML page is webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(page_source)}\n"
            "Determine whether a captcha or security challenge is currently open on the page. "
            "Return 'open' only when a real captcha, reCAPTCHA, hCaptcha, Cloudflare challenge, puzzle, or similar blocking security step is actually present in the HTML. "
            "Return 'closed' if no captcha is present, or if the HTML only contains hidden, placeholder, empty, or non-blocking captcha markup. "
            "Include brief evidence."
        )

        assessment_found, assessment = _llm_service.chat(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=CaptchaAssessment,
        )

        if not assessment_found:
            raise RuntimeError(
                f"Could not determine captcha state for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

        return assessment

    def _assess_iframe_page_source(self, page_source):
        user_prompt = (
            f"Following HTML is from inside a captcha-related iframe on webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(page_source)}\n"
            "Determine whether the captcha or security challenge is currently OPEN for human interaction. "
            "Return 'open' only if the iframe contains interactive challenge UI that a human can act on right now, such as a checkbox, verify button, challenge instructions, image tiles, puzzle, or audio challenge. "
            "Return 'closed' if the iframe only contains background plumbing, bootstrap markup, placeholders, hidden fields, or no currently interactive challenge UI. "
            "Include brief evidence."
        )

        assessment_found, assessment = _llm_service.chat(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=CaptchaAssessment,
        )

        if not assessment_found:
            raise RuntimeError(
                f"Could not determine captcha interaction state for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )

        return assessment

    def _assess_captcha_iframe(self, iframe_candidate):
        driver.switch_to.default_content()
        iframe_element = driver.find_element(By.XPATH, iframe_candidate["x_path"])
        driver.switch_to.frame(iframe_element)

        try:
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: d.execute_script("return document.readyState")
                    == "complete"
                )
            except Exception:
                pass

            time.sleep(2)
            iframe_page_source = driver.page_source
            return self._assess_iframe_page_source(iframe_page_source)
        finally:
            driver.switch_to.default_content()

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "next": None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        del input_dict
        return cls(parent_application_page=parent_application_page)
