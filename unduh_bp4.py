import os
import re
import csv
import time
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
)

URL = "https://coretaxdjp.pajak.go.id/registration-portal/id-ID/documents"

# =========================
# CONFIG
# =========================
DOWNLOAD_DIR = str(Path.cwd() / "downloads_coretax")
DOWNLOAD_LOG_FILE = str(Path.cwd() / "downloaded_docs.csv")

JENIS_DOKUMEN_FILTER = "Bukti Potong PPh"
TANGGAL_PEMBUATAN_FILTER = "10-04-2026 - 15-04-2026"

# None = semua halaman
MAX_PAGES = 50

# Profile Chrome yang sudah login
USER_DATA_DIR = r"C:\Users\Faradiani\AppData\Local\Google\Chrome\User Data"
PROFILE_DIR = "Default"
USE_PROFILE = False  # True = pakai profile, False = login manual setiap run

KEEP_BROWSER_OPEN_ON_ERROR = True

WAIT_SHORT = 10
WAIT_MEDIUM = 20
WAIT_LONG = 60

HIDE_AUTOMATION = True

# =========================
# DRIVER
# =========================
def setup_driver():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    chrome_options = Options()
    chrome_options.page_load_strategy = 'eager'  # Lebih cepat
    
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-notifications")
    
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
        "safebrowsing.enabled": True,
        "profile.default_content_setting_values.automatic_downloads": 1,
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    if HIDE_AUTOMATION:
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
    
    if USE_PROFILE and USER_DATA_DIR:
        chrome_options.add_argument(f"--user-data-dir={USER_DATA_DIR}")
        chrome_options.add_argument(f"--profile-directory={PROFILE_DIR}")
        print(f"Using Chrome profile: {USER_DATA_DIR} - {PROFILE_DIR}")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    if HIDE_AUTOMATION:
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

# =========================
# GENERIC HELPERS
# =========================
def safe_click(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(0.4)
    try:
        element.click()
    except (ElementClickInterceptedException, StaleElementReferenceException):
        driver.execute_script("arguments[0].click();", element)

def clear_and_fill(element, text):
    element.click()
    time.sleep(0.2)
    element.send_keys(Keys.CONTROL, "a")
    element.send_keys(Keys.BACKSPACE)
    element.send_keys(text)
    time.sleep(0.4)

def wait_grid_settle(seconds=3):
    time.sleep(seconds)

def wait_for_document_page(driver, timeout=120):
    wait = WebDriverWait(driver, timeout)
    wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//*[contains(normalize-space(.), 'Dokumen')]")
        )
    )
    wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//table | //p-table | //div[contains(@class,'p-datatable')]")
        )
    )

def wait_until_loading_disappears(driver, timeout=20):
    end = time.time() + timeout
    loading_xpaths = [
        "//*[contains(@class,'p-datatable-loading-overlay')]",
        "//*[contains(@class,'p-component-overlay')]",
        "//*[contains(@class,'loading')]",
        "//*[contains(@class,'spinner')]",
        "//*[contains(normalize-space(.), 'Loading')]",
    ]
    
    while time.time() < end:
        found_visible = False
        for xp in loading_xpaths:
            try:
                elems = driver.find_elements(By.XPATH, xp)
                for el in elems:
                    if el.is_displayed():
                        found_visible = True
                        break
                if found_visible:
                    break
            except Exception:
                pass
        
        if not found_visible:
            return True
        time.sleep(0.5)
    return False

def get_row_elements(driver):
    xpaths = [
        "//table/tbody/tr[not(contains(@class,'p-datatable-emptymessage'))]",
        "//p-table//table/tbody/tr[not(contains(@class,'p-datatable-emptymessage'))]",
        "//div[contains(@class,'p-datatable')]//table/tbody/tr[not(contains(@class,'p-datatable-emptymessage'))]",
        "//tr[@role='row']",
    ]
    
    for xp in xpaths:
        rows = driver.find_elements(By.XPATH, xp)
        filtered = []
        for r in rows:
            try:
                txt = r.text.strip()
                if r.is_displayed() and txt:
                    filtered.append(r)
            except Exception:
                pass
        if filtered:
            return filtered
    return []

def has_empty_state(driver):
    empty_xpaths = [
        "//*[contains(@class,'p-datatable-emptymessage')]",
        "//*[contains(normalize-space(.), 'No records found')]",
        "//*[contains(normalize-space(.), 'Tidak ada data')]",
        "//*[contains(normalize-space(.), 'No data')]",
    ]
    
    for xp in empty_xpaths:
        try:
            elems = driver.find_elements(By.XPATH, xp)
            for el in elems:
                if el.is_displayed():
                    return True
        except Exception:
            pass
    return False

def wait_until_rows_or_empty(driver, timeout=30):
    wait_until_loading_disappears(driver, timeout=min(timeout, 15))
    
    end = time.time() + timeout
    while time.time() < end:
        rows = get_row_elements(driver)
        if rows:
            return "rows"
        if has_empty_state(driver):
            return "empty"
        time.sleep(0.5)
    raise TimeoutException("Grid tidak menampilkan row maupun empty state.")

def get_first_document_number(driver):
    rows = get_row_elements(driver)
    if not rows:
        return None
    
    try:
        first_cell = rows[0].find_element(By.XPATH, "./td[1]")
        return first_cell.text.strip()
    except Exception:
        try:
            cells = rows[0].find_elements(By.XPATH, "./td")
            if cells:
                return cells[0].text.strip()
        except Exception:
            pass
    return None

def wait_until_grid_changes(driver, old_first_doc, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        wait_until_loading_disappears(driver, timeout=5)
        current = get_first_document_number(driver)
        
        if old_first_doc is None and current is not None:
            return True
        if current is not None and current != old_first_doc:
            return True
        if has_empty_state(driver):
            return True
        time.sleep(0.5)
    raise TimeoutException("Grid content tidak berubah.")

# =========================
# DOWNLOAD LOG (CSV)
# =========================
def load_downloaded_doc_numbers(log_file):
    downloaded = set()
    if not os.path.exists(log_file):
        return downloaded
    
    with open(log_file, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            doc_number = (row.get("doc_number") or "").strip()
            if doc_number:
                downloaded.add(doc_number)
    return downloaded

def append_download_log(log_file, doc_number, original_filename=""):
    file_exists = os.path.exists(log_file)
    
    with open(log_file, mode="a", newline="", encoding="utf-8") as f:
        fieldnames = ["doc_number", "downloaded_at", "original_filename"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        
        if not file_exists:
            writer.writeheader()
        
        writer.writerow({
            "doc_number": doc_number,
            "downloaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "original_filename": original_filename,
        })

def is_document_already_downloaded(doc_number: str, downloaded_set: set) -> bool:
    return doc_number in downloaded_set

# =========================
# FILTER
# =========================
def set_filter_jenis_dokumen(driver, value):
    print("Mencari field Jenis Dokumen...")
    
    inputs = WebDriverWait(driver, WAIT_MEDIUM).until(
        EC.presence_of_all_elements_located((By.XPATH, "//table/thead//input"))
    )
    
    if len(inputs) < 4:
        raise Exception("Input filter 'Jenis Dokumen' tidak ditemukan.")
    
    jenis_input = inputs[3]
    clear_and_fill(jenis_input, value)
    jenis_input.send_keys(Keys.ENTER)
    
    print(f"Filter Jenis Dokumen diisi: {value}")
    wait_grid_settle(2)

def set_filter_tanggal_pembuatan(driver, value):
    print("Mencari field Tanggal Pembuatan...")
    time.sleep(2)
    
    wait = WebDriverWait(driver, 20)
    tanggal_input = wait.until(
        EC.presence_of_element_located((By.ID, "CreationDatetime"))
    )
    
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tanggal_input)
    time.sleep(1)
    
    driver.execute_script("""
        const el = arguments[0];
        el.removeAttribute('readonly');
        el.readOnly = false;
    """, tanggal_input)
    
    time.sleep(0.5)
    
    driver.execute_script("""
        const el = arguments[0];
        const val = arguments[1];
        el.value = val;
        el.setAttribute('value', val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
    """, tanggal_input, value)
    
    time.sleep(1)
    
    try:
        tanggal_input.click()
        tanggal_input.send_keys(Keys.CONTROL, "a")
        tanggal_input.send_keys(Keys.BACKSPACE)
        tanggal_input.send_keys(value)
        tanggal_input.send_keys(Keys.TAB)
    except Exception:
        pass
    
    time.sleep(2)
    
    actual_value = driver.find_element(By.ID, "CreationDatetime").get_attribute("value")
    print(f"Value Tanggal Pembuatan terbaca: {actual_value}")
    
    if actual_value != value:
        raise TimeoutException(f"Field CreationDatetime tidak berhasil terisi. Expected='{value}', actual='{actual_value}'")
    
    print(f"Filter Tanggal Pembuatan diisi: {value}")
    time.sleep(2)

# =========================
# REFRESH
# =========================
def click_refresh_if_exists(driver):
    print("Mencari tombol Refresh...")
    
    wait = WebDriverWait(driver, 20)
    refresh_btn = wait.until(
        EC.element_to_be_clickable((
            By.XPATH,
            "//button[@ptooltip='Refresh' and @icon='pi pi-refresh']"
        ))
    )
    
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", refresh_btn)
    time.sleep(1)
    
    try:
        refresh_btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", refresh_btn)
    
    print("Refresh grid clicked.")
    wait_until_loading_disappears(driver, timeout=15)
    time.sleep(2)
    return True

# =========================
# DOWNLOAD PER ROW
# =========================
def get_row_data(driver):
    rows = get_row_elements(driver)
    results = []
    
    for idx, row in enumerate(rows, start=1):
        try:
            doc_number = row.find_element(By.XPATH, "./td[1]").text.strip()
        except Exception:
            doc_number = ""
        
        download_btn = None
        btn_xpaths = [
            ".//button[contains(normalize-space(.), 'Unduh')]",
            ".//button[@id='ActionDownloadButton']",
            ".//td[last()]//button",
        ]
        for xp in btn_xpaths:
            try:
                download_btn = row.find_element(By.XPATH, xp)
                break
            except Exception:
                pass
        
        results.append({
            "row_index": idx,
            "doc_number": doc_number,
            "download_btn": download_btn,
        })
    
    return results

def get_new_file_after_download(before_files: set, download_dir: str, timeout: int = 30):
    start = time.time()
    
    while time.time() - start < timeout:
        current_files = set(os.listdir(download_dir))
        new_files = current_files - before_files
        
        temp_files = [f for f in current_files if f.endswith(".crdownload")]
        if temp_files:
            time.sleep(1)
            continue
        
        if new_files:
            for f in new_files:
                if not f.endswith(".crdownload"):
                    return f
        time.sleep(1)
    return ""

def download_all_rows_on_current_page(driver, downloaded_set: set):
    rows = get_row_data(driver)
    print(f"Found {len(rows)} row(s) on current page.")
    
    downloaded_count = 0
    skipped_count = 0
    
    for item in rows:
        doc_number = item["doc_number"]
        
        if not doc_number:
            print(f"Row {item['row_index']}: nomor dokumen kosong, skip.")
            skipped_count += 1
            continue
        
        if is_document_already_downloaded(doc_number, downloaded_set):
            print(f"Row {item['row_index']} | {doc_number}: sudah tercatat di log, skip.")
            skipped_count += 1
            continue
        
        if item["download_btn"] is None:
            print(f"Row {item['row_index']} | {doc_number}: tombol Unduh tidak ditemukan, skip.")
            skipped_count += 1
            continue
        
        retry = 0
        while retry < 3:
            try:
                before_files = set(os.listdir(DOWNLOAD_DIR))
                
                current_rows = get_row_elements(driver)
                if item["row_index"] - 1 >= len(current_rows):
                    print(f"Row {item['row_index']} | {doc_number}: row tidak ditemukan lagi.")
                    break
                
                current_row = current_rows[item["row_index"] - 1]
                
                current_button = None
                btn_xpaths = [
                    ".//button[contains(normalize-space(.), 'Unduh')]",
                    ".//button[@id='ActionDownloadButton']",
                    ".//td[last()]//button",
                ]
                for xp in btn_xpaths:
                    try:
                        current_button = current_row.find_element(By.XPATH, xp)
                        break
                    except Exception:
                        pass
                
                if current_button is None:
                    print(f"Row {item['row_index']} | {doc_number}: tombol tidak ditemukan saat retry.")
                    break
                
                safe_click(driver, current_button)
                print(f"Downloading row {item['row_index']} | {doc_number} ...")
                
                new_file = get_new_file_after_download(before_files, DOWNLOAD_DIR, timeout=30)
                
                append_download_log(DOWNLOAD_LOG_FILE, doc_number, new_file)
                downloaded_set.add(doc_number)
                
                downloaded_count += 1
                time.sleep(2)
                break
                
            except StaleElementReferenceException:
                retry += 1
                print(f"Row {item['row_index']} | {doc_number}: stale, retry {retry}...")
                time.sleep(1.5)
            except Exception as e:
                print(f"Row {item['row_index']} | {doc_number}: gagal download -> {e}")
                break
    
    print(f"Page summary: downloaded={downloaded_count}, skipped={skipped_count}")

# =========================
# PAGINATION
# =========================
def get_active_page_number(driver):
    xpaths = [
        "//p-paginator//*[contains(@class,'p-highlight')]",
        "//div[contains(@class,'p-paginator')]//*[contains(@class,'p-highlight')]",
        "//button[contains(@class,'p-paginator-page') and contains(@class,'p-highlight')]",
    ]
    
    for xp in xpaths:
        elems = driver.find_elements(By.XPATH, xp)
        for el in elems:
            try:
                txt = el.text.strip()
                if txt.isdigit():
                    return int(txt)
            except Exception:
                pass
    return None

def go_next_page(driver, max_wait=60, retries=2):
    old_first_doc = get_first_document_number(driver)
    old_active_page = get_active_page_number(driver)
    
    print(f"Current first document: {old_first_doc}")
    print(f"Current active page: {old_active_page}")
    
    next_locators = [
        (By.XPATH, "//p-paginator//button[contains(@class,'p-paginator-next')]"),
        (By.XPATH, "//p-paginator//button[.//span[contains(@class,'pi-angle-right')]]"),
        (By.XPATH, "//div[contains(@class,'p-paginator')]//button[.//span[contains(@class,'pi-chevron-right') or contains(@class,'pi-angle-right')]]"),
    ]
    
    next_button = None
    for by, locator in next_locators:
        elems = driver.find_elements(by, locator)
        if elems:
            next_button = elems[0]
            break
    
    if not next_button:
        print("Next page button not found.")
        return False
    
    disabled_attr = next_button.get_attribute("disabled")
    class_attr = next_button.get_attribute("class") or ""
    aria_disabled = next_button.get_attribute("aria-disabled")
    
    if disabled_attr is not None or "p-disabled" in class_attr or aria_disabled == "true":
        print("Next page button is disabled.")
        return False
    
    for attempt in range(1, retries + 1):
        try:
            safe_click(driver, next_button)
            print(f"Clicked next page button. Waiting for page content to change... (attempt {attempt})")
        except Exception as e:
            print(f"Failed clicking next page on attempt {attempt}: {e}")
            if attempt == retries:
                return False
            time.sleep(2)
            continue
        
        end_time = time.time() + max_wait
        while time.time() < end_time:
            try:
                wait_until_loading_disappears(driver, timeout=10)
            except Exception:
                pass
            
            new_first_doc = get_first_document_number(driver)
            new_active_page = get_active_page_number(driver)
            
            if new_first_doc and old_first_doc and new_first_doc != old_first_doc:
                print(f"Successfully moved to next page. New first document: {new_first_doc}")
                wait_grid_settle(2)
                return True
            
            if old_active_page is not None and new_active_page is not None and new_active_page != old_active_page:
                print(f"Successfully moved to next page. Active page: {old_active_page} -> {new_active_page}")
                wait_grid_settle(2)
                return True
            
            if has_empty_state(driver):
                print("Next page leads to empty grid state.")
                return True
            
            time.sleep(1)
        
        print(f"Attempt {attempt}: page content still not changed after {max_wait} seconds.")
        
        if attempt < retries:
            time.sleep(3)
    
    print("Paginator clicked, but page content did not change after all retries.")
    return False

# =========================
# MAIN
# =========================
def run_automated_task():
    driver = None
    success = False
    
    try:
        downloaded_set = load_downloaded_doc_numbers(DOWNLOAD_LOG_FILE)
        print(f"Detected {len(downloaded_set)} previously downloaded doc number(s) from CSV log.")
        
        driver = setup_driver()
        print("Opening page...")
        driver.get(URL)
        
        print("\n" + "="*60)
        print("Menunggu halaman dokumen...")
        print("Jika menggunakan profile, seharusnya sudah login.")
        print("Jika belum login, silakan login manual sekarang.")
        print("="*60)
        
        # Tunggu halaman dokumen muncul
        wait_for_document_page(driver, timeout=180)
        print("Document page loaded.")
        
        before_refresh_first_doc = get_first_document_number(driver)
        
        print("Step 1 - Isi filter Jenis Dokumen")
        set_filter_jenis_dokumen(driver, JENIS_DOKUMEN_FILTER)
        
        print("Step 2 - Isi filter Tanggal Pembuatan")
        set_filter_tanggal_pembuatan(driver, TANGGAL_PEMBUATAN_FILTER)
        
        print("Step 3 - Klik Refresh")
        refreshed = click_refresh_if_exists(driver)
        if not refreshed:
            print("Refresh tidak berhasil ditemukan/diklik, lanjut cek grid langsung...")
        
        try:
            wait_until_grid_changes(driver, before_refresh_first_doc, timeout=20)
            print("Grid berubah setelah refresh.")
        except TimeoutException:
            print("Grid tidak berubah setelah refresh. Lanjut cek state grid...")
        
        state = wait_until_rows_or_empty(driver, timeout=30)
        if state == "rows":
            print("Row tabel muncul setelah filter/refresh.")
        else:
            print("Grid kosong setelah filter/refresh. Tidak ada data yang cocok.")
            success = True
            return
        
        page_num = 1
        visited_first_docs = set()
        
        while True:
            if MAX_PAGES is not None and page_num > MAX_PAGES:
                print(f"Stop: sudah mencapai batas MAX_PAGES = {MAX_PAGES}")
                break
            
            current_first_doc = get_first_document_number(driver)
            print(f"\n=== Processing page {page_num} | first doc: {current_first_doc} ===")
            
            if current_first_doc is not None and current_first_doc in visited_first_docs:
                print("Halaman ini sudah pernah diproses. Stop untuk menghindari loop.")
                break
            
            if current_first_doc is not None:
                visited_first_docs.add(current_first_doc)
            
            download_all_rows_on_current_page(driver, downloaded_set)
            
            if MAX_PAGES is not None and page_num >= MAX_PAGES:
                print(f"Stop: hanya memproses sampai {MAX_PAGES} halaman.")
                break
            
            time.sleep(3)
            moved = go_next_page(driver, max_wait=90, retries=2)
            if not moved:
                print("No more pages. Finished.")
                break
            
            state = wait_until_rows_or_empty(driver, timeout=20)
            if state == "empty":
                print("Page berikutnya kosong.")
                break
            
            page_num += 1
        
        print(f"All downloads attempted. Check folder: {DOWNLOAD_DIR}")
        print(f"CSV log file: {DOWNLOAD_LOG_FILE}")
        success = True
        
    except TimeoutException as e:
        print(f"Timeout occurred: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            if success:
                print("Task finished successfully. Browser will close in 5 seconds...")
                time.sleep(5)
                driver.quit()
            else:
                if KEEP_BROWSER_OPEN_ON_ERROR:
                    input("Terjadi error. Browser dibiarkan terbuka. Tekan Enter untuk menutup browser...")
                    driver.quit()
                else:
                    print("Browser will close in 5 seconds...")
                    time.sleep(5)
                    driver.quit()

if __name__ == "__main__":
    if USE_PROFILE:
        print("\n⚠️  Menggunakan Chrome Profile:")
        print(f"   USER_DATA_DIR: {USER_DATA_DIR}")
        print(f"   PROFILE_DIR: {PROFILE_DIR}")
        print("\nPastikan:")
        print("1. Chrome TIDAK sedang berjalan")
        print("2. Profile sudah login ke Coretax")
        print("\n")
    
    run_automated_task()