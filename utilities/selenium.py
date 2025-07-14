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
    ElementNotInteractableException,
    NoSuchElementException,
    JavascriptException,
)
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from bs4 import BeautifulSoup, Comment
import yaml
import time
from PIL import Image
import os
import logging
import platform
import subprocess
import sys
import glob
import htmlmin
import re
import psutil


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
            options.add_argument("--disable-popup-blocking")
            options.add_argument("--deny-permission-prompts")

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
            options.add_argument("--disable-popup-blocking")
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


def close_selenium_driver():
    global driver

    if driver is not None and (
        isinstance(driver, webdriver_wire.Chrome)
        or isinstance(driver, webdriver.Chrome)
        or isinstance(driver, uc.Chrome)
    ):
        try:
            driver.quit()
        except Exception as e:
            logging.error(f"Error closing Selenium driver: {e}")
        finally:
            driver = None


def kill_selenium_chrome():
    config = yaml.safe_load(open("config.yml"))

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.info["name"] and "chrome" in proc.info["name"].lower():
                cmdline = " ".join(proc.info["cmdline"])
                if f"user-data-dir={config['chrome_profile_path']}" in cmdline:
                    proc.terminate()
                    proc.wait(timeout=5)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


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


def switch_to_active_tab():
    global driver

    driver.switch_to.window(driver.window_handles[-1])


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


def is_element_visible(x_path=None, element=None):
    global driver

    if element:
        if not is_stale(element):
            element_size = element.size
            if (
                element.is_displayed()
                and element_size["width"] > 0
                and element_size["height"] > 0
            ):
                return True
            else:
                return False
        else:
            return False

    if not x_path:
        return False

    try:
        elements = driver.find_elements(By.XPATH, x_path)
        for element in elements:
            if not is_stale(element):
                element_size = element.size
                if (
                    element.is_displayed()
                    and element_size["width"] > 0
                    and element_size["height"] > 0
                ):
                    return True
        return False
    except (InvalidSelectorException, NoSuchElementException):
        return False


def element_has_area(x_path=None, element=None):
    global driver

    if element:
        element_size = element.size
        if element_size["width"] > 0 and element_size["height"] > 0:
            return True
        else:
            return False

    if not x_path:
        return False

    try:
        elements = driver.find_elements(By.XPATH, x_path)
        for element in elements:
            element_size = element.size
            if element_size["width"] > 0 and element_size["height"] > 0:
                return True
        return False
    except (InvalidSelectorException, NoSuchElementException):
        return False


def start_dom_mutation_observer(timeout=100):
    """
    MutationObserver that collects visible + attached DOM elements,
    and ignores irrelevant elements like <html>, <body>, etc.
    """
    global driver

    script = f"""
      // tear down any previous observer
      if (window.__observer) {{
        window.__observer.disconnect();
        window.__observer = null;
      }}

      window.__observedElements = [];

      const IGNORED_TAGS = ["HTML", "BODY", "HEAD", "SCRIPT", "STYLE"];

      function isVisibleAndAttached(node) {{
        if (!node || !document.documentElement.contains(node)) return false;
        if (IGNORED_TAGS.includes(node.tagName)) return false;

        const style = window.getComputedStyle(node);
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          node.offsetWidth > 0 &&
          node.offsetHeight > 0
        );
      }}

      function addIfValid(node) {{
        if (!isVisibleAndAttached(node)) return;
        if (!window.__observedElements.includes(node)) {{
          window.__observedElements.push(node);
        }}
      }}

      window.__observer = new MutationObserver(function(mutations) {{
        for (const mutation of mutations) {{
          if (mutation.type === "childList") {{
            for (const added of mutation.addedNodes) {{
              if (added.nodeType !== Node.ELEMENT_NODE) continue;
              setTimeout(() => addIfValid(added), {timeout});
            }}
          }}

          if (mutation.type === "attributes" && mutation.attributeName.match(/class|style/)) {{
            setTimeout(() => addIfValid(mutation.target), {timeout});
          }}
        }}
      }});

      window.__observer.observe(document.documentElement, {{
        childList: true,
        attributes: true,
        attributeFilter: ["class", "style"],
        subtree: true
      }});
    """
    driver.execute_script(script)


def get_observed_elements(timeout=3, poll_frequency=0.25):
    """
    Polls the global variable window.__observedElement until it is non-null
    or until the timeout is reached.

    Returns:
        The observed WebElement if found.

    Raises:
        Exception if no element is found within the timeout.
    """
    global driver

    elements = []
    end_time = time.time() + timeout
    while (time.time() < end_time) and (len(elements) == 0):
        try:
            elements = driver.execute_script(
                """
              return (function() {
                if (!window.__observedElements) return [];
            
                function isValid(node) {
                  if (!node || !document.documentElement.contains(node)) return false;
                  const style = window.getComputedStyle(node);
                  return (
                    style.display !== "none" &&
                    style.visibility !== "hidden" &&
                    node.offsetWidth > 0 &&
                    node.offsetHeight > 0
                  );
                }
            
                const validElements = window.__observedElements.filter(isValid);
                
                return validElements.filter(
                    el => !validElements.some(other => other !== el && other.contains(el))
                );
              })();
            """
            )

            if elements:
                elements = [element for element in elements if not is_stale(element)]
        except StaleElementReferenceException:
            pass

        time.sleep(poll_frequency)

    # Disconnect the observer from JS.
    stop_dom_mutation_observer()

    return elements


def stop_dom_mutation_observer():
    """
    Stops the DOM MutationObserver and clears the observed elements.
    """
    global driver

    driver.execute_script(
        """
        if (window.__observer) {
            window.__observer.disconnect();
            window.__observer = null;
        }
        window.__observedElements = [];
    """
    )


def get_element_xpath(element, xpath_type="full"):
    """Returns the full XPath of a Selenium WebElement using JavaScript."""
    global driver

    try:
        if xpath_type == "full":
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
        elif xpath_type == "relative":
            return driver.execute_script(
                """
                function getElementFullXPath(element) {
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
                };
                
                function getElementXPath(element) {
                    function isUnique(xpathExpression) {
                        return document.evaluate(
                            xpathExpression,
                            document,
                            null,
                            XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
                            null
                        ).snapshotLength === 1;
                    }
                
                    function getIndex(node) {
                        var index = 1;
                        var sibling = node.previousSibling;
                        while (sibling) {
                            if (sibling.nodeType === 1 && sibling.tagName === node.tagName) {
                                index++;
                            }
                            sibling = sibling.previousSibling;
                        }
                        return index;
                    }
                
                    function buildPath(startNode) {
                        var segments = [];
                        var currentNode = startNode;
                
                        // keep climbing up through html/body as well
                        while (currentNode && currentNode.nodeType === 1) {
                            var tagName = currentNode.tagName.toLowerCase();
                
                            // ID shortcut, but include any child segments so we still point to the original element
                            if (currentNode.id) {
                                var idBasedPath = '//' + tagName + '[@id="' + currentNode.id + '"]';
                                if (isUnique(idBasedPath)) {
                                    if (segments.length) {
                                        return idBasedPath + '/' + segments.join('/');
                                    }
                                    return idBasedPath;
                                }
                            }
                
                            // positional segment
                            var position = getIndex(currentNode);
                            segments.unshift(tagName + '[' + position + ']');
                
                            // try a //path
                            var partialPath = '//' + segments.join('/');
                            if (isUnique(partialPath)) {
                                return partialPath;
                            }
                
                            currentNode = currentNode.parentNode;
                        }
                
                        // full xpath fallback
                        return getElementFullXPath(startNode);
                    }
                
                    return buildPath(element);
                }
    
                return getElementXPath(arguments[0]);
                """,
                element,
            )
        else:
            raise ValueError("Invalid xpath_type. Use 'full' or 'relative'.")
    except StaleElementReferenceException:
        logging.warning("Element is stale, cannot retrieve XPath.")
        return None


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

    function cleanTextEdges(str) {
        return str
            .trim()  // First trim whitespace
            .replace(/^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$/g, '')  // Then trim special characters
            .trim();  // Finally trim again in case special chars created new leading/trailing spaces
    }

    function findSmallestElementByText(text) {
        const cleanedInput = cleanTextEdges(text);
        const allElements = Array.from(document.querySelectorAll('body *'));
        let matchingElements;

        if (cleanedInput.length > 70) {
            matchingElements = allElements.filter(el => {
                const cleanedElText = cleanTextEdges(el.textContent);
                return cleanedElText.includes(cleanedInput);
            });
        } else {
            matchingElements = allElements.filter(el => {
                const cleanedElText = cleanTextEdges(el.textContent);
                return cleanedElText === cleanedInput;
            });
        }

        if (matchingElements.length === 0) {
            return null;
        }

        // Helper to get element depth in the DOM tree
        function getDepth(el) {
            let depth = 0;
            while (el.parentElement) {
                depth++;
                el = el.parentElement;
            }
            return depth;
        }

        // Sort by text length first, then by nesting depth (desc)
        matchingElements.sort((a, b) => {
            const styleA = window.getComputedStyle(a);
            const styleB = window.getComputedStyle(b);
        
            const visibleA = (
                styleA.display !== "none" &&
                styleA.visibility !== "hidden" &&
                a.offsetWidth > 1 &&
                a.offsetHeight > 1
            );
            const visibleB = (
                styleB.display !== "none" &&
                styleB.visibility !== "hidden" &&
                b.offsetWidth > 1 &&
                b.offsetHeight > 1
            );
        
            if (visibleA !== visibleB) {
                return visibleB - visibleA;  // true > false, so visible comes first
            }
            
            const lenA = cleanTextEdges(a.textContent).length;
            const lenB = cleanTextEdges(b.textContent).length;
            if (lenA !== lenB) {
                return lenA - lenB;  // shorter text first
            }
            
            return getDepth(b) - getDepth(a);  // more nested first if tie
        });
        
        return getElementXPath(matchingElements[0]);
    }

    return findSmallestElementByText(arguments[0]);
    """

    xpath = driver.execute_script(js_script, text)
    return xpath


def simulate_empty_area_click(text_to_click=None):
    global driver

    # Step 1: Inject temporary element
    js_add_element = """
    const dummyDiv = document.createElement('div');
    dummyDiv.setAttribute('id', 'temp-dummy-click-area');

    const scrollX = window.scrollX;
    const scrollY = window.scrollY;

    dummyDiv.style.position = 'absolute';
    dummyDiv.style.left = (scrollX + 10) + 'px';
    dummyDiv.style.top = (scrollY + 10) + 'px';
    dummyDiv.style.width = '10px';
    dummyDiv.style.height = '10px';
    dummyDiv.style.backgroundColor = 'transparent';
    dummyDiv.style.zIndex = '999999';
    dummyDiv.style.cursor = 'pointer';

    document.body.appendChild(dummyDiv);
    """
    driver.execute_script(js_add_element)

    # Step 2: Fallback JS click (just in case)
    js_click = """
    const div = document.getElementById('temp-dummy-click-area');
    if (div) {
        const rect = div.getBoundingClientRect();
        const eventOpts = { bubbles: true, cancelable: true, clientX: rect.left + 5, clientY: rect.top + 5, view: window };
        div.dispatchEvent(new MouseEvent('mousedown', eventOpts));
        div.dispatchEvent(new MouseEvent('mouseup', eventOpts));
        div.dispatchEvent(new MouseEvent('click', eventOpts));
    }
    """
    driver.execute_script(js_click)

    # Step 3: Selenium ActionChains click (true browser interaction)
    try:
        temp_elem = driver.find_element(By.ID, "temp-dummy-click-area")
        ActionChains(driver).move_to_element(temp_elem).click().perform()
    except Exception as e:
        print("ActionChains click failed:", e)

    # Step 4: Cleanup
    time.sleep(0.1)  # slight delay to let DOM process focus change
    js_remove = """
    const div = document.getElementById('temp-dummy-click-area');
    if (div) div.remove();
    """
    driver.execute_script(js_remove)

    ActionChains(driver).send_keys(Keys.ESCAPE).perform()

    if text_to_click:
        # If text is provided, click on the element with that text to bring back focus
        try:
            xpath = get_xpath_by_text(text_to_click)
            if type(xpath) is not str:
                logging.warning(
                    f"XPath for text '{text_to_click}' is not a string: {xpath}"
                )
                return
            element = driver.find_element(By.XPATH, xpath)

            driver.execute_script(
                """
                const element = arguments[0];
                const rect = element.getBoundingClientRect();
                const elementTop = rect.top + window.pageYOffset;
                const viewportHeight = window.innerHeight;
                const offsetToCenter = elementTop - (viewportHeight / 2) + (rect.height / 2) + 100;
                window.scrollTo({top: offsetToCenter, behavior: 'auto'});
            """,
                element,
            )

            element.click()
        except (NoSuchElementException, InvalidSelectorException):
            logging.warning(f"Element with text '{text_to_click}' not found.")
        except ElementClickInterceptedException:
            element = driver.find_element(By.XPATH, xpath)
            actions = ActionChains(driver)
            actions.move_to_element(element).click().perform()

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
                    const absoluteUrl = (url.startsWith('http://') || url.startsWith('https://')) 
                        ? url 
                        : new URL(url, location.href).href;
                    const method = init.method || 'GET';
                    const body = init.body || '';

                    if (!window.capturedRequests.some(r => r.url === url && r.method === method && r.body === body)) {
                        window.capturedRequests.push({
                            type: 'fetch',
                            url: absoluteUrl,
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
                    const absoluteUrl = (this._requestUrl.startsWith('http://') || this._requestUrl.startsWith('https://')) 
                        ? this._requestUrl 
                        : new URL(this._requestUrl, location.href).href;
                    
                    if (!window.capturedRequests.some(r => r.url === this._requestUrl && r.method === this._requestMethod && r.body === (body || ''))) {
                        window.capturedRequests.push({
                            type: 'xhr',
                            url: absoluteUrl,
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


def clear_text_field(x_path, title=None, skip_all_sections=False):
    """
    Clears the input field using keyboard shortcuts to ensure any custom handlers are triggered.
    """

    global driver

    input_field = get_active_element_after_click(x_path, title=title)

    value = input_field.get_attribute("value") or input_field.text or ""
    if not value:
        return

    try:
        driver.execute_script(
            """
        const el = arguments[0];

        // Store prototype setter for value
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;

        // Use native setter to set the value
        nativeInputValueSetter.call(el, '');

        // Dispatch events to simulate real user input
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    """,
            input_field,
        )

        value = input_field.get_attribute("value") or input_field.text or ""
        if not value:
            return
    except JavascriptException:
        pass

    if not skip_all_sections:
        try:
            # Select all text (Ctrl+A) and delete
            input_field.send_keys(Keys.CONTROL + "a")
            driver.switch_to.active_element.send_keys(Keys.DELETE)
            time.sleep(0.5)

            value = input_field.get_attribute("value") or input_field.text or ""
            if not value:
                return
        except (
            ElementClickInterceptedException,
            ElementNotInteractableException,
            StaleElementReferenceException,
        ):
            pass

    if is_stale(input_field):
        input_field = get_active_element_after_click(x_path, title=title)

    # Directly set the value to empty and dispatch an input event
    driver.execute_script("arguments[0].value = '';", input_field)
    time.sleep(0.5)

    return


def get_active_element_after_click(x_path, title=None):
    """
    Clicks on the element at the given XPath and returns the active element.
    This is useful for ensuring that the correct element is focused after a click.
    """

    global driver

    simulate_empty_area_click()

    element = get_unique_element_by_xpath(x_path, title=title)
    driver.execute_script(
        """
        const element = arguments[0];
        const rect = element.getBoundingClientRect();
        const elementTop = rect.top + window.pageYOffset;
        const viewportHeight = window.innerHeight;
        const offsetToCenter = elementTop - (viewportHeight / 2) + (rect.height / 2) + 100;
        window.scrollTo({top: offsetToCenter, behavior: 'auto'});
    """,
        element,
    )
    time.sleep(0.5)

    try:
        if element.tag_name == "input":
            actions = ActionChains(driver)
            actions.move_to_element(element).click().perform()
        else:
            element.click()  # Ensure the field is focused
    except (ElementClickInterceptedException, ElementNotInteractableException):
        # Fallback: use JS to focus
        driver.execute_script("arguments[0].click();", element)
    except Exception:
        actions = ActionChains(driver)
        actions.move_to_element(element).click().perform()

    time.sleep(0.5)

    # Return the active element
    return driver.switch_to.active_element


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
        """
        const element = arguments[0];
        const rect = element.getBoundingClientRect();
        const elementTop = rect.top + window.pageYOffset;
        const viewportHeight = window.innerHeight;
        const offsetToCenter = elementTop - (viewportHeight / 2) + (rect.height / 2) + 100;
        window.scrollTo({top: offsetToCenter, behavior: 'auto'});
    """,
        input_field,
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


def get_computed_dimensions(tag):
    """
    Attempts to fetch computed dimensions (offsetWidth and offsetHeight)
    of the element in the live DOM via Selenium's driver.

    First, it tries to locate the element by its id; if not available or not unique,
    it builds a CSS selector using a set of allowed attributes. Returns a tuple
    (width, height) if a unique element is identified, or None otherwise.
    """

    driver = get_selenium_driver()

    # First try: use ID if available
    try:
        if tag.attrs and tag.has_attr("id"):
            el = driver.find_element("id", tag["id"])
            width = driver.execute_script("return arguments[0].offsetWidth;", el)
            height = driver.execute_script("return arguments[0].offsetHeight;", el)
            return (width, height)
    except Exception:
        pass

    # Allowed attributes from which we build a custom CSS selector.
    allowed_attrs = [
        "class",
        "href",
        "type",
        "name",
        "value",
        "display",
        "placeholder",
        "alt",
        "title",
        "role",
        "aria-label",
        "aria-labelledby",
        "aria-expanded",
        "data-automation-id",
        "data-id",
    ]

    # Build CSS selector using the tag name.
    selector = tag.name
    # For each allowed attribute, append a CSS condition if present.
    for attr in allowed_attrs:
        if tag.attrs and tag.has_attr(attr):
            value = tag[attr]
            if isinstance(value, list):
                # For attributes like "class" that can be a list, add each class.
                for cls in value:
                    selector += f".{cls}"
            else:
                selector += f"[{attr}='{value}']"

    # Attempt to find the element with our generated selector
    try:
        elements = driver.find_elements("css selector", selector)
        if len(elements) == 1:
            el = elements[0]
            width = driver.execute_script("return arguments[0].offsetWidth;", el)
            height = driver.execute_script("return arguments[0].offsetHeight;", el)
            return (width, height)
    except Exception:
        pass

    return None


def has_zero_dimension(tag):
    """
    Returns True if the tag appears to have zero width or zero height.

    Checks inline style and direct attributes first to avoid unnecessary driver calls.
    If these don't resolve the dimension, it then tries to get the computed dimensions
    from the live DOM using get_computed_dimensions().
    """
    # Check inline style if provided.
    if tag.attrs and tag.has_attr("style"):
        style = tag["style"]
        style_props = {}
        for decl in style.split(";"):
            decl = decl.strip()
            if ":" in decl:
                prop, val = decl.split(":", 1)
                style_props[prop.strip().lower()] = val.strip().lower()
        for dimension in ("width", "height"):
            if dimension in style_props:
                try:
                    # Extract digits and the period to form a number.
                    numeric_val = float(
                        "".join(
                            c for c in style_props[dimension] if c.isdigit() or c == "."
                        )
                    )
                    if numeric_val == 0:
                        return True
                except Exception:
                    pass

    # Check for explicit width/height attributes.
    for attr in ("width", "height"):
        if tag.attrs and tag.has_attr(attr):
            try:
                if float(tag[attr]) == 0:
                    return True
            except Exception:
                pass

    # Fallback: if we can determine computed dimensions from Selenium.
    dims = get_computed_dimensions(tag)
    if dims is not None:
        width, height = dims
        if width == 0 or height == 0:
            return True

    return False


def minify_html_for_gpt_prompt(html_content):
    # Parse the HTML content
    soup = BeautifulSoup(html_content, "html.parser")

    # Find all elements with style attribute
    for tag in soup.find_all(True):
        try:
            if tag and (
                (
                    tag.attrs
                    and tag.has_attr("type")
                    and tag["type"].strip().lower() == "hidden"
                )
                or (
                    tag.attrs
                    and tag.has_attr("class")
                    and any(
                        cls.strip().lower() == "hidden" for cls in tag.get("class", [])
                    )
                )
                or (
                    tag.attrs
                    and tag.has_attr("style")
                    and (
                        tag["style"].strip().lower() == "hidden"
                        or "display:none" in tag["style"].replace(" ", "").lower()
                    )
                )
            ):
                tag.decompose()  # Remove element and its children
        except TypeError:
            pass

    # Remove script and style tags
    for script_or_style in soup(["script", "style"]):
        script_or_style.decompose()

    # Remove any element that appears to have zero width or height.
    for tag in soup.find_all(True):
        if has_zero_dimension(tag):
            try:
                tag_element = find_element_from_bs4_tag(tag)
                if tag_element and not has_visible_descendant(tag_element):
                    tag.decompose()
            except Exception:
                pass

    # Remove comments
    for comment in soup.findAll(text=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Extract relevant tags
    relevant_tags = [
        "a",
        "button",
        "form",
        "input",
        "select",
        "textarea",
        "iframe",
        "h1",
        "h2",
        "h3",
        "div",
        "span",
        "li",
        "ul",
        "ol",
        "svg",
        "table",
        "tr",
        "td",
        "th",
        "thead",
        "tbody",
        "tfoot",
        "i",
    ]

    # Remove all children from each SVG tag so that only the tag remains with its attributes
    for svg in soup.find_all("svg"):
        svg.clear()

    for tag in soup.find_all(True):
        # Remove unnecessary attributes from the tags
        for attr in list(tag.attrs):
            if attr not in [
                "id",
                "class",
                "href",
                "type",
                "name",
                "value",
                "display",
                "placeholder",
                "alt",
                "title",
                "role",
                "aria-label",
                "aria-labelledby",
                "aria-expanded",
                "data-automation-id",
                "data-id",
                "tabindex",
                "contenteditable",
                "aria-haspopup",
            ]:
                del tag[attr]

        # Check if the tag has no attributes
        if tag.name.lower() != "svg" and (
            (not tag.attrs) or (tag.name not in relevant_tags)
        ):
            # Check if the tag is empty or contains only whitespace
            if not tag.contents or all(
                isinstance(content, str) and content.strip() == ""
                for content in tag.contents
            ):
                tag.decompose()  # Remove the tag completely
                continue

            tag.unwrap()
            continue

        # TODO: Following logic needs to be tested and fixed if necessary
        character_limit = 750
        if tag.string and len(tag.string.strip()) > character_limit:
            # Trim the text and add ellipsis
            trimmed_text = tag.string.strip()[:character_limit]
            tag.string.replace_with(trimmed_text)

    # Return the prettified, filtered HTML
    return htmlmin.minify(str(soup), remove_empty_space=True)


def find_clickable_parent_xpath(element_xpath, original_text=None):
    """Find the outermost clickable parent element that maintains the same text content.

    Args:
        element_xpath: XPath of the starting element
        original_text: Text content that must be preserved in parent elements

    Returns:
        XPath of the outermost clickable parent that maintains the same text
    """
    global driver

    element = driver.find_element(By.XPATH, element_xpath)

    if not original_text:
        original_text = element.text

    if not original_text:
        return element_xpath

    target_element = element
    parent = element

    while parent:
        try:
            # Check if parent element is clickable
            parent_width = driver.execute_script(
                "return arguments[0].offsetWidth;", parent
            )
            parent_height = driver.execute_script(
                "return arguments[0].offsetHeight;", parent
            )
            if (
                parent.is_enabled()
                and parent.is_displayed()
                and (parent_height > 0)
                and (parent_width > 0)
            ):
                # Verify text hasn't changed
                if parent.text == original_text:
                    target_element = parent
                else:
                    break

            # Try next parent
            parent = parent.find_element(By.XPATH, "./..")
        except:
            break

    return get_element_xpath(target_element)


def is_stale(element):
    try:
        # Try accessing any attribute or method that triggers a reference check
        element.tag_name
        return False
    except StaleElementReferenceException:
        return True


def generalize_xpath_attributes(xpath: str) -> str:
    """
    Converts XPath expressions to use starts-with(), contains(), and XPath 1.0-compatible ends-with().
    """
    attr_value_pattern = re.compile(r'@([\w:-]+)\s*=\s*([\'"])(.*?)\2')

    def to_starts_with(attr, val):
        return f"starts-with(@{attr}, '{val}')"

    def to_contains(attr, val):
        return f"contains(@{attr}, '{val}')"

    def to_ends_with(attr, val):
        return f"substring(@{attr}, string-length(@{attr}) - string-length('{val}') + 1) = '{val}'"

    def convert_attribute_to_matchers(attr: str, value: str) -> str:
        # Split around digits
        parts = re.split(r"(\d+)", value)
        text_parts = [p for p in parts if not p.isdigit() and p]

        if not text_parts:
            return f"@{attr}='{value}'"  # fallback

        if len(text_parts) == 1 and len(parts) == 1:
            # entire string, no digits
            return f"{to_starts_with(attr, value)} and {to_ends_with(attr, value)}"

        matchers = []
        for i, part in enumerate(parts):
            if part.isdigit() or not part.strip():
                continue

            if i == 0:
                matchers.append(to_starts_with(attr, part))
            elif i == len(parts) - 1:
                matchers.append(to_ends_with(attr, part))
            else:
                matchers.append(to_contains(attr, part))

        return " and ".join(matchers)

    def replace_bracket_content(match: re.Match) -> str:
        content = match.group(1)

        def attr_replacer(attr_match: re.Match) -> str:
            attr, _, val = attr_match.groups()
            return convert_attribute_to_matchers(attr, val)

        updated = attr_value_pattern.sub(attr_replacer, content)
        return f"[{updated}]"

    return re.sub(r"\[([^\[\]]+)\]", replace_bracket_content, xpath)


def has_visible_descendant(element):
    global driver

    return driver.execute_script(
        """
        const el = arguments[0];
        function hasVisibleDescendant(element) {
            if (!element || !element.children) return false;

            for (const child of element.children) {
                const style = window.getComputedStyle(child);
                const isVisible = (
                    style.display !== "none" &&
                    style.visibility !== "hidden" &&
                    child.offsetWidth > 0 &&
                    child.offsetHeight > 0
                );

                if (isVisible || hasVisibleDescendant(child)) {
                    return true;
                }
            }

            return false;
        }
        return hasVisibleDescendant(el);
    """,
        element,
    )


def generate_xpath(tag):
    """
    Generate an XPath expression for a BeautifulSoup tag.
    """
    path = []
    while tag and tag.name != "[document]":
        siblings = tag.find_previous_siblings(tag.name)
        index = len(siblings) + 1
        path.insert(0, f"{tag.name}[{index}]")
        tag = tag.parent
    return "/" + "/".join(path)


def find_element_from_bs4_tag(tag):
    """
    Tries to find the corresponding Selenium WebElement from a BeautifulSoup tag
    using a sequence of strategies: id, name, data-*, class, and guessed XPath.

    Parameters:
        tag: BeautifulSoup tag

    Returns:
        Selenium WebElement or None
    """
    global driver

    # 1. Try by ID
    if tag.has_attr("id"):
        try:
            return driver.find_element(By.ID, tag["id"])
        except NoSuchElementException:
            pass

    # 2. Try by Name
    if tag.has_attr("name"):
        try:
            return driver.find_element(By.NAME, tag["name"])
        except NoSuchElementException:
            pass

    # 3. Try by data-* attributes
    for attr in tag.attrs:
        if attr.startswith("data-"):
            try:
                selector = f'[{attr}="{tag[attr]}"]'
                return driver.find_element(By.CSS_SELECTOR, selector)
            except NoSuchElementException:
                continue

    # 4. Try by class (partial match)
    if tag.has_attr("class"):
        classes = tag["class"]
        for i in range(1, len(classes) + 1):
            selector = "." + ".".join(classes[:i])
            try:
                return driver.find_element(By.CSS_SELECTOR, f"{tag.name}{selector}")
            except NoSuchElementException:
                continue

    # 5. Try by guessed XPath (may fail if BS4 DOM doesn't match real DOM)
    guessed_xpath = generate_xpath(tag)
    try:
        return driver.find_element(By.XPATH, guessed_xpath)
    except Exception:
        pass

    # All strategies failed
    return None


def identify_options_container_type(element):
    """
    Identify the type of options container from a WebElement using its HTML structure.
    Returns one of: select-option, ul-li, ol-li, listbox-option, menu-menuitem, or None.
    """
    try:
        outer_html = element.get_attribute("outerHTML")
    except Exception:
        return None

    if not outer_html:
        return None

    if re.search(
        r"<select[^>]*>(?:\s*<option[^>]*>.*?</option>\s*)+</select>",
        outer_html,
        re.DOTALL | re.IGNORECASE,
    ):
        return "select-option"

    elif re.search(
        r"<ul[^>]*>(?:\s*<li[^>]*>.*?</li>\s*)+</ul>",
        outer_html,
        re.DOTALL | re.IGNORECASE,
    ):
        return "ul-li"

    elif re.search(
        r"<ol[^>]*>(?:\s*<li[^>]*>.*?</li>\s*)+</ol>",
        outer_html,
        re.DOTALL | re.IGNORECASE,
    ):
        return "ol-li"

    elif re.search(
        r'<(?P<outer_tag>\w+)[^>]*\srole=["\']listbox["\'][^>]*>'
        r'(?:.*?<\w+[^>]*\srole=["\']option["\'][^>]*>.*?</\w+>)+'
        r".*?</(?P=outer_tag)>",
        outer_html,
        re.DOTALL | re.IGNORECASE,
    ):
        return "listbox-option"

    elif re.search(
        r'<(?P<outer_tag>\w+)[^>]*\srole=["\']menu["\'][^>]*>'
        r'(?:.*?<\w+[^>]*\srole=["\']menuitem["\'][^>]*>.*?</\w+>)+'
        r".*?</(?P=outer_tag)>",
        outer_html,
        re.DOTALL | re.IGNORECASE,
    ):
        return "menu-menuitem"

    return None


def is_interactive_element(el):
    """Check if a WebElement is a user input element."""
    try:
        tag = el.tag_name.lower()
        INTERACTIVE_TAGS = {"input", "textarea", "select", "button"}
        if tag in INTERACTIVE_TAGS:
            return True

        if el.get_attribute("contenteditable") == "true":
            return True

        role = el.get_attribute("role")
        INTERACTIVE_ROLES = {
            "textbox",
            "combobox",
            "searchbox",
            "button",
            "listbox",
            "menu",
        }
        if role in INTERACTIVE_ROLES:
            return True

        tabindex = el.get_attribute("tabindex")
        if tabindex and tabindex.isdigit() and int(tabindex) >= 0:
            return True

        # Check dropdown-like patterns
        if identify_options_container_type(el):
            return True

        return False
    except Exception:
        return False


def find_first_interactive_descendant_excluding(base_el, exclude_el):
    try:
        all_descendants = base_el.find_elements(By.XPATH, ".//*")
        for el in all_descendants:
            # Exclude the subtree containing the title_element
            if exclude_el.id in [e.id for e in el.find_elements(By.XPATH, ".//*")]:
                continue
            if is_interactive_element(el):
                return el
    except Exception:
        pass
    return None


def find_input_block_for_title(title, max_levels: int = 4):
    """
    Traverse up the DOM from the title element (found by text) to find a parent
    that has an interactive input element either:
    - on the element itself
    - as a sibling
    - or in a common ancestor outside the title's own subtree
    """
    global driver

    title_xpath = get_xpath_by_text(title)
    if not title_xpath:
        return False, None

    title_element = driver.find_element(By.XPATH, title_xpath)

    # 1. Check if the title element itself is interactive
    if is_interactive_element(title_element):
        parent = title_element.find_element(By.XPATH, "..")
        return True, parent

    # 2. Check if any siblings are interactive
    parent = title_element.find_element(By.XPATH, "..")
    siblings = parent.find_elements(By.XPATH, "./*")
    for sib in siblings:
        if sib.id != title_element.id and is_interactive_element(sib):
            return True, parent

    # 3. Traverse upwards and search other descendant interactive inputs
    current = title_element
    for _ in range(max_levels):
        parent = current.find_element(By.XPATH, "..")

        interactive_input = find_first_interactive_descendant_excluding(
            parent, title_element
        )
        if interactive_input:
            return True, parent

        current = parent

    return False, current


def get_unique_element_by_xpath(xpath, title=None):
    """
    Returns a unique WebElement by its XPath.
    If multiple elements match, find the one that is at same level as given title.
    """
    global driver

    elements = driver.find_elements(By.XPATH, xpath)
    if len(elements) == 1:
        return elements[0]
    elif len(elements) > 1:
        if title:
            element_identified, user_input_element = find_input_block_for_title(title)
            if element_identified:
                element = user_input_element.find_elements(By.XPATH, f".{xpath}")
                if len(element) == 1:
                    return element[0]
                else:
                    logging.warning(
                        f"Multiple elements found for XPath '{xpath}' under title '{title}'."
                    )
                    return None
            else:
                logging.warning(
                    f"Multiple elements found for XPath '{xpath}' but no unique input block identified under title "
                    f"'{title}'."
                )
                return None
        else:
            logging.warning(
                f"Multiple elements found for XPath '{xpath}'. Returning first visible element."
            )
            for el in elements:
                if el.tag_name == "input":
                    return el
                elif is_element_visible(element=el):
                    return el

            logging.warning(
                f"None of the elements found for XPath '{xpath}' are visible."
            )
            return None
    else:
        logging.warning(f"No elements found for XPath '{xpath}'.")
        return None


def revoke_optional_permissions(url: str):
    """Revoke optional permissions (like geolocation, camera, etc.) for a given origin URL."""
    global driver

    driver.execute_cdp_cmd(
        "Browser.grantPermissions", {"origin": url, "permissions": []}
    )
