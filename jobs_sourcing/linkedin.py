from selenium.webdriver.common.by import By
import time
from urllib.parse import urlparse, parse_qs

from utilities import time_ago_to_epoch
from utilities.selenium import get_selenium_driver


def extract_linkedin_jobs():
    driver = get_selenium_driver(headless=False)
    url = "https://linkedin.com"
    driver.get(url)

    input("Please log into Linkedin and then press any key to continue...")

    url = "https://www.linkedin.com/jobs/search/?currentJobId=3909159410&f_E=4%2C5%2C6&f_TPR=r604800&f_WT=2&geoId=102713980&keywords=software&location=India&origin=JOB_SEARCH_PAGE_JOB_FILTER&refresh=true"
    driver.get(url)
    time.sleep(5)

    jobs = []
    jobs_count = driver.find_element(
        by=By.CLASS_NAME, value="jobs-search-results-list__subtitle"
    ).text
    jobs_count = int(jobs_count.split()[0])
    jobs_side_panel = driver.find_element(
        by=By.CLASS_NAME, value="jobs-search-results-list"
    )
    jobs_list = driver.find_element(
        by=By.CLASS_NAME, value="scaffold-layout__list-container"
    )
    jobs_scraped = 0
    cur_page = 1
    continue_scraping = True
    while (jobs_scraped <= min(jobs_count, 500)) and continue_scraping:
        for job in jobs_list.find_elements(By.XPATH, "./*"):
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
            linkedin_job_url = f"https://www.linkedin.com/jobs/view/{job_id}"

            job_description = driver.find_element(
                by=By.CLASS_NAME, value="jobs-search__job-details--wrapper"
            ).text
            linkedin_easy_apply = True if "Easy Apply" in job_description else False

            if linkedin_easy_apply:
                original_job_url = linkedin_job_url
                is_reposted_job = False
            else:
                apply_buttons = driver.find_elements(
                    by=By.CLASS_NAME, value="jobs-apply-button--top-card"
                )
                if apply_buttons:
                    main_window_handle = driver.current_window_handle
                    apply_buttons[0].click()
                    new_tab_handle = [
                        handle
                        for handle in driver.window_handles
                        if handle != main_window_handle
                    ][0]
                    driver.switch_to.window(new_tab_handle)
                    original_job_url = driver.current_url
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
                    "job_url": original_job_url.split("?")[0],
                    "repost_url": linkedin_job_url if is_reposted_job else None,
                    "is_reposted_job": is_reposted_job,
                    "job_posted_at": job_posted_at,
                    "job_description": job_description,
                    "linkedin_easy_apply": linkedin_easy_apply,
                }
            )
            jobs_scraped += 1

        continue_scraping = False
        pagination_section = driver.find_element(
            by=By.CSS_SELECTOR,
            value=".artdeco-pagination__pages.artdeco-pagination__pages--number",
        )
        ignore_more_pages_button = True
        for page in pagination_section.find_elements(By.XPATH, "./*"):
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

    driver.quit()

    return jobs
