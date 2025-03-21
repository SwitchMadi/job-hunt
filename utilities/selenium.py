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


def element_exists(x_path):
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


def take_element_screenshot(x_path, padding=40):
    global driver

    # Locate the element (adjust the XPath accordingly)
    element = driver.find_element(By.XPATH, x_path)

    # Scroll the element into view
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element
    )
    time.sleep(1)  # Wait for any scrolling animations/rendering

    # Retrieve the element's bounding rectangle relative to the viewport
    rect = driver.execute_script(
        "return arguments[0].getBoundingClientRect();", element
    )

    # Get the device pixel ratio
    dpr = driver.execute_script("return window.devicePixelRatio")

    # Compute coordinates for cropping (adjust with padding if needed)
    left = int((rect["left"] - padding) * dpr)
    top = int((rect["top"] - padding) * dpr)
    width = int((rect["width"] + 2 * padding) * dpr)
    height = int((rect["height"] + 2 * padding) * dpr)

    # Take a screenshot of the visible area (viewport)
    driver.save_screenshot("full_screenshot.png")

    # Open the screenshot and crop using the calculated coordinates
    image = Image.open("full_screenshot.png")
    cropped_image = image.crop((left, top, left + width, top + height))
    screenshot_file = "element_with_padding.png"
    cropped_image.save(screenshot_file)

    absolute_path = os.path.abspath(screenshot_file)
    return absolute_path


def get_xpath_by_text(text):
    global driver

    element = driver.find_element(By.XPATH, f"//*[text()='{text}']")
    # Function to generate XPath of the element
    return driver.execute_script(
        """
        function absoluteXPath(element) {
            var comp, comps = [];
            var parent = null;
            var xpath = '';
            var getPos = function(element) {
                var position = 1, sibling = element.previousSibling;
                while (sibling) {
                    if (sibling.nodeType === Node.ELEMENT_NODE && sibling.nodeName === element.nodeName) {
                        position++;
                    }
                    sibling = sibling.previousSibling;
                }
                return position;
            }
            if (element instanceof Document) {
                return '/';
            }
            for (; element && !(element instanceof Document); element = element.nodeType === Node.ATTRIBUTE_NODE ? element.ownerElement : element.parentNode) {
                comp = comps[comps.length] = {};
                switch (element.nodeType) {
                    case Node.TEXT_NODE:
                        comp.name = 'text()';
                        break;
                    case Node.ATTRIBUTE_NODE:
                        comp.name = '@' + element.nodeName;
                        break;
                    case Node.PROCESSING_INSTRUCTION_NODE:
                        comp.name = 'processing-instruction()';
                        break;
                    case Node.COMMENT_NODE:
                        comp.name = 'comment()';
                        break;
                    case Node.ELEMENT_NODE:
                        comp.name = element.nodeName;
                        break;
                }
                comp.position = getPos(element);
            }
            for (var i = comps.length - 1; i >= 0; i--) {
                comp = comps[i];
                xpath += '/' + comp.name.toLowerCase();
                if (comp.position !== null && comp.position > 1) {
                    xpath += '[' + comp.position + ']';
                }
            }
            return xpath;
        }
        return absoluteXPath(arguments[0]);
    """,
        element,
    )
