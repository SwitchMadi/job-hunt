import time
from typing import Optional, Dict, TYPE_CHECKING
from jobs.page_components import PageComponent, logger, get_page_component_class_name

# Import directly from modules to avoid circular dependency with __init__.py
from jobs.page_components.login.start_state import StartState
from jobs.page_components.login.types import LoginStateType
from utilities.selenium import get_selenium_driver

if TYPE_CHECKING:
    from jobs.page_components.login.base_state import LoginState

_driver = get_selenium_driver()


class Login(PageComponent):
    """
    Login component orchestrator that manages state machine transitions.
    States are stored as attributes (dictionary) rather than strict chain to allow flexible flows.
    """

    # User-specific states that always re-evaluate next state (not from persistence)
    USER_SPECIFIC_STATES = {
        LoginStateType.SIGN_IN_FORM,
        LoginStateType.ACCOUNT_CREATION_FORM,
        LoginStateType.ACCOUNT_VERIFICATION,
    }

    def __init__(self, parent_application_page):
        self.parent_application_page = parent_application_page
        self.login_section_url = _driver.current_url

        # States stored as dictionary by type (one per type, reusable across users)
        self.states: Dict[LoginStateType, Optional["LoginState"]] = {}
        self.current_state: Optional["LoginState"] = None

        # Standard PageComponent attributes
        self.next = None
        self.prev = None
        self.is_component_functional = False

    def proceed(self, retry=False):
        """
        Orchestrate state machine flow.
        Starts with Start state and transitions through states until terminal state (LoggedIn).
        User-specific states always re-evaluate next state; others use persisted data if available.
        """
        try:
            # Initialize with Start state if not already started
            if (
                LoginStateType.START not in self.states
                or self.states[LoginStateType.START] is None
            ):
                self._initialize_with_start_state()

            # Process states until we reach terminal state
            current = (
                self.current_state
                if self.current_state
                else self.states[LoginStateType.START]
            )

            while current:
                logger.info(
                    f"Processing login state: {current.current_state_type.value} for job "
                    f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                )

                # Execute current state
                try:
                    current.proceed()
                except Exception as e:
                    # Check if it's a verification failure (expected exceptions)
                    if (
                        current.current_state_type
                        == LoginStateType.ACCOUNT_VERIFICATION_FAILED
                    ):
                        raise
                    else:
                        logger.exception(
                            f"Error in state {current.current_state_type.value}: {e}"
                        )
                        raise

                # Check if we reached terminal state
                if current.is_terminal_state():
                    if current.current_state_type == LoginStateType.LOGGED_IN:
                        logger.info(
                            f"Successfully completed login flow for job "
                            f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                        )
                        self.is_component_functional = True
                        return
                    # AccountVerificationFailed raises in proceed()
                    # If we get here, it means terminal state was reached but wasn't LoggedIn
                    break

                # Determine next state
                # User-specific states always re-evaluate, others use persisted next if available
                next_state = None
                if current.current_state_type in self.USER_SPECIFIC_STATES:
                    # User-specific: always re-evaluate next state
                    logger.info(
                        f"Re-evaluating next state for user-specific state {current.current_state_type.value}"
                    )
                    time.sleep(3)  # Wait for page to stabilize
                    next_state_type = current.identify_next_state()

                    if not next_state_type:
                        logger.error(
                            f"Could not identify next login state from {current.current_state_type.value} for "
                            f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                        )
                        raise Exception(
                            f"Failed to identify next login state from {current.current_state_type.value}"
                        )

                    # Validate and get/create next state
                    next_state = self._get_or_create_state(next_state_type, current)
                else:
                    # Non-user-specific: check if persisted next state exists
                    if current.next:
                        logger.info(
                            f"Using persisted next state {current.next.current_state_type.value} for "
                            f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                        )
                        next_state = current.next
                    else:
                        # No persisted next, identify on-the-go
                        time.sleep(3)  # Wait for page to stabilize
                        next_state_type = current.identify_next_state()

                        if not next_state_type:
                            logger.error(
                                f"Could not identify next login state from {current.current_state_type.value} for "
                                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                            )
                            raise Exception(
                                f"Failed to identify next login state from {current.current_state_type.value}"
                            )

                        # Validate and get/create next state
                        next_state = self._get_or_create_state(next_state_type, current)

                        # Persist the next state relationship for future use
                        current.next = next_state
                        next_state.prev = current

                if not next_state:
                    raise Exception(f"Failed to get/create state instance")

                # Move to next state for next iteration
                current = next_state
                self.current_state = next_state

        except Exception as e:
            logger.exception(
                f"Error in login flow for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}. Error: {e}"
            )
            raise

    def _initialize_with_start_state(self):
        """Initialize the state machine with Start state"""
        start_state = StartState(parent_application_page=self.parent_application_page)
        self.states[LoginStateType.START] = start_state
        self.current_state = start_state

    def _get_or_create_state(
        self, state_type: LoginStateType, previous_state: Optional["LoginState"] = None
    ):
        """
        Get existing state instance if available, otherwise create new one.
        Reuses states to preserve identified fields (XPaths, etc.) across different users.
        """
        # Check if state already exists in dictionary
        if state_type in self.states and self.states[state_type] is not None:
            existing_state = self.states[state_type]
            logger.info(
                f"Reusing existing state {state_type.value} for "
                f"{self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
            )
            return existing_state

        # Create new state instance
        state_class_map = {
            LoginStateType.START: "StartState",
            LoginStateType.SIGN_IN_FORM: "SignInFormState",
            LoginStateType.OPEN_SIGN_IN_FORM_BUTTON: "OpenSignInFormButtonState",
            LoginStateType.ACCOUNT_CREATION_FORM: "AccountCreationFormState",
            LoginStateType.OPEN_ACCOUNT_CREATION_FORM_BUTTON: "OpenAccountCreationFormButtonState",
            LoginStateType.ACCOUNT_DOESNT_EXIST: "AccountDoesntExistState",
            LoginStateType.ACCOUNT_ALREADY_EXISTS: "AccountAlreadyExistsState",
            LoginStateType.ACCOUNT_VERIFICATION: "AccountVerificationState",
            LoginStateType.LOGGED_IN: "LoggedInState",
            LoginStateType.ACCOUNT_VERIFICATION_FAILED: "AccountVerificationFailedState",
            LoginStateType.CONFIRMATION_POPUP: "ConfirmationPopupState",
        }

        class_name = state_class_map.get(state_type)
        if not class_name:
            logger.error(f"No state class mapped for {state_type.value}")
            return None

        try:
            state_class = get_page_component_class_name(class_name)
            new_state = state_class(
                parent_application_page=self.parent_application_page
            )

            # Validate next state is allowed by state machine
            if previous_state:
                possible_next_states = previous_state.get_possible_next_states()
                if state_type not in possible_next_states:
                    logger.error(
                        f"Invalid state transition: {previous_state.current_state_type.value} -> {state_type.value} "
                        f"for {self.parent_application_page.parent_job.title}. URL - {self.parent_application_page.url}"
                    )
                    raise Exception(
                        f"Invalid state transition: {previous_state.current_state_type.value} -> {state_type.value}. "
                        f"Allowed: {[s.value for s in possible_next_states]}"
                    )

            # Store in dictionary
            self.states[state_type] = new_state

            return new_state
        except Exception as e:
            logger.exception(f"Failed to create state instance {class_name}: {e}")
            return None

    def to_dict(self):
        """
        Serialize Login component with all states stored as dictionary.
        Only non-user-specific states save their next state relationship.
        """
        # Serialize all states in dictionary
        states_dict = {}
        for state_type, state in self.states.items():
            if state:
                # For user-specific states, don't persist next state relationship
                state_dict = state.to_dict()
                if state_type in self.USER_SPECIFIC_STATES:
                    # Remove next from user-specific states (will be re-evaluated)
                    state_dict.pop("next", None)
                states_dict[state_type.value] = state_dict

        return {
            "class": self.__class__.__name__,
            "login_section_url": self.login_section_url,
            "states": states_dict,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        """
        Deserialize Login component and rebuild states dictionary.
        Restores states and their relationships (only non-user-specific next states).
        """
        instance = cls(parent_application_page=parent_application_page)
        instance.login_section_url = input_dict.get(
            "login_section_url", _driver.current_url
        )
        instance.is_component_functional = True

        # Rebuild states dictionary
        if input_dict.get("states"):
            states_dict = input_dict["states"]

            # Store next state relationships to restore later (before deserializing states)
            next_state_relationships = {}

            # First pass: create all state instances (temporarily remove next to prevent duplicate deserialization)
            for state_type_str, state_dict in states_dict.items():
                try:
                    state_type = LoginStateType(state_type_str)

                    # Store next relationship if present (for non-user-specific states)
                    if state_type not in cls.USER_SPECIFIC_STATES and state_dict.get(
                        "next"
                    ):
                        next_state_relationships[state_type] = state_dict["next"]
                        # Temporarily remove next from dict to prevent state from deserializing it
                        state_dict_copy = state_dict.copy()
                        state_dict_copy.pop("next", None)
                    else:
                        state_dict_copy = state_dict

                    state_class = get_page_component_class_name(
                        class_name=state_dict_copy["class"]
                    )
                    state_instance = state_class.from_dict(
                        state_dict_copy, parent_application_page
                    )
                    instance.states[state_type] = state_instance
                except Exception as e:
                    logger.warning(f"Failed to restore state {state_type_str}: {e}")

            # Second pass: restore next state relationships (only for non-user-specific states)
            next_state_class_map = {
                "StartState": LoginStateType.START,
                "SignInFormState": LoginStateType.SIGN_IN_FORM,
                "OpenSignInFormButtonState": LoginStateType.OPEN_SIGN_IN_FORM_BUTTON,
                "AccountCreationFormState": LoginStateType.ACCOUNT_CREATION_FORM,
                "OpenAccountCreationFormButtonState": LoginStateType.OPEN_ACCOUNT_CREATION_FORM_BUTTON,
                "AccountDoesntExistState": LoginStateType.ACCOUNT_DOESNT_EXIST,
                "AccountAlreadyExistsState": LoginStateType.ACCOUNT_ALREADY_EXISTS,
                "AccountVerificationState": LoginStateType.ACCOUNT_VERIFICATION,
                "LoggedInState": LoginStateType.LOGGED_IN,
                "AccountVerificationFailedState": LoginStateType.ACCOUNT_VERIFICATION_FAILED,
                "ConfirmationPopupState": LoginStateType.CONFIRMATION_POPUP,
            }

            for state_type, next_state_dict in next_state_relationships.items():
                try:
                    state_instance = instance.states.get(state_type)
                    if state_instance and next_state_dict:
                        next_state_type = next_state_class_map.get(
                            next_state_dict.get("class")
                        )

                        if next_state_type and next_state_type in instance.states:
                            state_instance.next = instance.states[next_state_type]
                            instance.states[next_state_type].prev = state_instance
                except Exception as e:
                    logger.warning(
                        f"Failed to restore next state relationship for {state_type.value}: {e}"
                    )

            # Don't restore current_state - each new journey starts fresh from START state

        if input_dict.get("next"):
            next_class = get_page_component_class_name(
                class_name=input_dict["next"]["class"]
            )
            next_component = next_class.from_dict(
                input_dict["next"], parent_application_page
            )
            instance.next = next_component
            if next_component:
                next_component.prev = instance

        return instance
