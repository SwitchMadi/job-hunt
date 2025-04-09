from selenium.common import (
    ElementNotInteractableException,
    StaleElementReferenceException,
    InvalidElementStateException,
)
from selenium.webdriver.common.by import By
import pyautogui
import time
import platform

from jobs.page_components import PageComponent, logger, get_page_component_class_name
from utilities.selenium import get_selenium_driver


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class Upload(PageComponent):
    def __init__(self, x_path, upload_type, parent_application_page, file_path=None):
        global driver
        self.x_path = x_path
        self.upload_type = upload_type
        self.file_path = file_path

        self.parent_application_page = parent_application_page

        self.next = None
        self.prev = None
        self.is_component_functional = False

    def proceed(self, retry=False):
        global driver

        if not self.file_path:
            logger.exception(
                f"file_path not set for Upload component.\nUpload instance - {vars(self)}"
            )

        try:
            element = driver.find_element(By.XPATH, self.x_path)
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", element
            )
            element.click()
            time.sleep(1)

            pyautogui.write(self.file_path, interval=0.05)
            time.sleep(1)

            current_os = platform.system()
            enter_count = 2 if current_os == "Darwin" else 1
            for _ in range(enter_count):
                pyautogui.press("enter")
                time.sleep(1)

            time.sleep(15)

            self.is_component_functional = True
        except (
            ElementNotInteractableException,
            StaleElementReferenceException,
            InvalidElementStateException,
        ) as e:
            logger.exception(
                f"An error occurred in class Upload.\n{e}\nUpload instance - {vars(self)}"
            )

        return

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "x_path": self.x_path,
            "upload_type": self.upload_type,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            upload_type=input_dict["upload_type"],
            parent_application_page=parent_application_page,
        )
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
