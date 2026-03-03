"""Quick integration test"""
from scraper import run_scraper
from normalizer import normalize_phone, normalize_address, detect_phone_issues

def status_cb(msg):
    print(f"STATUS: {msg}")

print("=== Starting scrape for 新宿区 (3 stores) ===")
stores, total_count, error_log = run_scraper("新宿区", 3, status_callback=status_cb)

if error_log:
    print(f"\nERROR LOG:\n{error_log}")

print(f"\n=== Results: {len(stores)} stores (Total Found: {total_count}) ===\n")
for i, s in enumerate(stores):
    raw_phone = s.get("phone", "")
    norm_phone = normalize_phone(raw_phone)
    raw_addr = s.get("address", "")
    norm_addr = normalize_address(raw_addr)
    issue = detect_phone_issues(raw_phone, norm_phone)
    
    print(f"--- Store {i+1} ---")
    print(f"  Name:  {s.get('store_name', '')}")
    print(f"  Genre: {s.get('genre', '')}")
    print(f"  Phone: {raw_phone} -> {norm_phone} {issue}")
    print(f"  Addr:  {raw_addr}")
    print(f"  Norm:  {norm_addr}")
    print()
