import uuid
import yaml
from datetime import datetime, timedelta, timezone
import pytz
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import os
import dotenv
import json
import tempfile

from utilities.sql import get_sql_query_output, execute_sql_query, get_sql_connection
from utilities.google_services.drive import DriveResource
from utilities.logging import get_logger
from utilities import generate_password, encrypt_string, decrypt_string, constants
from utilities.gpt.file_assistant import query_file
from utilities.gpt import get_gpt_response
from utilities.aws.s3 import S3Bucket
from user.resume import Resume
from plan import Plan


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
        self.parsed_resume = user["modified_resume"] or user["parsed_resume"] or {}
        self.password = decrypt_string(user["password"])

        self._drive_folder = None
        self._jobs_sheet = None
        self._job_filters = None
        self._google_oauth_credentials = None
        self._subscription = None

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
        result = execute_sql_query(user_create_query)

        # After creating the user, assign a trial subscription
        if result:
            # Get the newly created user to get the ID
            user = User.find_user_by_email(self.email)
            if user:
                user.assign_trial_subscription()

        return result

    def assign_trial_subscription(self):
        """Assign a trial subscription to the user if they don't have an active subscription"""
        try:
            # Check if user already has an active subscription
            if self.has_active_subscription:
                logger.info(
                    f"User {self.id} already has an active subscription: {self.subscription_plan_code}"
                )
                return False

            # Check if user has already utilized a trial (historical check)
            # For trial check, we need to check historical usage regardless of current plan
            trial_applications_query = f"""
                SELECT COUNT(*) as count
                FROM users.job_applications ja
                JOIN subscription.subscriptions s ON ja.subscription_id = s.id
                JOIN subscription.plans p ON s.plan_id = p.id
                WHERE ja.user_id = {self.id}
                AND p.code = 'TRIAL'
                AND ja.application_status = 'submitted'
            """
            result = get_sql_query_output(trial_applications_query)
            trial_applications_count = result[0]["count"] if result else 0

            if trial_applications_count > 0:
                logger.info(f"User {self.id} has already utilized a trial subscription")
                return False

            # Get the trial plan ID
            trial_plan_query = """
                SELECT id FROM subscription.plans 
                WHERE code = 'TRIAL' AND is_active = TRUE 
                LIMIT 1
            """
            trial_plan_result = get_sql_query_output(trial_plan_query)

            if not trial_plan_result:
                logger.error("Trial plan not found in subscription.plans table")
                return False

            trial_plan_id = trial_plan_result[0]["id"]

            # Calculate trial period from config
            trial_days = config.get("subscription", {}).get("trial_days", 7)
            current_time = int(datetime.now().timestamp())
            trial_end_time = int(
                (datetime.now() + timedelta(days=trial_days)).timestamp()
            )

            # Create trial subscription
            subscription_create_query = f"""
                INSERT INTO subscription.subscriptions
                (user_id, plan_id, start_at, current_period_start, current_period_end, is_active)
                VALUES 
                ({self.id}, {trial_plan_id}, {current_time}, {current_time}, {trial_end_time}, TRUE)
            """

            subscription_result = execute_sql_query(subscription_create_query)

            if subscription_result:
                logger.info(
                    f"Successfully assigned trial subscription to user {self.id}"
                )
                return True
            else:
                logger.error(f"Failed to create trial subscription for user {self.id}")
                return False

        except Exception as e:
            logger.exception(
                f"Error assigning trial subscription to user {self.id}: {e}"
            )
            return False

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

    @property
    def subscription(self):
        """Get user's active subscription details"""
        if self._subscription is None:
            subscription_query = f"""
                SELECT 
                    s.id as subscription_id,
                    s.start_at,
                    s.current_period_start,
                    s.current_period_end,
                    s.canceled_at,
                    s.is_active,
                    p.code as plan_code,
                    p.name as plan_name,
                    p.billing_period,
                    p.price_amount,
                    p.price_currency
                FROM subscription.subscriptions s
                JOIN subscription.plans p ON s.plan_id = p.id
                WHERE s.user_id = {self.id}
                AND s.is_active = TRUE
                ORDER BY s.created_at DESC
                LIMIT 1
            """
            result = get_sql_query_output(subscription_query)
            self._subscription = result[0] if result else None
        return self._subscription

    @property
    def has_active_subscription(self):
        """Check if user has an active subscription"""
        return self.subscription is not None

    @property
    def subscription_plan_code(self):
        """Get the current subscription plan code"""
        return self.subscription.get("plan_code") if self.subscription else None

    @property
    def subscription_plan_name(self):
        """Get the current subscription plan name"""
        return self.subscription.get("plan_name") if self.subscription else None

    # Generic service-based methods for extensible plan support
    def get_service_limit(self, service_code, plan_code=None):
        """Get limit for any service on any plan (or current plan if not specified)"""
        if plan_code is None:
            plan_code = self.subscription_plan_code

        if not plan_code:
            return 0

        limit_query = f"""
            SELECT pe.limit_quantity
            FROM subscription.plan_entitlements pe
            JOIN subscription.plans p ON pe.plan_id = p.id
            JOIN subscription.services s ON pe.service_id = s.id
            WHERE p.code = '{plan_code}'
            AND s.code = '{service_code}'
            AND pe.is_active = TRUE
        """
        result = get_sql_query_output(limit_query)
        return result[0]["limit_quantity"] if result else 0

    def get_service_usage(
        self, service_code, plan_code=None, period_start=None, period_end=None
    ):
        """Get usage for any service on any plan (or current plan if not specified)"""
        if plan_code is None:
            plan_code = self.subscription_plan_code

        if not plan_code:
            return 0

        # For lifetime services (like TRIAL), don't use period filtering
        if plan_code == "TRIAL":
            usage_query = f"""
                SELECT COUNT(*) as count
                FROM users.job_applications ja
                JOIN subscription.subscriptions s ON ja.subscription_id = s.id
                JOIN subscription.plans p ON s.plan_id = p.id
                WHERE ja.user_id = {self.id}
                AND p.code = '{plan_code}'
                AND ja.application_status = 'submitted'
            """
        else:
            # For period-based services, use subscription period
            if period_start is None or period_end is None:
                if self.subscription:
                    period_start = self.subscription.get("current_period_start", 0)
                    period_end = self.subscription.get("current_period_end", 0)
                else:
                    return 0

            if service_code == "JOB_APPLY":
                usage_query = f"""
                    SELECT COUNT(*) as count
                    FROM users.job_applications
                    WHERE user_id = {self.id}
                    AND subscription_id = {self.subscription.get("subscription_id")}
                    AND application_status = 'submitted'
                    AND created_at >= {period_start}
                    AND created_at <= {period_end}
                """
            elif service_code == "JOB_SHARE":
                usage_query = f"""
                    SELECT COUNT(*) as count
                    FROM users.jobs_shared js
                    JOIN subscription.subscriptions s ON js.subscription_id = s.id
                    JOIN subscription.plans p ON s.plan_id = p.id
                    WHERE js.user_id = {self.id}
                    AND p.code = '{plan_code}'
                    AND js.shared_at >= {period_start}
                    AND js.shared_at <= {period_end}
                """
            else:
                raise ValueError(f"Invalid service code: {service_code}")

        result = get_sql_query_output(usage_query)
        return result[0]["count"] if result else 0

    def get_service_remaining(self, service_code, plan_code=None):
        """Get remaining quota for any service on any plan"""
        limit = self.get_service_limit(service_code, plan_code)
        usage = self.get_service_usage(service_code, plan_code)
        return max(0, limit - usage)

    def can_use_service(self, service_code):
        """Check if user can use any service based on their current plan"""
        if not self.has_active_subscription:
            return False

        remaining = self.get_service_remaining(service_code)
        return remaining > 0

    def has_service_access(self, service_code):
        """Check if current plan provides access to a service"""
        if not self.subscription:
            return False

        plan_code = self.subscription_plan_code
        limit = self.get_service_limit(service_code, plan_code)
        return limit > 0

    def get_plan_entitlements(self, plan_code=None):
        """Get all entitlements for a plan"""
        if plan_code is None:
            plan_code = self.subscription_plan_code

        if not plan_code:
            return {}

        entitlements_query = f"""
            SELECT s.code as service_code, pe.limit_quantity
            FROM subscription.plan_entitlements pe
            JOIN subscription.plans p ON pe.plan_id = p.id
            JOIN subscription.services s ON pe.service_id = s.id
            WHERE p.code = '{plan_code}'
            AND pe.is_active = TRUE
        """
        result = get_sql_query_output(entitlements_query)

        entitlements = {}
        for row in result:
            entitlements[row["service_code"]] = row["limit_quantity"]

        return entitlements

    @property
    def current_plan_services(self):
        """Get all services available on current plan"""
        return self.get_plan_entitlements()

    @property
    def applications_remaining(self):
        """Get remaining job applications for current plan"""
        return self.get_service_remaining("JOB_APPLY")

    @property
    def applications_used(self):
        """Get used job applications for current plan"""
        return self.get_service_usage("JOB_APPLY")

    @property
    def applications_limit(self):
        """Get total job applications limit for current plan"""
        return self.get_service_limit("JOB_APPLY")

    @property
    def shares_remaining(self):
        """Get remaining job shares for current plan"""
        return self.get_service_remaining("JOB_SHARE")

    @property
    def shares_used(self):
        """Get used job shares for current plan"""
        return self.get_service_usage("JOB_SHARE")

    @property
    def shares_limit(self):
        """Get total job shares limit for current plan"""
        return self.get_service_limit("JOB_SHARE")

    @property
    def can_apply_for_jobs(self):
        """Check if user can apply for jobs based on their subscription"""
        return self.can_use_service("JOB_APPLY")

    @property
    def can_share_jobs(self):
        """Check if user can share jobs based on their subscription"""
        return self.can_use_service("JOB_SHARE")

    @property
    def subscription_status_summary(self):
        """Get a summary of user's subscription status"""
        if not self.has_active_subscription:
            return {
                "has_subscription": False,
                "plan": None,
                "can_apply": False,
                "can_share": False,
                "applications_remaining": 0,
                "shares_remaining": 0,
            }

        summary = {
            "has_subscription": True,
            "plan": self.subscription_plan_code,
            "plan_name": self.subscription_plan_name,
            "can_apply": self.can_apply_for_jobs,
            "can_share": self.can_share_jobs,
        }

        # Get all available services for current plan
        plan_services = self.current_plan_services

        if "JOB_APPLY" in plan_services:
            summary.update(
                {
                    "applications_remaining": self.applications_remaining,
                    "applications_used": self.applications_used,
                    "total_applications": self.applications_limit,
                }
            )

        if "JOB_SHARE" in plan_services:
            summary.update(
                {
                    "shares_remaining": self.shares_remaining,
                    "shares_used": self.shares_used,
                    "total_shares": self.shares_limit,
                }
            )

        return summary

    @property
    def subscription_period_info(self):
        """Get subscription period information"""
        if not self.subscription:
            return None

        return {
            "start_at": self.subscription.get("start_at"),
            "current_period_start": self.subscription.get("current_period_start"),
            "current_period_end": self.subscription.get("current_period_end"),
            "canceled_at": self.subscription.get("canceled_at"),
            "is_active": self.subscription.get("is_active"),
            "billing_period": self.subscription.get("billing_period"),
            "price_amount": self.subscription.get("price_amount"),
            "price_currency": self.subscription.get("price_currency"),
        }

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

        from utilities.google_services.sheet import (
            Sheet,
        )  # TODO: Moved here to avoid increasing lambda build size. Optimise using lambda layers.

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
        field_preferences = self._get_job_fields_preferences(job_filter_id)
        return User.preferred_jobs_query_filters(field_preferences)

    def _get_job_fields_preferences(self, job_filter_id):
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

        return field_preferences

    @classmethod
    def preferred_jobs_query_filters(
        cls,
        field_preferences,
        days_ago=15,
        min_years_offset=0,
        max_years_offset=0,
        skip_location=False,
        skip_location_requirement=False,
        skip_technical_skills=False,
    ):
        filters = {}

        if (
            "job_posted_days_ago" in field_preferences
            and True in field_preferences["job_posted_days_ago"]
        ):
            days_ago = int(field_preferences["job_posted_days_ago"][True][0])

        now = datetime.now()
        time_ago = now - timedelta(days=days_ago)
        time_ago = int(time_ago.timestamp())
        filters["job_posted_days_ago"] = (
            f"(coalesce(job_posted_at, created_at) >= {time_ago})"
        )

        for job_field, preferences in field_preferences.items():
            if job_field == "employees_count":
                filters[job_field] = (
                    f"(({job_field} >= {preferences[True][0]}) or {job_field} is null)"
                )
            elif job_field == "experience_requirement_min_years":
                if preferences[True]:
                    min_years = int(preferences[True][0]) - min_years_offset
                    filters[job_field] = (
                        f"((experience_requirement_max_years >= {min_years}) "
                        f"or experience_requirement_max_years is null)"
                    )
            elif job_field == "experience_requirement_max_years":
                if preferences[True]:
                    max_years = int(preferences[True][0]) + max_years_offset
                    filters[job_field] = (
                        f"((experience_requirement_min_years <= {max_years}) "
                        f"or experience_requirement_min_years is null)"
                    )
            elif job_field in ["company", "job_domain"]:
                queries = {}
                for is_preferred, values in preferences.items():
                    if values:
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

                if filters[job_field]:
                    filters[job_field] = f"({filters[job_field].strip(' and ')})"
                else:
                    del filters[job_field]
            elif job_field in [
                "title",
                "location",
                "location_requirement",
                "technical_skills",
                "employment_type",
            ]:
                if (
                    (job_field == "location" and skip_location)
                    or (
                        job_field == "location_requirement"
                        and skip_location_requirement
                    )
                    or (job_field == "technical_skills" and skip_technical_skills)
                ):
                    continue
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
                    if query_list:
                        condition = "or" if is_preferred else "and"
                        filters[
                            job_field
                        ] += f"({f' {condition} '.join(query_list)}) and "

                if filters[job_field]:
                    filters[job_field] = f"({filters[job_field].strip(' and ')})"
                else:
                    del filters[job_field]

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
        import numpy as np  # TODO: Moved here to avoid increasing lambda build size. Optimise using lambda layers.

        # Check if user can share jobs based on subscription
        if not self.can_share_jobs:
            subscription_status = self.subscription_status_summary
            logger.warning(
                f"User {self.email} cannot share jobs due to subscription limits. "
                f"Subscription status: {subscription_status}"
            )
            return False

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

            # Add subscription_id to track job sharing usage
            subscription_id = (
                self.subscription.get("subscription_id") if self.subscription else None
            )
            df_unshared_jobs["subscription_id"] = subscription_id

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

        file_extension = os.path.splitext(self.resume)[1]
        file_local_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=file_extension, delete=False
            ) as temp_file:
                file_local_path = temp_file.name
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
        finally:
            # Clean up temporary file
            if file_local_path and os.path.exists(file_local_path):
                os.remove(file_local_path)

    @property
    def first_name(self):
        return self.name.split(" ")[0]

    @property
    def middle_name(self):
        name_parts = self.name.split(" ")
        if len(name_parts) > 2:
            return " ".join(name_parts[1:-1])
        return None

    @property
    def last_name(self):
        return self.name.split(" ")[-1]

    @property
    def country(self):
        if self.parsed_resume:
            return self.parsed_resume.get("personal_details").get("country")
        return None

    @property
    def city(self):
        if self.parsed_resume:
            return self.parsed_resume.get("personal_details").get("city")
        return None

    @property
    def state(self):
        if self.parsed_resume:
            return self.parsed_resume.get("personal_details").get("state")
        return None

    @property
    def successful_applications_count(self):
        """Count the number of successful job applications for this user"""
        if not hasattr(self, "_successful_applications_count"):
            query = f"""
                SELECT COUNT(*) as count
                FROM users.job_applications
                WHERE user_id = {self.id}
                AND application_status = 'submitted'
            """
            result = get_sql_query_output(query)
            self._successful_applications_count = result[0]["count"] if result else 0

        return self._successful_applications_count

    @property
    def should_stream_applications(self):
        """Determine if streaming should be enabled - only for trial users whose plan is not exhausted"""
        if self.subscription_plan_code != "TRIAL":
            return False
        return self.applications_remaining > 0

    @property
    def phone_number(self):
        if self.parsed_resume:
            # without special characters
            phone = (
                self.parsed_resume.get("personal_details").get("phone").get("number")
            )
            if phone:
                phone = "".join(filter(str.isdigit, phone))
                # remove country code
                if len(phone) > 10:
                    phone = phone[-10:]
                return phone
        return None

    @property
    def phone_country_code(self):
        if self.parsed_resume:
            return (
                self.parsed_resume.get("personal_details")
                .get("phone")
                .get("country_code")
            )
        return None

    def fetch_job_ids_to_apply(self, threshold=15):
        """
        Fetch job IDs to apply with iterative parameter adjustment to meet threshold.

        Args:
            threshold (int): Minimum number of jobs required. Default is 10.

        Returns:
            list: List of job IDs that meet the criteria
        """
        # Step 1: Get the active job filter ID for the user
        job_filters_query = f"""
            SELECT id
            FROM users.job_filters
            WHERE user_id = {self.id}
            AND is_active;
        """
        job_filter = get_sql_query_output(job_filters_query)

        if not job_filter:
            return []  # No active job filters found

        job_filter_id = job_filter[0]["id"]

        # Step 2: Get job field preferences
        job_field_preferences = self._get_job_fields_preferences(job_filter_id)

        # Step 3: Define iteration parameters in order of preference
        iteration_params = [
            # 1. skip_technical_skills as True
            {"skip_technical_skills": True},
            # 2. skip_location_requirement as True, along with previous points
            {"skip_technical_skills": True, "skip_location_requirement": True},
            # 3. skip_location as True, along with previous points
            {
                "skip_technical_skills": True,
                "skip_location_requirement": True,
                "skip_location": True,
            },
            # 4. min_years_offset & max_years_offset as 1, along with previous points
            {
                "skip_technical_skills": True,
                "skip_location_requirement": True,
                "skip_location": True,
                "min_years_offset": 1,
                "max_years_offset": 1,
            },
            # 5. min_years_offset & max_years_offset as 2, along with previous points
            {
                "skip_technical_skills": True,
                "skip_location_requirement": True,
                "skip_location": True,
                "min_years_offset": 2,
                "max_years_offset": 2,
            },
            # 6. min_years_offset & max_years_offset as 3, along with previous points
            {
                "skip_technical_skills": True,
                "skip_location_requirement": True,
                "skip_location": True,
                "min_years_offset": 3,
                "max_years_offset": 3,
            },
        ]

        # Step 4: Try with default parameters first
        sql_preference_filters = User.preferred_jobs_query_filters(
            job_field_preferences
        )
        job_ids = self._get_application_job_ids_with_filters(sql_preference_filters)

        if len(job_ids) >= threshold:
            logger.info(
                f"Found {len(job_ids)} jobs with default filters, meeting threshold of {threshold}"
            )
            return job_ids

        # Step 5: Iteratively try with relaxed parameters
        for i, params in enumerate(iteration_params):
            logger.info(f"Trying iteration {i+1} with parameters: {params}")

            sql_preference_filters = User.preferred_jobs_query_filters(
                job_field_preferences, **params
            )
            job_ids = self._get_application_job_ids_with_filters(sql_preference_filters)

            if len(job_ids) >= threshold:
                logger.info(
                    f"Found {len(job_ids)} jobs with relaxed filters (iteration {i+1}), meeting threshold of {threshold}"
                )
                return job_ids

        # Step 6: Return whatever we found if threshold not met
        logger.info(
            f"Threshold of {threshold} not met. Returning {len(job_ids)} jobs found with most relaxed filters."
        )
        return job_ids

    def update_subscription_status(
        self, plan_code, status, payment_id=None, payment_amount=None
    ):
        """
        Update user's subscription status after successful payment.

        Args:
            plan_code (str): The subscription plan code (e.g., 'PAID')
            status (str): The subscription status (e.g., 'ACTIVE')
            payment_id (str): PayPal payment ID for tracking
            payment_amount (str): Payment amount for record keeping
        """
        try:
            # Get the plan ID for the given plan code
            plan_query = f"""
                SELECT id FROM subscription.plans 
                WHERE code = '{plan_code}' AND is_active = TRUE 
                LIMIT 1
            """
            plan_result = get_sql_query_output(plan_query)

            if not plan_result:
                logger.error(f"Plan with code '{plan_code}' not found")
                return False

            plan_id = plan_result[0]["id"]

            # Deactivate any existing active subscriptions
            deactivate_query = f"""
                UPDATE subscription.subscriptions 
                SET is_active = FALSE, canceled_at = {int(datetime.now().timestamp())}
                WHERE user_id = {self.id} AND is_active = TRUE
            """
            execute_sql_query(deactivate_query)

            # Create new subscription
            current_time = int(datetime.now().timestamp())

            # Get billing period from plan table
            period_days = Plan.get_plan_billing_period_days(plan_id)
            period_end_time = int(
                (datetime.now() + timedelta(days=period_days)).timestamp()
            )

            subscription_create_query = f"""
                INSERT INTO subscription.subscriptions
                (user_id, plan_id, start_at, current_period_start, current_period_end, is_active)
                VALUES 
                ({self.id}, {plan_id}, {current_time}, {current_time}, {period_end_time}, TRUE)
            """

            subscription_result = execute_sql_query(subscription_create_query)

            if subscription_result:
                logger.info(
                    f"Successfully updated subscription for user {self.id} to plan {plan_code}"
                )

                # Clear cached subscription data
                self._subscription = None

                return True
            else:
                logger.error(f"Failed to create subscription for user {self.id}")
                return False

        except Exception as e:
            logger.exception(
                f"Error updating subscription status for user {self.id}: {e}"
            )
            return False

    def _get_application_job_ids_with_filters(self, sql_preference_filters):
        """
        Helper method to get job details with given SQL preference filters.

        Args:
            sql_preference_filters (str): SQL filter conditions

        Returns:
            list: List of job details with job_id, job_hash_id, job_url, title, company, location
        """
        job_details_query = f"""
            WITH submitted_jobs AS (
                SELECT DISTINCT job_id
                FROM users.job_applications
                WHERE user_id = {self.id}
                AND application_status = 'submitted'
            ),
            failed_jobs AS (
                SELECT job_id
                FROM users.job_applications
                WHERE user_id = {self.id}
                AND application_status = 'failed'
                GROUP BY job_id
                HAVING COUNT(*) >= 3
            )
            SELECT 
                j.id job_id,
                j.job_hash_id,
                j.job_url,
                j.title,
                j.company,
                j.location
            FROM jobs.jobs j
            JOIN jobs.application_steps a ON j.id = a.job_id
            WHERE a.is_application_feasible = true
            and a.is_identification_complete = true
            and a.is_active = true
            AND j.id in (
                select id
                from jobs.jobs
                where is_active
                and {sql_preference_filters}
            )
            AND j.job_url ilike '%greenhouse%'
            AND j.id NOT IN (SELECT job_id FROM submitted_jobs)
            AND j.id NOT IN (SELECT job_id FROM failed_jobs)
            ORDER BY j.id
        """

        job_details = get_sql_query_output(job_details_query)
        return job_details
