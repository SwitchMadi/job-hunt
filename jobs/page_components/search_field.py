import time
from selenium.webdriver.common.by import By
from selenium.common import ElementNotInteractableException

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
    start_dom_mutation_observer,
    get_observed_elements,
    is_element_visible,
    clear_text_field,
)


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
                x_path=x_path, category="search_field", parent_application_page=None
            )
            element.answer = special_key
            element.proceed()
            time.sleep(2)  # Allow API calls to trigger
        except ElementNotInteractableException:
            clear_text_field(x_path)
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

        is_search_field = False
        for request in captured_requests:
            if not is_tracking_domain(request["url"]):
                # Check decoded query params
                for key, value in request.get("decodedQueryParams", {}).items():
                    if special_key in value:
                        is_search_field = True
                        break

                # Check POST body
                if (
                    not is_search_field
                    and request["method"] == "POST"
                    and request["body"]
                ):
                    if special_key in request["body"]:
                        is_search_field = True
                        break

                if is_search_field:
                    break

        clear_text_field(x_path)
        simulate_empty_area_click()

        return is_search_field

    def proceed(self, retry=False):
        try:
            input_count = min(2, len(self.answer.split(" ")))
            while input_count >= 0:
                if input_count > 0:
                    input_key = " ".join(self.answer.split(" ")[:input_count])
                else:
                    input_key = "a"

                element = TextInput(
                    x_path=self.x_path,
                    category="search_field",
                    parent_application_page=None,
                )
                element.answer = input_key

                if not self.options_container_x_path:
                    start_dom_mutation_observer()
                    element.proceed()
                    time.sleep(2)
                    observed_elements = get_observed_elements()

                    is_container_present, container_x_path = (
                        ApplicationField.identify_options_container(
                            field_title=self.title,
                            field_x_path=self.x_path,
                            observed_elements=observed_elements,
                            html_type="search_field",
                            job_title=self.parent_application_page.parent_job.title,
                        )
                    )
                    self.options_container_x_path = container_x_path
                    if not is_container_present or not container_x_path:
                        raise Exception(
                            f"Couldn't find options container for {self.category} "
                            f"for {self.parent_application_page.parent_job.title}. "
                            f"URL - {self.parent_application_page.url}"
                        )

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
                        closest_option = ApplicationField.extract_field_answer(
                            job_title=self.parent_application_page.parent_job.title,
                            job_url=self.parent_application_page.url,
                            company_name=self.parent_application_page.parent_job.company,
                            field_title=self.title,
                            question=self.question,
                            answer_type="enum",
                            options=[option["text"] for option in options],
                            closest_answer=self.answer,
                        )

                    option = [
                        option for option in options if option["text"] == closest_option
                    ][0]
                    # Get the clickable parent xpath for this option
                    clickable_xpath = find_clickable_parent_xpath(
                        option["x_path"], option["text"]
                    )

                    # Create a Button instance for the clickable element
                    option_button = Button(
                        x_path=clickable_xpath,
                        button_type="search_option",
                        parent_application_page=self.parent_application_page,
                    )
                    option_button.proceed()
                    break
                else:
                    input_count -= 1

            if is_element_visible(self.options_container_x_path):
                raise Exception(
                    f"Couldn't proceed on following search field {self.category} for "
                    f"{self.parent_application_page.parent_job.title}. "
                    f"URL - {self.parent_application_page.url}"
                )

            self.is_component_functional = True
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
            answer = ApplicationField.extract_field_answer(
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
