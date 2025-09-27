from utilities.logging import get_logger
from utilities.aws import send_lambda_response
from utilities.sql import get_sql_query_output
from user import User

logger = get_logger(name="preferred_jobs_count")


def expand_field_values_with_synonyms(field_values, job_field):
    """
    Expand field values with synonyms from the database.
    Similar to how User._get_job_fields_preferences works.

    Args:
        field_values: List of values to expand
        job_field: The job field name (e.g., 'technical_skills', 'location', etc.)

    Returns:
        List of expanded values including synonyms
    """
    if not field_values:
        return []

    # Create a query to get synonyms for the given field values
    values_str = "', '".join([v.replace("'", "''") for v in field_values])
    synonyms_query = f"""
        select coalesce(t2.related_job_field, t1.job_field) as job_field,
               unnest(coalesce(t2.synonyms, ARRAY[t1.value])) as value
        from (select unnest(ARRAY['{values_str}']) as value) t1
        left join jobs.field_value_synonyms t2
        on t1.value = t2.value 
        and t2.job_field = '{job_field}'
    """

    try:
        synonyms_data = get_sql_query_output(query=synonyms_query)
        expanded_values = [row["value"] for row in synonyms_data if row["value"]]
        return list(set(expanded_values))  # Remove duplicates
    except Exception as e:
        logger.warning(f"Failed to expand synonyms for {job_field}: {e}")
        return field_values  # Fallback to original values


@send_lambda_response(logger)
def lambda_handler(event, context):
    # Use multiValueQueryStringParameters as the authoritative source
    multi_params = event.get("multiValueQueryStringParameters", {}) or {}
    query_params = event.get("queryStringParameters", {}) or {}

    # Merge logic: arrays from multi_params, others from query_params if not present in multi
    merged_params = {
        k: v if len(v) > 1 or k.endswith("[]") else v[0]
        for k, v in multi_params.items()
    }
    merged_params.update(
        {k: v for k, v in query_params.items() if k not in merged_params}
    )

    # Convert to nested dict
    nested_params = parse_nested_query(merged_params)

    # Defensive parsing of experience
    experience = nested_params.get("experience", {})
    try:
        min_exp = (
            int(experience.get("min", 0)) if experience.get("min") is not None else 0
        )
        max_exp = (
            int(experience.get("max", 0)) if experience.get("max") is not None else 0
        )
    except ValueError:
        raise ValueError(f"Invalid experience range provided: {experience}")

    # Ensure list values
    def ensure_list(val):
        return val if isinstance(val, list) else [val] if val else []

    # Enhanced filters with synonyms support
    # Get base values for each field
    domains = ensure_list(nested_params.get("domains"))
    location_requirement = ensure_list(nested_params.get("locationRequirement"))
    locations = ensure_list(nested_params.get("locations"))
    skills = ensure_list(nested_params.get("skills"))

    # Filter out "United States" from location values
    locations = [loc for loc in locations if loc.lower() != "united states"]

    # Expand values with synonyms for fields that support them
    expanded_domains = expand_field_values_with_synonyms(domains, "job_domain")
    expanded_location_requirement = expand_field_values_with_synonyms(
        location_requirement, "location_requirement"
    )
    expanded_locations = expand_field_values_with_synonyms(locations, "location")
    expanded_skills = expand_field_values_with_synonyms(skills, "technical_skills")

    field_preferences = {
        "job_domain": {True: expanded_domains},
        "experience_requirement_min_years": {True: [min_exp]},
        "experience_requirement_max_years": {True: [max_exp]},
        "location_requirement": {True: expanded_location_requirement},
        "location": {True: expanded_locations},
        "technical_skills": {True: expanded_skills},
    }

    query = f"""
        SELECT count(*) AS count
        FROM jobs.jobs
        WHERE is_active
          AND job_posted_at > EXTRACT(EPOCH FROM (CURRENT_DATE - INTERVAL '1 day'))
          AND {User.preferred_jobs_query_filters(field_preferences)}
          AND is_non_automatable = false;
    """

    jobs_count = get_sql_query_output(query=query)[0]
    jobs_count["count"] = int(jobs_count["count"])

    logger.info(
        f"Average daily count of {jobs_count['count']} found for following preferences (with synonyms) - \n{field_preferences}"
    )

    return jobs_count


def parse_nested_query(params):
    result = {}

    for full_key, value in params.items():
        keys = []
        buffer = ""
        in_brackets = False

        for char in full_key:
            if char == "[":
                if buffer:
                    keys.append(buffer)
                    buffer = ""
                in_brackets = True
            elif char == "]":
                if buffer:
                    keys.append(buffer)
                    buffer = ""
                in_brackets = False
            elif in_brackets or char != "[":
                buffer += char
        if buffer:
            keys.append(buffer)

        # Build nested structure
        current = result
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
        current[keys[-1]] = value

    return result
