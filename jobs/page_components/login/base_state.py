from abc import ABC, abstractmethod
from typing import List, Optional
from jobs.page_components import PageComponent
from jobs.page_components.login.types import LoginStateType, STATE_MACHINE_TRANSITIONS


class LoginState(PageComponent, ABC):
    """Abstract base class for all login states implementing the state machine pattern"""

    def __init__(self, parent_application_page):
        self.parent_application_page = parent_application_page
        self.next = None
        self.prev = None
        self.is_component_functional = False
        self._current_state_type = None

    def _find_login_component(self):
        """Find the Login component instance from application page steps"""
        from jobs.page_components.login.login_class import Login

        current_step = self.parent_application_page.head_step
        while current_step:
            if isinstance(current_step, Login):
                return current_step
            current_step = current_step.next
        return None

    def _update_steps_if_first_time(self):
        """Call update_steps for Login component when state becomes functional for first time"""
        # Only call if this is the first time becoming functional (not from DB)
        if not self.is_component_functional:
            login_component = self._find_login_component()
            if login_component:
                from jobs.page_components import logger

                logger.info(
                    f"Updating Login component in application steps for job - "
                    f"{self.parent_application_page.parent_job.title}, url - {self.parent_application_page.url}"
                )
                self.parent_application_page.update_steps(
                    step=login_component, inplace=True
                )

    @property
    @abstractmethod
    def current_state_type(self) -> LoginStateType:
        """Return the type of this state"""
        pass

    def get_possible_next_states(self) -> List[LoginStateType]:
        """Get list of possible next states based on state machine rules"""
        return STATE_MACHINE_TRANSITIONS.get(self.current_state_type, [])

    def is_terminal_state(self) -> bool:
        """Check if this is a terminal state (no next states possible)"""
        return len(self.get_possible_next_states()) == 0

    @abstractmethod
    def identify_next_state(self) -> Optional[LoginStateType]:
        """
        Use GPT to identify the actual next state from HTML.
        Should return one of the possible next states from get_possible_next_states().
        Returns None if identification fails.
        """
        pass

    @abstractmethod
    def proceed(self, retry=False):
        """
        Execute this state's logic.
        For non-terminal states, should identify and prepare for next state transition.
        """
        pass

    @abstractmethod
    def to_dict(self):
        """Serialize state to dictionary for persistence"""
        pass

    @classmethod
    @abstractmethod
    def from_dict(cls, input_dict, parent_application_page):
        """Deserialize state from dictionary"""
        pass
