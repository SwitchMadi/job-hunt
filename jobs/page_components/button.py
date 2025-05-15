import time
import random
from selenium.common import (
    ElementNotInteractableException,
    ElementClickInterceptedException,
)
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from jobs.page_components import PageComponent, logger, get_page_component_class_name
from utilities.selenium import get_selenium_driver, is_element_visible


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

    def _human_like_delay(self):
        """Add a random delay to mimic human response time"""
        time.sleep(random.uniform(0.5, 2))

    def _move_mouse_naturally(self, element, actions):
        """Move mouse in a more natural way to the element"""
        # Get element location and size
        location = element.location
        size = element.size

        # Calculate a random point within the element
        offset_x = random.randint(5, size["width"] - 5)
        offset_y = random.randint(5, size["height"] - 5)

        # Create a curved movement by adding intermediate points
        start_x = random.randint(0, 100)
        start_y = random.randint(0, 100)

        # Move to initial position
        actions.move_by_offset(start_x, start_y)

        # Add some "human-like" curved movement
        steps = random.randint(3, 6)
        for _ in range(steps):
            actions.pause(random.uniform(0.1, 0.3))
            actions.move_by_offset(
                (location["x"] + offset_x - start_x) // steps,
                (location["y"] + offset_y - start_y) // steps,
            )

        return actions

    def proceed(self, retry=False):
        global driver

        try:
            if not is_element_visible(self.x_path):
                logger.warning(
                    f"Element not visible in class Button's proceed method.\nButton instance - {vars(self)}"
                )
                self.is_component_functional = False
                return

            # Add initial random delay
            self._human_like_delay()

            element = driver.find_element(By.XPATH, self.x_path)

            # Scroll element into view with some randomness in scroll position
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", element
            )

            # Add small delay after scrolling
            time.sleep(random.uniform(0.3, 0.7))

            # Create action chains for more natural movement
            actions = ActionChains(driver)
            actions = self._move_mouse_naturally(element, actions)

            # Add a tiny pause before clicking
            actions.pause(random.uniform(0.1, 0.3))

            if self.button_type == "dropdown":
                driver.execute_script(
                    """
                    const element = arguments[0];
                    const rect = element.getBoundingClientRect();
                    const elementTop = rect.top + window.pageYOffset;
                    const viewportHeight = window.innerHeight;
                    const offsetToCenter = elementTop - (viewportHeight / 2) + (rect.height / 2) + 100;
                    window.scrollTo({top: offsetToCenter, behavior: 'smooth'});
                """,
                    element,
                )
                time.sleep(0.2)
                WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, self.x_path))
                )
                element.click()
            else:
                # Use JavaScript to dispatch native events for more reliable clicking
                driver.execute_script(
                    """
                    function simulateClick(element) {
                        ['mousedown', 'mouseup', 'click'].forEach(eventType => {
                            const event = new MouseEvent(eventType, {
                                view: window,
                                bubbles: true,
                                cancelable: true,
                                clientX: element.getBoundingClientRect().left + 5,
                                clientY: element.getBoundingClientRect().top + 5
                            });
                            element.dispatchEvent(event);
                        });
                    }
                    simulateClick(arguments[0]);
                """,
                    element,
                )

            # Random delay after clicking
            time.sleep(random.uniform(1.5, 2.5))
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
                raise e

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
