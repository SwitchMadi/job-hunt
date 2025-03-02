from abc import ABC, abstractmethod
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
)
from selenium.webdriver.common.action_chains import ActionChains

from utilities.selenium import get_selenium_driver
from utilities.logging import get_logger
from utilities import pascal_to_snake_casing


logger = get_logger(name="job")
driver = get_selenium_driver(headless=False)
driver.set_page_load_timeout(15)


def get_page_component_class_name(class_name):
    module_name = pascal_to_snake_casing(class_name)
    if class_name == "VerifyAccount":
        module_name = "login"
    try:
        return globals()[class_name]
    except KeyError:
        return eval(f'globals()["{module_name}"].{class_name}')


class PageComponent(ABC):
    @abstractmethod
    def proceed(self):
        pass

    @abstractmethod
    def to_dict(self):
        pass

    @abstractmethod
    def from_dict(self, input_dict, parent_application_page):
        pass


class Button(PageComponent):
    def __init__(
        self,
        x_path,
        button_type,
        parent_application_page,
        click_result=None,
    ):
        global driver
        self.x_path = x_path
        self.button_type = button_type
        self.parent_application_page = parent_application_page
        self.click_result = click_result

        self.next = None
        self.prev = None
        self.is_component_functional = True
        self.attempt = 1
        self.max_attempt = 3

    def proceed(self):
        global driver

        try:
            element = driver.find_element(By.XPATH, self.x_path)
            driver.execute_script("arguments[0].scrollIntoView(true);", element)
            element.click()
            time.sleep(10)
        except ElementNotInteractableException as e:
            logger.info(
                f"element not interactable in class Button's proceed method.\n{e}\nButton instance - {vars(self)}"
            )
            element = driver.find_element(By.XPATH, self.x_path)
            driver.execute_script("arguments[0].click();", element)
            time.sleep(10)
        except ElementClickInterceptedException as e:
            logger.info(
                f"element click intercepted in class Button's proceed method.\n{e}\nButton instance - {vars(self)}"
            )
            element = driver.find_element(By.XPATH, self.x_path)
            actions = ActionChains(driver)
            actions.move_to_element(element).click().perform()
            time.sleep(10)
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
            "click_result": self.click_result,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            button_type=input_dict["button_type"],
            parent_application_page=parent_application_page,
            click_result=input_dict["click_result"],
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


class TextInput(PageComponent):
    def __init__(
        self,
        x_path,
        input_type,
        parent_application_page,
    ):
        global driver
        self.x_path = x_path
        self.input_type = input_type
        self.parent_application_page = parent_application_page
        self.is_component_functional = True

        self.next = None
        self.prev = None

    def proceed(self):
        global driver

        try:
            element = driver.find_element(By.XPATH, self.x_path)
            if self.input_type == "otp_textbox":
                element.click()
                for otp_digit in str(
                    self.parent_application_page.account_verification_otp
                ):
                    active_element = driver.switch_to.active_element
                    active_element.send_keys(f"{otp_digit}")
            else:
                element.send_keys(self.input_text)
                element.send_keys(Keys.RETURN)
        except Exception as e:
            logger.exception(
                f"Unexpected error occurred in class TextInput's proceed method.\n{e}\n"
                f"TextInput instance - {vars(self)}"
            )
            self.is_component_functional = False

        return

    @property
    def input_text(self):
        if self.input_type == "username":
            input_text = self.parent_application_page.parent_job.user.email
        elif self.input_type == "password":
            input_text = self.parent_application_page.parent_job.user.password
        else:
            raise Exception(
                f"Invalid input_type for class TextInput - {self.input_type}"
            )

        return input_text

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "x_path": self.x_path,
            "input_type": self.input_type,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            input_type=input_dict["input_type"],
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
