from jobs.page_components.login.base_state import LoginState
from jobs.page_components.login.types import LoginStateType
from jobs.page_components import logger


class AccountVerificationFailedState(LoginState):
    """State when account verification fails - raises exception"""

    def __init__(self, parent_application_page, failure_reason=None):
        super().__init__(parent_application_page)
        self.failure_reason = failure_reason

    @property
    def current_state_type(self) -> LoginStateType:
        return LoginStateType.ACCOUNT_VERIFICATION_FAILED

    def proceed(self, retry=False):
        """Account verification failed - raise exception"""
        error_msg = (
            f"Account verification failed for job {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}"
        )
        if self.failure_reason:
            error_msg += f" Reason: {self.failure_reason}"
        logger.error(error_msg)
        raise Exception(error_msg)

    def identify_next_state(self):
        """No next state - raises exception"""
        return None

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "failure_reason": self.failure_reason,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            parent_application_page=parent_application_page,
            failure_reason=input_dict.get("failure_reason"),
        )

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
