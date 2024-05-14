import uuid
import yaml
from datetime import datetime, timedelta
import pytz
import numpy as np

from utilities.sql import get_sql_query_output, execute_sql_query, get_sql_connection
from utilities.google_services.drive import DriveResource
from utilities.google_services.sheet import Sheet


config = yaml.safe_load(open("config.yml"))


class User:
    def __init__(self, email=None, name=None):
        self.email = email

        user = User.find_user_by_email(email)
        if user is None:
            self.hash_id = uuid.uuid4()
            self.name = name
            self.save_to_db()
            user = User.find_user_by_email(email)

        self.id = user["id"]
        self.hash_id = user["user_hash_id"]
        self.name = user["name"]

        self._drive_folder = None
        self._jobs_sheet = None
        self._job_filters = None

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
            (user_hash_id, email, name)
            values ('{self.hash_id}', '{self.email}', '{self.name}')
        """
        return execute_sql_query(user_create_query)

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

        self._drive_folder = user_folder
        return self._drive_folder

    @property
    def jobs_sheet(self):
        if self._jobs_sheet:
            return self._jobs_sheet

        today = datetime.now(pytz.timezone("Asia/Kolkata")).date()
        cur_month = f"{today.year}{str(today.month).zfill(2)}"

        jobs_sheet = None
        for resource in self.drive_folder.get_folder_resources():
            if (resource["mimeType"] == "application/vnd.google-apps.spreadsheet") and (
                resource["name"] == cur_month
            ):
                jobs_sheet = Sheet(sheet_id=resource["id"])

        if jobs_sheet is None:
            jobs_sheet = Sheet(title=cur_month, folder_id=self.drive_folder.id)

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
            elif job_field in (["employees_count", "experience_requirement"]):
                job_field_name = (
                    "experience_requirement_min_years"
                    if job_field == "experience_requirement"
                    else job_field
                )
                filters[job_field] = f"({job_field_name} >= {preferences[True][0]})"
            elif job_field in (["company", "software_domain"]):
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
                ["title", "location", "location_requirement", "technical_skills"]
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
                if job_field == "technical_skills":
                    condition = "and"
                else:
                    condition = "or"
                for _, query_list in queries.items():
                    filters[job_field] += f"({f' {condition} '.join(query_list)}) and "
                filters[job_field] = f"({filters[job_field].strip(' and ')})"

        if filters.get("software_domain") and filters.get("title"):
            filters["software_domain_and_title"] = (
                f"({filters.get('software_domain')} or {filters.get('title')})"
            )
            del filters["software_domain"]
            del filters["title"]

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
            limit 10
        """
        df_unshared_jobs = get_sql_query_output(query=query, output_as_dataframe=True)

        return df_unshared_jobs

    def share_jobs(self):
        today = datetime.now(pytz.timezone("Asia/Kolkata")).date()
        today = f"{today.year}{str(today.month).zfill(2)}{str(today.day).zfill(2)}"

        for cur_filter in self.job_filters:
            df_unshared_jobs = self.get_unshared_jobs(cur_filter["id"])
            skip_columns = [
                "id",
                "job_posted_at",
                "created_at",
                "updated_at",
                "source",
                "job_description",
                "is_active",
            ]
            keep_columns = [
                col for col in df_unshared_jobs.columns if col not in skip_columns
            ]

            df_unshared_jobs["job_posted_at_ist"] = df_unshared_jobs[
                "job_posted_at_ist"
            ].astype(str)
            df_unshared_jobs = df_unshared_jobs.replace({np.nan: None})
            tab_name = f"{today}-{cur_filter['name']}"[:50]
            self.jobs_sheet.add_new_tab(tab_name=tab_name)
            self.jobs_sheet.delete_tab(tab_name="Sheet1")

            self.jobs_sheet.write_dataframe_to_tab(
                df=df_unshared_jobs[keep_columns], tab_name=tab_name, mode="append"
            )
            self.jobs_sheet.reset_tab_row_heights(tab_name=tab_name)

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
