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
    element_exists,
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

        user_work_experience = (
            self.parent_application_page.parent_job.user.parsed_resume.get(
                "work_experience", []
            )
        )
        curr_work_experience_index = 0
        while user_work_experience and (
            curr_work_experience_index < len(user_work_experience)
        ):
            if curr_node is None:
                if not self.work_experience_fields:
                    resp = self._identify_work_experience_fields()

                    if isinstance(resp, list):
                        return resp
                    else:
                        curr_node = resp
                else:
                    curr_node = self._extract_known_work_experience_fields_info()

            if curr_node and isinstance(curr_node, WorkExperience):
                curr_node.work_experience_info = user_work_experience[
                    curr_work_experience_index
                ]
                curr_node.proceed()
                self.is_component_functional = True

                self._update_nodes(curr_node)

                curr_work_experience_index += 1
                curr_node = curr_node.next

            if curr_node is None:
                curr_node = self._identify_add_work_experience_button()

            if curr_node and not isinstance(curr_node, WorkExperience):
                curr_node = self._add_another_work_experience(curr_node)

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
        self.parent_application_page.update_steps(self, inplace=True)

        return

    def _add_another_work_experience(self, curr_node):
        if curr_node.next is not None:
            curr_node.proceed()
            curr_node = curr_node.next
            return curr_node

        start_dom_mutation_observer()
        curr_node.proceed()
        observed_elements = get_observed_elements()

        self.is_component_functional = True
        self._update_nodes(curr_node)

        if not self.work_experience_fields:
            curr_node = self._identify_work_experience_fields(observed_elements)
        else:
            curr_node = self._extract_known_work_experience_fields_info(
                observed_elements
            )

        return curr_node

    def _extract_known_work_experience_fields_info(
        self, observed_elements=None, retry=False, prev_x_paths=None
    ):
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
            observed_elements_html = observed_elements_html.strip()
        else:
            observed_elements_html = ""

        if not observed_elements_html:
            user_prompt = (
                f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title} at a "
                f"company called {self.parent_application_page.parent_job.company}.\n"
                f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
                f"Current page has UI elements to add candidate's work experience. It has either or all of "
                f"the following elements on the current page -\n"
                f"1. Empty fields to start adding work experience details like company, job title, responsibilities etc.\n"
                f"2. A button to mark complete filling in current work experience info. If 1st point is not valid "
                f"(meaning already fields to enter work experience is not present) then this button will also not "
                f"be present.\n\n"
                f"I have already added {self.identified_work_experiences_count} work experiences and I am going to fill "
                f"in work experience number {self.identified_work_experiences_count + 1}. Give me XPath details about "
                f"work experience section number {self.identified_work_experiences_count + 1} only. There are following "
                f"fields to fill in -\n"
                f"{field_details_prompt}\n\n"
                f"Carefully analyse whole HTML and give XPath of the above fields along with mark complete current work "
                f"experience button if there is any.\n"
                f"1. STRICTLY IGNORE all fields which are not related to candidate's "
                f"work experience section and not belonging to work experience section number "
                f"{self.identified_work_experiences_count + 1}."
            )
        else:
            user_prompt = (
                f"There is a job application webpage for {self.parent_application_page.parent_job.title} at a "
                f"company called {self.parent_application_page.parent_job.company}.\n"
                "I clicked a button to add work experience details. I am using javascript mutation observer to "
                "observe DOM changes. When I clicked the button, the observer observed that following "
                "elements were added or modified in the DOM -\n"
                f"{observed_elements_html}\n\n"
                f"Out of these observed elements, assess which observed element is strictly having interactive "
                f"work experience fields and then you MUST make all the decisions based on that observed "
                f"element only which is strictly having the interactive work experience fields."
                f"The relevant observed element has either or all of "
                f"the following elements on the current page -\n"
                f"1. Empty fields to start adding work experience details like company, job title, responsibilities etc.\n"
                f"2. A button to mark complete filling in current work experience info. If 1st point is not valid "
                f"(meaning already fields to enter work experience is not present) then this button will also not "
                f"be present.\n\n"
                f"I have already added {self.identified_work_experiences_count} work experiences and I am going to fill "
                f"in work experience number {self.identified_work_experiences_count + 1}. There are following "
                f"fields to fill in -\n"
                f"{field_details_prompt}\n\n"
                f"Carefully analyse whole HTML and give XPath of the above fields along with mark complete current work "
                f"experience button if there is any.\n"
                f"1. STRICTLY IGNORE all fields which are not related to candidate's "
                f"work experience section and not belonging to work experience section number "
                f"{self.identified_work_experiences_count + 1}."
                f"2. STRICTLY answer all queries and extract all info only from relevant observed element and nothing else."
            )

        if retry and prev_x_paths:
            user_prompt += (
                f"\n\nIn previous GPT call, I got following x_paths which were not valid -\n"
                f"{', '.join(f'{key} - {value}' for key, value in prev_x_paths.items())}\n"
                f"Please retry and give valid x_paths for the fields mentioned above."
            )

        class WorkExperienceFieldInfo(BaseModel):
            field_id: int = Field(
                ...,
                description="field_id mentioned in the prompt",
            )
            field_x_path: str = Field(
                ...,
                description="XPath of the work experience field which can be used in selenium chrome driver to "
                "search the field. Don't use HTML hierarchy to construct XPath. XPath of the first field if"
                " there are many.",
            )

        if observed_elements_html:

            class WorkExperienceSectionFields(BaseModel):
                relevant_observed_element_number: int = Field(
                    ...,
                    description="Number of the observed element which is strictly having interactive work "
                    "experience fields.",
                )
                work_experience_fields: List[WorkExperienceFieldInfo] = Field(
                    ...,
                    description="Fields to start adding work experience details like company, job title, responsibilities etc.",
                )
                mark_complete_button_text: Optional[str] = Field(
                    ...,
                    description="Identify the text of the button that finalizes or saves the current work "
                    "experience input. This button is typically labeled with terms like 'Done', 'Save', "
                    "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                    "finalization of work experience input. It can also be a symbol like + etc. Focus on "
                    "buttons whose action logically concludes the process of entering work experience details. "
                    "It may or may not be present.",
                )
                mark_complete_button_x_path: Optional[str] = Field(
                    ...,
                    description="Identify the XPath of the button that finalizes or saves the current work "
                    "experience input. This button is typically labeled with terms like 'Done', 'Save', "
                    "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                    "finalization of work experience input. It can also be a symbol like + etc. Focus on "
                    "buttons whose action logically concludes the process of entering work experience details. "
                    "It may or may not be present.",
                )

        else:

            class WorkExperienceSectionFields(BaseModel):
                work_experience_fields: List[WorkExperienceFieldInfo] = Field(
                    ...,
                    description="Fields to start adding work experience details like company, job title, responsibilities etc.",
                )
                mark_complete_button_text: Optional[str] = Field(
                    ...,
                    description="Identify the text of the button that finalizes or saves the current work "
                    "experience input. This button is typically labeled with terms like 'Done', 'Save', "
                    "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                    "finalization of work experience input. It can also be a symbol like + etc. Focus on "
                    "buttons whose action logically concludes the process of entering work experience details. "
                    "It may or may not be present.",
                )
                mark_complete_button_x_path: Optional[str] = Field(
                    ...,
                    description="Identify the XPath of the button that finalizes or saves the current work "
                    "experience input. This button is typically labeled with terms like 'Done', 'Save', "
                    "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                    "finalization of work experience input. It can also be a symbol like + etc. Focus on "
                    "buttons whose action logically concludes the process of entering work experience details. "
                    "It may or may not be present.",
                )

        fields_found, fields = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=WorkExperienceSectionFields,
        )
        if fields_found:
            curr_node = None

            if fields.work_experience_fields:
                invalid_x_paths = {}
                if fields.mark_complete_button_x_path and not element_exists(
                    fields.mark_complete_button_x_path
                ):
                    invalid_x_paths["mark_complete_button_x_path"] = (
                        fields.mark_complete_button_x_path
                    )

                if invalid_x_paths and not retry:
                    # retry if we have invalid x_paths
                    return self._extract_known_work_experience_fields_info(
                        observed_elements=observed_elements,
                        retry=True,
                        prev_x_paths=invalid_x_paths,
                    )

                work_experience_fields = []
                for field in fields.work_experience_fields:
                    component = self.work_experience_fields[field.field_id - 1]
                    component.x_path = field.field_x_path

                    work_experience_fields.append(component)

                if fields.mark_complete_button_x_path and isinstance(self.head, Button):
                    mark_complete_work_experience_button = Button(
                        x_path=fields.mark_complete_button_x_path,
                        button_type="mark_complete_current_work_experience",
                        parent_application_page=self.parent_application_page,
                    )
                else:
                    mark_complete_work_experience_button = None

                curr_node = WorkExperience(
                    work_experience_fields=work_experience_fields,
                    save_button=mark_complete_work_experience_button,
                    work_experience_no=self.identified_work_experiences_count + 1,
                    parent_application_page=self.parent_application_page,
                    refetch_fields=True,
                )

            if curr_node:
                return curr_node

        logger.error(
            f"Couldn't extract new work experience fields for {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}"
        )
        return None

    def _identify_add_work_experience_button(self, retry=False, prev_x_path=None):
        global driver

        user_prompt = (
            f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title} at a "
            f"company called {self.parent_application_page.parent_job.company}.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Current page may or may not have a button to start adding new / another work experience. "
            f"Carefully analyse whole HTML and give XPath of the above button if there is any."
        )

        if retry and prev_x_path:
            user_prompt += (
                f"\n\nIn previous GPT call, I got following x_path which was not valid -\n"
                f"add_new_work_experience_x_path - {prev_x_path}\n"
                f"Please retry and give valid x_path for the button mentioned above."
            )

        class AddWorkExperienceButton(BaseModel):
            add_new_work_experience_x_path: Optional[str] = Field(
                ...,
                description="XPath of button to add new / another work experience.",
            )

        fields_found, fields = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=AddWorkExperienceButton,
        )
        if fields_found:
            if fields.add_new_work_experience_x_path:
                if not element_exists(fields.add_new_work_experience_x_path):
                    if not retry:
                        # retry if we have invalid x_path
                        return self._identify_add_work_experience_button(
                            retry=True, prev_x_path=prev_x_path
                        )
                    else:
                        logger.error(
                            f"Invalid x_path for add new work experience button - {fields.add_new_work_experience_x_path}"
                        )
                        return None

                add_work_experience_button = Button(
                    x_path=fields.add_new_work_experience_x_path,
                    button_type="add_another_work_experience",
                    parent_application_page=self.parent_application_page,
                )

                return add_work_experience_button

        logger.warn(
            f"Couldn't extract add work experience button for {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}"
        )
        return None

    def _identify_work_experience_fields(self, observed_elements=[]):
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
                    "I clicked a button to add work experience. I am using javascript mutation observer to "
                    "observe DOM changes. When I clicked the button, the observer observed that following "
                    "elements were added or modified in the DOM -\n"
                    f"{observed_elements_html}\n\n"
                    f"Out of these observed elements, assess which observed element is strictly having interactive "
                    f"work experience fields and then you MUST make all the decisions based on that observed "
                    f"element only which is strictly having the interactive work experience fields."
                )
            else:
                observed_elements_prompt = ""
        else:
            observed_elements_prompt = ""

        (
            interactive_work_experience_fields_visible,
            work_experience_fields_titles,
            are_fields_comprehensive,
        ) = self._are_interactive_work_experience_fields_visible(
            observed_elements_prompt
        )
        if interactive_work_experience_fields_visible and are_fields_comprehensive:
            user_prompt = (
                f"Following HTML is of a job application webpage for {self.parent_application_page.parent_job.title} at a "
                f"company called {self.parent_application_page.parent_job.company}.\n"
                f"HTML: {observed_elements_prompt if observed_elements_prompt else minify_html_for_gpt_prompt(driver.page_source)}\n"
                f"Current page has UI elements to add candidate's work experience. It has either first or both or "
                f"none of the following elements on the current page -\n"
                f"1. Strictly interactive fields to fill work experience details like company, job title, responsibilities, major etc. "
                f"This maybe possible that fields strictly related to work experience are not present on the page, "
                f"in that case don't return any field details. Don't confuse yourself between personal and work "
                f"experience fields. Ignore add new / another work experience button while evaluating this point.\n"
                f"2. A button to mark complete filling in current work experience info. If 1st point is not valid "
                f"(meaning already fields to enter work experience is not present) then this button will also not "
                f"be present.\n\n"
                f"Carefully analyse the {'relevant observed element' if observed_elements_prompt else 'whole HTML'} and find out "
                f"whether only first or all are present and visible.\n"
                f"1. STRICTLY IGNORE all fields which are not related to candidate's work experience section.\n"
                f"{'2. STRICTLY answer all queries and extract all info only from relevant observed element and nothing else.' if observed_elements_prompt else ''}"
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

            class WorkExperienceFieldInfo(BaseModel):
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
                    description="work experience field category like company, job title, responsibilities etc.",
                )

            if observed_elements_prompt:

                class WorkExperienceSectionFields(BaseModel):
                    relevant_observed_element_number: int = Field(
                        ...,
                        description="Number of the observed element which is strictly having interactive work "
                        "experience fields.",
                    )
                    work_experience_fields: Optional[List[WorkExperienceFieldInfo]] = (
                        Field(
                            ...,
                            description="Strictly interactive & clearly visible fields to add work experience details "
                            "like company, job title, responsibilities etc.",
                        )
                    )
                    mark_complete_button_text: Optional[str] = Field(
                        ...,
                        description="Identify the text of the button that finalizes or saves the current work "
                        "experience input. This button is typically labeled with terms like 'Done', 'Save', "
                        "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                        "finalization of work experience input. It can also be a symbol like + etc. Focus on "
                        "buttons whose action logically concludes the process of entering work experience details. "
                        "It may or may not be present. Don't confuse yourself with button to finish / submit "
                        "job application itself.",
                    )
                    mark_complete_button_x_path: Optional[str] = Field(
                        ...,
                        description="Identify the XPath of the button that finalizes or saves the current work "
                        "experience input. This button is typically labeled with terms like 'Done', 'Save', "
                        "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                        "finalization of work experience input. It can also be a symbol like + etc. Focus on "
                        "buttons whose action logically concludes the process of entering work experience details. "
                        "It may or may not be present. Don't confuse yourself with button to finish / submit "
                        "job application itself.",
                    )

            else:

                class WorkExperienceSectionFields(BaseModel):
                    work_experience_fields: Optional[List[WorkExperienceFieldInfo]] = (
                        Field(
                            ...,
                            description="Strictly interactive & clearly visible fields to add work experience details "
                            "like company, job title, responsibilities etc.",
                        )
                    )
                    mark_complete_button_text: Optional[str] = Field(
                        ...,
                        description="Identify the text of the button that finalizes or saves the current work "
                        "experience input. This button is typically labeled with terms like 'Done', 'Save', "
                        "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                        "finalization of work experience input. It can also be a symbol like + etc. Focus on "
                        "buttons whose action logically concludes the process of entering work experience details. "
                        "It may or may not be present. Don't confuse yourself with button to finish / submit "
                        "job application itself.",
                    )
                    mark_complete_button_x_path: Optional[str] = Field(
                        ...,
                        description="Identify the XPath of the button that finalizes or saves the current work "
                        "experience input. This button is typically labeled with terms like 'Done', 'Save', "
                        "'Complete', 'Confirm' etc. Think of similar texts which can be used to suggestion "
                        "finalization of work experience input. It can also be a symbol like + etc. Focus on "
                        "buttons whose action logically concludes the process of entering work experience details. "
                        "It may or may not be present. Don't confuse yourself with button to finish / submit "
                        "job application itself.",
                    )

            fields_found, fields = get_gpt_response(
                constants.gpt["system_prompts"]["application_step_identification"],
                user_prompt,
                response_format=WorkExperienceSectionFields,
            )
            if fields_found:
                curr_node = None

                if fields.work_experience_fields:
                    if fields.mark_complete_button_x_path and not element_exists(
                        fields.mark_complete_button_x_path
                    ):
                        prompt = (
                            "The x_path that we are trying to extract is of mark complete button which is used to mark"
                            " current work experience as complete."
                        )
                        fields.mark_complete_button_x_path = (
                            ApplicationField.extract_correct_x_path(
                                prev_x_path=fields.mark_complete_button_x_path,
                                prompt=prompt,
                                job_title=self.parent_application_page.parent_job.title,
                                job_url=self.parent_application_page.url,
                            )
                        )
                        if not fields.mark_complete_button_x_path:
                            raise Exception(
                                "Couldn't extract valid x_path for mark complete button."
                            )

                    work_experience_fields = []
                    for field in fields.work_experience_fields:
                        if field.field_category.value in ["start_date", "end_date"]:
                            from jobs.page_components.date_field import DateField

                            application_field_component = DateField(
                                title=field.field_title,
                                question=field.field_question,
                                category=field.field_category.value,
                                parent_application_page=self.parent_application_page,
                                persist_context_fields=False,
                            )
                        else:
                            application_field = ApplicationField(
                                parent_application_page=self.parent_application_page,
                                title=field.field_title,
                                question=field.field_question,
                                category=field.field_category.value,
                            )
                            application_field_component = (
                                application_field.get_field_component()
                            )

                        if application_field_component:
                            work_experience_fields.append(application_field_component)

                    if (
                        work_experience_fields
                        and fields.mark_complete_button_x_path
                        and isinstance(self.head, Button)
                    ):
                        mark_complete_work_experience_button = Button(
                            x_path=fields.mark_complete_button_x_path,
                            button_type="mark_complete_current_work_experience",
                            parent_application_page=self.parent_application_page,
                        )
                    else:
                        mark_complete_work_experience_button = None

                    if work_experience_fields:
                        curr_node = WorkExperience(
                            work_experience_fields=work_experience_fields,
                            save_button=mark_complete_work_experience_button,
                            work_experience_no=self.identified_work_experiences_count
                            + 1,
                            parent_application_page=self.parent_application_page,
                            refetch_fields=True,
                        )

                return curr_node
            else:
                return None
        elif (
            interactive_work_experience_fields_visible and not are_fields_comprehensive
        ):
            logger.info(
                f"Work experience fields are visible but not comprehensive for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )
            return work_experience_fields_titles
        else:
            logger.warn(
                f"Couldn't extract work experience fields for {self.parent_application_page.parent_job.title}. "
                f"URL - {self.parent_application_page.url}"
            )
            return None

    def _are_interactive_work_experience_fields_visible(self, observed_elements_prompt):
        global driver

        user_prompt = (
            f"Following HTML of a job application webpage for {self.parent_application_page.parent_job.title} at a "
            f"company called {self.parent_application_page.parent_job.company}.\n"
            f"HTML: {observed_elements_prompt if observed_elements_prompt else minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Current HTML may have following UI elements -\n"
            f"1. Strictly interactive fields to fill work experience details like company, job title, responsibilities, major etc. "
            f"This maybe possible that fields strictly related to work experience are not present on the page, "
            f"in that case don't return any field details. Don't confuse yourself between personal and work "
            f"experience fields. Ignore add new / another work experience button while evaluating this point.\n"
            f"Carefully analyse the whole HTML and find out "
            f"whether only first or all are present and visible.\n"
            f"1. STRICTLY IGNORE all fields which are not related to candidate's work experience section.\n"
        )

        class WorkExperienceSectionInfo(BaseModel):
            interactive_work_experience_fields_visible: bool = Field(
                ...,
                description="Determine whether interactive fields *strictly* related to work experiences are currently "
                "**present and clearly visible** on the page.\n"
                "- **Strictly IGNORE** the presence of any add work experience button.\n"
                "- Your assessment must be **based solely on the actual visibility of interactive work experience related input fields**, "
                "not on page instructions or labels.",
            )
            work_experience_fields_titles: Optional[List[str]] = Field(
                ...,
                description="If interactive work experience fields are visible, return their exact titles. "
                "This is optional and may not be present if no work experience fields are visible.",
            )
            are_fields_comprehensive: bool = Field(
                ...,
                description="Determine whether the visible work experience fields are comprehensive enough to cover all "
                "necessary work experience information. If not, return False. This is to judge if the section is about "
                "collecting comprehensive work experience information or is just couple of standalone fields which are "
                "not intended for gathering comprehensive information about work experience.",
            )
            add_new_work_experience_button_visible: bool = Field(
                ...,
                description="Determine whether the button to add new / another work experience is currently "
                "**present and clearly visible** on the page.\n",
            )

        info_found, info = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=WorkExperienceSectionInfo,
        )
        if info_found:
            return (
                info.interactive_work_experience_fields_visible,
                info.work_experience_fields_titles,
                info.are_fields_comprehensive,
                info.add_new_work_experience_button_visible,
            )
        else:
            return False, [], None, False

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
    def __init__(
        self,
        work_experience_fields,
        save_button,
        work_experience_no,
        parent_application_page,
        refetch_fields=False,
    ):
        self.work_experience_fields = work_experience_fields
        self.save_button = save_button
        self.work_experience_no = work_experience_no
        self.parent_application_page = parent_application_page
        self.refetch_fields = refetch_fields

        self.work_experience_info = {}

        self.next = None
        self.prev = None

    def proceed(self, retry=False):
        for field in self.work_experience_fields:
            self._process_field(field)

        if self.refetch_fields:
            additional_fields = self._refetch_fields()
            if additional_fields:
                logger.info(
                    f"Adding additional {len(additional_fields)} work experience fields to work experience "
                    f"section {self.work_experience_no} for job {self.parent_application_page.parent_job.title} "
                    f"at url {self.parent_application_page.url}."
                )
                self.work_experience_fields.append(additional_fields)

                for field in additional_fields:
                    self._process_field(field)

        if self.save_button:
            self.save_button.proceed()

    def _process_field(self, field):
        question_backup = field.question
        field.question = (
            f"{question_backup}\n"
            f"Above question should be answered for following work experience information -\n"
            f"{self.work_experience_info}"
        )

        category_backup = field.category
        field.category = (
            f"work_experience__{category_backup}__{self.work_experience_no}"
        )

        field.proceed()

        field.question = question_backup
        field.category = category_backup

    def _refetch_fields(self):
        """Fetch additional work experience fields that are not already present in existing work_experience_fields"""
        global driver

        user_prompt = (
            f"Following HTML is of a job application webpage for {self.parent_application_page.parent_job.title} at a "
            f"company called {self.parent_application_page.parent_job.company}.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"Current page has UI elements to add candidate's work experience. I am currently working on "
            f"work experience number {self.work_experience_no}. If more than one work experience sections seem to be present on "
            f"the page, focus only on work experience section number {self.work_experience_no} and completely "
            f"ignore all other work experience sections. "
            f"Identify strictly interactive fields to fill work experience "
            f"details like company, job title, responsibilities, major etc. Only return fields that are "
            f"clearly visible, interactive, and related to work experiences.\n"
            f"1. STRICTLY IGNORE all fields which are not related to candidate's work experience section. "
            f"If more than one work experience sections seem to be present, ignore fields not belonging to work "
            f"experience section number {self.work_experience_no}.\n"
        )

        from enum import Enum

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

        class WorkExperienceFieldInfo(BaseModel):
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
                description="work experience field category like company, job title, responsibilities etc.",
            )

        class WorkExperienceFields(BaseModel):
            work_experience_fields: List[WorkExperienceFieldInfo] = Field(
                ...,
                description="Strictly interactive & clearly visible fields to add work experience "
                "details like company, job title, responsibilities etc.",
            )

        fields_found, fields = get_gpt_response(
            constants.gpt["system_prompts"]["application_step_identification"],
            user_prompt,
            response_format=WorkExperienceFields,
        )

        additional_fields = []
        if fields_found and fields.work_experience_fields:
            # Filter out any fields that might have duplicate titles by mistake
            filtered_fields = []
            existing_field_titles = [
                field.title for field in self.work_experience_fields
            ]
            for field in fields.work_experience_fields:
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
                else:
                    application_field = ApplicationField(
                        parent_application_page=self.parent_application_page,
                        title=field.field_title,
                        question=field.field_question,
                        category=field.field_category.value,
                    )
                    application_field_component = (
                        application_field.get_field_component()
                    )

                if application_field_component:
                    additional_fields.append(application_field_component)

        return additional_fields

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "work_experience_fields": [
                field.to_dict() for field in self.work_experience_fields
            ],
            "save_button": self.save_button.to_dict() if self.save_button else None,
            "work_experience_no": self.work_experience_no,
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

        save_button = None
        if input_dict["save_button"]:
            button_class = get_page_component_class_name(
                class_name=input_dict["save_button"]["class"]
            )
            save_button = button_class.from_dict(
                input_dict["save_button"], parent_application_page
            )

        instance = cls(
            work_experience_fields=fields,
            save_button=save_button,
            work_experience_no=input_dict["work_experience_no"],
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
