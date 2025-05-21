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
    get_observed_elements,
    minify_html_for_gpt_prompt,
    is_stale,
)
from utilities import constants
from utilities.gpt import get_gpt_response


driver = get_selenium_driver()
driver.set_page_load_timeout(15)


class WorkExperienceSection(PageComponent):
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

    def proceed(self, retry=False):
        curr_node = self.head

        user_work_ex = self.parent_application_page.parent_job.user.parsed_resume.get(
            "work_experience", []
        )
        for work_ex in user_work_ex:
            if curr_node is None:
                if not self.work_experience_fields:
                    curr_node = self._identify_work_experience_fields()
                else:
                    curr_node = self._extract_known_work_experience_fields_info()

            if curr_node and not isinstance(curr_node, WorkExperience):
                curr_node = self._add_another_work_ex(curr_node)

            if curr_node and isinstance(curr_node, WorkExperience):
                curr_node.work_ex_info = work_ex
                curr_node.proceed()
                curr_node = curr_node.next

        self.is_component_functional = True

        return

    @property
    def work_experience_fields(self):
        curr_node = self.head
        while curr_node:
            if isinstance(curr_node, WorkExperience):
                return curr_node.work_experience_fields

            curr_node = curr_node.next

        return []

    @property
    def identified_work_experiences_count(self):
        curr_node = self.head
        count = 0
        while curr_node:
            if isinstance(curr_node, WorkExperience):
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
            f"Updating new work experience fields in db for job - "
            f"{self.parent_application_page.parent_job.title}, url - {self.parent_application_page.url}"
        )
        self.parent_application_page.save_application_steps()

        return

    def _add_another_work_ex(self, curr_node):
        if curr_node.next is not None:
            curr_node.proceed()
            curr_node = curr_node.next
            return curr_node

        start_dom_mutation_observer()
        curr_node.proceed()
        observed_elements = get_observed_elements()

        if not self.work_experience_fields:
            curr_node = self._identify_work_experience_fields(observed_elements)
        else:
            curr_node = self._extract_known_work_experience_fields_info(
                observed_elements
            )

        return curr_node

    def _extract_known_work_experience_fields_info(self, observed_elements=None):
        global driver

        field_details_prompt = "\n\n".join(
            f"field_id - {i + 1}. field_title - {field.field_title} | field_category - {field.field_category}"
            for i, field in enumerate(self.work_experience_fields)
        )

        if observed_elements:
            observed_elements_html = "\n".join(
                f"{i + 1}. Element {i + 1} - {minify_html_for_gpt_prompt(el.get_attribute('outerHTML'))}"
                for i, el in enumerate(observed_elements)
                if not is_stale(el)
            )
            observed_elements_prompt = (
                "I clicked a button to add work experience. I am using javascript mutation observer to "
                "observe DOM changes. When I clicked the button, the observer observed that following "
                "elements were added or modified in the DOM -\n"
                f"{observed_elements_html}\n\n"
            )
        else:
            observed_elements_prompt = ""

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title} at a "
            f"company called {self.parent_application_page.parent_job.company}.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Current page has UI elements to add candidate's work experience. It has either 1st or both of the "
            f"following elements on the current page -\n"
            f"1. Empty fields to start adding work experience details like company, job title, responsibilities etc.\n"
            f"2. A button to start adding new work experiences.\n"
            f"I have already added {self.identified_work_experiences_count} work experiences and I am going to fill in "
            f"work experience number {self.identified_work_experiences_count + 1}. Give me XPath details about work "
            f"experience section number {self.identified_work_experiences_count + 1} only. There are following fields "
            f"to fill in -\n"
            f"{field_details_prompt}\n"
            f"{observed_elements_prompt}"
            f"Carefully analyse whole HTML and give XPath of the above fields along with add new experience button if "
            f"there is any. STRICTLY IGNORE all fields which are not related to candidate's work experience"
            f" section or sections which are already filled."
        )

        class ExperienceFieldInfo(BaseModel):
            field_id: int = Field(
                ...,
                description="field_id mentioned in the prompt",
            )
            field_x_path: str = Field(
                ...,
                description="XPath of the work experience field which can be used in selenium chrome driver to search "
                "the field. Don't use HTML hierarchy to construct XPath. XPath of the first field if there "
                "are many.",
            )

        class ExperienceSectionFields(BaseModel):
            add_experience_x_path: Optional[str] = Field(
                ..., description="XPath of button to add new work experience"
            )
            work_experience_fields: List[ExperienceFieldInfo] = Field(
                ...,
                description="Fields to start adding work experience details like company, job title, responsibilities "
                "etc.",
            )

        fields_found, fields = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=ExperienceSectionFields,
        )
        if fields_found:
            curr_node = None

            if fields.work_experience_fields:
                work_ex_fields = []
                for field in fields.work_experience_fields:
                    component = self.work_experience_fields[field.field_id - 1]
                    component.x_path = field.field_x_path

                    work_ex_fields.append(component)

                curr_node = WorkExperience(
                    work_experience_fields=work_ex_fields,
                    experience_no=self.identified_work_experiences_count + 1,
                    parent_application_page=self.parent_application_page,
                )
                self._update_nodes(curr_node)

            if fields.add_experience_x_path:
                add_experience_button = Button(
                    x_path=fields.add_experience_x_path,
                    button_type="add_another_work_experience",
                    parent_application_page=self.parent_application_page,
                )
                self._update_nodes(add_experience_button)

                if not curr_node:
                    curr_node = add_experience_button

            if curr_node:
                return curr_node

        logger.error(
            f"Couldn't extract new work experience fields for {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}"
        )
        return None

    def _identify_work_experience_fields(self, observed_elements=None):
        global driver

        if observed_elements:
            observed_elements_html = "\n".join(
                f"{i + 1}. Element {i + 1} - {minify_html_for_gpt_prompt(el.get_attribute('outerHTML'))}"
                for i, el in enumerate(observed_elements)
                if not is_stale(el)
            )

            observed_elements_prompt = (
                "I clicked a button to add work experience. I am using javascript mutation observer to "
                "observe DOM changes. When I clicked the button, the observer observed that following "
                "elements were added or modified in the DOM -\n"
                f"{observed_elements_html}\n\n"
            )
        else:
            observed_elements_prompt = ""

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title} at a "
            f"company called {self.parent_application_page.parent_job.company}.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Current page has UI elements to add candidate's work experience. It has either or both of the following "
            f"elements on the current page -\n"
            f"1. Fields to start adding work experience details like company, job title, responsibilities etc.\n"
            f"2. A button to start adding new work experiences.\n"
            f"{observed_elements_prompt}"
            f"Carefully analyse whole HTML and find out whether only one of the above two elements are present on the "
            f"page OR both are present. STRICTLY IGNORE all fields which are not related to candidate's work experience"
            f" section. Extract details of the elements present."
        )

        class FieldCategory(Enum):
            job_title = "job_title"
            company_name = "company_name"
            location = "location"
            start_date = "start_date"
            end_date = "end_date"
            responsibilities = "responsibilities"
            achievements = "achievements"
            experience_related_url = "experience_related_url"
            industry = "industry"
            employment_type = "employment_type"
            other = "other"

        class ExperienceFieldInfo(BaseModel):
            field_title: str = Field(
                ...,
                description="Work experience field's exact title / question mentioned on the webpage, without any "
                "modification.",
            )
            field_question: Optional[str] = Field(
                ...,
                description="If field title on its own is not self explanatory then modify it so that it makes sense as"
                " a question.",
            )
            field_category: FieldCategory = Field(
                ...,
                description="Work experience field category like job title, company name etc.",
            )

        class ExperienceSectionFields(BaseModel):
            add_experience_x_path: Optional[str] = Field(
                ..., description="XPath of button to add new work experience"
            )
            work_experience_fields: Optional[List[ExperienceFieldInfo]] = Field(
                ...,
                description="Fields to start adding work experience details like company, job title, responsibilities "
                "etc.",
            )

        fields_found, fields = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=ExperienceSectionFields,
        )
        if fields_found:
            curr_node = None

            if fields.work_experience_fields:
                work_ex_fields = []
                for field in fields.work_experience_fields:
                    application_field = ApplicationField(
                        parent_application_page=self.parent_application_page,
                        title=field.field_title,
                        question=field.field_question,
                        category=field.field_category.value,
                    )
                    application_field_component = (
                        application_field.get_field_component()
                    )
                    work_ex_fields.append(application_field_component)

                curr_node = WorkExperience(
                    work_experience_fields=work_ex_fields,
                    experience_no=self.identified_work_experiences_count + 1,
                    parent_application_page=self.parent_application_page,
                )
                self._update_nodes(curr_node)

            if fields.add_experience_x_path:
                add_experience_button = Button(
                    x_path=fields.add_experience_x_path,
                    button_type="add_another_work_experience",
                    parent_application_page=self.parent_application_page,
                )
                self._update_nodes(add_experience_button)

                if not curr_node:
                    curr_node = add_experience_button

            if curr_node:
                return curr_node

        logger.error(
            f"Couldn't extract work experience fields for {self.parent_application_page.parent_job.title}. "
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


class WorkExperience(PageComponent):
    def __init__(self, work_experience_fields, experience_no, parent_application_page):
        self.work_experience_fields = work_experience_fields
        self.experience_no = experience_no
        self.parent_application_page = parent_application_page

        self.work_ex_info = {}

        self.next = None
        self.prev = None

    def proceed(self, retry=False):
        for field in self.work_experience_fields:
            question_backup = field.question
            field.question = (
                f"{question_backup}\n"
                f"Above question should be answered for following work experience information -\n"
                f"{self.work_ex_info}"
            )

            category_backup = field.category
            field.category = f"work_experience__{category_backup}__{self.experience_no}"

            field.proceed()

            field.question = question_backup
            field.category = category_backup

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "work_experience_fields": [
                field.to_dict() for field in self.work_experience_fields
            ],
            "experience_no": self.experience_no,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        fields = []
        for field_input_dict in input_dict["work_experience_fields"]:
            field_class = get_page_component_class_name(
                class_name=field_input_dict["class"]
            )
            field = field_class.from_dict(field_input_dict, parent_application_page)
            fields.append(field)

        instance = cls(
            work_experience_fields=fields,
            experience_no=input_dict["experience_no"],
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
