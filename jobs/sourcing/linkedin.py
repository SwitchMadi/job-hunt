from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
)
import time
from urllib.parse import urlparse, parse_qs
import yaml

from utilities.constants import non_automatable_job_boards
from utilities import time_ago_to_epoch
from utilities.selenium import get_selenium_driver
from utilities.logging import get_logger
from jobs import ApplicationPage


logger = get_logger(name="scrape_linkedin")


def extract_linkedin_jobs(jobs_url, scraped_linkedin_job_ids):
    config = yaml.safe_load(open("config.yml"))

    driver = get_selenium_driver()
    driver.set_page_load_timeout(300)

    try:
        driver.get("https://linkedin.com")
    except TimeoutException:
        logger.critical(
            f"Failed to load linkedin. Current timeout - 300. URL - https://linkedin.com"
        )
        return []

    if config["scraping"]["linkedin"]["login_pause"]:
        input("Please log into Linkedin and then press any key to continue...")

    try:
        driver.get(jobs_url)
    except TimeoutException:
        logger.critical(
            f"Failed to load linkedin URL. Current timeout - 300. URL - {jobs_url}"
        )
        return []

    driver.set_page_load_timeout(15)
    time.sleep(5)

    try:
        jobs_count = driver.find_element(
            by=By.CLASS_NAME, value="jobs-search-results-list__subtitle"
        ).text
        jobs_count = int(jobs_count.split()[0].replace(",", ""))

        jobs_elements = driver.find_elements(
            By.XPATH, "//li[contains(@class, 'scaffold-layout__list')]"
        )
        if not jobs_elements:
            logger.warn("No jobs found on the page.")
            return []

        jobs_container = jobs_elements[0].find_element(By.XPATH, "./.. /..")
    except NoSuchElementException as e:
        logger.exception(f"No element found - {e}")
        return []

    non_feasible_domains = ApplicationPage.get_non_feasible_domains()
    jobs = []
    jobs_scraped = 0
    cur_page = 1
    continue_scraping = True
    while (
        jobs_scraped <= min(jobs_count, config["scraping"]["linkedin"]["max_job_count"])
    ) and continue_scraping:
        try:
            for job in jobs_elements:
                try:
                    # Scroll the jobs side panel to the current job
                    driver.execute_script(
                        "arguments[0].scrollTop = arguments[1].offsetTop;",
                        jobs_container,
                        job,
                    )

                    job.click()
                    time.sleep(1)

                    current_url = driver.current_url
                    parsed_url = urlparse(current_url)
                    query_params = parse_qs(parsed_url.query)
                    job_id = query_params.get("currentJobId", [None])[0]

                    if job_id in scraped_linkedin_job_ids:
                        logger.info(
                            f"Skipping already scraped linkedin job id - {job_id}"
                        )
                        continue

                    linkedin_job_url = f"https://www.linkedin.com/jobs/view/{job_id}"
                    logger.info(f"Job collected - {linkedin_job_url}")

                    job_description = driver.find_element(
                        by=By.CLASS_NAME, value="jobs-search__job-details--wrapper"
                    ).text
                    linkedin_easy_apply = (
                        True if "Easy Apply" in job_description else False
                    )

                    if linkedin_easy_apply:
                        original_job_url = linkedin_job_url
                        is_reposted_job = False
                    else:
                        apply_buttons = driver.find_elements(
                            by=By.CLASS_NAME, value="jobs-apply-button--top-card"
                        )
                        if apply_buttons:
                            main_window_handle = driver.current_window_handle

                            try:
                                apply_buttons[0].click()
                                dialogue = driver.find_elements(
                                    by=By.CSS_SELECTOR,
                                    value=".artdeco-modal.artdeco-modal--layer-default",
                                )
                                if dialogue:
                                    dialogue = dialogue[0]
                                    apply_button = dialogue.find_element(
                                        by=By.CLASS_NAME, value="jobs-s-apply"
                                    )
                                    apply_button.click()
                            except TimeoutException:
                                logger.warn(
                                    "Job application page took more than 10 seconds to load."
                                )

                            new_tab_handle = [
                                handle
                                for handle in driver.window_handles
                                if handle != main_window_handle
                            ][0]

                            driver.switch_to.window(new_tab_handle)

                            try:
                                original_job_url = driver.current_url
                            except TimeoutException:
                                logger.warn(
                                    "Job application page URL fetch took more than 10 seconds to load."
                                )
                                original_job_url = driver.execute_script(
                                    "return window.location.href;"
                                )
                            except Exception as e:
                                logger.warn(
                                    f"Job application page URL fetch failed with error - {e}."
                                )
                                original_job_url = driver.execute_script(
                                    "return window.location.href;"
                                )

                            driver.close()
                            is_reposted_job = True
                            driver.switch_to.window(main_window_handle)
                        else:
                            continue

                    top_card_text = driver.find_element(
                        by=By.CLASS_NAME,
                        value="job-details-jobs-unified-top-card__primary-description-container",
                    ).text
                    post_time_text = [
                        x for x in top_card_text.split("·") if "ago" in x.lower()
                    ][0].strip()
                    post_time_text = " ".join(post_time_text.split()[-3:])
                    job_posted_at = time_ago_to_epoch(post_time_text)

                    jobs.append(
                        {
                            "job_url": original_job_url,
                            "repost_url": linkedin_job_url if is_reposted_job else None,
                            "is_reposted_job": is_reposted_job,
                            "job_posted_at": job_posted_at,
                            "job_description": job_description,
                            "linkedin_easy_apply": linkedin_easy_apply,
                            "is_non_automatable": any(
                                domain in original_job_url
                                for domain in non_automatable_job_boards
                                + non_feasible_domains
                            ),
                        }
                    )
                    jobs_scraped += 1
                except ElementClickInterceptedException as e:
                    logger.warn(
                        f"ElementClickInterceptedException exception occurred while scraping a job - {e}"
                    )
                    raise e
                except Exception as e:
                    logger.exception(
                        f"An unexpected error occurred while scraping a job - {e}"
                    )

            continue_scraping = False
            try:
                pagination_section = driver.find_element(
                    By.XPATH,
                    "//div[contains(@class, 'jobs-search-results-list__pagination')]",
                )
            except NoSuchElementException:
                logger.info(f"Pagination not found. Stopping to scrape further.")
                continue

            ignore_more_pages_button = True
            for page in pagination_section.find_elements(By.XPATH, ".//li"):
                if page.text == str(cur_page):
                    ignore_more_pages_button = False
                if (page.text == str(cur_page + 1)) or (
                    (ignore_more_pages_button is False) and (page.text == "…")
                ):
                    page.click()
                    cur_page += 1
                    continue_scraping = True
                    time.sleep(5)
                    break
        except ElementClickInterceptedException as e:
            logger.warn(
                f"ElementClickInterceptedException exception occurred while scraping page - {e}"
            )
            driver.refresh()
        except Exception as e:
            logger.exception(f"An unexpected error occurred while scraping page - {e}")
            continue_scraping = False

    return jobs
