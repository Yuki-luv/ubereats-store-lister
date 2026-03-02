import pandas as pd
import os
from datetime import datetime

HISTORY_FILE = "scrape_history.csv"

def load_history():
    """履歴ファイルを読み込み、DataFrameを返す。存在しない場合は空のDFを返す。"""
    if os.path.exists(HISTORY_FILE):
        try:
            df = pd.read_csv(HISTORY_FILE)
            return df
        except Exception:
            return pd.DataFrame(columns=["store_name", "url", "address", "last_scraped"])
    return pd.DataFrame(columns=["store_name", "url", "address", "last_scraped"])

def get_seen_urls():
    """履歴にあるURLのセットを返す。"""
    df = load_history()
    if not df.empty:
        return set(df["url"].tolist())
    return set()

def save_to_history(new_stores_list):
    """
    新規店舗リストを履歴に追加保存する。
    重複はURLベースでチェックし、存在しないものだけを追加する。
    """
    if not new_stores_list:
        return 0
    
    df_history = load_history()
    seen_urls = set(df_history["url"].tolist()) if not df_history.empty else set()
    
    to_add = []
    for s in new_stores_list:
        url = s.get("url")
        if url and url not in seen_urls:
            to_add.append({
                "store_name": s.get("store_name", ""),
                "url": url,
                "address": s.get("address_normalized", s.get("address", "")),
                "last_scraped": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            seen_urls.add(url)
    
    if to_add:
        df_new = pd.DataFrame(to_add)
        df_combined = pd.concat([df_history, df_new], ignore_index=True)
        df_combined.to_csv(HISTORY_FILE, index=False, encoding='utf-8-sig')
        return len(to_add)
    
    return 0

def filter_new_stores(stores_list):
    """リストの中から履歴にない店舗のみを返す。"""
    seen_urls = get_seen_urls()
    return [s for s in stores_list if s.get("url") not in seen_urls]
