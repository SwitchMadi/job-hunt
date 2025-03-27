import time
from selenium.webdriver.common.by import By

from jobs import ApplicationField
from jobs.page_components import PageComponent, DropDown, get_page_component_class_name
from utilities.selenium import (
    get_selenium_driver,
    start_network_observer,
    get_observed_network_calls,
    stop_network_observer,
    simulate_empty_area_click,
    start_dom_mutation_observer,
    get_observed_element,
    get_element_xpath,
    element_exists,
)


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class SearchField(PageComponent):
    def __init__(self, x_path, title, category, parent_application_page):
        self.x_path = x_path
        self.title = title
        self.category = category
        self.parent_application_page = parent_application_page

        self.options_container_x_path = None
        self._answer = None

        self.is_component_functional = False

        self.next = None
        self.prev = None

    @classmethod
    def validate_search_field(cls, x_path, field_title):
        global driver

        start_network_observer()

        element = driver.find_element(By.XPATH, x_path)
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", element
        )

        special_key = "special_key"
        element.send_keys(special_key)
        time.sleep(2)  # Allow API calls to trigger

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
                    if special_key == value:
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

        simulate_empty_area_click(field_title)
        return is_search_field

    def proceed(self):
        input_count = min(2, len(self.answer.split(" ")))
        while input_count >= 0:
            if input_count > 0:
                input_key = " ".join(self.answer.split(" ")[:input_count])
            else:
                input_key = "a"

            element = driver.find_element(By.XPATH, self.x_path)

            if not self.options_container_x_path:
                start_dom_mutation_observer()
                element.send_keys(input_key)
                time.sleep(2)
                options_container = get_observed_element()
                self.options_container_x_path = get_element_xpath(options_container)
            else:
                element.send_keys(input_key)
                time.sleep(2)

            options = DropDown.extract_dropdown_options(
                job_title=self.parent_application_page.parent_job.title,
                job_url=self.parent_application_page.url,
                question=self.title,
                options_container_x_path=self.options_container_x_path,
            )
            if options:
                closest_option = (
                    self.answer
                    if [option for option in options if option["text"] == self.answer]
                    else None
                )

                if closest_option is None:
                    closest_option = ApplicationField.extract_field_answer(
                        job_title=self.parent_application_page.parent_job.title,
                        job_url=self.parent_application_page.url,
                        company_name=self.parent_application_page.parent_job.company,
                        question=self.title,
                        answer_type="enum",
                        options=[option["text"] for option in options],
                        closest_answer=self.answer,
                    )

                option = [
                    option for option in options if option["text"] == closest_option
                ][0]
                option_element = driver.find_element(By.XPATH, option["x_path"])
                option_element.click()
            else:
                input_count -= 1

        if element_exists(self.options_container_x_path):
            raise Exception(
                f"Couldn't proceed on following search field {self.category} for "
                f"{self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )

        self.is_component_functional = True
        return

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
                question=self.title,
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
            "category": self.category,
            "options_container_x_path": self.options_container_x_path,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            title=input_dict["title"],
            category=input_dict["category"],
            parent_application_page=parent_application_page,
        )

        instance.options_container_x_path = input_dict["options_container_x_path"]
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
