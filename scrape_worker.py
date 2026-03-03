"""
Uber Eats Japan スクレイピング - サブプロセスとして実行されるスクリプト
Playwright（同期API）を使って店舗情報を取得し、JSONで標準出力に書き出す

使い方:
    python scrape_worker.py <address_query> <max_stores>
"""
import json
import re
import sys
import time
import os
from typing import Optional
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# Windows環境でのリダイレクト時に文字化けを防ぐため、UTF-8固定にする
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, Exception):
        pass


BASE_URL = "https://www.ubereats.com"
FEED_URL = f"{BASE_URL}/jp/feed"


def log(msg: str):
    """進捗ログをJSON形式で標準出力に書き出す"""
    print(json.dumps({"type": "status", "message": msg}), flush=True)


def emit_result(data: list, total_count: int = 0):
    """結果をJSON形式で標準出力に書き出す"""
    print(json.dumps({
        "type": "result", 
        "data": data,
        "total_count": total_count
    }, ensure_ascii=False), flush=True)


def get_store_detail_via_api(page, store_uuid: str) -> dict:
    """内部APIで店舗詳細を取得"""
    try:
        api_url = f"{BASE_URL}/_p/api/getStoreV1"
        payload = {"storeUuid": store_uuid, "sfNuggetCount": 0}
        
        response = page.evaluate("""
            (args) => {
                return new Promise((resolve) => {
                    fetch(args.url, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'x-csrf-token': 'x',
                        },
                        body: JSON.stringify(args.payload),
                        credentials: 'include',
                    })
                    .then(resp => resp.ok ? resp.json() : null)
                    .then(data => resolve(data))
                    .catch(() => resolve(null));
                });
            }
        """, {"url": api_url, "payload": payload})
        
        if not response:
            return {}
        
        return extract_store_info(response)
    except Exception:
        return {}


def extract_store_info(api_response: dict) -> dict:
    """APIレスポンスから店舗情報を抽出"""
    data = api_response.get("data", api_response)
    info = {"store_name": "", "address": "", "genre": "", "phone": ""}
    
    # 店舗名
    info["store_name"] = data.get("title", data.get("name", ""))
    
    # 住所 - 複数のパスを探索
    location = data.get("location", {})
    if isinstance(location, dict):
        info["address"] = location.get("address", "")
        if not info["address"]:
            info["address"] = location.get("streetAddress", "")
        if not info["address"]:
            info["address"] = location.get("formattedAddress", "")
    
    # ジャンル
    categories = data.get("categories", [])
    if categories:
        names = []
        for cat in categories:
            if isinstance(cat, dict):
                n = cat.get("name", cat.get("title", ""))
                if n:
                    names.append(n)
            elif isinstance(cat, str):
                names.append(cat)
        info["genre"] = " / ".join(names)
    
    if not info["genre"]:
        cuisine_list = data.get("cuisineList", [])
        if cuisine_list:
            info["genre"] = " / ".join(cuisine_list)
    
    # 電話番号 - 複数のキーから探索
    for key in ["phoneNumber", "phone", "rawPhoneNumber"]:
        val = data.get(key, "")
        if val:
            info["phone"] = str(val)
            break
    
    # storeInfo 内のデータ
    si = data.get("storeInfo", {})
    if isinstance(si, dict):
        if not info["phone"]:
            info["phone"] = si.get("phoneNumber", "")
        if not info["address"]:
            info["address"] = si.get("address", "")
    
    return info


def scrape_store_page_info(page, store_url: str) -> dict:
    """店舗ページから情報をスクレイピング（フォールバック）"""
    info = {"store_name": "", "address": "", "genre": "", "phone": ""}
    try:
        page.goto(store_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)
        
        # 店舗名
        h1 = page.query_selector('h1')
        if h1:
            info["store_name"] = h1.text_content().strip()
            
        # ページ全体のテキストから電話番号を抽出
        page_text = page.evaluate("() => document.body.innerText")
        
        # 最下部の「店舗の電話番号 : XXXX」から抽出 (スクレイピング)
        phone_match = re.search(r'店舗の電話番号\s*[:：]\s*([+\d\-() ]{8,})', page_text, re.IGNORECASE)
        if phone_match:
            info["phone"] = phone_match.group(1).strip()
        else:
            # 英語などのフォールバック
            phone_match = re.search(r'(?:Phone|TEL|Phone Number)[：:\s]*([+\d\-() ]{8,})', page_text, re.IGNORECASE)
            if phone_match:
                info["phone"] = phone_match.group(1).strip()
        
        # 住所の確実な抽出（H1タグの周辺のDOM構造から取得）
        # Uber Eatsの店舗ページ上部：
        # Line 1: 店舗名(h1)
        # Line 2: 評価等のメタデータ (例: 5.0 ☆ (4) ・ 配達手数料 ¥0 ・ 情報)
        # Line 3: 住所 (例: 田中町1-6 エビスタ西宮 1f Street Kitchen, 西宮市, APAC 662-0973)
        dom_address = page.evaluate("""
            () => {
                const h1 = document.querySelector('h1');
                if (h1 && h1.parentElement) {
                    const parentText = h1.parentElement.innerText;
                    if (parentText) {
                        const lines = parentText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                        // H1以降のテキスト行を順番にチェック
                        for (let i = 1; i < lines.length; i++) {
                            const line = lines[i];
                            // 評価や手数料関連の行をスキップ
                            if (line.includes('☆') || line.includes('★') || line.includes('配達') || line.includes('手数料') || line.includes('¥')) {
                                continue;
                            }
                            // 数字やカンマ、カッコだけの行（レビュー数など）をスキップ (例: "(25,000+)")
                            if (line.match(/^[\\(\\)\\d, +]+$/)) {
                                continue;
                            }
                            // 距離などをスキップ (例: "1.5 km")
                            if (line.match(/^[\\d.,\\s]+k?m$/i)) {
                                continue;
                            }
                            // 短すぎる行、またはジャンル（カテゴリ）名と思われる行をスキップ
                            // ジャンル名は通常短く設定されており、住所には数字やハイフン、特定のキーワードが含まれることが多い
                            if (line.length < 8) {
                                continue;
                            }
                            
                            // 住所っぽい行（文字数、記号、地名など）を返す
                            // 住所には県、市、区、町、数字、ハイフンなどの特徴がある
                            if (!line.includes('メニュー') && !line.includes('AM') && !line.includes('PM')) {
                                // 住所の確度を高めるためのチェック（数字が含まれているか、または都道府県市の文字が含まれているか）
                                if (line.match(/[\\d０-９]/) || line.match(/[都道府県市区町村]/)) {
                                    return line;
                                }
                            }
                        }
                    }
                }
                return "";
            }
        """)
        
        if dom_address:
            info["address"] = dom_address
        else:
            # 万が一DOMで見つからなかった場合のフォールバック正規表現
            address_patterns = [
                r'(?:日本[、,]\s*)?(?:〒\d{3}-\d{4}\s*)?((?:東京都|北海道|京都府|大阪府|.{2,3}県)[^\n]+(?:市区町村|[市区郡])[^\n]+)',
                r'((?:東京都|北海道|京都府|大阪府|.{2,3}県)[^\n]{4,})',
                r'([^\n]+市[^\n]+区[^\n]+[0-9１-９]+[^\n]*)'
            ]
            for pat in address_patterns:
                match = re.search(pat, page_text)
                if match:
                    addr_cand = match.group(1).strip()
                    if len(addr_cand) > 5 and not re.search(r'配達|手数料|分|¥|口コミ|評価|ジャンル|カテゴリー', addr_cand):
                        info["address"] = addr_cand
                        break
                    
    except Exception:
        pass
    
    return info


# 地域名 → URLスラッグ
AREA_SLUG_MAP = {
    "新宿": "shinjuku-tokyo", "新宿区": "shinjuku-tokyo",
    "渋谷": "shibuya-tokyo", "渋谷区": "shibuya-tokyo",
    "港区": "minato-tokyo", "千代田区": "chiyoda-tokyo",
    "中央区": "chuo-tokyo", "品川区": "shinagawa-tokyo",
    "目黒区": "meguro-tokyo", "世田谷区": "setagaya-tokyo",
    "大田区": "ota-tokyo", "杉並区": "suginami-tokyo",
    "中野区": "nakano-tokyo", "豊島区": "toshima-tokyo",
    "北区": "kita-tokyo", "荒川区": "arakawa-tokyo",
    "板橋区": "itabashi-tokyo", "練馬区": "nerima-tokyo",
    "足立区": "adachi-tokyo", "葛飾区": "katsushika-tokyo",
    "江戸川区": "edogawa-tokyo", "台東区": "taito-tokyo",
    "墨田区": "sumida-tokyo", "江東区": "koto-tokyo",
    "文京区": "bunkyo-tokyo",
    "横浜": "yokohama-kanagawa", "横浜市": "yokohama-kanagawa",
    "川崎": "kawasaki-kanagawa", "川崎市": "kawasaki-kanagawa",
    "大阪": "osaka-osaka", "大阪市": "osaka-osaka", "大阪市北区": "osaka-osaka", "大阪市中央区": "osaka-osaka", "大阪市西区": "osaka-osaka", "大阪市浪速区": "osaka-osaka",
    "名古屋": "nagoya-aichi", "名古屋市": "nagoya-aichi", "中区": "nagoya-aichi", "中村区": "nagoya-aichi",
    "福岡": "fukuoka-fukuoka", "福岡市": "fukuoka-fukuoka", "博多区": "fukuoka-fukuoka", "中央区": "fukuoka-fukuoka",
    "札幌": "sapporo-hokkaido", "札幌市": "sapporo-hokkaido", "中央区": "sapporo-hokkaido",
    "仙台": "sendai-miyagi", "仙台市": "sendai-miyagi", "青葉区": "sendai-miyagi",
    "神戸": "kobe-hyogo", "神戸市": "kobe-hyogo", "中央区": "kobe-hyogo",
    "京都": "kyoto-kyoto", "京都市": "kyoto-kyoto", "下京区": "kyoto-kyoto", "中京区": "kyoto-kyoto",
    "広島": "hiroshima-hiroshima", "広島市": "hiroshima-hiroshima", "中区": "hiroshima-hiroshima",
    "さいたま": "saitama-saitama", "さいたま市": "saitama-saitama", "大宮区": "saitama-saitama", "浦和区": "saitama-saitama",
    "千葉": "chiba-chiba", "千葉市": "chiba-chiba", "中央区": "chiba-chiba",
}


def area_to_slug(area_name: str) -> str:
    # 完全に一致するもののみ返すように修正
    # 「大阪市北区」に対して「北区（東京）」が部分一致してしまうのを防ぐため
    return AREA_SLUG_MAP.get(area_name, "")


def collect_store_links(page, max_stores: int, exclude_chains: bool = False, exclude_file: Optional[str] = None) -> list:
    """
    ページから店舗リンクを収集する。
    UUIDは base64エンコード形式（例: HdnURPoeTZ6FPXaCuYbXRw）
    """
    seen_urls = set()
    if exclude_file and os.path.exists(exclude_file):
        try:
            with open(exclude_file, 'r', encoding='utf-8') as f:
                hist_data = json.load(f)
                seen_urls = set(hist_data)
        except Exception:
            pass

    seen_ids = set()
    store_links = []
    scroll_attempts = 0
    
    while len(store_links) < max_stores and scroll_attempts < 30:
        # 店舗リンクを取得（UUID形式を修正: base64エンコード対応）
        links_data = page.evaluate("""
            (args) => {
                const links = [];
                const excludeChains = args.excludeChains;
                const MAJOR_CHAINS = [
                    "マクドナルド", "スターバックス", "ドミノ・ピザ", "ピザハット", "ピザーラ", 
                    "バーガーキング", "ケンタッキー", "吉野家", "すき家", "松屋", "なか卯",
                    "ガスト", "サイゼリヤ", "ジョイフル", "ココス", "デニーズ", "大戸屋", "やよい軒",
                    "モスバーガー", "ロッテリア", "サブウェイ", "フレッシュネスバーガー",
                    "スシロー", "くら寿司", "はま寿司", "かっぱ寿司", "元気寿司",
                    "ココイチ", "CoCo壱番屋", "ほっともっと", "オリジン弁当", "本家かまどや",
                    "タリーズ", "ドトール", "サンマルク", "エクセルシオール", "プロント", "コメダ珈琲",
                    "丸亀製麺", "はなまるうどん", "餃子の王将", "大阪王将", "日高屋", "幸楽苑",
                    "銀だこ", "てんや", "松のや", "マイカリー食堂", "かつや", "ローソン", "セブンイレブン", "ファミリーマート"
                ];
                
                document.querySelectorAll('a[href*="/store/"]').forEach(a => {
                    const href = a.getAttribute('href') || '';
                    if (!href.includes('/jp/store/') && !href.includes('/store/')) return;
                    
                    // URL構造: /jp/store/[slug]/[base64-uuid]
                    // base64 UUID は英数字と -, _ を含む短い文字列
                    const parts = href.split('/store/');
                    if (parts.length < 2) return;
                    const pathAfterStore = parts[1];
                    const segments = pathAfterStore.split('/');
                    const slug = segments[0] || '';
                    const storeId = segments[1] || '';
                    
                    if (!storeId || storeId.length < 5) return;
                    
                    // 店舗名を取得
                    const nameEl = a.querySelector('h3');
                    let name = nameEl ? nameEl.textContent.trim() : '';
                    
                    // h3 が無い場合、最初の意味のあるテキストを取得
                    if (!name) {
                        const spans = a.querySelectorAll('span');
                        for (const span of spans) {
                            const t = span.textContent.trim();
                            if (t && t.length > 2 && t.length < 60 && !t.match(/^[\\d¥.]+/) && !t.includes('分') && !t.includes('km')) {
                                name = t;
                                break;
                            }
                        }
                    }
                    
                    if (!name) return;
                    
                    // 大手チェーンの除外
                    if (excludeChains) {
                        const isChain = MAJOR_CHAINS.some(chain => name.includes(chain));
                        if (isChain) return;
                    }
                    
                    // ジャンル情報を抽出
                    let genre = '';
                    // aタグ内のすべてのテキストを取得し、改行や記号で分割
                    const allText = a.innerText || a.textContent || '';
                    
                    // 評価、時間、手数料などのキーワード
                    const junkPatterns = [/分/, /km/, /¥/, /★/, /☆/, /評価/, /配達/, /手数料/, /無料/];
                    
                    // ジャンルが含まれそうな断片を抽出
                    // 1. セパレーターによる分割
                    const textChunks = allText.split(/[\\n•・·⋅|]/);
                    const genreCandidates = [];
                    
                    for (let p of textChunks) {
                        let t = p.trim();
                        // 条件: 短い、数字のみではない、特定キーワードを含まない、店舗名と一致しない
                        if (t.length > 1 && t.length < 25 && 
                            !t.match(/^[0-9. ()+]+$/) && 
                            !junkPatterns.some(reg => reg.test(t)) &&
                            t !== name) {
                            genreCandidates.push(t);
                        }
                    }
                    
                    // 2. data-testid="store-card-metadata" 等の特定の要素があれば優先的にチェック
                    const meta = a.querySelector('[data-testid="store-card-metadata"]');
                    if (meta) {
                        const metaText = meta.innerText || '';
                        const metaParts = metaText.split(/[\\n•・·⋅|]/);
                        for (let p of metaParts) {
                            let t = p.trim();
                            if (t.length > 1 && t.length < 25 && !t.match(/^[0-9. ()+]+$/) && !junkPatterns.some(reg => reg.test(t)) && t !== name) {
                                if (!genreCandidates.includes(t)) genreCandidates.push(t);
                            }
                        }
                    }

                    genre = genreCandidates.join(' / ');
                    
                    links.push({
                        name: name.substring(0, 80),
                        href: href,
                        storeId: storeId,
                        genre: genre,
                    });
                });
                return links;
            }
        """, {"excludeChains": exclude_chains})
        
        new_found = 0
        for link in links_data:
            sid = link["storeId"]
            full_url = link["href"] if link["href"].startswith("http") else BASE_URL + link["href"]
            
            if sid and sid not in seen_ids and full_url not in seen_urls:
                seen_ids.add(sid)
                store_links.append({
                    "name": link["name"],
                    "url": full_url,
                    "store_id": sid,
                    "genre": link["genre"],
                })
                new_found += 1
        
        if new_found > 0:
            log(f"店舗リストを収集中... ({len(store_links)}件)")
        
        if len(store_links) >= max_stores:
            break
        
        # スクロールで追加読み込み
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(1500)
        scroll_attempts += 1
        
        # 一定回数新しいものが見つからなければ終了
        if new_found == 0 and scroll_attempts > 8:
            break
    
    return store_links[:max_stores]


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"type": "error", "message": "使用法: python scrape_worker.py <地域名> <最大件数> [--exclude-chains]"}))
        sys.exit(1)
    
    address_query = sys.argv[1]
    max_stores = int(sys.argv[2])
    exclude_chains = "--exclude-chains" in sys.argv
    exclude_file = None
    if "--exclude-file" in sys.argv:
        idx = sys.argv.index("--exclude-file")
        if idx + 1 < len(sys.argv):
            exclude_file = sys.argv[idx + 1]
    
    stores = []
    
    with sync_playwright() as p:
        log("ブラウザを起動中...")
        
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled']
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            geolocation={"longitude": 139.6917, "latitude": 35.6895},
            permissions=["geolocation"],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        
        # 検索キーワードに基づいてジオロケーションを調整
        if "大阪" in address_query:
            context.set_geolocation({"longitude": 135.5023, "latitude": 34.6937})
        elif "名古屋" in address_query:
            context.set_geolocation({"longitude": 136.9066, "latitude": 35.1815})
        elif "福岡" in address_query:
            context.set_geolocation({"longitude": 130.4017, "latitude": 33.5904})
        
        try:
            # --- Step 1: ページアクセス ---
            slug = area_to_slug(address_query)
            
            # Cityページは20〜30件しか表示されないため、大量取得時はフィード検索を使う
            use_city_page = bool(slug) and max_stores <= 25
            
            if use_city_page:
                log(f"都市ページにアクセス中... ({slug})")
                page.goto(f"{BASE_URL}/jp/city/{slug}", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4000)
            else:
                # フィードページで住所を入力して検索（無限スクロール可能）
                log("Uber Eats Japan にアクセス中...")
                page.goto(FEED_URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)
                page.screenshot(path="debug_step1_loaded.png")
                
                # クッキー同意ダイアログを閉じる
                for cookie_sel in [
                    'button:has-text("OK")',
                    'button:has-text("同意")',
                    'button:has-text("Accept")',
                    '[data-testid="accept-button"]',
                ]:
                    try:
                        btn = page.query_selector(cookie_sel)
                        if btn:
                            btn.click()
                            page.wait_for_timeout(1000)
                            break
                    except Exception:
                        continue
                
                log(f"住所「{address_query}」を入力中...")
                
                # 入力フィールドを取得
                input_el = None
                for sel in [
                    '[data-testid="address-input"]',
                    '[data-testid="location-typeahead-input"]',
                    'input[id="location-typeahead-home-input"]',
                    'input[aria-label*="住所"]',
                    'input[placeholder*="住所"]',
                    'input[placeholder*="Address"]',
                    'input[type="text"]',
                ]:
                    try:
                        input_el = page.wait_for_selector(sel, timeout=3000)
                        if input_el:
                            input_el.click()
                            page.screenshot(path="debug_step2_clicked.png")
                            break
                    except Exception:
                        continue
                
                if not input_el:
                    log("警告: 入力フィールドが見つかりませんでした。Enterキーによる続行を試みます。")
                    page.keyboard.type(address_query, delay=100)
                    page.keyboard.press("Enter")
                else:
                    # 入力欄をクリアにする（既存の値を全選択して削除）
                    input_el.click()
                    page.wait_for_timeout(500)
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.wait_for_timeout(500)
                    
                    # 文字を入力
                    input_el.fill(address_query)
                    page.wait_for_timeout(1000)
                    
                    # 入力された内容を再確認
                    current_val = input_el.input_value()
                    if not current_val:
                        log("再入力中...")
                        input_el.type(address_query, delay=10)
                
                page.screenshot(path="debug_step3_typed.png")
                
                # サジェストを待ってクリック
                suggestion_clicked = False
                log("サジェストを確認中...")
                
                # サジェストが出るまで少し待機を強める
                page.wait_for_timeout(2000)
                
                for _ in range(12): # 最大約12秒待機
                    for sel in [
                        '[data-testid="location-suggestion"]',
                        'ul[role="listbox"] li',
                        '[role="option"]',
                        'li[role="option"]',
                        'div[aria-label*="住所"]',
                    ]:
                        try:
                            suggestions = page.query_selector_all(sel)
                            if suggestions:
                                # 最初の有効なサジェストをクリック
                                for sug in suggestions:
                                    text = sug.text_content() or ""
                                    if text.strip():
                                        sug.click()
                                        suggestion_clicked = True
                                        log(f"サジェストを選択しました: {text.strip()[:20]}...")
                                        break
                            if suggestion_clicked: break
                        except Exception:
                            continue
                    if suggestion_clicked: break
                    page.wait_for_timeout(1000)
                
                if not suggestion_clicked:
                    log("サジェストが見つかりませんでした。Enterキーを送信します。")
                    page.keyboard.press("Enter")
                
                # サジェスト選択後、またはEnter後の画面遷移を待つ
                page.wait_for_timeout(3000)
                
                # 「配達時間」や「今すぐ配達」などのモーダル、または配達ボタンが出る場合
                for confirm_sel in [
                    'button[data-testid="delivery-mode-button"]',
                    'button:has-text("配達")',
                    'button:has-text("今すぐ配達")',
                    'button:has-text("検索")',
                    'button:has-text("Done")',
                    'form button[type="submit"]',
                ]:
                    try:
                        btn = page.query_selector(confirm_sel)
                        if btn and btn.is_visible():
                            btn.click()
                            page.wait_for_timeout(2000)
                            break
                    except Exception:
                        continue
                
                # 店舗リンクが現れるまで最大20秒待機
                try:
                    page.wait_for_selector('a[href*="/store/"]', timeout=20000)
                except Exception:
                    page.wait_for_timeout(5000)
                
                page.screenshot(path="debug_step4_result.png")
            
            # --- Step 2: 店舗リンクを収集 ---
            log(f"店舗リストを収集中... (目標: {max_stores}件{'、大手チェーン除外' if exclude_chains else ''})")
            
            # --- 追加: 地域全体の店舗数（合計件数）を抽出 ---
            total_count_text = ""
            try:
                # 「◯◯件以上のレストラン」などのテキストを探す
                # 複数のセレクタを試す
                for sel in ["h1", "h2", "[data-testid='feed-header']"]:
                    el = page.query_selector(sel)
                    if el:
                        text = el.text_content()
                        # 「件」が含まれていて数字が含まれている場合に合計数と見なす
                        if "件" in text and any(c.isdigit() for c in text):
                            total_count_text = text
                            break
            except:
                pass
            
            total_count = 0
            if total_count_text:
                # 数字部分だけ抽出 (例: "542件以上の店舗" -> 542)
                nums = re.findall(r'(\d+)', total_count_text)
                if nums:
                    total_count = int(nums[0])
            
            # 1. 地域名から店舗リスト（リンク）を取得
            store_links = collect_store_links(page, max_stores, exclude_chains, exclude_file)
            
            if not store_links:
                page.screenshot(path="debug_screenshot.png")
                log("店舗が見つかりませんでした。別の地域名をお試しください。")
                emit_result([], total_count=0)
                browser.close()
                return
            
            # 発見した件数とサイト表示の合計数の大きい方を採用
            found_count = len(store_links)
            display_total = max(found_count, total_count)
            
            log(f"{found_count}件の店舗を発見（地域合計: 約{display_total}件）。詳細情報を取得中...")
            
            # --- Step 3: 各店舗の詳細を取得 ---
            for i, store_link in enumerate(store_links):
                name = store_link["name"]
                url = store_link["url"]
                store_id = store_link["store_id"]
                genre = store_link["genre"]
                
                log(f"店舗情報を取得中... ({i+1}/{found_count}): {name}")
                
                # まずAPIで試す
                info = get_store_detail_via_api(page, store_id)
                
                # APIで取れなかったら店舗ページのモーダルからスクレイピング
                if not info.get("store_name") or not info.get("phone"):
                    page_info = scrape_store_page_info(page, url)
                    # APIの結果とマージ（APIの方を優先）
                    for key in ["store_name", "address", "genre", "phone"]:
                        if not info.get(key) and page_info.get(key):
                            info[key] = page_info[key]
                
                # リストからの情報で補完
                if not info.get("store_name"):
                    info["store_name"] = name
                if not info.get("genre") and genre:
                    info["genre"] = genre
                
                info["url"] = url
                
                # 必要なキーを保証
                for k in ["store_name", "address", "genre", "phone", "url"]:
                    info.setdefault(k, "")
                
                stores.append(info)
                page.wait_for_timeout(300)
        
        except Exception as e:
            log(f"エラー: {str(e)}")
            try:
                if 'page' in locals() and not page.is_closed():
                    page.screenshot(path="debug_screenshot.png")
            except:
                pass
        finally:
            browser.close()
    
    emit_result(stores, total_count=display_total if 'display_total' in locals() else len(stores))


if __name__ == "__main__":
    main()
