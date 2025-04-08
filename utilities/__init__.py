import hashlib
import datetime
import shutil
import os
from bs4 import BeautifulSoup, Comment
import random
import string
from cryptography.fernet import Fernet
import dotenv
import re

from utilities.selenium import get_selenium_driver


dotenv.load_dotenv()


def generate_hash(input_string):
    hash_object = hashlib.sha256(input_string.encode())
    _hash = hash_object.hexdigest()

    return _hash


def time_ago_to_epoch(time_ago):
    # Get the current datetime
    now = datetime.datetime.now()

    # Split the input string to extract numbers and time units
    parts = time_ago.split()

    # Check if the format is correct (e.g., "2 hours ago")
    if len(parts) == 3 and parts[2] == "ago":
        try:
            value = int(parts[0])  # the 'X' in 'X hours ago'
            unit = parts[1]  # the 'hours' in 'X hours ago'

            # Calculate the time delta based on the unit
            if unit.startswith("second"):
                delta = datetime.timedelta(seconds=value)
            elif unit.startswith("minute"):
                delta = datetime.timedelta(minutes=value)
            elif unit.startswith("hour"):
                delta = datetime.timedelta(hours=value)
            elif unit.startswith("day"):
                delta = datetime.timedelta(days=value)
            elif unit.startswith("week"):
                delta = datetime.timedelta(weeks=value)
            elif unit.startswith("month"):
                delta = datetime.timedelta(days=value * 30)
            elif unit.startswith("year"):
                delta = datetime.timedelta(days=value * 365)
            else:
                return None  # Unsupported time unit

            # Calculate the past time
            past_time = now - delta

            # Return as Unix epoch time
            return int(past_time.timestamp())
        except ValueError:
            # In case of conversion errors
            return None
    else:
        return None


def zip_directory(source_dir, zip_file_path):
    """
    Zips the contents of the source directory and creates a zip file at the specified path.

    :param source_dir: Directory to be zipped.
    :param zip_file_path: Path where the zip file should be created.
    """
    shutil.make_archive(
        base_name=os.path.splitext(zip_file_path)[0], format="zip", root_dir=source_dir
    )


def unzip_directory(zip_file_path, extract_dir):
    """
    Unzips the contents of the zip file into the specified directory.

    :param zip_file_path: Path to the zip file.
    :param extract_dir: Directory where the contents should be extracted.
    """
    shutil.unpack_archive(zip_file_path, extract_dir)


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
            tag.decompose()

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
        "svg",
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
    return soup.prettify()


def generate_password():
    length = 12

    # Define the character sets
    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    special_characters = "!@#$%^&*"

    # Make sure the password contains at least one of each required character type
    password = [
        random.choice(uppercase),
        random.choice(lowercase),
        random.choice(digits),
        random.choice(
            string.ascii_letters
        ),  # At least one alphabetic character (uppercase or lowercase)
        random.choice(special_characters),
    ]

    # Fill the rest of the password length with random characters from all sets combined
    all_characters = uppercase + lowercase + digits + special_characters
    password += random.choices(all_characters, k=length - len(password))

    # Shuffle to ensure randomness
    random.shuffle(password)

    return "".join(password)


def encrypt_string(input_string):
    cipher_suite = Fernet(os.getenv("ENCRYPTION_KEY"))
    encoded_password = input_string.encode("utf-8")
    encrypted_password = cipher_suite.encrypt(encoded_password)
    return encrypted_password.decode("utf-8")


def decrypt_password(input_string):
    cipher_suite = Fernet(os.getenv("ENCRYPTION_KEY"))
    decoded_password = input_string.encode("utf-8")
    decrypted_password = cipher_suite.decrypt(decoded_password)
    return decrypted_password.decode("utf-8")


def str_to_bool(value: str) -> bool:
    return value.lower() in ("true", "1")


def pascal_to_snake_casing(name: str) -> str:
    # Insert an underscore before each uppercase letter (except at the beginning)
    s1 = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    return s1.lower()
