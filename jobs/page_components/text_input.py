from typing import Optional, List
from selenium.common import ElementNotInteractableException
from selenium.webdriver import Keys
import pyperclip
from selenium.webdriver.common.action_chains import ActionChains
from pydantic import BaseModel, Field

from jobs import ApplicationField
from jobs.page_components import PageComponent, logger, get_page_component_class_name
from utilities.selenium import (
    get_selenium_driver,
    clear_text_field,
    generalize_xpath_attributes,
    element_has_area,
    get_active_element_after_click,
    start_dom_mutation_observer,
    get_unique_element_by_xpath,
    element_exists,
    simulate_empty_area_click,
    is_element_in_popup,
    extract_element_value,
)
from utilities.gpt import get_gpt_response
from utilities import constants


class InputFormatExpectations(BaseModel):
    """Model to store detected input format expectations for a text field."""

    allows_numeric: bool = Field(
        default=True, description="Whether the field accepts numeric characters (0-9)"
    )
    allows_alpha: bool = Field(
        default=True,
        description="Whether the field accepts alphabetic characters (a-z, A-Z)",
    )
    allowed_special_characters: Optional[List[str]] = Field(
        default=None,
        description="List of special characters that are allowed. None means not tested or all allowed.",
    )
    disallowed_special_characters: Optional[List[str]] = Field(
        default=None,
        description="List of special characters that are explicitly disallowed.",
    )
    max_length: Optional[int] = Field(
        default=None,
        description="Maximum character length allowed. None means no limit detected.",
    )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "InputFormatExpectations":
        """Create instance from dictionary."""
        return cls(**data)


# Categories that should undergo input format validation
VALIDATE_INPUT_FORMAT_CATEGORIES = {
    "phone_country_code",
    "phone_number_without_country_code",
    "work_experience",
    "education",
    "cover_letter",
    "other",
}

# Patterns in category names that should trigger validation (for dynamic categories)
VALIDATE_INPUT_FORMAT_PATTERNS = {
    "work_experience__responsibilities__",
    "work_experience__achievements__",
    "work_experience__other__",
    "education__other__",
}


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class TextInput(PageComponent):
    def __init__(
        self,
        x_path,
        category,
        parent_application_page,
        title=None,
        question=None,
        hit_enter=False,
    ):
        global driver

        self.x_path = x_path
        self.title = title
        self.question = question
        self.category = category
        self.hit_enter = hit_enter
        self.parent_application_page = parent_application_page

        self._answer = None
        self.is_component_functional = False
        self.container_x_path = None
        self._input_format_expectations: Optional[InputFormatExpectations] = None

        self.next = None
        self.prev = None

    def proceed(
        self, retry=False, start_mutation_observer=False, skip_input_validation=False
    ):
        global driver

        answer_input_successful = False
        try:
            if (
                self.x_path.startswith("/")
                and not self.x_path.startswith("//")
                and not element_exists(self.x_path)
            ):
                self.x_path = "/" + self.x_path

            element = get_unique_element_by_xpath(
                self.x_path, self.title, container_xpath=self.container_x_path
            )
            if not element:
                logger.warning(
                    f"Element with XPath {self.x_path} not found. "
                    f"URL - {self.parent_application_page.url if self.parent_application_page else None}"
                )
                self.is_component_functional = False
                return

            if not element_has_area(element=element):
                logger.warn(
                    f"Element with XPath {self.x_path} not found. "
                    f"URL - {self.parent_application_page.url if self.parent_application_page else None} "
                    f"Retrying with generalized XPath..."
                )
                self.x_path = generalize_xpath_attributes(self.x_path)
                element = get_unique_element_by_xpath(
                    self.x_path, self.title, container_xpath=self.container_x_path
                )

                if not element_has_area(element=element):
                    logger.warning(
                        f"Element has zero dimension in class TextInput's proceed method.\nTextInput instance - "
                        f"{vars(self)}"
                    )
                    self.is_component_functional = False
                    return answer_input_successful

            if not self.answer:
                return answer_input_successful

            # Input format validation and formatting (for non-special categories)
            if self._should_validate_input_format(
                skip_validation=skip_input_validation
            ):
                # Detect input format expectations if not already done
                if self._input_format_expectations is None:
                    self._input_format_expectations = (
                        self._detect_input_format_expectations()
                    )

                # Check if answer meets expectations and format if needed
                if not self._answer_meets_expectations(
                    self.answer, self._input_format_expectations
                ):
                    logger.info(
                        f"Answer for '{self.title}' doesn't meet input format expectations, reformatting..."
                    )
                    self._answer = self._format_answer(
                        self.answer, self._input_format_expectations
                    )

            if not self.category.endswith(("- month", "- day", "- year")):
                clear_text_field(
                    self.x_path, title=self.title, container_xpath=self.container_x_path
                )

            # Only click empty area if element is not in a popup and not a date sub-field
            if not is_element_in_popup(self.x_path) and not self.category.endswith(
                ("- month", "- day", "- year")
            ):
                simulate_empty_area_click(
                    text_to_click=self.title, container_xpath=self.container_x_path
                )

            if start_mutation_observer:
                start_dom_mutation_observer(timeout=1500)

            element = get_active_element_after_click(
                self.x_path, title=self.title, container_xpath=self.container_x_path
            )

            if self.category == "otp_textbox":
                for letter in str(self.answer):
                    active_element = driver.switch_to.active_element
                    active_element.send_keys(f"{letter}")

                answer_input_successful = True
            elif self.category == "date_field":
                pyperclip.copy(self.answer)

                ActionChains(driver).key_down(Keys.COMMAND).send_keys("v").key_up(
                    Keys.COMMAND
                ).perform()

                actual_value = element.get_attribute("value") or element.text or ""
                if not actual_value or (
                    not actual_value.strip().lower() in str(self.answer).strip().lower()
                ):
                    # Force set using JavaScript if value doesn't match
                    driver.execute_script(
                        "arguments[0].value = arguments[1]; "
                        "arguments[0].dispatchEvent(new Event('input', { bubbles: true })); "
                        "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
                        element,
                        str(self.answer),
                    )

                answer_input_successful = True
            else:
                try:
                    element.send_keys(self.answer)
                except ElementNotInteractableException:
                    logger.warn(
                        f"Element not interactable in class TextInput's proceed method.\n"
                        f"TextInput instance - {vars(self)}"
                    )
                    pass

                # Force check and set value if needed
                actual_value = element.get_attribute("value") or element.text or ""
                answer_input_successful = (
                    actual_value.strip().lower() == str(self.answer).strip().lower()
                )
                if not answer_input_successful and not self.category.endswith(
                    ("- month", "- day", "- year")
                ):
                    active_element = driver.switch_to.active_element
                    active_element.send_keys(self.answer)

                if not answer_input_successful:
                    # Force check and set value if needed
                    actual_value = element.get_attribute("value") or element.text or ""
                    answer_input_successful = (
                        actual_value.strip().lower() == str(self.answer).strip().lower()
                    )
                    if not answer_input_successful:
                        # Force set using JavaScript if value doesn't match
                        driver.execute_script(
                            "arguments[0].value = arguments[1]; "
                            "arguments[0].dispatchEvent(new Event('input', { bubbles: true })); "
                            "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
                            element,
                            str(self.answer),
                        )

            if self.hit_enter:
                element.send_keys(Keys.RETURN)

            # store the response
            if self.parent_application_page and (
                self.question
                or self.category in ["otp_textbox", "username", "password"]
            ):
                answer = self.answer
                if self.category in ["otp_textbox", "password"]:
                    answer = "*" * len(str(self.answer))

                question = self.question
                if self.category == "username":
                    question = "What is your username?"
                elif self.category == "password":
                    question = "What is your password?"
                elif self.category == "otp_textbox":
                    question = "What is the OTP?"

                self.parent_application_page.save_field_response(
                    question=question,
                    response=answer,
                )

            self.is_component_functional = True
        except Exception as e:
            logger.exception(
                f"Unexpected error occurred in class TextInput's proceed method.\nTextInput instance - {vars(self)}"
            )
            raise e

        return answer_input_successful

    def _should_validate_input_format(self, skip_validation: bool = False) -> bool:
        """
        Determine if input format validation should be performed for this field.

        Validation is performed only for specific categories:
        - Phone related fields (phone_country_code, phone_number_without_country_code)
        - Other (generic text fields)
        - Work experience: responsibilities, achievements, other
        - Education: other

        Args:
            skip_validation: If True, skip validation regardless of category.

        Returns:
            True if validation should be performed, False otherwise.
        """
        # Skip if explicitly requested
        if skip_validation:
            return False

        # Skip if no category
        if not self.category:
            return False

        # Check if category is in the explicit validation list
        if self.category in VALIDATE_INPUT_FORMAT_CATEGORIES:
            return True

        # Check if category matches any of the validation patterns (for dynamic categories)
        for pattern in VALIDATE_INPUT_FORMAT_PATTERNS:
            if pattern in self.category:
                return True

        # All other categories should not be validated
        return False

    def _detect_input_format_expectations(self) -> InputFormatExpectations:
        """
        Detect input format expectations by probing the text field with various inputs.

        Uses Selenium to send different types of characters and observe what the
        field accepts. No forced JavaScript value setting is used.

        Detection order:
        1. Numeric check
        2. Alpha check
        3. Length check (using allowed character types from steps 1-2)
        4. Special characters check in batches (only if alpha is acceptable)

        Returns:
            InputFormatExpectations object with detected constraints.
        """
        expectations = InputFormatExpectations()

        try:
            element = get_unique_element_by_xpath(
                self.x_path, self.title, container_xpath=self.container_x_path
            )
            if not element:
                logger.warning(
                    f"Could not find element for input format detection. XPath: {self.x_path}"
                )
                return expectations

            # Test 1: Check if numeric characters are allowed
            clear_text_field(
                self.x_path, title=self.title, container_xpath=self.container_x_path
            )
            test_numeric = "12345"
            element.send_keys(test_numeric)
            actual_value = extract_element_value(element) or ""
            # Check if any numeric chars were accepted
            numeric_accepted = any(c in actual_value for c in test_numeric)
            expectations.allows_numeric = numeric_accepted
            logger.debug(
                f"Numeric test: sent '{test_numeric}', got '{actual_value}', allows_numeric={numeric_accepted}"
            )

            # Test 2: Check if alphabetic characters are allowed
            clear_text_field(
                self.x_path, title=self.title, container_xpath=self.container_x_path
            )
            test_alpha = "abcde"
            element.send_keys(test_alpha)
            actual_value = extract_element_value(element) or ""
            # Check if any alpha chars were accepted
            alpha_accepted = any(c in actual_value.lower() for c in test_alpha)
            expectations.allows_alpha = alpha_accepted
            logger.debug(
                f"Alpha test: sent '{test_alpha}', got '{actual_value}', allows_alpha={alpha_accepted}"
            )

            # Test 3: Check max length using appropriate character type based on what's allowed
            clear_text_field(
                self.x_path, title=self.title, container_xpath=self.container_x_path
            )

            # Build test string based on what's allowed
            if expectations.allows_numeric and expectations.allows_alpha:
                # Both allowed: use alphanumeric
                test_long_string = "a1b2c3d4e5" * 50  # 500 chars total
            elif expectations.allows_numeric:
                # Only numeric: use numeric
                test_long_string = "1234567890" * 50  # 500 chars total
            elif expectations.allows_alpha:
                # Only alpha: use alpha
                test_long_string = "abcdefghij" * 50  # 500 chars total
            else:
                # Neither allowed: skip length test (field likely has other constraints)
                test_long_string = ""
                logger.debug("Neither numeric nor alpha allowed, skipping length test")

            if test_long_string:
                element.send_keys(test_long_string)
                actual_value = extract_element_value(element) or ""
                actual_length = len(actual_value)

                if actual_length < 500:
                    expectations.max_length = actual_length
                    logger.debug(f"Max length detected: {actual_length}")
                else:
                    logger.debug(
                        "No max length constraint detected (500+ chars accepted)"
                    )

            # Test 4: Check special characters in batches (only if alpha is acceptable)
            if expectations.allows_alpha:
                special_chars_to_test = "!@#$%^&*()-_=+[]{}|;:',.<>?/\\`~"
                allowed_special = []
                disallowed_special = []

                # Determine batch size based on max_length
                # If max_length is not detected, assume we can test all at once
                batch_size = len(special_chars_to_test)  # Default: test all at once
                if expectations.max_length is not None:
                    batch_size = expectations.max_length
                    logger.debug(
                        f"Max length ({expectations.max_length}) detected, testing special chars in batches of {batch_size}"
                    )

                # Split special characters into batches
                num_batches = (
                    len(special_chars_to_test) + batch_size - 1
                ) // batch_size
                logger.debug(
                    f"Testing {len(special_chars_to_test)} special chars in {num_batches} batch(es)"
                )

                # Test each batch
                for batch_idx in range(num_batches):
                    start_idx = batch_idx * batch_size
                    end_idx = min(start_idx + batch_size, len(special_chars_to_test))
                    batch_chars = special_chars_to_test[start_idx:end_idx]

                    clear_text_field(
                        self.x_path,
                        title=self.title,
                        container_xpath=self.container_x_path,
                    )

                    # Send the batch of special characters
                    element.send_keys(batch_chars)
                    actual_value = extract_element_value(element) or ""

                    # Check which characters from this batch were accepted
                    for char in batch_chars:
                        if char in actual_value:
                            allowed_special.append(char)
                        else:
                            disallowed_special.append(char)

                    logger.debug(
                        f"Special chars batch {batch_idx + 1}/{num_batches}: "
                        f"sent '{batch_chars}', received '{actual_value}', "
                        f"allowed={[c for c in batch_chars if c in actual_value]}, "
                        f"disallowed={[c for c in batch_chars if c not in actual_value]}"
                    )

                if allowed_special:
                    expectations.allowed_special_characters = allowed_special
                if disallowed_special:
                    expectations.disallowed_special_characters = disallowed_special

                logger.debug(
                    f"Special chars test complete: allowed={allowed_special}, disallowed={disallowed_special}"
                )
            else:
                logger.debug(
                    "Alpha not allowed, skipping special character test (fields that only accept numeric typically don't accept special chars)"
                )

            # Clean up: clear the field after detection
            clear_text_field(
                self.x_path, title=self.title, container_xpath=self.container_x_path
            )

            logger.info(
                f"Input format expectations detected for '{self.title}': "
                f"numeric={expectations.allows_numeric}, alpha={expectations.allows_alpha}, "
                f"max_length={expectations.max_length}, "
                f"allowed_special={len(expectations.allowed_special_characters or [])} chars, "
                f"disallowed_special={len(expectations.disallowed_special_characters or [])} chars"
            )

        except Exception as e:
            logger.exception(
                f"Error detecting input format expectations for '{self.title}': {e}"
            )

        return expectations

    def _answer_meets_expectations(
        self, answer: str, expectations: InputFormatExpectations
    ) -> bool:
        """
        Check if the answer meets the detected input format expectations.

        Args:
            answer: The answer string to validate.
            expectations: The detected input format expectations.

        Returns:
            True if the answer meets all expectations, False otherwise.
        """
        if not answer:
            return True

        answer_str = str(answer)

        # Check max length
        if (
            expectations.max_length is not None
            and len(answer_str) > expectations.max_length
        ):
            logger.debug(
                f"Answer exceeds max length: {len(answer_str)} > {expectations.max_length}"
            )
            return False

        # Check for disallowed characters
        has_numeric = any(c.isdigit() for c in answer_str)
        has_alpha = any(c.isalpha() for c in answer_str)

        # If answer has numeric but field doesn't allow numeric
        if has_numeric and not expectations.allows_numeric:
            logger.debug(
                "Answer contains numeric characters but field doesn't allow them"
            )
            return False

        # If answer has alpha but field doesn't allow alpha
        if has_alpha and not expectations.allows_alpha:
            logger.debug(
                "Answer contains alphabetic characters but field doesn't allow them"
            )
            return False

        # Check special characters
        if expectations.disallowed_special_characters:
            for char in answer_str:
                if (
                    not char.isalnum()
                    and not char.isspace()
                    and char in expectations.disallowed_special_characters
                ):
                    logger.debug(
                        f"Answer contains disallowed special character: '{char}'"
                    )
                    return False

        return True

    def _format_answer(self, answer: str, expectations: InputFormatExpectations) -> str:
        """
        Format the answer to meet input format expectations using GPT.

        This method should only be called when the answer does not meet the
        detected input format expectations.

        Args:
            answer: The original answer string.
            expectations: The detected input format expectations.

        Returns:
            Formatted answer that meets the expectations, or original if formatting fails.
        """
        if not answer:
            return answer

        answer_str = str(answer)

        # Build constraint description for GPT
        constraints = []

        if not expectations.allows_numeric:
            constraints.append("NO numeric characters (0-9) are allowed")
        if not expectations.allows_alpha:
            constraints.append("NO alphabetic characters (a-z, A-Z) are allowed")

        if expectations.max_length is not None:
            constraints.append(
                f"Maximum length is {expectations.max_length} characters"
            )

        if expectations.disallowed_special_characters:
            disallowed_chars = "".join(expectations.disallowed_special_characters)
            constraints.append(
                f"The following special characters are NOT allowed: {disallowed_chars}"
            )

        if expectations.allowed_special_characters:
            allowed_chars = "".join(expectations.allowed_special_characters)
            constraints.append(
                f"The following special characters ARE allowed: {allowed_chars}"
            )

        if not constraints:
            # No constraints to apply
            return answer_str

        constraints_text = "\n".join(f"- {c}" for c in constraints)

        # Build context about the field
        field_context = f"Field title: {self.title}" if self.title else ""
        if self.question:
            field_context += f"\nQuestion: {self.question}"

        user_prompt = (
            f"I need to input the following answer into a text field, but it doesn't meet the field's "
            f"input format requirements.\n\n"
            f"Original answer: {answer_str}\n\n"
            f"{field_context}\n\n"
            f"The text field has the following input constraints:\n{constraints_text}\n\n"
            f"Please reformat the answer to meet these constraints while preserving as much of the "
            f"original meaning and information as possible. If the answer needs to be shortened, "
            f"prioritize keeping the most important information. If certain characters need to be "
            f"removed, try to replace them with allowed alternatives or simply remove them.\n\n"
            f"Return ONLY the reformatted answer text, nothing else."
        )

        class FormattedAnswer(BaseModel):
            formatted_answer: str = Field(
                ...,
                description="The reformatted answer that meets all the input constraints.",
            )

        try:
            format_success, result = get_gpt_response(
                constants.gpt["system_prompts"]["application_step_identification"],
                user_prompt,
                response_format=FormattedAnswer,
            )

            if format_success and result.formatted_answer:
                formatted = result.formatted_answer
                logger.info(
                    f"Answer reformatted for '{self.title}': "
                    f"'{answer_str[:50]}...' -> '{formatted[:50]}...'"
                )
                return formatted
            else:
                logger.warning(
                    f"GPT could not reformat answer for '{self.title}', using original"
                )
                return answer_str

        except Exception as e:
            logger.exception(f"Error formatting answer for '{self.title}': {e}")
            return answer_str

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "x_path": self.x_path,
            "category": self.category,
            "title": self.title,
            "question": self.question,
            "hit_enter": self.hit_enter,
            "container_x_path": self.container_x_path,
            "input_format_expectations": (
                self._input_format_expectations.to_dict()
                if self._input_format_expectations
                else None
            ),
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            x_path=input_dict["x_path"],
            category=input_dict["category"],
            title=input_dict["title"],
            question=input_dict["question"],
            hit_enter=input_dict["hit_enter"],
            parent_application_page=parent_application_page,
        )
        instance.container_x_path = input_dict.get("container_x_path")
        instance.is_component_functional = True

        # Restore input format expectations if previously detected
        if input_dict.get("input_format_expectations"):
            instance._input_format_expectations = InputFormatExpectations.from_dict(
                input_dict["input_format_expectations"]
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

    @property
    def answer(self):
        if self._answer is not None:
            return self._answer

        answer = ApplicationField.get_field_value(
            field_category=self.category,
            user=self.parent_application_page.parent_job.user,
        )
        if not answer:
            answer, _ = ApplicationField.extract_field_answer(
                job_title=self.parent_application_page.parent_job.title,
                job_url=self.parent_application_page.url,
                company_name=self.parent_application_page.parent_job.company,
                field_title=self.title or self.category,
                question=self.question,
                answer_type="text",
                parsed_resume=self.parent_application_page.parent_job.user.parsed_resume,
            )

        self._answer = answer
        return self._answer

    @answer.setter
    def answer(self, value):
        self._answer = value
