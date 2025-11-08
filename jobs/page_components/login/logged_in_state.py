from jobs.page_components.login.base_state import LoginState
from jobs.page_components.login.types import LoginStateType
from jobs.page_components import logger


class LoggedInState(LoginState):
    """Terminal state indicating successful login"""

    @property
    def current_state_type(self) -> LoginStateType:
        return LoginStateType.LOGGED_IN

    def proceed(self, retry=False):
        """Logged in successfully - this is a terminal state"""
        logger.info(
            f"Successfully logged in for job {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}"
        )
        self._update_steps_if_first_time()
        self.is_component_functional = True
        # State machine will handle transition to End (next component)

    def identify_next_state(self):
        """Terminal state - no next state"""
        return None

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(parent_application_page=parent_application_page)
        instance.is_component_functional = True

        if input_dict.get("next"):
            from jobs.page_components import get_page_component_class_name

            next_class = get_page_component_class_name(
                class_name=input_dict["next"]["class"]
            )
            next_component = next_class.from_dict(
                input_dict["next"], parent_application_page
            )
            instance.next = next_component
            next_component.prev = instance

        return instance
