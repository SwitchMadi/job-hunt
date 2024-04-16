from utilities.selenium import get_selenium_driver
from selenium.webdriver.common.by import By
import time


def extract_linkedin_jobs():
    driver = get_selenium_driver(headless=False)
    url = "https://linkedin.com"
    driver.get(url)

    input("Please log into Linkedin and then press any key to continue...")

    url = "https://www.linkedin.com/jobs/search/?f_WT=2&geoId=102713980&keywords=software&location=India&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true"
    driver.get(url)

    time.sleep(5)
    job_description = driver.find_element(
        by=By.CLASS_NAME, value="jobs-search__job-details--wrapper"
    ).text

    driver.quit()

    return job_description
