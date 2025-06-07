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
        curr_node = self.head

        user_education = self.parent_application_page.parent_job.user.parsed_resume.get(
            "education", []
        )
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
                curr_education_index += 1
                self.is_component_functional = True
                curr_node = curr_node.next

            if curr_node is None:
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
        observed_elements = get_observed_elements()

        if not self.education_fields:
            curr_node = self._identify_education_fields(observed_elements)
        else:
            curr_node = self._extract_known_education_fields_info(observed_elements)

        return curr_node

    def _extract_known_education_fields_info(
        self, observed_elements=None, retry=False, prev_x_paths=None
    ):
        global driver

        field_details_prompt = "\n\n".join(
            f"field_id - {i + 1}. field_title - {field.field_title} | field_category - {field.field_category}"
            for i, field in enumerate(self.education_fields)
        )

        if observed_elements:
            observed_elements_html = "\n".join(
                f"{i + 1}. Element {i + 1} - {minify_html_for_gpt_prompt(el.get_attribute('outerHTML'))}"
                for i, el in enumerate(observed_elements)
                if not is_stale(el)
            )
            observed_elements_prompt = (
                "I clicked a button to add education qualification details. I am using javascript mutation observer to "
                "observe DOM changes. When I clicked the button, the observer observed that following "
                "elements were added or modified in the DOM -\n"
                f"{observed_elements_html}\n\n"
                f"Out of these observed elements, assess which observed element is strictly having interactive "
                f"education qualification fields and then you MUST make all the decisions based on that observed "
                f"element only which is strictly having the interactive education qualification fields."
            )
        else:
            observed_elements_prompt = ""

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
            f"{observed_elements_prompt}"
            f"Carefully analyse whole HTML and give XPath of the above fields along with mark complete current education "
            f"qualification button if there is any.\n"
            f"1. STRICTLY IGNORE all fields which are not related to candidate's "
            f"education qualification section and not belonging to education qualification section number "
            f"{self.identified_educations_count + 1}."
            f"{'2. STRICTLY answer all queries and extract all info only from relevant observed element and nothing else.' if observed_elements_prompt else ''}"
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

        if observed_elements_prompt:

            class EducationSectionFields(BaseModel):
                observed_element_number: int = Field(
                    ...,
                    description="Number of the observed element which is strictly having interactive education "
                    "qualification fields.",
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
        )
        if fields_found:
            curr_node = None

            if fields.education_fields:
                invalid_x_paths = {}
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

                if fields.mark_complete_button_x_path:
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
                    education_no=self.identified_educations_count + 1,
                    parent_application_page=self.parent_application_page,
                )
                self._update_nodes(curr_node)

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
                self._update_nodes(add_education_button)

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

        interactive_education_fields_visible = (
            self._are_interactive_education_fields_visible(observed_elements_prompt)
        )
        if interactive_education_fields_visible:
            user_prompt = (
                f"Following HTML page is job application webpage for {self.parent_application_page.parent_job.title} at a "
                f"company called {self.parent_application_page.parent_job.company}.\n"
                f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
                f"Current page has UI elements to add candidate's education qualification. It has either first or both or "
                f"none of the following elements on the current page -\n"
                f"1. Strictly interactive fields to fill education qualification details like college, degree, major etc. "
                f"This maybe possible that fields strictly related to education qualification are not present on the page, "
                f"in that case don't return any field details. Don't confuse yourself between personal and education "
                f"qualification fields. Ignore add new / another education button while evaluating this point.\n"
                f"2. A button to mark complete filling in current education qualification info. If 1st point is not valid "
                f"(meaning already fields to enter education qualification is not present) then this button will also not "
                f"be present.\n\n"
                f"{observed_elements_prompt}"
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

            if observed_elements_prompt:

                class EducationSectionFields(BaseModel):
                    observed_element_number: int = Field(
                        ...,
                        description="Number of the observed element which is strictly having interactive education "
                        "qualification fields.",
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
                    proof_of_education_fields_present: Optional[str] = Field(
                        None,
                        description="If interactive and visible education fields are present then give proof of that.",
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
                            education_fields.append(application_field_component)

                    if education_fields and fields.mark_complete_button_x_path:
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
                            education_no=self.identified_educations_count + 1,
                            parent_application_page=self.parent_application_page,
                        )
                        self._update_nodes(curr_node)

                if curr_node:
                    return curr_node

        logger.warn(
            f"Couldn't extract education fields for {self.parent_application_page.parent_job.title}. "
            f"URL - {self.parent_application_page.url}"
        )
        return None

    @staticmethod
    def _are_interactive_education_fields_visible(observed_elements_prompt):
        global driver

        user_prompt = (
            f"Following HTML page is job application webpage for Quantitative Engineering - Associate - Global Banking & Markets at a "
            f"company called Goldman Sachs.\n"
            f"HTML: {minify_html_for_gpt_prompt(driver.page_source)}\n"
            f"{observed_elements_prompt}"
            f"Current page may have following UI elements -\n"
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
        )
        if info_found:
            return info.interactive_education_fields_visible
        else:
            return False

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
        self, education_fields, save_button, education_no, parent_application_page
    ):
        self.education_fields = education_fields
        self.save_button = save_button
        self.education_no = education_no
        self.parent_application_page = parent_application_page

        self.education_info = {}

        self.next = None
        self.prev = None

    def proceed(self, retry=False):
        for field in self.education_fields:
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

        if self.save_button:
            self.save_button.proceed()

    def to_dict(self):
        return {
            "class": self.__class__.__name__,
            "education_fields": [field.to_dict() for field in self.education_fields],
            "save_button": self.save_button.to_dict() if self.save_button else None,
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
