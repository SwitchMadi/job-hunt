from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class Proficiency(Enum):
    BEGINNER = "Beginner"
    INTERMEDIATE = "Intermediate"
    ADVANCED = "Advanced"
    EXPERT = "Expert"


class SkillCategory(Enum):
    PROGRAMMING_LANGUAGE = "Programming Language"
    FRAMEWORK = "Framework"
    DATABASE = "Database"
    CLOUD = "Cloud"
    INFRASTRUCTURE = "Infrastructure"
    DEVOPS = "DevOps"
    FRONTEND = "Frontend"
    BACKEND = "Backend"
    DATA_ENGINEERING = "Data Engineering"
    DATA_ANALYTICS = "Data Analytics"
    SECURITY = "Security"
    MACHINE_LEARNING = "Machine Learning"
    TESTING = "Testing"
    PRODUCT_MANAGEMENT = "Product Management"
    PROJECT_MANAGEMENT = "Project Management"
    DESIGN = "Design"


class EmploymentType(Enum):
    FULLTIME = "Fulltime"
    CONTRACTUAL = "Contractual"
    INTERNSHIP = "Internship"
    PARTTIME = "Part-time"
    FREELANCE = "Freelance"
    TEMPORARY = "Temporary"
    CONSULTANT = "Consultant"
    VOLUNTEER = "Volunteer"


# Model for date fields (all as integers)
class DateField(BaseModel):
    year: int = Field(..., description="Year as an integer, e.g. 2021")
    month: Optional[int] = Field(
        None, description="Month as an integer, e.g. 4 for April"
    )
    date: Optional[int] = Field(None, description="Day of the month as an integer")


# Model for phone details
class Phone(BaseModel):
    country_code: str = Field(..., description="Country calling code, e.g. '+91'")
    number: str = Field(
        ...,
        description="Phone number without the country code. Having only the digits without any "
        "special character",
    )


class Platform(Enum):
    LinkedIn = "LinkedIn"
    GitHub = "GitHub"
    Portfolio = "Portfolio Website"
    Blog = "Personal Blog"
    Medium = "Medium"
    Dribbble = "Dribbble"
    Behance = "Behance"
    Kaggle = "Kaggle"
    StackOverflow = "Stack Overflow"
    Twitter = "Twitter"
    YouTube = "YouTube"
    GoogleScholar = "Google Scholar"
    CodePen = "CodePen"
    ProductHunt = "Product Hunt"
    Other = "Other"


class SocialLink(BaseModel):
    platform: Platform = Field(..., description="Social media platform or website type")
    url: str = Field(..., description="URL of the profile or personal website")


class Salutation(Enum):
    MR = "Mr."
    MRS = "Mrs."
    MS = "Ms."
    DR = "Dr."
    PROF = "Prof."


class PersonalDetails(BaseModel):
    salutation: Optional[Salutation] = Field(
        ...,
        description="Most appropriate salutation / title / name prefix of the"
        " candidate",
    )
    name: str = Field(..., description="Full name of the candidate")
    phone: Optional[Phone] = Field(
        None, description="Phone details with country code and number"
    )
    email: Optional[str] = Field(None, description="Email address")
    address: Optional[str] = Field(
        None, description="Full residential address or location"
    )
    country: Optional[str] = Field(
        None, description="Residential country of the candidate"
    )
    state: Optional[str] = Field(None, description="Residential state of the candidate")
    city: Optional[str] = Field(None, description="Residential city of the candidate")
    social_links: Optional[List[SocialLink]] = Field(
        None, description="List of social media profiles or personal website links"
    )


class WorkExperience(BaseModel):
    job_title: str = Field(..., description="Title of the job position")
    company: str = Field(..., description="Name of the company or organization")
    location: Optional[str] = Field(None, description="Job location (City, Country)")
    start_date: Optional[DateField] = Field(None, description="Start date of the job")
    end_date: Optional[DateField] = Field(
        None, description="End date of the job or current if ongoing"
    )
    responsibilities: Optional[List[str]] = Field(
        None, description="List of responsibilities"
    )
    achievements: Optional[List[str]] = Field(
        None, description="List of achievements mentioned"
    )
    job_url: Optional[str] = Field(
        None,
        description="URL if there is any mentioned in the resume for the work experience",
    )
    industry: Optional[str] = Field(
        None, description="Industry sector of the job/company"
    )
    employment_type: Optional[EmploymentType] = Field(
        None,
        description="Type of employment (e.g. Fulltime, Contractual, Internship, etc.)",
    )


class Degree(Enum):
    BE = "Bachelor of Engineering"
    BTech = "Bachelor of Technology"
    ME = "Master of Engineering"
    MTech = "Master of Technology"
    BSc = "Bachelor of Science"
    BCA = "Bachelor of Computer Applications"
    BA = "Bachelor of Arts"
    BCom = "Bachelor of Commerce"
    BBA = "Bachelor of Business Administration"
    MBA = "Master of Business Administration"
    MSc = "Master of Science"
    MA = "Master of Arts"
    MCom = "Master of Commerce"
    BFA = "Bachelor of Fine Arts"
    BDes = "Bachelor of Design"
    MFA = "Master of Fine Arts"
    PhD = "Doctor of Philosophy"
    Diploma = "Diploma"
    Certificate = "Certificate"
    Associate = "Associate Degree"
    Other = "Other"


class Education(BaseModel):
    degree: Degree = Field(..., description="Degree or certification earned")
    field_of_study: Optional[str] = Field(None, description="Major or field of study")
    institution: str = Field(..., description="Name of the educational institution")
    location: Optional[str] = Field(None, description="Location of the institution")
    start_date: Optional[DateField] = Field(None, description="Start date")
    end_date: Optional[DateField] = Field(None, description="Graduation or end date")
    details: Optional[str] = Field(
        None, description="Additional details such as thesis title or projects"
    )


class Skill(BaseModel):
    name: str = Field(
        ..., description="Name of the skill (e.g. 'Python', 'Kubernetes')"
    )
    category: Optional[SkillCategory] = Field(None, description="Category of the skill")
    proficiency: Optional[Proficiency] = Field(
        None, description="Proficiency level for the skill"
    )


class SkillSection(BaseModel):
    section_name: str = Field(
        ..., description="Section title (e.g. 'Technical Skills', 'Soft Skills')"
    )
    skills: List[Skill] = Field(..., description="List of skills under this section")


class Project(BaseModel):
    project_name: str = Field(..., description="Name of the project")
    description: Optional[str] = Field(None, description="Brief project description")
    technologies: Optional[List[str]] = Field(
        None, description="Technologies or tools used in the project"
    )
    url: Optional[str] = Field(None, description="Link to the project (if available)")


class Certification(BaseModel):
    title: str = Field(..., description="Certification title")
    issuing_organization: Optional[str] = Field(
        None, description="Issuing organization"
    )
    issue_date: Optional[DateField] = Field(
        None, description="Issue date of the certification"
    )
    expiration_date: Optional[DateField] = Field(
        None, description="Expiration date (if any)"
    )
    credential_id: Optional[str] = Field(None, description="Credential ID or reference")
    url: Optional[str] = Field(None, description="URL for verification or more details")


class Language(BaseModel):
    language: str = Field(..., description="Spoken language name")
    proficiency: Optional[Proficiency] = Field(
        None, description="Proficiency level in the spoken language"
    )


class Resume(BaseModel):
    personal_details: PersonalDetails = Field(
        ..., description="Personal details of the candidate"
    )
    summary: str = Field(
        ..., description="Professional summary or objective in at least 100 words"
    )
    work_experience: List[WorkExperience] = Field(
        ..., description="List of work experience entries"
    )
    education: List[Education] = Field(
        ..., description="List of educational qualifications"
    )
    skill_sections: Optional[List[SkillSection]] = Field(
        None, description="List of skill sections, each containing multiple skills"
    )
    projects: Optional[List[Project]] = Field(
        None, description="List of projects, if any"
    )
    certifications: Optional[List[Certification]] = Field(
        None, description="List of certifications or courses completed"
    )
    languages: Optional[List[Language]] = Field(
        None, description="Spoken languages known along with proficiency"
    )
