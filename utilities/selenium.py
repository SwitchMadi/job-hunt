from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import InvalidSelectorException
from bs4 import BeautifulSoup
import yaml
import time


driver = None


def get_selenium_driver(headless=True):
    global driver

    if driver is None:
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
        options.add_argument("--deny-permission-prompts")

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


def disable_browser_alerts():
    global driver

    # disable browser alerts
    driver.execute_script(
        """
        window.alert = function() {};
        window.confirm = function() { return true; };
        window.prompt = function() { return null; };
    """
    )

    return True


def extract_iframe_urls(html_content):
    # Parse the HTML content with BeautifulSoup
    soup = BeautifulSoup(html_content, "html.parser")

    # Find all iframe elements in the HTML
    iframes = soup.find_all("iframe")
    iframe_urls = []

    # Iterate through each iframe
    for iframe in iframes:
        # Get the iframe's src attribute
        src = iframe.get("src")
        if src:
            iframe_urls.append(src)
        else:
            # Look for meta refresh tag inside the iframe if src is not available
            meta_refresh = iframe.find("meta", {"http-equiv": "refresh"})
            if meta_refresh:
                # Parse the URL from the content attribute
                content = meta_refresh.get("content")
                if content:
                    url = content.split("url=")[-1].strip()
                    iframe_urls.append(url)

    return iframe_urls


def x_path_exists(x_path):
    global driver

    try:
        elements = driver.find_elements(By.XPATH, x_path)
        if elements:
            return True
        else:
            return False
    except InvalidSelectorException:
        return False


def start_observer():
    """
    Injects a MutationObserver into the page that looks for a new element
    that is rendered and visible (i.e. not hidden via display:none or zero dimensions).
    When found, the element is stored in window.__observedElement.
    """
    global driver

    script = """
    if (!window.__observedElement) {
      window.__observedElement = null;
      var observer = new MutationObserver(function(mutations) {
        for (var mutation of mutations) {
          for (var node of mutation.addedNodes) {
            if (node.nodeType !== Node.ELEMENT_NODE) continue;
            var computedStyle = window.getComputedStyle(node);
            if (computedStyle.display === "none") continue;
            if (node.offsetWidth === 0 && node.offsetHeight === 0) continue;
            window.__observedElement = node;
            observer.disconnect();
            return;
          }
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }
    """
    driver.execute_script(script)


def get_observed_element(timeout=10, poll_frequency=0.5):
    """
    Polls the global variable window.__observedElement until it is non-null
    or until the timeout is reached.

    Returns:
        The observed WebElement if found.

    Raises:
        Exception if no element is found within the timeout.
    """
    global driver

    end_time = time.time() + timeout
    while time.time() < end_time:
        element = driver.execute_script("return window.__observedElement;")
        if element is not None:
            return element
        time.sleep(poll_frequency)
    raise Exception("Timeout waiting for new element")


def get_element_xpath(element):
    """Returns the full XPath of a Selenium WebElement using JavaScript."""
    global driver

    return driver.execute_script(
        """
        function getElementXPath(element) {
            if (element.id !== '')
                return 'id(\"' + element.id + '\")';
            if (element === document.body)
                return element.tagName.toLowerCase();

            var ix = 0;
            var siblings = element.parentNode.childNodes;
            for (var i = 0; i < siblings.length; i++) {
                var sibling = siblings[i];
                if (sibling === element)
                    return getElementXPath(element.parentNode) + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
                if (sibling.nodeType === 1 && sibling.tagName === element.tagName)
                    ix++;
            }
        }
        return getElementXPath(arguments[0]);
    """,
        element,
    )
