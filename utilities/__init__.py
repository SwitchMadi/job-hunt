import datetime
import shutil
import random
import string
import dotenv
import re
import time
import functools
import os
import base64
import hashlib
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend


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


def encrypt_string(data: str, mode: str = "fernet") -> str:
    if mode == "fernet":
        return _encrypt_fernet(data)
    elif mode == "aes":
        return _encrypt_aes(data)
    else:
        raise ValueError("Unsupported mode. Use 'fernet' or 'aes'")


def decrypt_string(data: str, mode: str = "fernet") -> str:
    if mode == "fernet":
        return _decrypt_fernet(data)
    elif mode == "aes":
        return _decrypt_aes(data)
    else:
        raise ValueError("Unsupported mode. Use 'fernet' or 'aes'")


# === Fernet encryption (default) ===


def _encrypt_fernet(data: str) -> str:
    cipher_suite = Fernet(_get_fernet_key())
    encrypted = cipher_suite.encrypt(data.encode("utf-8"))
    return encrypted.decode("utf-8")


def _decrypt_fernet(data: str) -> str:
    cipher_suite = Fernet(_get_fernet_key())
    decrypted = cipher_suite.decrypt(data.encode("utf-8"))
    return decrypted.decode("utf-8")


def _get_fernet_key():
    secret = os.getenv("ENCRYPTION_KEY")
    if not secret:
        raise ValueError("ENCRYPTION_KEY environment variable not set")

    try:
        # Try using as-is (base64 encoded)
        base64.urlsafe_b64decode(secret.encode())
        return secret.encode()
    except Exception:
        # Derive Fernet-compatible key from passphrase
        key = hashlib.sha256(secret.encode()).digest()
        return base64.urlsafe_b64encode(key)


# === AES (CryptoJS-compatible) ===


def _encrypt_aes(data: str) -> str:
    secret = os.getenv("ENCRYPTION_KEY")
    if not secret:
        raise ValueError("ENCRYPTION_KEY environment variable not set")

    key = hashlib.sha256(secret.encode()).digest()
    iv = os.urandom(16)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()

    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(data.encode()) + padder.finalize()

    ciphertext = encryptor.update(padded_data) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode()


def _decrypt_aes(data: str) -> str:
    secret = os.getenv("ENCRYPTION_KEY")
    if not secret:
        raise ValueError("ENCRYPTION_KEY environment variable not set")

    key = hashlib.sha256(secret.encode()).digest()
    encrypted_data = base64.b64decode(data)

    iv = encrypted_data[:16]
    ciphertext = encrypted_data[16:]

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()

    padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
    return plaintext.decode()


def str_to_bool(value: str) -> bool:
    return value.lower() in ("true", "1")


def pascal_to_snake_casing(name: str) -> str:
    # Insert an underscore before each uppercase letter (except at the beginning)
    s1 = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    return s1.lower()


def retry(times=3, delay=1, exceptions=(Exception,), raise_exception=True):
    from utilities.logging import get_logger

    logger = get_logger("utilities")

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    logger.exception(f"[{func.__name__}] Attempt {attempt} failed: {e}")
                    if attempt < times:
                        time.sleep(delay)
                    else:
                        if raise_exception:
                            raise
                        else:
                            logger.warning(
                                f"[{func.__name__}] All attempts failed. Returning..."
                            )
                            return

        return wrapper

    return decorator


def clean_text_edges(text: str) -> str:
    """
    Strip leading/trailing whitespace and any non-alphanumeric
    characters at the edges of the string, then trim again.
    """
    # 1. Initial whitespace trim (same as .trim() in JS)
    text = text.strip()

    # 2. Remove non-alphanumeric chars from start or end
    text = re.sub(r"^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$", "", text)

    # 3. Final whitespace trim in case step 2 exposed new spaces
    return text.strip()
