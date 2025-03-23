import uuid
import yaml
from datetime import datetime, timedelta, timezone
import pytz
import numpy as np
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import os
import dotenv
import json

from utilities.sql import get_sql_query_output, execute_sql_query, get_sql_connection
from utilities.google_services.drive import DriveResource
from utilities.google_services.sheet import Sheet
from utilities.logging import get_logger
from utilities import generate_password, encrypt_string, decrypt_password, constants
from utilities.gpt.file_assistant import query_file
from utilities.gpt import get_gpt_response
from utilities.aws.s3 import S3Bucket
from user.resume import Resume


logger = get_logger(name="user")

dotenv.load_dotenv()
config = yaml.safe_load(open("config.yml"))


class User:
    def __init__(self, email=None, name=None):
        self.email = email

        user = User.find_user_by_email(email)
        if user is None:
            self.hash_id = uuid.uuid4()
            self.name = name
            self.password = encrypt_string(generate_password())
            self.save_to_db()
            user = User.find_user_by_email(email)

        self.id = user["id"]
        self.hash_id = user["user_hash_id"]
        self.name = user["name"]
        self.resume = user["resume"]
        self.parsed_resume = user["parsed_resume"] or {}
        self.password = decrypt_password(user["password"])

        self._drive_folder = None
        self._jobs_sheet = None
        self._job_filters = None
        self._google_oauth_credentials = None

    @staticmethod
    def find_user_by_email(email):
        user_query = f"""
            select *
            from users.users
            where email = '{email}'
        """
        user = get_sql_query_output(user_query)
        if user:
            return user[0]
        else:
            return None

    def save_to_db(self):
        user_create_query = f"""
            insert into users.users
            (user_hash_id, email, name, password)
            values ('{self.hash_id}', '{self.email}', '{self.name}', '{self.password}')
        """
        return execute_sql_query(user_create_query)

    def update_to_db(self, **fields):
        if not fields:
            raise ValueError("At least one field must be provided to update.")

        def format_sql_value(value):
            # Handle SQL NULL for None values.
            if value is None:
                return "NULL"
            # For strings, escape single quotes and wrap in single quotes.
            elif isinstance(value, str):
                return "'" + value.replace("'", "''") + "'"
            # Convert booleans to SQL-compatible TRUE/FALSE.
            elif isinstance(value, bool):
                return "TRUE" if value else "FALSE"
            # For other types (int, float, etc.) use the string representation.
            else:
                return str(value)

        # Build the SET clause dynamically using the formatted values.
        set_clause = ", ".join(
            f"{field} = {format_sql_value(value)}" for field, value in fields.items()
        )

        user_update_query = f"""
            UPDATE users.users
            SET {set_clause}
            WHERE id = {self.id}
        """
        return execute_sql_query(user_update_query)

    def add_job_preference(self, job_field, value):
        job_preference_query = f"""
            insert into users.job_filter_preferences
            (user_id, job_field, value)
            values ({self.id}, '{job_field}', '{value}')
        """
        return execute_sql_query(job_preference_query)

    @property
    def drive_folder(self):
        if self._drive_folder:
            return self._drive_folder

        user_folder_id = None
        root_folder = DriveResource(resource_id="root")
        for resource in root_folder.get_folder_resources():
            if (resource["mimeType"] == "application/vnd.google-apps.folder") and (
                resource["name"] == self.email
            ):
                user_folder_id = resource["id"]

        if user_folder_id:
            user_folder = DriveResource(resource_id=user_folder_id)
        else:
            user_folder = DriveResource(
                name=self.email,
                resource_type="folder",
                parent_folder_id=root_folder.id,
            )
            user_folder.share(email=self.email)
            user_folder.share(email=config["admin_email"])

        self._drive_folder = user_folder
        return self._drive_folder

    @property
    def jobs_sheet(self):
        if self._jobs_sheet:
            return self._jobs_sheet

        today = datetime.now(pytz.timezone("Asia/Kolkata")).date()
        cur_month = f"{today.year}{str(today.month).zfill(2)}"
        sheet_name = f"SwitchMadi Jobs | Month {cur_month}"

        jobs_sheet = None
        for resource in self.drive_folder.get_folder_resources():
            if (resource["mimeType"] == "application/vnd.google-apps.spreadsheet") and (
                resource["name"] == sheet_name
            ):
                jobs_sheet = Sheet(sheet_id=resource["id"])

        if jobs_sheet is None:
            jobs_sheet = Sheet(title=sheet_name, folder_id=self.drive_folder.id)

        self._jobs_sheet = jobs_sheet
        return self._jobs_sheet

    def _preferred_jobs_query_filters(self, job_filter_id):
        """
        This private method returns SQL query filter which will return jobs based on user preferences and job age.

        Args:
            job_age (int): Job age in days. Jobs older than this will be ignored.

        Returns:
            str: SQL query filter
        """

        user_preferences_query = f"""
            select coalesce(t2.related_job_field, t1.job_field) job_field,
                   unnest(coalesce(t2.synonyms, ARRAY[t1.value])) as value,
                   is_preferred
            from users.job_filter_preferences t1
            left join jobs.field_value_synonyms t2
            on t1.job_field = t2.job_field
            and t1.value = t2.value 
            where t1.user_id = {self.id}
            and t1.is_active
            and t1.job_filter_id = {job_filter_id}
        """
        df_user_preferences = get_sql_query_output(
            query=user_preferences_query, output_as_dataframe=True
        )
        df_user_preferences["value"] = df_user_preferences["value"].apply(
            lambda x: x.replace("'", "''")
        )
        grouped_preferences = (
            df_user_preferences.groupby(["job_field", "is_preferred"])["value"]
            .agg(list)
            .unstack()
        )
        field_preferences = grouped_preferences.apply(
            lambda x: x.dropna().to_dict(), axis=1
        ).to_dict()

        filters = {}
        for job_field, preferences in field_preferences.items():
            if job_field == "job_posted_days_ago":
                now = datetime.now()
                time_ago = now - timedelta(days=int(preferences[True][0]))
                time_ago = int(time_ago.timestamp())
                filters[job_field] = (
                    f"(coalesce(job_posted_at, created_at) >= {time_ago})"
                )
            elif job_field in (["employees_count"]):
                filters[job_field] = (
                    f"(({job_field} >= {preferences[True][0]}) or {job_field} is null)"
                )
            elif job_field in (["experience_requirement_min_years"]):
                filters[job_field] = (
                    f"((experience_requirement_max_years >= {preferences[True][0]}) "
                    f"or experience_requirement_max_years is null)"
                )
            elif job_field in (["experience_requirement_max_years"]):
                filters[job_field] = (
                    f"((experience_requirement_min_years <= {preferences[True][0]}) "
                    f"or experience_requirement_min_years is null)"
                )
            elif job_field in (["company", "job_domain"]):
                queries = {}
                for is_preferred, values in preferences.items():
                    if is_preferred:
                        queries[is_preferred] = (
                            f"""{job_field} in ('{"', '".join(values)}')"""
                        )
                    else:
                        queries[is_preferred] = (
                            f"""{job_field} not in ('{"', '".join(values)}')"""
                        )

                filters[job_field] = ""
                for _, query in queries.items():
                    filters[job_field] += f"{query} and "
                filters[job_field] = f"({filters[job_field].strip(' and ')})"
            elif job_field in (
                [
                    "title",
                    "location",
                    "location_requirement",
                    "technical_skills",
                    "employment_type",
                ]
            ):
                queries = {}
                for is_preferred, values in preferences.items():
                    queries[is_preferred] = []
                    if is_preferred:
                        for value in values:
                            queries[is_preferred].append(
                                f"""lower({job_field}) ilike '%{value.lower()}%'"""
                            )
                    else:
                        for value in values:
                            queries[is_preferred].append(
                                f"""lower({job_field}) not ilike '%{value.lower()}%'"""
                            )

                filters[job_field] = ""
                for is_preferred, query_list in queries.items():
                    condition = "or" if is_preferred else "and"
                    filters[job_field] += f"({f' {condition} '.join(query_list)}) and "
                filters[job_field] = f"({filters[job_field].strip(' and ')})"

        filters = [query for _, query in filters.items()]
        filters = " and\n".join(filters)

        return filters

    @property
    def job_filters(self):
        if self._job_filters:
            return self._job_filters

        job_filters_query = f"""
            select id, "name"
            from users.job_filters
            where user_id = {self.id}
            and is_active
        """
        job_filters = get_sql_query_output(query=job_filters_query)
        self._job_filters = job_filters if job_filters else []

        return self._job_filters

    def get_unshared_jobs(self, job_filter_id):
        query = f"""
            select *, to_timestamp(coalesce(job_posted_at, created_at)) AT TIME ZONE 'Asia/Kolkata' as job_posted_at_ist
            from jobs.jobs
            where id not in (
                    select job_id
                    from users.jobs_shared
                    where user_id = {self.id}
                    and job_filter_id = {job_filter_id}
                )
            and is_active
            and {self._preferred_jobs_query_filters(job_filter_id)}
            order by coalesce(job_posted_at, created_at) desc
        """
        df_unshared_jobs = get_sql_query_output(query=query, output_as_dataframe=True)

        return df_unshared_jobs

    def share_jobs(self):
        logger.info(f"Sharing jobs for {self.email}...")

        today = datetime.now(pytz.timezone("Asia/Kolkata")).date()
        today = f"{today.year}{str(today.month).zfill(2)}{str(today.day).zfill(2)}"

        for cur_filter in self.job_filters:
            df_unshared_jobs = self.get_unshared_jobs(cur_filter["id"])
            skip_columns = [
                "id",
                "job_hash_id",
                "job_posted_at",
                "created_at",
                "updated_at",
                "source",
                "job_description",
                "is_active",
                "is_reposted_job",
                "repost_url",
                "description_language",
            ]
            keep_columns = [
                col for col in df_unshared_jobs.columns if col not in skip_columns
            ]
            keep_columns.append("applied")

            df_unshared_jobs["job_posted_at_ist"] = df_unshared_jobs[
                "job_posted_at_ist"
            ].astype(str)
            df_unshared_jobs = df_unshared_jobs.replace({np.nan: None})
            df_unshared_jobs["applied"] = False

            tab_name = f"{today}-{cur_filter['name']}"[:50]
            self.jobs_sheet.add_new_tab(tab_name=tab_name)
            self.jobs_sheet.delete_tab(tab_name="Sheet1")

            self.jobs_sheet.write_dataframe_to_tab(
                df=df_unshared_jobs[keep_columns], tab_name=tab_name, mode="append"
            )
            self.jobs_sheet.reset_tab_row_heights(tab_name=tab_name)
            self.jobs_sheet.freeze_rows(tab_name, rows=1)
            self.jobs_sheet.make_range_bold(tab_name, range_str="A1:Z1")

            df_unshared_jobs = df_unshared_jobs[["id"]].rename(columns={"id": "job_id"})
            df_unshared_jobs["user_id"] = self.id
            df_unshared_jobs["job_filter_id"] = cur_filter["id"]

            con = get_sql_connection(con_type="sqlalchemy")
            df_unshared_jobs.to_sql(
                name="jobs_shared",
                con=con,
                schema="users",
                if_exists="append",
                index=False,
                chunksize=1000,
                method="multi",
            )

        return True

    @property
    def google_oauth_credentials(self):
        """
        Load the credentials from the database using the user_id.
        """

        if self._google_oauth_credentials:
            return self._google_oauth_credentials

        credentials = None

        query = f"""
            SELECT * 
            FROM users.google_oauth_tokens 
            WHERE user_id = {self.id}
        """
        result = get_sql_query_output(query)

        if result:
            token_data = result[0]
            credentials = Credentials(
                token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                expiry=datetime.fromtimestamp(token_data["expires_at"]),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=os.getenv("GOOGLE_CLIENT_ID"),
                client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
                scopes=token_data["scope"].split(","),
            )

            if credentials.expired and credentials.refresh_token:
                try:
                    credentials.refresh(Request())
                    self.google_oauth_credentials = credentials
                except Exception as e:
                    logger.exception(f"Failed to refresh google oauth token: {e}")
                    credentials = None

        self._google_oauth_credentials = credentials

        return credentials

    @google_oauth_credentials.setter
    def google_oauth_credentials(self, credentials):
        self._google_oauth_credentials = credentials
        self._save_google_oauth_credentials()
        return

    def _save_google_oauth_credentials(self):
        """
        Upsert the OAuth2 credentials to the SQL database.
        """
        credentials = self.google_oauth_credentials
        expires_at = int(credentials.expiry.replace(tzinfo=timezone.utc).timestamp())
        query = f"""
            INSERT INTO users.google_oauth_tokens
            (user_id, access_token, refresh_token, expires_at, scope)
            VALUES (
                {self.id}, '{credentials.token}', '{credentials.refresh_token}', {expires_at},
                '{','.join(credentials.scopes)}'
            )
            ON CONFLICT (user_id)
            DO UPDATE SET
                access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                expires_at = EXCLUDED.expires_at,
                scope = EXCLUDED.scope;
            """

        execute_sql_query(query)

        return

    def save_resume(self, file_local_path):
        s3 = S3Bucket(bucket_name=config["s3_bucket"])

        file_extension = file_local_path.split(".")[-1]
        file_s3_path = f"user_data/resumes/{self.hash_id}.{file_extension}"
        s3.upload_data(file_local_path=file_local_path, file_s3_path=file_s3_path)
        self.update_to_db(resume=file_s3_path)
        self.resume = file_s3_path

        return True

    def parse_resume(self):
        if not self.resume:
            logger.warn(f"We don't have user's resume. user_id - {self.id}")
            return

        logger.info(f"Downloading resume for user_id - {self.id}...")
        s3 = S3Bucket(bucket_name=config["s3_bucket"])

        file_name = self.resume.split("/")[-1]
        file_local_path = f"{config['other_files_folder']}/{file_name}"

        s3.fetch_data(file_s3_path=self.resume, file_local_path=file_local_path)

        logger.info(f"Parsing resume for user_id - {self.id}...")
        resume_summary = query_file(
            query="Extract resume content in structured manner. Do not leave any information and do not add any of "
            "your comments.",
            file=file_local_path,
        )

        user_prompt = (
            f"Following is resume summary for a candidate named {self.name}. Extract information from the resume into"
            f"structured output as mentioned in response_format.\n"
            f"Resume summary -\n"
            f"{resume_summary}"
        )
        resume_info_extracted, resume_info = get_gpt_response(
            constants.gpt["system_prompts"]["resume_parser"],
            user_prompt,
            response_format=Resume,
        )

        if resume_info_extracted:
            resume_info = resume_info.model_dump(mode="json")
            self.update_to_db(parsed_resume=json.dumps(resume_info))
            self.parsed_resume = resume_info
            return True
        else:
            logger.error(f"Couldn't extract resume fields for user_id - {self.id}")
            return False

    @property
    def first_name(self):
        return self.name.split(" ")[0]

    @property
    def last_name(self):
        return self.name.split(" ")[-1]
