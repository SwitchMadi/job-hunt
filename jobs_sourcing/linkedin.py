from utilities.selenium import get_selenium_driver
from selenium.webdriver.common.by import By
import time
from urllib.parse import urlparse, parse_qs


def extract_linkedin_jobs():
    driver = get_selenium_driver(headless=False)
    url = "https://linkedin.com"
    driver.get(url)

    input("Please log into Linkedin and then press any key to continue...")

    url = "https://www.linkedin.com/jobs/search/?f_WT=2&geoId=102713980&keywords=software&location=India&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true"
    driver.get(url)
    time.sleep(5)

    jobs = []
    jobs_side_panel = driver.find_element(
        by=By.CLASS_NAME, value="jobs-search-results-list"
    )
    jobs_list = driver.find_element(
        by=By.CLASS_NAME, value="scaffold-layout__list-container"
    )
    for job in jobs_list.find_elements(By.XPATH, "./*")[:15]:
        # Scroll the jobs side panel to the current job
        driver.execute_script(
            "arguments[0].scrollTop = arguments[1].offsetTop;", jobs_side_panel, job
        )

        job.click()
        time.sleep(1)

        current_url = driver.current_url
        parsed_url = urlparse(current_url)
        query_params = parse_qs(parsed_url.query)
        job_id = query_params.get("currentJobId", [None])[0]
        job_url = f"https://www.linkedin.com/jobs/view/{job_id}"

        job_description = driver.find_element(
            by=By.CLASS_NAME, value="jobs-search__job-details--wrapper"
        ).text

        jobs.append({"job_url": job_url, "job_description": job_description})

    driver.quit()

    return jobs
