import time
from selenium.common import (
    ElementNotInteractableException,
    ElementClickInterceptedException,
)
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By

from jobs.page_components import PageComponent, logger, get_page_component_class_name
from utilities.selenium import get_selenium_driver


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class Button(PageComponent):
    def __init__(self, x_path, button_type, parent_application_page):
        global driver
        self.x_path = x_path
        self.button_type = button_type
        self.parent_application_page = parent_application_page

        self.next = None
        self.prev = None
        self.is_component_functional = True
        self.attempt = 1
        self.max_attempt = 3

    def proceed(self):
        global driver

        try:
            element = driver.find_element(By.XPATH, self.x_path)
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", element
            )
            element.click()
            time.sleep(2)
        except ElementNotInteractableException as e:
            logger.info(
                f"element not interactable in class Button's proceed method.\n{e}\nButton instance - {vars(self)}"
            )
            element = driver.find_element(By.XPATH, self.x_path)
            driver.execute_script("arguments[0].click();", element)
            time.sleep(2)
        except ElementClickInterceptedException as e:
            logger.info(
                f"element click intercepted in class Button's proceed method.\n{e}\nButton instance - {vars(self)}"
            )
            element = driver.find_element(By.XPATH, self.x_path)
            actions = ActionChains(driver)
            actions.move_to_element(element).click().perform()
            time.sleep(2)
        except Exception as e:
            if self.attempt <= self.max_attempt:
                logger.info(
                    f"Retrying class Button's proceed method.\nButton instance - {vars(self)}"
                )
                time.sleep(2 * (self.attempt**2))
                self.attempt += 1
                return self.proceed()
            else:
                logger.exception(
                    f"Unexpected error occurred in class Button's proceed method.\n{e}\nButton instance - {vars(self)}"
                )
                self.is_component_functional = False

        return

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "x_path": self.x_path,
            "button_type": self.button_type,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            button_type=input_dict["button_type"],
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
