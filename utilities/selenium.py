from selenium import webdriver
from seleniumwire import webdriver as webdriver_wire
import undetected_chromedriver as uc
from selenium_stealth import stealth
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    InvalidSelectorException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
)
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from bs4 import BeautifulSoup
import yaml
import time
from PIL import Image
import os
import logging
import platform
import subprocess
import sys
import glob


driver = None


def get_selenium_driver():
    global driver

    config = yaml.safe_load(open("config.yml"))

    driver_type = config["selenium_driver_type"]
    headless = config["selenium_headless"]

    if driver is None:
        if driver_type == "undetected":
            # Start undetected Chrome
            options = uc.ChromeOptions()

            if headless:
                options.add_argument("--headless")
            else:
                options.add_argument(
                    "--start-maximized"
                )  # open Browser in maximized mode

            options.add_argument(
                "--disable-blink-features=AutomationControlled"
            )  # disables detection feature

            options.add_argument(
                f"--user-data-dir={config['chrome_profile_path']}"
            )  # User Data directory
            if config.get("user_email"):
                options.add_argument(
                    f"--profile-directory={config['user_email']}"
                )  # Profile directory

            # Create driver
            driver = uc.Chrome(options=options)
        else:
            # Setup Chrome options
            options = Options()
            if headless:
                options.add_argument("--headless")
            else:
                options.add_argument(
                    "start-maximized"
                )  # open Browser in maximized mode
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

            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
            options.add_argument(f"user-agent={user_agent}")

            options.add_argument("window-size=1920,1080")
            options.add_argument("window-position=0,0")

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
            if driver_type == "selenium_wire":
                driver = webdriver_wire.Chrome(service=service, options=options)
                logging.getLogger("seleniumwire").setLevel(logging.ERROR)
                import_seleniumwire_ca_cert()
            else:
                driver = webdriver.Chrome(service=service, options=options)

            # This script attempts to set navigator.webdriver to undefined
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            stealth(
                driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
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


def start_dom_mutation_observer():
    """
    Injects a MutationObserver into the page that looks for a new element
    that is rendered and visible (i.e. not hidden via display:none or zero dimensions).
    When found, the element is stored in window.__observedElement.
    """
    global driver

    script = """
    if (!window.__observedElement) {
      window.__observedElement = null;
      window.__observer = new MutationObserver(function(mutations) {
        for (var mutation of mutations) {
          for (var node of mutation.addedNodes) {
            if (node.nodeType !== Node.ELEMENT_NODE) continue;
            var computedStyle = window.getComputedStyle(node);
            if (computedStyle.display === "none") continue;
            if (node.offsetWidth === 0 && node.offsetHeight === 0) continue;
            window.__observedElement = node;
            return;
          }
        }
      });
      window.__observer.observe(document.body, { childList: true, subtree: true });
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
        try:
            element = driver.execute_script("return window.__observedElement;")
            if element is not None:
                # Disconnect the observer from JS.
                driver.execute_script(
                    "if(window.__observer){ window.__observer.disconnect(); window.__observer = null; }"
                )
                return element
        except StaleElementReferenceException:
            pass
        time.sleep(poll_frequency)

    return None


def get_element_xpath(element):
    """Returns the full XPath of a Selenium WebElement using JavaScript."""
    global driver

    return driver.execute_script(
        """
        function getElementXPath(element) {
            if (element.id !== '')
                return 'id("' + element.id + '")';
            if (element === document.documentElement)
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

    js_script = """
    function getElementXPath(el) {
        if (el.tagName.toLowerCase() === 'html') {
            return '/html[1]';
        }
        if (el === document.body) {
            return '/html[1]/body[1]';
        }

        const siblings = Array.from(el.parentNode.children).filter(e => e.tagName === el.tagName);
        const ix = siblings.indexOf(el) + 1;

        return getElementXPath(el.parentNode) + '/' + el.tagName.toLowerCase() + '[' + ix + ']';
    }

    function findSmallestElementByText(text) {
        const allElements = Array.from(document.querySelectorAll('body *'));
        const matchingElements = allElements.filter(el => el.textContent.trim() === text.trim());

        if (matchingElements.length === 0) {
            return null;
        }

        matchingElements.sort((a, b) => a.textContent.length - b.textContent.length);
        return getElementXPath(matchingElements[0]);
    }

    return findSmallestElementByText(arguments[0]);
    """

    xpath = driver.execute_script(js_script, text)

    return xpath


def simulate_empty_area_click(text_to_click=None):
    global driver

    js_script = """
    const eventOpts = { bubbles: true, cancelable: true, view: window };
    const body = document.body;

    body.dispatchEvent(new MouseEvent('mousedown', eventOpts));
    body.dispatchEvent(new MouseEvent('mouseup', eventOpts));
    body.dispatchEvent(new MouseEvent('click', eventOpts));
    """

    driver.execute_script(js_script)

    # Clicking address bar and then pressing escape to close any dropdown
    action = ActionChains(driver)
    current_os = platform.system()

    if current_os == "Darwin":  # macOS
        action.key_down(Keys.COMMAND).send_keys("l").key_up(Keys.COMMAND).perform()
    else:  # Windows and Linux
        action.key_down(Keys.ALT).send_keys("d").key_up(Keys.ALT).perform()

    action.send_keys(Keys.ESCAPE).perform()

    # if text_to_click is set, then click the text to simulate empty area click
    if text_to_click:
        text_x_path = get_xpath_by_text(text_to_click)
        if text_x_path:
            element = driver.find_element(By.XPATH, text_x_path)
            element.click()

    return


def find_ca_cert():
    interpreter_dir = os.path.dirname(sys.executable)

    possible_paths = [
        os.path.expanduser("~/.seleniumwire/ca.crt"),
        os.path.join(interpreter_dir, "lib", "site-packages", "seleniumwire", "ca.crt"),
    ]

    # Handle cases with versioned Python folder (e.g., python3.10)
    lib_path = os.path.join(interpreter_dir, "..", "lib")
    versioned_python_dirs = glob.glob(os.path.join(lib_path, "python*"))

    for version_dir in versioned_python_dirs:
        possible_paths.append(
            os.path.join(version_dir, "site-packages", "seleniumwire", "ca.crt")
        )

    for path in possible_paths:
        cert_path = os.path.abspath(path)
        if os.path.exists(cert_path):
            return cert_path

    raise FileNotFoundError(f"CA certificate not found in paths: {possible_paths}")


def is_cert_already_installed(cert_path):
    system = platform.system()
    if system == "Darwin":  # macOS
        result = subprocess.run(
            ["security", "find-certificate", "-a", "-c", "Selenium Wire", "-Z"],
            capture_output=True,
            text=True,
        )
        return "SHA-1" in result.stdout

    elif system == "Windows":
        result = subprocess.run(
            ["certutil", "-store", "Root"], capture_output=True, text=True, shell=True
        )
        return "Selenium Wire" in result.stdout

    elif system == "Linux":
        cert_filename = os.path.basename(cert_path)
        return os.path.exists(
            os.path.join("/usr/local/share/ca-certificates/", cert_filename)
        )

    else:
        raise OSError(f"Unsupported OS: {system}")


def import_seleniumwire_ca_cert():
    system = platform.system()
    ca_cert_path = find_ca_cert()

    if is_cert_already_installed(ca_cert_path):
        logging.info("Certificate is already installed.")
        return

    if system == "Darwin":  # macOS
        try:
            subprocess.run(
                [
                    "sudo",
                    "security",
                    "add-trusted-cert",
                    "-d",
                    "-r",
                    "trustRoot",
                    "-k",
                    "/Library/Keychains/System.keychain",
                    ca_cert_path,
                ],
                check=True,
            )
            print("Certificate successfully imported on macOS.")
        except subprocess.CalledProcessError as e:
            print("Error importing certificate on macOS:", e)

    elif system == "Windows":
        try:
            subprocess.run(
                ["certutil", "-addstore", "-f", "Root", ca_cert_path],
                shell=True,
                check=True,
            )
            print("Certificate successfully imported on Windows.")
        except subprocess.CalledProcessError as e:
            print("Error importing certificate on Windows:", e)

    elif system == "Linux":
        try:
            target_cert = "/usr/local/share/ca-certificates/seleniumwire_ca.crt"
            subprocess.run(["sudo", "cp", ca_cert_path, target_cert], check=True)
            subprocess.run(["sudo", "update-ca-certificates"], check=True)
            print("Certificate successfully imported on Linux.")
        except subprocess.CalledProcessError as e:
            print("Error importing certificate on Linux:", e)

    else:
        raise OSError(f"Unsupported OS: {system}")


def start_network_observer():
    global driver

    driver.execute_script(
        """
        window.capturedRequests = [];
        if (!window.__networkObserverInstalled) {
            (function() {
                function decodeQueryParams(url) {
                    let params = {};
                    try {
                        let queryString = url.split('?')[1];
                        if (queryString) {
                            queryString.split('&').forEach(function(part) {
                                let [key, value] = part.split('=');
                                params[decodeURIComponent(key)] = decodeURIComponent(value || '');
                            });
                        }
                    } catch (e) {}
                    return params;
                }

                window._originalFetch = window.fetch;
                window.fetch = function(input, init = {}) {
                    const url = typeof input === 'string' ? input : input.url;
                    const method = init.method || 'GET';
                    const body = init.body || '';

                    if (!window.capturedRequests.some(r => r.url === url && r.method === method && r.body === body)) {
                        window.capturedRequests.push({
                            type: 'fetch',
                            url: url,
                            method: method,
                            body: body,
                            decodedQueryParams: decodeQueryParams(url)
                        });
                    }

                    return window._originalFetch.apply(this, arguments);
                };

                window._originalXHROpen = XMLHttpRequest.prototype.open;
                window._originalXHRSend = XMLHttpRequest.prototype.send;

                XMLHttpRequest.prototype.open = function(method, url) {
                    this._requestMethod = method;
                    this._requestUrl = url;
                    return window._originalXHROpen.apply(this, arguments);
                };

                XMLHttpRequest.prototype.send = function(body) {
                    if (!window.capturedRequests.some(r => r.url === this._requestUrl && r.method === this._requestMethod && r.body === (body || ''))) {
                        window.capturedRequests.push({
                            type: 'xhr',
                            url: this._requestUrl,
                            method: this._requestMethod,
                            body: body || '',
                            decodedQueryParams: decodeQueryParams(this._requestUrl)
                        });
                    }

                    return window._originalXHRSend.apply(this, arguments);
                };

                window.__networkObserverInstalled = true;
            })();
        }
    """
    )


def stop_network_observer():
    global driver

    driver.execute_script(
        """
        if (window._originalFetch) {
            window.fetch = window._originalFetch;
        }
        if (window._originalXHROpen && window._originalXHRSend) {
            XMLHttpRequest.prototype.open = window._originalXHROpen;
            XMLHttpRequest.prototype.send = window._originalXHRSend;
        }
        window.__networkObserverInstalled = false;
        window.capturedRequests = [];
    """
    )


def get_observed_network_calls():
    global driver

    return driver.execute_script("return window.capturedRequests || [];")


def clear_text_field(x_path):
    """
    Clears the input field using keyboard shortcuts to ensure any custom handlers are triggered.
    """

    global driver

    input_field = driver.find_element(By.XPATH, x_path)

    # Scroll the element into view
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', inline: 'center'});", input_field
    )

    try:
        input_field.click()  # Ensure the field is focused
    except ElementClickInterceptedException:
        pass

    # Select all text (Ctrl+A) and delete
    input_field.send_keys(Keys.CONTROL + "a")
    input_field.send_keys(Keys.DELETE)
    time.sleep(0.5)

    # Directly set the value to empty and dispatch an input event
    driver.execute_script("arguments[0].value = '';", input_field)
    time.sleep(0.5)

    return


def simulate_typing(xpath, text):
    """
    Simulates human-like typing into an input field by sending individual key events.

    Parameters:
        xpath (str): XPath for the input field element.
        text (str): Text to type character by character.
    """

    global driver

    actions = ActionChains(driver)

    # Locate the input field using the provided XPath
    input_field = driver.find_element(By.XPATH, xpath)

    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});", input_field
    )

    clear_text_field(xpath)

    # Simulate pressing and releasing the key for the character
    for char in text:
        actions.key_down(char).key_up(char).perform()
        time.sleep(0.3)

    current_value = input_field.get_attribute("value")
    if current_value != text:
        clear_text_field(xpath)
        return False

    return True
