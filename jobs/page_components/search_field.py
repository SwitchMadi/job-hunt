import time
from selenium.common import ElementNotInteractableException
from pydantic import BaseModel, Field
import re

from jobs import ApplicationField
from jobs.page_components import PageComponent, get_page_component_class_name
from jobs.page_components.drop_down import DropDown
from jobs.page_components.button import Button
from jobs.page_components.text_input import TextInput
from utilities.selenium import (
    find_clickable_parent_xpath,
    get_selenium_driver,
    start_network_observer,
    get_observed_network_calls,
    stop_network_observer,
    simulate_empty_area_click,
    get_observed_elements,
    is_element_visible,
    clear_text_field,
)
from utilities.gpt import get_gpt_response
from utilities import constants


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class SearchField(PageComponent):
    def __init__(self, x_path, title, question, category, parent_application_page):
        self.options_xpath_pattern = None
        self.x_path = x_path
        self.title = title
        self.question = question
        self.category = category
        self.parent_application_page = parent_application_page

        self.options_container_x_path = None
        self._answer = None
        self._search_phrases = []

        self.is_component_functional = False

        self.next = None
        self.prev = None

    @classmethod
    def validate_search_field(cls, x_path, field_title, retry=False):
        global driver

        start_network_observer()

        try:
            special_key = "special_key"
            element = TextInput(
                x_path=x_path,
                category="search_field",
                title=field_title,
                parent_application_page=None,
            )
            element.answer = special_key
            element.proceed()
            time.sleep(2)  # Allow API calls to trigger
        except ElementNotInteractableException:
            clear_text_field(x_path, title=field_title)
            simulate_empty_area_click()
            return False
        except Exception as e:
            if not retry:
                return SearchField.validate_search_field(
                    x_path, field_title, retry=True
                )
            else:
                raise e

        captured_requests = get_observed_network_calls()
        stop_network_observer()

        tracking_domains = [
            "firebase.com",
            "google-analytics.com",
            "clevertap.com",
            "moengage.com",
            "facebook.com",
            "fbcdn.net",
            "analytics.google.com",
            "segment.io",
            "mixpanel.com",
            "hotjar.com",
            "inkedin.com/li/track",
        ]

        def is_tracking_domain(url):
            return any(domain in url for domain in tracking_domains)

        special_domains = [
            {"domain": "jobs.ashbyhq.com", "search_pattern": "Autocomplete"}
        ]

        is_search_field = False
        for request in captured_requests:
            if not is_tracking_domain(request["url"]):
                # Check decoded query params
                for key, value in request.get("decodedQueryParams", {}).items():
                    if special_key in value.lower():
                        if any(
                            domain["domain"] in request["url"]
                            for domain in special_domains
                        ):
                            special_domain = [
                                domain
                                for domain in special_domains
                                if domain["domain"] in request["url"]
                            ][0]
                            if (
                                special_domain["search_pattern"].lower()
                                in value.lower()
                            ):
                                is_search_field = True
                                break
                        else:
                            is_search_field = True
                            break

                # Check POST body
                if (
                    not is_search_field
                    and request["method"] == "POST"
                    and request["body"]
                ):
                    if special_key in request["body"].lower():
                        if any(
                            domain["domain"] in request["url"]
                            for domain in special_domains
                        ):
                            special_domain = [
                                domain
                                for domain in special_domains
                                if domain["domain"] in request["url"]
                            ][0]
                            if (
                                special_domain["search_pattern"].lower()
                                in request["body"].lower()
                            ):
                                is_search_field = True
                                break
                        else:
                            is_search_field = True
                            break

                if is_search_field:
                    break

        clear_text_field(x_path, title=field_title)
        simulate_empty_area_click()

        return is_search_field

    def proceed(self, retry=False):
        try:
            for input_key in self.search_phrases:
                element = TextInput(
                    x_path=self.x_path,
                    category="search_field",
                    title=self.title,
                    parent_application_page=None,
                )
                element.answer = input_key

                if not self.options_container_x_path:
                    simulate_empty_area_click(text_to_click=self.title)
                    element.proceed(start_mutation_observer=True)
                    time.sleep(2)
                    observed_elements = get_observed_elements(timeout=10)

                    is_container_present, container_x_path = (
                        ApplicationField.identify_options_container(
                            field_title=self.title,
                            field_x_path=self.x_path,
                            observed_elements=observed_elements,
                            html_type="search_field",
                            job_title=self.parent_application_page.parent_job.title,
                        )
                    )
                    if not is_container_present or not container_x_path:
                        continue

                    self.options_container_x_path = container_x_path
                else:
                    element.proceed()
                    time.sleep(2)

                if not self.options_xpath_pattern:
                    self.options_xpath_pattern, options = DropDown.get_dropdown_options(
                        job_title=self.parent_application_page.parent_job.title,
                        job_url=self.parent_application_page.url,
                        field_title=self.title,
                        question=self.question,
                        options_container_x_path=self.options_container_x_path,
                    )
                else:
                    options = DropDown.build_options_list(self.options_xpath_pattern)

                if options:
                    closest_option = (
                        self.answer
                        if [
                            option
                            for option in options
                            if option["text"] == self.answer
                        ]
                        else None
                    )

                    if closest_option is None:
                        closest_option, is_selected_option_correct = (
                            ApplicationField.extract_field_answer(
                                job_title=self.parent_application_page.parent_job.title,
                                job_url=self.parent_application_page.url,
                                company_name=self.parent_application_page.parent_job.company,
                                field_title=self.title,
                                question=self.question,
                                answer_type="enum",
                                options=[option["text"] for option in options],
                                closest_answer=self.answer,
                            )
                        )

                        if not is_selected_option_correct:
                            continue

                    option = [
                        option for option in options if option["text"] == closest_option
                    ][0]

                    # Create a Button instance for the clickable element
                    option_button = Button(
                        x_path=option["x_path"],
                        title=self.title,
                        button_type="search_option",
                        parent_application_page=self.parent_application_page,
                    )
                    option_button.proceed()

                    if is_element_visible(self.options_container_x_path):
                        # Get the clickable parent xpath for this option
                        clickable_xpath = find_clickable_parent_xpath(
                            option["x_path"], option["text"]
                        )
                        option_button.x_path = clickable_xpath
                        option_button.proceed()

                    if not is_element_visible(self.options_container_x_path):
                        self.is_component_functional = True
                        return
                    else:
                        break

            if not self.options_container_x_path or is_element_visible(
                self.options_container_x_path
            ):
                raise Exception(
                    f"Couldn't proceed on following search field {self.category} for "
                    f"{self.parent_application_page.parent_job.title}. "
                    f"URL - {self.parent_application_page.url}"
                )

            return
        except Exception as e:
            if not retry:
                self.proceed(retry=True)
            else:
                raise e

    @property
    def answer(self):
        if self._answer is not None:
            return self._answer

        answer = ApplicationField.get_field_value(
            field_category=self.category,
            user=self.parent_application_page.parent_job.user,
        )
        if not answer:
            answer, _ = ApplicationField.extract_field_answer(
                job_title=self.parent_application_page.parent_job.title,
                job_url=self.parent_application_page.url,
                company_name=self.parent_application_page.parent_job.company,
                field_title=self.title,
                question=self.question,
                answer_type="text",
                parsed_resume=self.parent_application_page.parent_job.user.parsed_resume,
            )

        self._answer = answer
        return self._answer

    @staticmethod
    def generate_sub_phrases(phrase):
        stopwords = {"an", "a", "the", "of", "in", "on", "at", "by", "for", "with"}
        punctuation = {",", ".", "-", "–", "—"}

        def is_noise(token):
            return token.lower() in stopwords or token in punctuation

        # Tokenize: keep words and punctuation as separate tokens
        tokens = re.findall(r"\b\w+\b|[^\w\s]", phrase)

        results = set()
        for i in range(len(tokens)):
            for j in range(i + 1, len(tokens) + 1):
                sub = tokens[i:j]

                # Strip noise from start
                while sub and is_noise(sub[0]):
                    sub = sub[1:]

                # Strip noise from end
                while sub and is_noise(sub[-1]):
                    sub = sub[:-1]

                if sub:
                    results.add(" ".join(sub))

        # Sort: longer phrases first, then alphabetically
        return sorted(results, key=lambda x: (-len(x.split()), x.lower()))

    @property
    def search_phrases(self):
        if self._search_phrases:
            return self._search_phrases

        original_answer_phrases = self.generate_sub_phrases(self.answer)

        class SearchPhrase(BaseModel):
            search_phrase: str = Field(
                ..., description="The search phrase to be used in the search field."
            )

        class SearchPhrases(BaseModel):
            search_phrases: list[SearchPhrase]

        user_prompt = (
            f"I have to answer following question in a search dropdown field type input -\n"
            f"{self.question}\n"
            f"Field title is - {self.title}\n"
            f"My answer is - {self.answer}\n"
            f"Now it may happen that my exact answer will not result in any search result when searched "
            f"exactly. So I have to try different phrases to find most relevant search result. There may be "
            f"different names or phrases of my answer ({self.answer}) so consider those as well. Now give me"
            f" a list of different phrases to search one by one to find most relevant search result. "
            f"Consider other possible names or phrases for my answer and order the list from most relevant "
            f"phrase and precise phrase to search, to less narrowed search but still relevant phrase. "
            f"Keep in mind that most search dropdown may have implemented ONLY EXACT SEARCH (no fuzzy search) so "
            f"substrings, different order & combinations of words & commas should be tried for such search dropdowns "
            f"to increase getting relevant search results, rather than unnecessary noise in phrases which is more "
            f"ideal for fuzzy searches. Give 20 phrases in order asked earlier."
        )

        search_phrases_found, search_phrases = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=SearchPhrases,
        )
        if search_phrases_found:
            original_answer_phrases = original_answer_phrases + [
                phrase.search_phrase for phrase in search_phrases.search_phrases
            ]

        self._search_phrases = list(dict.fromkeys(original_answer_phrases))

        # Add single character vowels to the search phrases as fallback phrases in case nothing works
        self._search_phrases = self._search_phrases + ["a", "e", "i", "o", "u"]

        return self._search_phrases

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "x_path": self.x_path,
            "title": self.title,
            "question": self.question,
            "category": self.category,
            "options_container_x_path": self.options_container_x_path,
            "options_xpath_pattern": self.options_xpath_pattern,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            title=input_dict["title"],
            question=input_dict["question"],
            category=input_dict["category"],
            parent_application_page=parent_application_page,
        )

        instance.options_container_x_path = input_dict["options_container_x_path"]
        instance.options_xpath_pattern = input_dict["options_xpath_pattern"]
        instance.is_component_functional = True

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
