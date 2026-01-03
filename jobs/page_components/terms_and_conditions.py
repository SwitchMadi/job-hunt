from pydantic import BaseModel, Field
from enum import Enum

from jobs.page_components import (
    PageComponent,
    get_page_component_class_name,
    ApplicationField,
)
from utilities import constants
from utilities.llm import create_llm_service
from utilities.selenium import (
    get_selenium_driver,
    minify_html_for_gpt_prompt,
)

_llm_service = create_llm_service(provider="openai")

driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class TermsAndConditions(PageComponent):
    def __init__(self, parent_application_page):
        self.parent_application_page = parent_application_page

        self.tnc_fields = []
        self.field_component = None
        self.component_identified = False

        self.next = None
        self.prev = None
        self.is_component_functional = False

    def proceed(self, retry=False):
        if not self.component_identified:
            return self._identify()

        for tnc_field in self.tnc_fields:
            tnc_field.proceed()

    def _identify(self, retry=False):
        global driver

        user_prompt = (
            f"Following HTML is of job application webpage for {self.parent_application_page.parent_job.title}."
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"The webpage has one or more TnC or consent fields for applying to the job. Consent can be of different "
            f"types like privacy policy, terms of service, data processing related, marketing / promotional related etc. "
            f"Strictly ignore cookies consent popups for this assessment. "
            f"Analyse the whole HTML very carefully for extracting details of all TnC or consent fields to accept the "
            f"terms or give consent."
        )

        class FieldCategory(Enum):
            PRIVACY_POLICY_ACCEPTANCE = "privacy_policy_acceptance"
            TERMS_OF_SERVICE_AGREEMENT = "terms_of_service_agreement"
            DATA_PROCESSING_CONSENT = "data_processing_consent"
            MARKETING_EMAIL_OPT_IN = "marketing_email_opt_in"
            THIRD_PARTY_DATA_SHARING = "third_party_data_sharing"
            BACKGROUND_CHECK_AUTHORIZATION = "background_check_authorization"
            DEMOGRAPHIC_DATA_COLLECTION = "demographic_data_collection"
            INTERVIEW_RECORDING_CONSENT = "interview_recording_consent"
            AUTOMATED_SCREENING_CONSENT = "automated_screening_consent"

        class TnCFieldInfo(BaseModel):
            field_title: str = Field(
                ...,
                description="TnC or consent field's exact title / question mentioned on the webpage, without any "
                "modification whatsoever. Just pick what's in HTML and respond as it is, not matter how long it is.",
            )
            field_question: str = Field(
                ...,
                description="If TnC or consent title on its own is not self explanatory so modify it, so that it "
                "makes sense as a question. Otherwise respond same as field title.",
            )
            field_category: FieldCategory = Field(
                ...,
                description="Category of the TnC or consent field. It can be one of the following: "
                "privacy_policy_acceptance, terms_of_service_agreement, data_processing_consent, "
                "marketing_email_opt_in, third_party_data_sharing, background_check_authorization, "
                "cookie_consent, demographic_data_collection, interview_recording_consent, "
                "automated_screening_consent. Strictly ignore cookies consent popups for this assessment.",
            )

        class TnCFields(BaseModel):
            tnc_fields: list[TnCFieldInfo]

        tnc_field_found, tnc_fields = _llm_service.chat(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=TnCFields,
        )
        if tnc_field_found:
            for tnc_field in tnc_fields.tnc_fields:
                application_field = ApplicationField(
                    parent_application_page=self.parent_application_page,
                    title=tnc_field.field_title,
                    question=tnc_field.field_question,
                    category=tnc_field.field_category.value,
                )
                application_field_component = application_field.get_field_component()
                if application_field_component:
                    application_field_component.proceed()
                    if application_field_component.is_component_functional:
                        self.is_component_functional = True
                        self.component_identified = True
                        self.tnc_fields.append(application_field_component)
                    else:
                        raise Exception(
                            f"Couldn't proceed on one of the TnC fields with title {tnc_field.field_title} for "
                            f"job title {self.parent_application_page.parent_job.title}. "
                            f"URL - {self.parent_application_page.url}"
                        )
        else:
            raise Exception(
                f"Couldn't extract TnC field for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "tnc_fields": [field.to_dict() for field in self.tnc_fields],
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        instance = cls(
            parent_application_page=parent_application_page,
        )

        for field in input_dict["tnc_fields"]:
            field_component_class = get_page_component_class_name(
                class_name=field["class"]
            )
            field_component = field_component_class.from_dict(
                input_dict=field,
                parent_application_page=parent_application_page,
            )
            instance.tnc_fields.append(field_component)

        instance.component_identified = True

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
