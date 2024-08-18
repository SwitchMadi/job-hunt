from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import yaml


def get_selenium_driver(headless=True):
    config = yaml.safe_load(open("config.yml"))

    # Setup Chrome options
    options = Options()
    if headless:
        options.add_argument("--headless")
    else:
        options.add_argument("start-maximized")  # open Browser in maximized mode
    options.add_argument("disable-infobars")  # disabling infobars
    options.add_argument("--disable-extensions")  # disabling extensions
    options.add_argument(
        "--disable-dev-shm-usage"
    )  # overcome limited resource problems
    options.add_argument("--no-sandbox")  # Bypass OS security model
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-blink-features=AutomationControlled")

    options.add_argument(
        f"user-data-dir={config['chrome_profile_path']}"
    )  # User Data directory
    if config.get("user_email"):
        options.add_argument(
            f"profile-directory={config['user_email']}"
        )  # Profile directory

    # Set up service
    service = Service(executable_path=config["chromedriver"])

    # Start browser
    driver = webdriver.Chrome(service=service, options=options)

    # This script attempts to set navigator.webdriver to undefined
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    return driver
