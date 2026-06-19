import json
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import os
from datetime import datetime
import logging
import re
import random
from urllib.parse import urlparse

# === Config ===
OUTPUT_DIR = "output"
LOG_FILE = "shadowhawk.log"
MAX_WORKERS = 20
TIMEOUT = 15
RETRIES = 2

# === Logger Setup ===
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# === ANSI Colors ===
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15'
]

def load_sites():
    """Загрузка сайтов с созданием дефолтного файла при отсутствии"""
    try:
        with open("sites.json", "r", encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        default_sites = {
            "GitHub": "https://github.com/{}",
            "Twitter": "https://twitter.com/{}",
            "Instagram": "https://instagram.com/{}",
            "Reddit": "https://reddit.com/user/{}",
            "YouTube": "https://youtube.com/@{}",
            "Facebook": "https://facebook.com/{}",
            "LinkedIn": "https://linkedin.com/in/{}",
            "Pinterest": "https://pinterest.com/{}",
            "Tumblr": "https://{}.tumblr.com",
            "VK": "https://vk.com/{}"
        }
        with open("sites.json", "w", encoding='utf-8') as f:
            json.dump(default_sites, f, indent=2, ensure_ascii=False)
        print(CYAN + "[+] Created default sites.json" + RESET)
        return default_sites

def validate_proxy(proxy):
    """Валидация прокси"""
    pattern = r'^(https?|socks4|socks5)://[a-zA-Z0-9\-\.]+:\d+(?:/)?$'
    return re.match(pattern, proxy) is not None

def check_username(site, url_template, username, proxy=None):
    """Проверка username на конкретном сайте с поддержкой прокси и ретраев"""
    url = url_template.format(username)
    
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', random.choice(USER_AGENTS))
            
            opener = urllib.request.build_opener()
            if proxy and validate_proxy(proxy):
                proxy_handler = urllib.request.ProxyHandler({
                    'http': proxy,
                    'https': proxy
                })
                opener = urllib.request.build_opener(proxy_handler)
            
            with opener.open(req, timeout=TIMEOUT) as response:
                if response.status == 200:
                    msg = f"[+] Found on {site}: {url}"
                    print(GREEN + msg + RESET)
                    logging.info(msg)
                    return (site, url, "Found")
                elif response.status == 403:
                    msg = f"[!] Blocked on {site} (403)"
                    print(YELLOW + msg + RESET)
                    return (site, url, "Blocked")
                    
        except urllib.error.HTTPError as e:
            if e.code == 404:
                msg = f"[-] Not found on {site}"
                print(RED + msg + RESET)
                return (site, url, "Not Found")
            elif e.code == 429:
                msg = f"[!] Rate limited on {site}"
                print(YELLOW + msg + RESET)
                return (site, url, "Rate Limited")
            elif e.code == 403:
                msg = f"[!] Access denied on {site}"
                print(YELLOW + msg + RESET)
                return (site, url, "Blocked")
        except urllib.error.URLError as e:
            if attempt < RETRIES - 1:
                logging.warning(f"Retry {attempt+1}/{RETRIES} for {site}: {e}")
                continue
            msg = f"[!] Connection error on {site}"
            print(YELLOW + msg + RESET)
            return (site, url, f"Error: {str(e)}")
        except Exception as e:
            msg = f"[!] Error checking {site}"
            print(YELLOW + msg + RESET)
            logging.error(f"{msg}: {e}")
            return (site, url, f"Error: {str(e)}")
    
    return (site, url, "Not Found")

def search_all(username, proxy=None, max_workers=MAX_WORKERS):
    """Поиск по всем сайтам с многопоточностью"""
    results = []
    sites = load_sites()
    
    print(CYAN + f"[*] Scanning {len(sites)} sites with {max_workers} workers..." + RESET)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(check_username, site, url_template, username, proxy): site
            for site, url_template in sites.items()
        }
        
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception as e:
                site = futures[future]
                logging.error(f"Unexpected error for {site}: {e}")
    
    return results

def extract_emails_and_phones(text):
    """Расширенный парсинг email и телефонов"""
    # Email pattern
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    emails = re.findall(email_pattern, text)
    
    # Phone pattern (международный и местный форматы)
    phone_pattern = r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
    phones = re.findall(phone_pattern, text)
    
    # Уникализация
    emails = list(set(emails))
    phones = list(set(phones))
    
    return emails, phones

def save_results(results):
    """Сохранение результатов в txt и csv"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    txt_file = os.path.join(OUTPUT_DIR, f"results_{timestamp}.txt")
    csv_file = os.path.join(OUTPUT_DIR, f"results_{timestamp}.csv")
    json_file = os.path.join(OUTPUT_DIR, f"results_{timestamp}.json")

    # TXT
    with open(txt_file, "w", encoding='utf-8') as f:
        f.write(f"ShadowHawk OSINT Results - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("="*50 + "\n\n")
        for site, url, status in results:
            f.write(f"{status}: {site} -> {url}\n")
    
    # CSV
    with open(csv_file, "w", newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Site", "URL", "Status"])
        writer.writerows(results)
    
    # JSON
    with open(json_file, "w", encoding='utf-8') as f:
        json.dump({
            "timestamp": timestamp,
            "results": [
                {"site": site, "url": url, "status": status}
                for site, url, status in results
            ]
        }, f, indent=2, ensure_ascii=False)

    found_count = sum(1 for _, _, status in results if status == "Found")
    print(CYAN + f"\n[✓] Results saved to:")
    print(f"    📄 {txt_file}")
    print(f"    📊 {csv_file}")
    print(f"    📋 {json_file}")
    print(f"    🎯 Found: {found_count}/{len(results)} sites" + RESET)
    
    return found_count

def interactive_mode():
    """Интерактивный режим с выбором действий"""
    print(CYAN + "\n🕵️  ShadowHawk OSINT Scanner v2.0" + RESET)
    print(YELLOW + "="*40 + RESET)
    print("1. 🔍 Username Search")
    print("2. 📧 Extract Emails & Phones from Text")
    print("3. ⚙️  Bulk Search (from file)")
    print("4. ℹ️  About")
    print("5. 🚪 Exit")
    
    choice = input("\n📌 Choose option (1-5): ").strip()
    
    if choice == "1":
        username = input("🔎 Enter username: ").strip()
        if not username:
            print(RED + "[!] Username cannot be empty" + RESET)
            return
        
        proxy = input("🌐 Proxy (ip:port or protocol://ip:port, leave blank): ").strip() or None
        if proxy and not validate_proxy(proxy):
            print(YELLOW + "[!] Invalid proxy format, continuing without proxy" + RESET)
            proxy = None
        
        print(f"\n🔍 Searching for '{username}'...\n")
        results = search_all(username, proxy)
        save_results(results)
        print(GREEN + "\n[✓] Search completed!" + RESET)
        
    elif choice == "2":
        sample = input("📝 Paste text to scan (or path to file):\n")
        text = sample
        if os.path.isfile(sample):
            with open(sample, 'r', encoding='utf-8') as f:
                text = f.read()
        
        emails, phones = extract_emails_and_phones(text)
        print("\n" + CYAN + "="*40 + RESET)
        print(f"📧 Emails found ({len(emails)}):")
        for email in sorted(emails):
            print(f"  - {email}")
        print(f"\n📱 Phone numbers found ({len(phones)}):")
        for phone in sorted(phones):
            print(f"  - {phone}")
        print(CYAN + "="*40 + RESET)
        
    elif choice == "3":
        filepath = input("📄 Path to file with usernames (one per line): ").strip()
        if not os.path.isfile(filepath):
            print(RED + "[!] File not found" + RESET)
            return
        
        proxy = input("🌐 Proxy (leave blank): ").strip() or None
        
        with open(filepath, 'r', encoding='utf-8') as f:
            usernames = [line.strip() for line in f if line.strip()]
        
        print(CYAN + f"[*] Scanning {len(usernames)} usernames..." + RESET)
        all_results = {}
        for username in usernames:
            print(f"\n🔍 Searching '{username}'...")
            results = search_all(username, proxy, max_workers=15)
            all_results[username] = results
            save_results(results)
        
        print(GREEN + f"\n[✓] Bulk scan complete for {len(usernames)} usernames" + RESET)
        
    elif choice == "4":
        print(CYAN + """
╔═══════════════════════════════════════╗
║   ShadowHawk OSINT Scanner v2.0      ║
║   Created by Swill Way               ║
║   For educational and research use   ║
╚═══════════════════════════════════════╝
        """ + RESET)
    elif choice == "5":
        print(CYAN + "🦅 ShadowHawk - Stay Safe!" + RESET)
        return
    
    print(CYAN + "\n🦅 ShadowHawk - Stay Safe!" + RESET)

def main():
    """Точка входа"""
    try:
        interactive_mode()
    except KeyboardInterrupt:
        print(YELLOW + "\n[!] Interrupted by user" + RESET)
    except Exception as e:
        print(RED + f"\n[!] Fatal error: {e}" + RESET)
        logging.critical(f"Fatal error: {e}")

if __name__ == "__main__":
    main()
