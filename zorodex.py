import os
import re
import time
import json
import requests
import tkinter as tk
from tkinter import filedialog
from tqdm import tqdm
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# -------------------- Utility Functions --------------------

def pick_download_folder():
    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Choose Download Folder")
    return folder or "."

def parse_selection(input_str, max_index):
    indices = set()
    for token in input_str.split(","):
        token = token.strip()
        if "-" in token:
            start, end = map(int, token.split("-"))
            indices.update(range(start, end + 1))
        else:
            indices.add(int(token))
    return sorted(i for i in indices if 0 <= i < max_index)


def save_download_links(anime_name, links, folder):
    os.makedirs(folder, exist_ok=True)
    filename = os.path.join(folder, f"{anime_name}_download_links.json")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(links, f, indent=2)
    print(f"\n\tSaved all links to {filename}")

# -------------------- Selenium/BeautifulSoup Scrapers --------------------

def resolve_friendly_url(url: str) -> str:
    options = uc.ChromeOptions()
    options.headless = True
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = uc.Chrome(options=options)
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/anime/']"))
        )
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/anime/']"):
            href = a.get_attribute("href")
            if "/anime/" in href:
                return href
        return None
    finally:
        driver.quit()

def scrape_episodes(url):
    options = uc.ChromeOptions()
    options.headless = True
    driver = uc.Chrome(options=options)
    all_episodes = []

    try:
        driver.get(url)

        # Get anime name
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "anime-header")))
        header = driver.find_element(By.CLASS_NAME, "anime-header")
        raw_title = header.find_element(By.TAG_NAME, "h1").text.strip()
        anime_name = raw_title.splitlines()[0].strip()


        # Click download tab to reveal episode links
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "label.btn.btn-dark.btn-sm"))
        ).click()

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/play/']"))
        )

        while True:
            WebDriverWait(driver, 10).until(
                lambda d: len(d.find_elements(By.CSS_SELECTOR, "a[href^='/play/']")) > 0
            )
            time.sleep(1)  # let JS settle

            soup = BeautifulSoup(driver.page_source, "html.parser")
            episode_links = soup.select("a[href^='/play/']")
            
            if not episode_links:
                break  # no episodes found

            # Track to detect pagination stall
            current_first_text = episode_links[0].text.strip()
            if 'last_seen_text' in locals() and current_first_text == last_seen_text:
                print("[-] Episode list didn't change, breaking pagination loop.")
                break

            episodes = [(a.text.strip(), f"https://animepahe.ru{a['href']}") for a in episode_links]
            all_episodes.extend(episodes)

            last_seen_text = current_first_text  # update after checking

            try:
                try:
                    page_nav = driver.find_element(By.CSS_SELECTOR, "nav[aria-label='Page navigation']")
                except Exception:
                    break
                
                next_btn = page_nav.find_element(By.CSS_SELECTOR, "a.page-link.next-page")
                li_parent = next_btn.find_element(By.XPATH, "..")
                if "disabled" in li_parent.get_attribute("class"):
                    break

                next_btn.click()
                time.sleep(1)  # give time to switch pages
            except Exception as e:
                print(f"[-] Done or failed to go next: {e}")
                break



    except Exception as e:
        print(f"[-] Error scraping: {e}")
    finally:
        driver.quit()

    # Deduplicate while preserving order
    seen = set()
    unique_episodes = []
    for title, url in reversed(all_episodes):
        if url not in seen:
            seen.add(url)
            unique_episodes.append((title, url))
    
    return list(reversed(unique_episodes)), anime_name


def extract_download_link(url, preferred_quality="1080p"):
    options = uc.ChromeOptions()
    options.headless = True
    driver = uc.Chrome(options=options)
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "downloadMenu"))).click()
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        quality_links = {}
        for a in soup.select("#pickDownload a"):
            text = a.text.strip()
            href = a.get("href")
            if "1080p" in text:
                return href
            elif "720p" in text:
                quality_links["720p"] = href
            elif "480p" in text:
                quality_links["480p"] = href
        return quality_links.get("720p") or quality_links.get("480p")
    finally:
        driver.quit()

def resolve_final_kwik_link(url):
    options = uc.ChromeOptions()
    options.headless = True
    driver = uc.Chrome(options=options)
    while True:
        try:
            driver.get(url)
            time.sleep(6)
            kwik_link = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//a[text()="Continue"]'))
            )
            href = kwik_link.get_attribute("href")
            if kwik_link:
                kwik_link.click()
                break
            else:
                driver.refresh()
        except:
            print("Error in continueing to download page")
            driver.quit()
    return href

def extract_final_download_link(url):
    options = uc.ChromeOptions()
    options.headless = True
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = uc.Chrome(options=options)
    download_url = None
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//button[@type="submit"]'))
        ).click()
        print("[+] Download button clicked, waiting for GET request")
        time.sleep(2)

        episode_count = 1
        for entry in driver.get_log("performance"):
            msg = entry.get("message")
            if not msg:
                continue
            try:
                msg_json = json.loads(msg)
                params = msg_json.get("message", {}).get("params", {})
                request = params.get("request", {})
                url = request.get("url", "")
                if url.startswith("https://") and ".mp4" in url:
                    download_url = url
                    print(f"[✓] Found download URL for episode: {episode_count}")
                    episode_count += 1
                    break
            except Exception:
                continue
    except Exception as e:
        print(f"Error in extracting GET request: {e}")
    finally:
        driver.quit()
    return download_url

# -------------------- Download Functions --------------------

def download_video(url, anime_name, ep_num, folder, retries=3, delay=5):
    filename = f"{anime_name} EP{ep_num.zfill(3)}.mp4"
    full_path = os.path.join(folder, filename)

    for attempt in range(1, retries + 1):
        print(f"Attempt {attempt} to download {filename}")
        try:
            with requests.get(url, stream=True, timeout=20) as r:
                r.raise_for_status()
                with open(full_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            print(f"[✓] Downloaded {filename}")
            return
        except Exception as e:
            print(f"[-] Failed on attempt {attempt} for {filename}: {e}")
            if attempt < retries:
                print(f"[↻] Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                print(f"[✗] Giving up on {filename} after {retries} attempts.")


def download_from_saved_links(anime_name, folder):
    filename = os.path.join(folder, f"{anime_name}_download_links.json")
    if not os.path.exists(filename):
        print("[-] Link file not found.")
        return
    with open(filename, "r", encoding="utf-8") as f:
        links = json.load(f)
    for entry in tqdm(links, desc="Downloading", unit="ep", dynamic_ncols=True):
        ep_num = entry["episode"]
        url = entry["url"]
        tqdm.write(f"[→] EP{ep_num}")
        download_video(url, anime_name, ep_num, folder)



def sanitize_name(name):
    # Remove control characters and invalid file path characters
    name = name.strip()
    name = re.sub(r'[<>:"/\\|?*\n\r\t]', '', name)
    name = re.sub(r'\s+', ' ', name)  # collapse multiple spaces
    return name


# -------------------- Main Script --------------------
def main():
    print("""
#  $$$$$$$$\                              $$$$$$$\                      
#  \____$$  |                             $$  __$$\                     
#      $$  / $$$$$$\   $$$$$$\   $$$$$$\  $$ |  $$ | $$$$$$\  $$\   $$\ 
#     $$  / $$  __$$\ $$  __$$\ $$  __$$\ $$ |  $$ |$$  __$$\ \$$\ $$  |
#    $$  /  $$ /  $$ |$$ |  \__|$$ /  $$ |$$ |  $$ |$$$$$$$$ | \$$$$  / 
#   $$  /   $$ |  $$ |$$ |      $$ |  $$ |$$ |  $$ |$$   ____| $$  $$<  
#  $$$$$$$$\\$$$$$$  |$$ |      \$$$$$$  |$$$$$$$  |\$$$$$$$\ $$  /\$$\ 
#  \________|\______/ \__|       \______/ \_______/  \_______|\__/  \__|
""")
    download_dir = pick_download_folder()
    print(f"[+] Download location set to: {download_dir}")
    input_url = input("Enter the AnimePahe URL (e.g. https://animepahe.ru/anime/...): ").strip()
    if "/anime/" not in input_url:
        input_url = resolve_friendly_url(input_url)
        if not input_url:
            print("[-] Failed to resolve URL.")
            exit(1)
    

    # Scrape all episodes first
    episodes, anime_name = scrape_episodes(input_url)
    # Center the anime name in the terminal
    if hasattr(anime_name, 'text'):
        anime_name_str = anime_name.text.strip()
    else:
        anime_name_str = str(anime_name).strip()
    terminal_width = os.get_terminal_size().columns
    print(f"{anime_name_str.center(terminal_width)}")
    
    total_eps = len(episodes)

    if not episodes:
        print("[-] No episodes found")
        exit(1)

    print(f"\tTotal episodes found: {total_eps}")

    # Now prompt for selection
    selection = input("\tSelect episodes (1-30, 90): ").strip()
    selected_indices = [i - 1 for i in parse_selection(selection, total_eps)]


    download_links = []
    for i in selected_indices:
        title, play_url = episodes[i]
        ep_num = str(i + 1).zfill(3)

        print(f"[+] Resolving download link for episode {ep_num}")
        intermediate = extract_download_link(play_url)
        if not intermediate:
            print(f"[-] Could not resolve download link for ep {ep_num}")
            continue
        final_url = resolve_final_kwik_link(intermediate)
        if not final_url:
            print(f"[-] Failed to resolve final link for ep {ep_num}")
            continue
        download_url = extract_final_download_link(final_url)
        if not download_url:
            print(f"[-] Failed to extract download URL for ep {ep_num}")
            continue
        download_links.append({
            "episode": ep_num,
            "url": download_url
        })

    sanitized_name = sanitize_name(anime_name_str)

    save_download_links(sanitized_name, download_links, download_dir)
    download_from_saved_links(sanitized_name, download_dir)



if __name__ == '__main__':
    main()
