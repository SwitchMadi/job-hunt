from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum

from jobs.page_components import (
    PageComponent,
    get_page_component_class_name,
    logger,
    ApplicationField,
)
from jobs.page_components.button import Button
from utilities.selenium import (
    get_selenium_driver,
    start_dom_mutation_observer,
    get_observed_element,
)
from utilities import minify_html_for_gpt_prompt, constants
from utilities.gpt import get_gpt_response


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class EducationSection(PageComponent):
    def __init__(
        self,
        parent_application_page,
        head=None,
    ):
        global driver
        self.parent_application_page = parent_application_page
        self.head = head

        self.is_component_functional = False
        self.head = self.tail = head

        if self.head:
            next_node = self.head.next
            while next_node:
                self.tail = next_node
                next_node = next_node.next

        self.next = None
        self.prev = None

    def proceed(self):
        curr_node = self.head

        user_education = self.parent_application_page.parent_job.user.parsed_resume.get(
            "education", []
        )
        for education in user_education:
            if curr_node is None:
                if not self.education_fields:
                    curr_node = self._identify_education_fields()
                else:
                    curr_node = self._extract_known_education_fields_info()

            if curr_node and not isinstance(curr_node, Education):
                curr_node = self._add_another_education_qualification(curr_node)

            if curr_node and isinstance(curr_node, Education):
                curr_node.education_info = education
                curr_node.proceed()
                curr_node = curr_node.next

        self.is_component_functional = True

        return

    @property
    def education_fields(self):
        curr_node = self.head
        while curr_node:
            if isinstance(curr_node, Education):
                return curr_node.education_fields

            curr_node = curr_node.next

        return []

    @property
    def identified_educations_count(self):
        curr_node = self.head
        count = 0
        while curr_node:
            if isinstance(curr_node, Education):
                count += 1

            curr_node = curr_node.next

        return count

    def _update_nodes(self, node):
        if self.head is None:
            self.head = node
            self.tail = node
        else:
            self.tail.next = node
            node.prev = self.tail
            self.tail = node

        logger.info(
            f"Updating new education fields in db for job - "
            f"{self.parent_application_page.parent_job.title}, url - {self.parent_application_page.url}"
        )
        self.parent_application_page.save_application_steps()

        return

    def _add_another_education_qualification(self, curr_node):
        if curr_node.next is not None:
            curr_node.proceed()
            curr_node = curr_node.next
            return curr_node

        start_dom_mutation_observer()
        curr_node.proceed()
        observed_elem = get_observed_element()

        if not self.education_fields:
            curr_node = self._identify_education_fields(observed_elem)
        else:
            curr_node = self._extract_known_education_fields_info(observed_elem)

        return curr_node

    def _extract_known_education_fields_info(self, observed_elem=None):
        global driver

        field_details_prompt = "\n\n".join(
            f"field_id - {i + 1}. field_title - {field.field_title} | field_category - {field.field_category}"
            for i, field in enumerate(self.education_fields)
        )

        if observed_elem:
            observed_element_prompt = (
                "I clicked a button to add education qualification details. I am using javascript mutation observer to "
                "observe DOM changes. When I clicked the button, the observer observed that following "
                "element was added to the DOM -\n"
                f"{observed_elem.get_attribute('outerHTML')}\n"
            )
        else:
            observed_element_prompt = ""

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title} at a "
            f"company called {self.parent_application_page.parent_job.company}.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Current page has UI elements to add candidate's education qualification. It has either 1st or both of "
            f"the following elements on the current page -\n"
            f"1. Empty fields to start adding education qualification details like college, degree etc.\n"
            f"2. A button to start adding new eduction qualification.\n"
            f"I have already added {self.identified_educations_count} education qualifications and I am going to fill "
            f"in education qualification number {self.identified_educations_count + 1}. Give me XPath details about "
            f"education qualification section number {self.identified_educations_count + 1} only. There are following "
            f"fields to fill in -\n"
            f"{field_details_prompt}\n"
            f"{observed_element_prompt}"
            f"Carefully analyse whole HTML and give XPath of the above fields along with add new education "
            f"qualification button if there is any. STRICTLY IGNORE all fields which are not related to candidate's "
            f"education qualification section or sections which are already filled."
        )

        class EducationFieldInfo(BaseModel):
            field_id: int = Field(
                ...,
                description="field_id mentioned in the prompt",
            )
            field_x_path: str = Field(
                ...,
                description="XPath of the education qualification field which can be used in selenium chrome driver to "
                "search the field. Don't use HTML hierarchy to construct XPath. XPath of the first field if"
                " there are many.",
            )

        class EducationSectionFields(BaseModel):
            add_education_x_path: Optional[str] = Field(
                ..., description="XPath of button to add new education qualification"
            )
            education_fields: List[EducationFieldInfo] = Field(
                ...,
                description="Fields to start adding education qualification details like college, degree etc.",
            )

        fields_found, fields = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=EducationSectionFields,
        )
        if fields_found:
            curr_node = None

            if fields.education_fields:
                education_fields = []
                for field in fields.education_fields:
                    component = self.education_fields[field.field_id - 1]
                    component.x_path = field.field_x_path

                    education_fields.append(component)

                curr_node = Education(
                    education_fields=education_fields,
                    education_no=self.identified_educations_count + 1,
                    parent_application_page=self.parent_application_page,
                )
                self._update_nodes(curr_node)

            if fields.add_education_x_path:
                add_education_qualification_button = Button(
                    x_path=fields.add_education_x_path,
                    button_type="add_another_education_qualification",
                    parent_application_page=self.parent_application_page,
                )
                self._update_nodes(add_education_qualification_button)

                if not curr_node:
                    curr_node = add_education_qualification_button

            if curr_node:
                return curr_node

        logger.error(
            f"Couldn't extract new education qualification fields for {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}"
        )
        return None

    def _identify_education_fields(self, observed_elem=None):
        global driver

        if observed_elem:
            observed_element_prompt = (
                "I clicked a button to add education qualification. I am using javascript mutation observer to "
                "observe DOM changes. When I clicked the button, the observer observed that following "
                "element was added to the DOM -\n"
                f"{observed_elem.get_attribute('outerHTML')}\n"
            )
        else:
            observed_element_prompt = ""

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title} at a "
            f"company called {self.parent_application_page.parent_job.company}.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Current page has UI elements to add candidate's education qualification. It has either or both of the "
            f"following elements on the current page -\n"
            f"1. Fields to start adding education qualification details like college, degree etc.\n"
            f"2. A button to start adding new education qualification.\n"
            f"{observed_element_prompt}"
            f"Carefully analyse whole HTML and find out whether only one of the above two elements are present on the "
            f"page OR both are present. STRICTLY IGNORE all fields which are not related to candidate's education "
            f"qualification section. Extract details of the elements present."
        )

        class FieldCategory(Enum):
            degree = "degree"
            field_of_study = "field_of_study"
            institution = "institution"
            location = "location"
            start_date = "start_date"
            end_date = "end_date"
            other = "other"

        class EducationFieldInfo(BaseModel):
            field_title: str = Field(
                ...,
                description="Education field's exact title / question mentioned on the webpage, without any "
                "modification.",
            )
            field_question: Optional[str] = Field(
                ...,
                description="If field title on its own is not self explanatory then modify it so that it makes sense as"
                " a question.",
            )
            field_category: FieldCategory = Field(
                ...,
                description="Education qualification field category like college, degree etc.",
            )

        class EducationSectionFields(BaseModel):
            add_education_x_path: Optional[str] = Field(
                ..., description="XPath of button to add new education qualification"
            )
            education_fields: Optional[List[EducationFieldInfo]] = Field(
                ...,
                description="Fields to start adding education qualification details like college, degree etc.",
            )

        fields_found, fields = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=EducationSectionFields,
        )
        if fields_found:
            curr_node = None

            if fields.education_fields:
                education_fields = []
                for field in fields.education_fields:
                    application_field = ApplicationField(
                        parent_application_page=self.parent_application_page,
                        title=field.field_title,
                        question=field.field_question,
                        category=field.field_category.value,
                    )
                    application_field_component = (
                        application_field.get_field_component()
                    )
                    education_fields.append(application_field_component)

                curr_node = Education(
                    education_fields=education_fields,
                    education_no=self.identified_educations_count + 1,
                    parent_application_page=self.parent_application_page,
                )
                self._update_nodes(curr_node)

            if fields.add_education_x_path:
                add_education_button = Button(
                    x_path=fields.add_education_x_path,
                    button_type="add_another_education_qualification",
                    parent_application_page=self.parent_application_page,
                )
                self._update_nodes(add_education_button)

                if not curr_node:
                    curr_node = add_education_button

            if curr_node:
                return curr_node

        logger.error(
            f"Couldn't extract education fields for {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}"
        )
        return None

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "head": self.head.to_dict(),
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        head_class = get_page_component_class_name(
            class_name=input_dict["head"]["class"]
        )
        head = head_class.from_dict(input_dict["head"], parent_application_page)

        instance = cls(
            head=head,
            parent_application_page=parent_application_page,
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


class Education(PageComponent):
    def __init__(self, education_fields, education_no, parent_application_page):
        self.education_fields = education_fields
        self.education_no = education_no
        self.parent_application_page = parent_application_page

        self.education_info = {}

        self.next = None
        self.prev = None

    def proceed(self):
        for field in self.education_fields:
            question_backup = field.question
            field.question = (
                f"{question_backup}\n"
                f"Above question should be answered for following education information -\n"
                f"{self.education_info}"
            )

            category_backup = field.category
            field.category = f"{category_backup}__{self.education_no}"

            field.proceed()

            field.question = question_backup
            field.category = category_backup

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "education_fields": [field.to_dict() for field in self.education_fields],
            "education_no": self.education_no,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        fields = []
        for field_input_dict in input_dict["education_fields"]:
            field_class = get_page_component_class_name(
                class_name=field_input_dict["class"]
            )
            field = field_class.from_dict(field_input_dict, parent_application_page)
            fields.append(field)

        instance = cls(
            education_fields=fields,
            education_no=input_dict["education_no"],
            parent_application_page=parent_application_page,
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
