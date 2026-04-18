# Import types and constants first (no dependencies on other login modules)
from jobs.page_components.login.types import (
    LoginStateType,
    STATE_MACHINE_TRANSITIONS,
    START_STATE_PRIORITY,
)

# Import base state class (no dependencies on concrete state classes)
from jobs.page_components.login.base_state import LoginState

# Import all state classes for easy access (after base and types are imported)
from jobs.page_components.login.start_state import StartState
from jobs.page_components.login.sign_in_form_state import SignInFormState
from jobs.page_components.login.open_sign_in_form_button_state import (
    OpenSignInFormButtonState,
)
from jobs.page_components.login.account_creation_form_state import (
    AccountCreationFormState,
)
from jobs.page_components.login.open_account_creation_form_button_state import (
    OpenAccountCreationFormButtonState,
)
from jobs.page_components.login.account_doesnt_exist_state import (
    AccountDoesntExistState,
)
from jobs.page_components.login.account_already_exists_state import (
    AccountAlreadyExistsState,
)
from jobs.page_components.login.account_verification_state import (
    AccountVerificationState,
)
from jobs.page_components.login.logged_in_state import LoggedInState
from jobs.page_components.login.account_verification_failed_state import (
    AccountVerificationFailedState,
)
from jobs.page_components.login.confirmation_popup_state import ConfirmationPopupState

# Backward compatibility: VerifyAccount alias for AccountVerificationState
# Note: This maintains compatibility but AccountVerificationState should be used in new code
VerifyAccount = AccountVerificationState

# Import Login class last (after all state classes are defined)
from jobs.page_components.login.login_class import Login
