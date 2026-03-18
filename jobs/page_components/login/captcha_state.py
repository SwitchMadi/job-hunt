from jobs.page_components.login.base_state import LoginState
from jobs.page_components.login.types import LoginStateType
from jobs.page_components import logger


class CaptchaState(LoginState):
    """State when captcha is detected - raises exception"""

    @property
    def current_state_type(self) -> LoginStateType:
        return LoginStateType.CAPTCHA

    def proceed(self, retry=False):
        """Captcha detected - raise exception"""
        error_msg = (
            f"Captcha is present on login page for job {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}. Cannot proceed with automated login."
        )
        logger.error(error_msg)
        raise Exception(
            "Security is enabled on login (captcha detected), so skipping login!"
        )

    def identify_next_state(self):
        """No next state - raises exception"""
        return None

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(parent_application_page=parent_application_page)

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
