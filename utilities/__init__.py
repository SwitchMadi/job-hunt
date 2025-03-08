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


def minify_html_for_gpt_prompt(html_content):
    # Parse the HTML content
    soup = BeautifulSoup(html_content, "html.parser")

    # Find all elements with style attribute
    for tag in soup.find_all(style=True):
        try:
            if tag and tag.has_attr("style"):
                style = tag["style"].lower()
                if "display:none" in style.replace(" ", ""):
                    tag.decompose()  # Remove element and its children
        except TypeError:
            pass

    # Remove script and style tags
    for script_or_style in soup(["script", "style"]):
        script_or_style.decompose()

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
    ]

    for tag in soup.find_all(True):
        # Remove unnecessary attributes from the tags
        for attr in list(tag.attrs):
            if attr not in ["id", "class", "href", "type", "name", "value", "display"]:
                del tag[attr]

        # Check if the tag has no attributes
        if (not tag.attrs) or (tag.name not in relevant_tags):
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
