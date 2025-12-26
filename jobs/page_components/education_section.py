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
from jobs.page_components.check_box import CheckBox
from utilities.selenium import (
    get_selenium_driver,
    start_dom_mutation_observer,
    get_observed_elements,
    minify_html_for_gpt_prompt,
    is_stale,
    element_exists,
    get_xpath_by_text,
)
from utilities import constants
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

    def proceed(self, retry=False):
        if not self.is_component_functional:
            (
                add_education_button_present,
                is_comprehensive,
                comprehensive_fields,
                non_comprehensive_fields,
            ) = self._analyze_section_structure()
            if non_comprehensive_fields:
                self._process_non_comprehensive_fields(non_comprehensive_fields)

            if not add_education_button_present and not is_comprehensive:
                return None

        curr_node = self.head

        user_education = self.parent_application_page.parent_job.user.parsed_resume.get(
            "education", []
        )
        if not user_education:
            logger.warn(
                f"No education information found in user resume for job - "
                f"{self.parent_application_page.parent_job.title}, url - {self.parent_application_page.url}"
            )
            return None

        # TODO: in future, we can support multiple education sections
        user_education = user_education[:1]  # limiting to only education section

        curr_education_index = 0
        while user_education and (curr_education_index < len(user_education)):
            if curr_node is None:
                if not self.education_fields:
                    curr_node = self._identify_education_fields()
                else:
                    curr_node = self._extract_known_education_fields_info()

            if curr_node and isinstance(curr_node, Education):
                curr_node.education_info = user_education[curr_education_index]
                curr_node.proceed()
                self.is_component_functional = True

                self._update_nodes(curr_node)

                curr_education_index += 1
                curr_node = curr_node.next

            if curr_node is None and curr_education_index < len(user_education):
                curr_node = self._identify_add_education_button()

            if curr_node and not isinstance(curr_node, Education):
                curr_node = self._add_another_education_qualification(curr_node)

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
        # Check if node with same education_no already exists to avoid duplicates
        if isinstance(node, Education):
            curr = self.head
            while curr:
                if (
                    isinstance(curr, Education)
                    and curr.education_no == node.education_no
                ):
                    logger.info(
                        f"Skipping duplicate education node with education_no={node.education_no} "
                        f"for job {self.parent_application_page.parent_job.title}"
                    )
                    return
                curr = curr.next

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
        # TODO : Uncomment this when we support multiple education sections
        # self.parent_application_page.update_steps(step=self, inplace=True)

        return

    def _add_another_education_qualification(self, curr_node):
        if curr_node.next is not None:
            curr_node.proceed()
            curr_node = curr_node.next
            return curr_node

        start_dom_mutation_observer()
        curr_node.proceed()
        observed_elements = get_observed_elements()

        self.is_component_functional = True
        self._update_nodes(curr_node)

        if not self.education_fields:
            curr_node = self._identify_education_fields(observed_elements)
        else:
            curr_node = self._extract_known_education_fields_info(observed_elements)

        return curr_node

    def _extract_known_education_fields_info(
        self, observed_elements=None, retry=False, prev_x_paths=None
    ):
        global driver

        field_details_prompts = []
        for i, field in enumerate(self.education_fields):
            field_title = None
            if hasattr(field, "title"):
                field_title = field.title
            elif hasattr(field, "field_title"):
                field_title = field.field_title

            field_category = "education"
            if hasattr(field, "category"):
                field_category = field.category
            elif hasattr(field, "field_category"):
                field_category = field.field_category

            field_details_prompts.append(
                f"field_id - {i + 1}. field_title - {field_title} | field_category - {field_category}"
            )

        field_details_prompt = "\n\n".join(field_details_prompts)

        if observed_elements:
            observed_elements_html = "\n".join(
                f"{i + 1}. Element {i + 1} - {minify_html_for_gpt_prompt(el.get_attribute('outerHTML'))}"
                for i, el in enumerate(observed_elements)
                if not is_stale(el)
            )
            observed_elements_html = observed_elements_html.strip()
        else:
            observed_elements_html = ""

        if not observed_elements_html:
            user_prompt = (
                f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title} at a "
                f"company called {self.parent_application_page.parent_job.company}.\n"
                f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
                f"Current page has UI elements to add candidate's education qualification. It has either or all of "
                f"the following elements on the current page -\n"
                f"1. Empty fields to start adding education qualification details like college, degree etc.\n"
                f"2. A button to mark complete filling in current education qualification info. If 1st point is not valid "
                f"(meaning already fields to enter education qualification is not present) then this button will also not "
                f"be present.\n\n"
                f"I have already added {self.identified_educations_count} education qualifications and I am going to fill "
                f"in education qualification number {self.identified_educations_count + 1}. Give me XPath details about "
                f"education qualification section number {self.identified_educations_count + 1} only. There are following "
                f"fields to fill in -\n"
                f"{field_details_prompt}\n\n"
                f"Carefully analyse whole HTML and give XPath of the above fields along with mark complete current education "
                f"qualification button if there is any.\n"
                f"1. STRICTLY IGNORE all fields which are not related to candidate's "
                f"education qualification section and not belonging to education qualification section number "
                f"{self.identified_educations_count + 1}."
            )
        else:
            user_prompt = (
                f"There is a job application webpage for {self.parent_application_page.parent_job.title} at a "
                f"company called {self.parent_application_page.parent_job.company}.\n"
                "I clicked a button to add education qualification details. I am using javascript mutation observer to "
                "observe DOM changes. When I clicked the button, the observer observed that following "
                "elements were added or modified in the DOM -\n"
                f"{observed_elements_html}\n\n"
                f"Out of these observed elements, assess which observed element is strictly having interactive "
                f"education qualification fields and then you MUST make all the decisions based on that observed "
                f"element only which is strictly having the interactive education qualification fields."
                f"The relevant observed element has either or all of "
                f"the following elements on the current page -\n"
                f"1. Empty fields to start adding education qualification details like college, degree etc.\n"
                f"2. A button to mark complete filling in current education qualification info. If 1st point is not valid "
                f"(meaning already fields to enter education qualification is not present) then this button will also not "
                f"be present.\n\n"
                f"I have already added {self.identified_educations_count} education qualifications and I am going to fill "
                f"in education qualification number {self.identified_educations_count + 1}. There are following "
                f"fields to fill in -\n"
                f"{field_details_prompt}\n\n"
                f"Carefully analyse whole HTML and give XPath of the above fields along with mark complete current education "
                f"qualification button if there is any.\n"
                f"1. STRICTLY IGNORE all fields which are not related to candidate's "
                f"education qualification section and not belonging to education qualification section number "
                f"{self.identified_educations_count + 1}."
                f"2. STRICTLY answer all queries and extract all info only from relevant observed element and nothing else."
            )

        if retry and prev_x_paths:
            user_prompt += (
                f"\n\nIn previous GPT call, I got following x_paths which were not valid -\n"
                f"{', '.join(f'{key} - {value}' for key, value in prev_x_paths.items())}\n"
                f"Please retry and give valid x_paths for the fields mentioned above."
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

        if observed_elements_html:

            class EducationSectionFields(BaseModel):
                relevant_observed_element_number: int = Field(
                    ...,
                    description="Number of the observed element which is strictly having interactive education "
                    "qualification fields.",
                )
                education_container_x_path: str = Field(
                    ...,
                    description="XPath of the outer-most container element that contains ONLY the interactive "
                    "education qualification fields for the current education qualification section number mentioned in the prompt. "
                    "This should be stable and usable with selenium to scope subsequent field lookups.",
                )
                education_fields: List[EducationFieldInfo] = Field(
                    ...,
                    description="Fields to start adding education qualification details like college, degree etc.",
                )
                mark_complete_button_text: Optional[str] = Field(
                    ...,
                    description="Identify the text of the button that finalizes or saves the current education "
                    "qualification input. This button is typically labeled with terms like 'Done', 'Save', "
                    "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                    "finalization of education qualification input. It can also be a symbol like + etc. Focus on "
                    "buttons whose action logically concludes the process of entering education details. "
                    "It may or may not be present.",
                )
                mark_complete_button_x_path: Optional[str] = Field(
                    ...,
                    description="Identify the XPath of the button that finalizes or saves the current education "
                    "qualification input. This button is typically labeled with terms like 'Done', 'Save', "
                    "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                    "finalization of education qualification input. It can also be a symbol like + etc. Focus on "
                    "buttons whose action logically concludes the process of entering education details. "
                    "It may or may not be present.",
                )

        else:

            class EducationSectionFields(BaseModel):
                education_container_x_path: str = Field(
                    ...,
                    description="XPath of the outer-most container element that contains ONLY the interactive "
                    "education qualification fields for the current education qualification section number mentioned in the prompt. "
                    "This should be stable and usable with selenium to scope subsequent field lookups.",
                )
                education_fields: List[EducationFieldInfo] = Field(
                    ...,
                    description="Fields to start adding education qualification details like college, degree etc.",
                )
                mark_complete_button_text: Optional[str] = Field(
                    ...,
                    description="Identify the text of the button that finalizes or saves the current education "
                    "qualification input. This button is typically labeled with terms like 'Done', 'Save', "
                    "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                    "finalization of education qualification input. It can also be a symbol like + etc. Focus on "
                    "buttons whose action logically concludes the process of entering education details. "
                    "It may or may not be present.",
                )
                mark_complete_button_x_path: Optional[str] = Field(
                    ...,
                    description="Identify the XPath of the button that finalizes or saves the current education "
                    "qualification input. This button is typically labeled with terms like 'Done', 'Save', "
                    "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                    "finalization of education qualification input. It can also be a symbol like + etc. Focus on "
                    "buttons whose action logically concludes the process of entering education details. "
                    "It may or may not be present.",
                )

        fields_found, fields = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=EducationSectionFields,
            model="intermediate",
        )
        if fields_found:
            curr_node = None

            if fields.education_fields:
                invalid_x_paths = {}
                if not element_exists(fields.education_container_x_path):
                    invalid_x_paths["education_container_x_path"] = (
                        fields.education_container_x_path
                    )
                if fields.mark_complete_button_x_path and not element_exists(
                    fields.mark_complete_button_x_path
                ):
                    invalid_x_paths["mark_complete_button_x_path"] = (
                        fields.mark_complete_button_x_path
                    )

                if invalid_x_paths and not retry:
                    # retry if we have invalid x_paths
                    return self._extract_known_education_fields_info(
                        observed_elements=observed_elements,
                        retry=True,
                        prev_x_paths=invalid_x_paths,
                    )

                education_fields = []
                for field in fields.education_fields:
                    component = self.education_fields[field.field_id - 1]
                    component.x_path = field.field_x_path

                    education_fields.append(component)

                if fields.mark_complete_button_x_path and isinstance(self.head, Button):
                    mark_complete_education_button = Button(
                        x_path=fields.mark_complete_button_x_path,
                        button_type="mark_complete_current_education",
                        parent_application_page=self.parent_application_page,
                    )
                else:
                    mark_complete_education_button = None

                curr_node = Education(
                    education_fields=education_fields,
                    save_button=mark_complete_education_button,
                    container_x_path=fields.education_container_x_path,
                    education_no=self.identified_educations_count + 1,
                    parent_application_page=self.parent_application_page,
                    refetch_fields=True,
                )

            if curr_node:
                return curr_node

        logger.error(
            f"Couldn't extract new education qualification fields for {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}"
        )
        return None

    def _identify_add_education_button(self, retry=False, prev_x_path=None):
        global driver

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title} at a "
            f"company called {self.parent_application_page.parent_job.company}.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Current page may or may not have a button to start adding new / another education qualification. "
            f"Carefully analyse whole HTML and give XPath of the above button if there is any."
        )

        if retry and prev_x_path:
            user_prompt += (
                f"\n\nIn previous GPT call, I got following x_path which was not valid -\n"
                f"add_new_education_x_path - {prev_x_path}\n"
                f"Please retry and give valid x_path for the button mentioned above."
            )

        class AddEducationButton(BaseModel):
            add_new_education_x_path: Optional[str] = Field(
                ...,
                description="XPath of button to add new / another education qualification.",
            )

        fields_found, fields = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=AddEducationButton,
            model="intermediate",
        )
        if fields_found:
            if fields.add_new_education_x_path:
                if not element_exists(fields.add_new_education_x_path):
                    if not retry:
                        # retry if we have invalid x_path
                        return self._identify_add_education_button(
                            retry=True, prev_x_path=prev_x_path
                        )
                    else:
                        logger.error(
                            f"Invalid x_path for add new education button - {fields.add_new_education_x_path}"
                        )
                        return None

                add_education_button = Button(
                    x_path=fields.add_new_education_x_path,
                    button_type="add_another_education_qualification",
                    parent_application_page=self.parent_application_page,
                )

                return add_education_button

        logger.warn(
            f"Couldn't extract add education button for {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}"
        )
        return None

    def _identify_education_fields(self, observed_elements=[]):
        global driver

        if observed_elements:
            observed_elements_html = "\n".join(
                f"{i + 1}. Observed element number {i + 1} - \n{minify_html_for_gpt_prompt(el.get_attribute('outerHTML'))}"
                for i, el in enumerate(observed_elements)
                if not is_stale(el)
            )
            observed_elements_html = observed_elements_html.strip()

            if observed_elements_html:
                observed_elements_prompt = (
                    "I clicked a button to add education qualification. I am using javascript mutation observer to "
                    "observe DOM changes. When I clicked the button, the observer observed that following "
                    "elements were added or modified in the DOM -\n"
                    f"{observed_elements_html}\n\n"
                    f"Out of these observed elements, assess which observed element is strictly having interactive "
                    f"education qualification fields and then you MUST make all the decisions based on that observed "
                    f"element only which is strictly having the interactive education qualification fields."
                )
            else:
                observed_elements_prompt = ""
        else:
            observed_elements_prompt = ""

        interactive_education_fields_visible = (
            self._are_interactive_education_fields_visible(observed_elements_prompt)
        )
        if interactive_education_fields_visible:
            user_prompt = (
                f"Following HTML is of a job application webpage for {self.parent_application_page.parent_job.title} at a "
                f"company called {self.parent_application_page.parent_job.company}.\n"
                f"HTML: {observed_elements_prompt if observed_elements_prompt else minify_html_for_gpt_prompt(driver.page_source)}\n"
                f"Current page has UI elements to add candidate's education qualification. It has either first or both or "
                f"none of the following elements on the current page -\n"
                f"1. Strictly interactive fields to fill education qualification details like college, degree, major etc. "
                f"This maybe possible that fields strictly related to education qualification are not present on the page, "
                f"in that case don't return any field details. Don't confuse yourself between personal and education "
                f"qualification fields. Ignore add new / another education button while evaluating this point.\n"
                f"2. A button to mark complete filling in current education qualification info. If 1st point is not valid "
                f"(meaning already fields to enter education qualification is not present) then this button will also not "
                f"be present.\n\n"
                f"Carefully analyse the {'relevant observed element' if observed_elements_prompt else 'whole HTML'} and find out "
                f"whether only first or all are present and visible.\n"
                f"1. STRICTLY IGNORE all fields which are not related to candidate's education qualification section.\n"
                f"{'2. STRICTLY answer all queries and extract all info only from relevant observed element and nothing else.' if observed_elements_prompt else ''}"
            )

            class FieldCategory(Enum):
                degree = "degree"
                field_of_study = "field_of_study"
                institution = "institution"
                location = "location"
                start_date = "start_date"
                end_date = "end_date"
                currently_studying_here = "currently_studying_here"
                other = "other"

            class EducationFieldInfo(BaseModel):
                field_title: str = Field(
                    ...,
                    description="Education field's exact title / question mentioned on the webpage, without any "
                    "modification.",
                )
                field_question: str = Field(
                    ...,
                    description="What is grammatically correct question, answering which will help process the field?",
                )
                field_category: FieldCategory = Field(
                    ...,
                    description="Education qualification field category like college, degree etc.",
                )

            if observed_elements_prompt:

                class EducationSectionFields(BaseModel):
                    relevant_observed_element_number: int = Field(
                        ...,
                        description="Number of the observed element which is strictly having interactive education "
                        "qualification fields.",
                    )
                    education_container_x_path: str = Field(
                        ...,
                        description="XPath of the outer-most container element that contains ONLY the interactive "
                        "education qualification fields. This should be stable and usable with selenium to scope subsequent "
                        "field lookups.",
                    )
                    education_fields: Optional[List[EducationFieldInfo]] = Field(
                        ...,
                        description="Strictly interactive & clearly visible fields to add education qualification details "
                        "like college, degree etc.",
                    )
                    mark_complete_button_text: Optional[str] = Field(
                        ...,
                        description="Identify the text of the button that finalizes or saves the current education "
                        "qualification input. This button is typically labeled with terms like 'Done', 'Save', "
                        "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                        "finalization of education qualification input. It can also be a symbol like + etc. Focus on "
                        "buttons whose action logically concludes the process of entering education details. "
                        "It may or may not be present. Don't confuse yourself with button to finish / submit "
                        "job application itself.",
                    )
                    mark_complete_button_x_path: Optional[str] = Field(
                        ...,
                        description="Identify the XPath of the button that finalizes or saves the current education "
                        "qualification input. This button is typically labeled with terms like 'Done', 'Save', "
                        "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                        "finalization of education qualification input. It can also be a symbol like + etc. Focus on "
                        "buttons whose action logically concludes the process of entering education details. "
                        "It may or may not be present. Don't confuse yourself with button to finish / submit "
                        "job application itself.",
                    )

            else:

                class EducationSectionFields(BaseModel):
                    education_container_x_path: str = Field(
                        ...,
                        description="XPath of the outer-most container element that contains ONLY the interactive "
                        "education qualification fields. This should be stable and usable with selenium to scope subsequent "
                        "field lookups.",
                    )
                    education_fields: Optional[List[EducationFieldInfo]] = Field(
                        ...,
                        description="Strictly interactive & clearly visible fields to add education qualification details "
                        "like college, degree etc.",
                    )
                    mark_complete_button_text: Optional[str] = Field(
                        ...,
                        description="Identify the text of the button that finalizes or saves the current education "
                        "qualification input. This button is typically labeled with terms like 'Done', 'Save', "
                        "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                        "finalization of education qualification input. It can also be a symbol like + etc. Focus on "
                        "buttons whose action logically concludes the process of entering education details. "
                        "It may or may not be present. Don't confuse yourself with button to finish / submit "
                        "job application itself.",
                    )
                    mark_complete_button_x_path: Optional[str] = Field(
                        ...,
                        description="Identify the XPath of the button that finalizes or saves the current education "
                        "qualification input. This button is typically labeled with terms like 'Done', 'Save', "
                        "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                        "finalization of education qualification input. It can also be a symbol like + etc. Focus on "
                        "buttons whose action logically concludes the process of entering education details. "
                        "It may or may not be present. Don't confuse yourself with button to finish / submit "
                        "job application itself.",
                    )

            fields_found, fields = get_gpt_response(
                constants.gpt["system_prompts"]["application_step_identification"],
                user_prompt,
                response_format=EducationSectionFields,
                model="intermediate",
            )
            if fields_found:
                curr_node = None

                if fields.education_fields:
                    if fields.mark_complete_button_x_path and not element_exists(
                        fields.mark_complete_button_x_path
                    ):
                        prompt = (
                            "The x_path that we are trying to extract is of mark complete button which is used to mark"
                            " current education qualification as complete."
                        )
                        container_x_path = (
                            fields.education_container_x_path
                            if fields.education_container_x_path
                            and element_exists(fields.education_container_x_path)
                            else None
                        )
                        fields.mark_complete_button_x_path = (
                            ApplicationField.extract_correct_x_path(
                                prev_x_path=fields.mark_complete_button_x_path,
                                prompt=prompt,
                                job_title=self.parent_application_page.parent_job.title,
                                job_url=self.parent_application_page.url,
                                container_x_path=container_x_path,
                            )
                        )
                        if not fields.mark_complete_button_x_path:
                            raise Exception(
                                "Couldn't extract valid x_path for mark complete button."
                            )
                    if not element_exists(fields.education_container_x_path):
                        # Best-effort correction of container x_path
                        prompt = (
                            "The x_path that we are trying to extract is of the container element that wraps the "
                            "interactive education qualification fields on the page."
                        )
                        fields.education_container_x_path = (
                            ApplicationField.extract_correct_x_path(
                                prev_x_path=fields.education_container_x_path,
                                prompt=prompt,
                                job_title=self.parent_application_page.parent_job.title,
                                job_url=self.parent_application_page.url,
                            )
                        )
                        if not fields.education_container_x_path:
                            raise Exception(
                                "Couldn't extract valid x_path for education container."
                            )

                    education_fields = []
                    for field in fields.education_fields:
                        if field.field_category.value in ["start_date", "end_date"]:
                            from jobs.page_components.date_field import DateField

                            application_field_component = DateField(
                                title=field.field_title,
                                question=field.field_question,
                                category=field.field_category.value,
                                parent_application_page=self.parent_application_page,
                                persist_context_fields=False,
                            )
                            application_field_component.container_x_path = (
                                fields.education_container_x_path
                            )
                        else:
                            application_field = ApplicationField(
                                parent_application_page=self.parent_application_page,
                                title=field.field_title,
                                question=field.field_question,
                                category=field.field_category.value,
                                container_x_path=fields.education_container_x_path,
                            )
                            application_field_component = (
                                application_field.get_field_component()
                            )

                        if application_field_component:
                            education_fields.append(application_field_component)

                    # Reorder fields to put currently_studying_here fields at the start
                    education_fields = sorted(
                        education_fields,
                        key=lambda f: f.category != "currently_studying_here",
                    )

                    if (
                        education_fields
                        and fields.mark_complete_button_x_path
                        and isinstance(self.head, Button)
                    ):
                        mark_complete_education_button = Button(
                            x_path=fields.mark_complete_button_x_path,
                            button_type="mark_complete_current_education",
                            parent_application_page=self.parent_application_page,
                        )
                    else:
                        mark_complete_education_button = None

                    if education_fields:
                        curr_node = Education(
                            education_fields=education_fields,
                            save_button=mark_complete_education_button,
                            container_x_path=fields.education_container_x_path,
                            education_no=self.identified_educations_count + 1,
                            parent_application_page=self.parent_application_page,
                            refetch_fields=True,
                        )

                return curr_node

        logger.warn(
            f"Couldn't extract education fields for {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}"
        )
        return None

    def _are_interactive_education_fields_visible(self, observed_elements_prompt):
        global driver

        user_prompt = (
            f"Following HTML of a job application webpage for {self.parent_application_page.parent_job.title} at a "
            f"company called {self.parent_application_page.parent_job.company}.\n"
            f"HTML: {observed_elements_prompt if observed_elements_prompt else minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Current HTML may have following UI elements -\n"
            f"1. Strictly interactive fields to fill education qualification details like college, degree, major etc. "
            f"This maybe possible that fields strictly related to education qualification are not present on the page, "
            f"in that case don't return any field details. Don't confuse yourself between personal and education "
            f"qualification fields. Ignore add new / another education button while evaluating this point.\n"
            f"Carefully analyse the whole HTML and find out "
            f"whether only first or all are present and visible.\n"
            f"1. STRICTLY IGNORE all fields which are not related to candidate's education qualification section.\n"
        )

        class EducationSectionInfo(BaseModel):
            interactive_education_fields_visible: bool = Field(
                ...,
                description="Determine whether interactive fields *strictly* related to education qualifications are currently "
                "**present and clearly visible** on the page.\n"
                "- **Strictly IGNORE** the presence of any add education qualification button.\n"
                "- Your assessment must be **based solely on the actual visibility of interactive educational input fields**, "
                "not on page instructions or labels.",
            )

        info_found, info = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=EducationSectionInfo,
            model="intermediate",
        )
        if info_found:
            return info.interactive_education_fields_visible
        else:
            return False

    def _extract_page_elements(self):
        """
        Private method to analyze all user input fields and buttons on the current page
        using GPT to determine education qualification relevance.

        Returns:
            tuple: (fields_analysis, buttons_analysis) where each is a list of dicts
                   containing element details and relevance flags
        """
        global driver

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title} at a "
            f"company called {self.parent_application_page.parent_job.company}.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Analyze this page and provide the following information:\n"
            f"1. List ALL user input fields (text inputs, dropdowns, textareas, date fields, etc.) - anything that is NOT a button\n"
            f"2. For each field, determine if it is related to education qualification or not\n"
            f"3. List ALL buttons on the page\n"
            f"4. For each button, determine if it is for adding new/another education qualification or not\n"
            f"Be thorough and include ALL interactive elements you can find."
        )

        class Fields(BaseModel):
            field_title: str = Field(
                ...,
                description="Exact field title/label as shown on the page, without any modification.",
            )
            is_education_qualification_related: bool = Field(
                ...,
                description="Boolean flag indicating whether this field is related to education qualification or not.",
            )

        class Buttons(BaseModel):
            button_text: str = Field(
                ...,
                description="Exact button text as shown on the page, without any modification.",
            )
            is_add_education_qualification_button: bool = Field(
                ...,
                description="Boolean flag indicating whether this button is for adding new/another education qualification or not.",
            )

        class PageElements(BaseModel):
            input_fields: List[Fields] = Field(
                ...,
                description="List of all user input fields found on the page (excluding buttons).",
            )
            buttons: List[Buttons] = Field(
                ..., description="List of all buttons found on the page."
            )

        analysis_found, analysis = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=PageElements,
            model="intermediate",
        )

        if analysis_found:
            fields_analysis = [
                {
                    "field_title": field.field_title,
                    "is_education_qualification_related": field.is_education_qualification_related,
                }
                for field in analysis.input_fields
            ]

            buttons_analysis = [
                {
                    "button_text": button.button_text,
                    "is_add_education_qualification_button": button.is_add_education_qualification_button,
                }
                for button in analysis.buttons
            ]

            return fields_analysis, buttons_analysis
        else:
            logger.error(
                f"Couldn't analyze page elements for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )
            return [], []

    def _analyze_education_qualification_fields_comprehensiveness(self, field_titles):
        """
        Private method to analyze education qualification related field titles to determine if they are
        comprehensive enough to gather specific education qualification details or just random questions.

        Args:
            field_titles (list): List of field title strings

        Returns:
            tuple: (is_comprehensive, field_analysis) where:
                   - is_comprehensive: bool indicating if fields are comprehensive
                   - field_analysis: list of dicts with field details and relevance flags
        """
        if not field_titles:
            return False, []

        # Create numbered list for GPT analysis
        field_titles_text = "\n".join(
            f"{i+1}. {title}" for i, title in enumerate(field_titles)
        )

        user_prompt = (
            f"Following are education qualification related fields from a job application webpage for "
            f"{self.parent_application_page.parent_job.title} at {self.parent_application_page.parent_job.company}.\n"
            f"Education Qualification Fields:\n{field_titles_text}\n\n"
            f"Analyze these fields and determine:\n"
            f"1. Whether these fields COLLECTIVELY are comprehensive enough to gather a candidate's "
            f"specific education qualification details in a thorough manner\n"
            f"2. For each individual field, whether it is genuinely intended to collect comprehensive "
            f"education qualification information or seems like a random/standalone question\n\n"
            f"IMPORTANT GUIDELINES FOR COMPREHENSIVENESS:\n"
            f"- Fields are considered COLLECTIVELY comprehensive if they together capture the core components "
            f"of an education qualification: (1) institution/college/university name, (2) academic focus "
            f"(degree type, major, field of study, or similar), and (3) time period (start/end dates, years attended, "
            f"graduation year, or similar temporal information). Additional fields that provide supplementary details "
            f"are bonuses but not required for comprehensiveness.\n"
            f"- For individual fields: A field is comprehensive if it's part of a structured education form that "
            f"collects multiple related pieces of information to build a complete education record, rather than a "
            f"standalone generic question that doesn't require detailed information.\n"
            f"- Time period fields can be represented in various formats (separate start/end dates, first/last year, "
            f"years attended, graduation date, etc.) - all are valid representations.\n"
            f"- When evaluating collective comprehensiveness, be GENEROUS - if the fields together allow building "
            f"a complete education entry with the three core components mentioned above, they should be considered "
            f"comprehensive even if some optional supplementary fields are missing.\n\n"
            f"Examples for reference (these are just illustrative examples, not an exhaustive list):\n"
            f"- COMPREHENSIVE: Multiple fields that together capture institution, academic focus, and time period "
            f"(e.g., fields asking for school name, degree/major, and dates/years together form a comprehensive set).\n"
            f"- NON-COMPREHENSIVE: Standalone questions that don't require detailed information (e.g., yes/no questions "
            f"about having a degree, single dropdowns asking only for highest education level without details, "
            f"questions that don't allow building a complete education record)."
        )

        class FieldComprehensiveness(BaseModel):
            field_number: int = Field(
                ...,
                description="Serial number of the field from the provided list (1-based index).",
            )
            is_comprehensive_education_qualification_field: bool = Field(
                ...,
                description="Boolean flag indicating whether this specific field is part of a structured "
                "education qualification form that collects multiple related pieces of information to build a "
                "complete education record, rather than a standalone generic question. Fields that are part of "
                "a comprehensive form should be marked as True, even if they don't capture complete information by themselves.",
            )
            reason_for_comprehensiveness: str = Field(
                ...,
                description="Reasoning for why this field is considered comprehensive or not.",
            )

        class EducationQualificationFieldsAnalysis(BaseModel):
            individual_field_analysis: List[FieldComprehensiveness] = Field(
                ...,
                description="Analysis of each individual field's comprehensiveness for education qualification collection. "
                "Return only the field numbers (1-based index) and boolean flags, not the full field titles.",
            )
            are_fields_collectively_comprehensive: bool = Field(
                ...,
                description="Boolean indicating whether all the fields together are comprehensive enough "
                "to gather a candidate's specific education qualification details. Return True if the fields "
                "collectively capture the core components: (1) institution/college/university name, "
                "(2) academic focus (degree type, major, field of study, or similar), and (3) time period "
                "(start/end dates, years attended, graduation year, or similar temporal information). "
                "Be generous - if these core components are present, return True even if optional "
                "supplementary fields are missing.",
            )
            reason_for_collective_comprehensiveness: str = Field(
                ...,
                description="Reasoning for why the fields are collectively considered comprehensive or not.",
            )

        analysis_found, analysis = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=EducationQualificationFieldsAnalysis,
            model="intermediate",
        )

        if analysis_found:
            # Create a mapping of field numbers to boolean flags
            field_flags = {}
            for field in analysis.individual_field_analysis:
                field_index = field.field_number - 1  # Convert to 0-based index
                if 0 <= field_index < len(field_titles):
                    field_flags[field_index] = (
                        field.is_comprehensive_education_qualification_field
                    )

            # Attach boolean flags to original field titles
            field_analysis = []
            for i, title in enumerate(field_titles):
                field_analysis.append(
                    {
                        "field_title": title,
                        "is_comprehensive_education_qualification_field": field_flags.get(
                            i, False
                        ),
                    }
                )

            return analysis.are_fields_collectively_comprehensive, field_analysis
        else:
            logger.error(
                f"Couldn't analyze education qualification fields comprehensiveness for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )
            return False, []

    def _analyze_section_structure(self):
        is_comprehensive = False
        comprehensive_fields = []
        non_comprehensive_fields = []

        fields, buttons = self._extract_page_elements()

        add_education_button_present = (
            True
            if [
                button
                for button in buttons
                if button["is_add_education_qualification_button"]
            ]
            else False
        )

        education_qualification_fields = [
            field["field_title"]
            for field in fields
            if field["is_education_qualification_related"]
        ]
        if education_qualification_fields:
            is_comprehensive, field_analysis = (
                self._analyze_education_qualification_fields_comprehensiveness(
                    education_qualification_fields
                )
            )

            comprehensive_fields = [
                field["field_title"]
                for field in field_analysis
                if field["is_comprehensive_education_qualification_field"]
            ]

            non_comprehensive_fields = [
                field["field_title"]
                for field in field_analysis
                if not field["is_comprehensive_education_qualification_field"]
            ]

        return (
            add_education_button_present,
            is_comprehensive,
            comprehensive_fields,
            non_comprehensive_fields,
        )

    def _process_non_comprehensive_fields(self, fields):
        for field in fields:
            application_field = ApplicationField(
                parent_application_page=self.parent_application_page,
                title=field,
                question=field,
                category="education",
            )
            application_field_component = application_field.get_field_component()
            if application_field_component:
                application_field_component.proceed()
                self.parent_application_page.update_steps(application_field_component)

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
    def __init__(
        self,
        education_fields,
        save_button,
        container_x_path,
        education_no,
        parent_application_page,
        refetch_fields=False,
    ):
        self.education_fields = education_fields
        self.save_button = save_button
        if not container_x_path:
            raise ValueError("Education.container_x_path is required")
        self.container_x_path = container_x_path
        self.education_no = education_no
        self.parent_application_page = parent_application_page
        self.refetch_fields = refetch_fields

        self.education_info = {}

        self.next = None
        self.prev = None

    def proceed(self, retry=False):
        # Fail fast if container is missing/stale
        if not element_exists(self.container_x_path):
            raise ValueError(
                f"Education container_x_path is missing or stale: {self.container_x_path} "
                f"for job {self.parent_application_page.parent_job.title} at url {self.parent_application_page.url}"
            )

        for field in self.education_fields:
            # Skip end_date field if currently_studying_here checkbox is checked and end_date element doesn't exist
            if field.category == "end_date":
                if self._should_skip_end_date_field(field):
                    logger.info(
                        f"Skipping end_date field '{field.title}' because currently_studying_here is checked "
                        f"and end_date element doesn't exist in DOM for job {self.parent_application_page.parent_job.title}"
                    )
                    continue

            self._process_field(field)

        if self.refetch_fields:
            additional_fields = self._refetch_fields()
            if additional_fields:
                logger.info(
                    f"Adding additional {len(additional_fields)} education fields to education "
                    f"section {self.education_no} for job {self.parent_application_page.parent_job.title} "
                    f"at url {self.parent_application_page.url}."
                )
                self.education_fields.extend(additional_fields)

                for field in additional_fields:
                    self._process_field(field)

        if self.save_button:
            self.save_button.container_x_path = self.container_x_path
            self.save_button.proceed()

    def _process_field(self, field):
        question_backup = field.question
        field.question = (
            f"{question_backup}\n"
            f"Above question should be answered for following education information -\n"
            f"{self.education_info}"
        )

        category_backup = field.category
        field.category = f"education__{category_backup}__{self.education_no}"

        field.proceed()

        field.question = question_backup
        field.category = category_backup

    def _should_skip_end_date_field(self, end_date_field):
        """
        Check if end_date field should be skipped based on currently_studying_here checkbox state.

        Returns True if:
        1. A currently_studying_here field exists
        2. It's a CheckBox type
        3. It's a boolean checkbox
        4. It's currently checked
        5. The end_date field element doesn't exist in DOM
        """
        # Find currently_studying_here field
        currently_studying_field = None
        for f in self.education_fields:
            if f.category == "currently_studying_here":
                currently_studying_field = f
                break

        if not currently_studying_field:
            return False

        # Check if it's a CheckBox
        if not isinstance(currently_studying_field, CheckBox):
            return False

        # Check if it's boolean type and is checked
        if not currently_studying_field.is_boolean:
            return False

        if not currently_studying_field.is_checked:
            return False

        # Check if end_date field element doesn't exist in DOM using its title
        if hasattr(end_date_field, "title") and end_date_field.title:
            if not get_xpath_by_text(
                end_date_field.title, container_xpath=self.container_x_path
            ):
                return True

        return False

    def _refetch_fields(self):
        """Fetch additional education fields that are not already present in existing education_fields"""
        global driver

        user_prompt = (
            f"Following HTML is of a job application webpage for {self.parent_application_page.parent_job.title} at a "
            f"company called {self.parent_application_page.parent_job.company}.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Current page has UI elements to add candidate's education qualification. I am currently working on "
            f"education qualification number {self.education_no}. If more than one education sections seem to be present on "
            f"the page, focus only on education qualification section number {self.education_no} and completely "
            f"ignore all other education sections. "
            f"Identify strictly interactive fields to fill education qualification "
            f"details like college, degree, major etc. Only return fields that are "
            f"clearly visible, interactive, and related to education qualifications.\n"
            f"1. STRICTLY IGNORE all fields which are not related to candidate's education qualification section. "
            f"If more than one education sections seem to be present, ignore fields not belonging to education "
            f"qualification section number {self.education_no}.\n"
        )

        from enum import Enum

        class FieldCategory(Enum):
            degree = "degree"
            field_of_study = "field_of_study"
            institution = "institution"
            location = "location"
            start_date = "start_date"
            end_date = "end_date"
            currently_studying_here = "currently_studying_here"
            other = "other"

        class EducationFieldInfo(BaseModel):
            field_title: str = Field(
                ...,
                description="Education field's exact title / question mentioned on the webpage, without any "
                "modification.",
            )
            field_question: str = Field(
                ...,
                description="What is grammatically correct question, answering which will help process the field?",
            )
            field_category: FieldCategory = Field(
                ...,
                description="Education qualification field category like college, degree etc.",
            )

        class EducationFields(BaseModel):
            education_fields: List[EducationFieldInfo] = Field(
                ...,
                description="Strictly interactive & clearly visible fields to add education qualification "
                "details like college, degree etc.",
            )

        fields_found, fields = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=EducationFields,
            model="intermediate",
        )

        additional_fields = []
        if fields_found and fields.education_fields:
            # Filter out any fields that might have duplicate titles by mistake
            filtered_fields = []
            existing_field_titles = [field.title for field in self.education_fields]
            for field in fields.education_fields:
                if field.field_title not in existing_field_titles:
                    filtered_fields.append(field)

            for field in filtered_fields:
                if field.field_category.value in ["start_date", "end_date"]:
                    from jobs.page_components.date_field import DateField

                    application_field_component = DateField(
                        title=field.field_title,
                        question=field.field_question,
                        category=field.field_category.value,
                        parent_application_page=self.parent_application_page,
                        persist_context_fields=False,
                    )
                    application_field_component.container_x_path = self.container_x_path
                else:
                    application_field = ApplicationField(
                        parent_application_page=self.parent_application_page,
                        title=field.field_title,
                        question=field.field_question,
                        category=field.field_category.value,
                        container_x_path=self.container_x_path,
                    )
                    application_field_component = (
                        application_field.get_field_component()
                    )

                if application_field_component:
                    additional_fields.append(application_field_component)

        # Reorder fields to put currently_studying_here fields at the start
        additional_fields = sorted(
            additional_fields,
            key=lambda f: f.category != "currently_studying_here",
        )

        return additional_fields

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "education_fields": [field.to_dict() for field in self.education_fields],
            "save_button": self.save_button.to_dict() if self.save_button else None,
            "container_x_path": self.container_x_path,
            "education_no": self.education_no,
            "next": self.next.to_dict() if self.next else None,
        }

    @classmethod
    def from_dict(cls, input_dict, parent_application_page):
        if not input_dict.get("container_x_path"):
            raise ValueError("Education.from_dict: missing required 'container_x_path'")
        container_x_path = input_dict.get("container_x_path")

        fields = []
        for field_input_dict in input_dict["education_fields"]:
            field_class = get_page_component_class_name(
                class_name=field_input_dict["class"]
            )
            field = field_class.from_dict(field_input_dict, parent_application_page)
            fields.append(field)

        save_button = None
        if input_dict["save_button"]:
            button_class = get_page_component_class_name(
                class_name=input_dict["save_button"]["class"]
            )
            save_button = button_class.from_dict(
                input_dict["save_button"], parent_application_page
            )

        instance = cls(
            education_fields=fields,
            save_button=save_button,
            container_x_path=container_x_path,
            education_no=input_dict["education_no"],
            parent_application_page=parent_application_page,
        )
        instance.is_component_functional = True

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
