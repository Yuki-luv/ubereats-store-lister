"""
Uber Eats Japan 店舗リスト取得ツール
コールセンター業務向けUI
"""
import streamlit as st
import pandas as pd
import io
import time
from datetime import datetime
import json
import base64
from scraper import run_scraper
from normalizer import normalize_phone, normalize_address, detect_phone_issues, detect_address_issues
import history
import streamlit.components.v1 as components
import streamlit as st
import os

# オンライン環境の時だけ、ブラウザ本体を強制的にインストールする
if os.environ.get("STREAMLIT_SERVER_PORT"):
    os.system("playwright install chromium")

# --- 認証機能：これより上に追加 ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if not st.session_state.password_correct:
        st.title("🔒 ログイン")
        pwd = st.text_input("パスワード", type="password")
        if st.button("ログイン"):
            if pwd == st.secrets["password"]: # StreamlitのSecretsに設定したパスワード
                st.session_state.password_correct = True
                st.rerun()
            else:
                st.error("パスワードが違います")
        return False
    return True

if not check_password():
    st.stop() # パスワードが通るまで、下の既存コードを読み込ませない

# --- ここから下に、今の app.py の中身を全部そのまま貼る ---


# ───────────────────────────────────────────
# ページ設定
# ───────────────────────────────────────────
st.set_page_config(
    page_title="UberEats 店舗リスト取得",
    page_icon="🍔",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ───────────────────────────────────────────
# カスタムCSS（UberEats風のクリーンなUI）
# ───────────────────────────────────────────
st.markdown("""
<style>
    /* Google Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&display=swap');
    
    * {
        font-family: 'Helvetica Neue', Helvetica, Arial, 'Noto Sans JP', sans-serif;
    }
    
    /* ヘッダー */
    .app-header {
        background-color: #000000;
        color: white;
        padding: 1.5rem 2rem;
        border-radius: 8px;
        margin-bottom: 2rem;
        display: flex;
        align-items: center;
        gap: 1.5rem;
    }
    .app-header h1 {
        margin: 0;
        font-size: 2rem;
        font-weight: 700;
        color: white;
        letter-spacing: -0.5px;
    }
    .app-header p {
        margin: 0.4rem 0 0 0;
        font-size: 0.95rem;
        color: #e2e2e2;
    }
    .header-icon {
        font-size: 3rem;
    }
    
    /* Uber緑のアクセント */
    .uber-green {
        color: #06C167;
    }
    
    /* 検索ボックスエリア */
    .search-area {
        background: #ffffff;
        border: 1px solid #e2e2e2;
        border-radius: 8px;
        padding: 1.5rem;
        margin-bottom: 2rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
    }
    
    /* 統計カード */
    .stat-card {
        background: #ffffff;
        border: 1px solid #e2e2e2;
        border-radius: 8px;
        padding: 1.5rem 1rem;
        text-align: center;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
        margin-bottom: 1rem;
    }
    .stat-number {
        font-size: 2.2rem;
        font-weight: 700;
        color: #000000;
    }
    .stat-label {
        font-size: 0.85rem;
        color: #545454;
        margin-top: 0.4rem;
        font-weight: 500;
    }
    
    /* ボタンスタイル */
    .stButton > button {
        background-color: #06C167;
        color: white;
        border: none;
        padding: 0.75rem 2rem;
        border-radius: 8px;
        font-weight: 700;
        font-size: 1.05rem;
        transition: background-color 0.2s;
    }
    .stButton > button:hover {
        background-color: #049e54;
        color: white;
    }
    
    /* ダウンロードボタン特化 */
    div[data-testid="stDownloadButton"] > button {
        background-color: #000000;
        color: white;
    }
    div[data-testid="stDownloadButton"] > button:hover {
        background-color: #333333;
        color: white;
    }
    
    /* 免責事項 */
    .disclaimer {
        background: #f6f6f6;
        border-left: 4px solid #06C167;
        padding: 1rem 1.2rem;
        font-size: 0.85rem;
        color: #545454;
        margin-top: 2rem;
        border-radius: 0 4px 4px 0;
    }
</style>
""", unsafe_allow_html=True)

# ───────────────────────────────────────────
# ヘッダー
# ───────────────────────────────────────────
st.markdown("""
<div class="app-header">
    <div class="header-icon">🍔</div>
    <div>
        <h1>Uber Eats<span class="uber-green">型</span> 店舗リスト抽出</h1>
        <p>コールセンターのアウトバウンド架電業務に特化した連絡先リスト作成ツール</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ───────────────────────────────────────────
# セッション状態の初期化
# ───────────────────────────────────────────
if "results" not in st.session_state:
    st.session_state.results = None
if "search_query" not in st.session_state:
    st.session_state.search_query = ""

# ───────────────────────────────────────────
# 検索エリア
# ───────────────────────────────────────────
st.markdown("### 検索条件設定")
col_input, col_count = st.columns([3, 1])

with col_input:
    area_input = st.text_input(
        "📍 お届け先の住所・地域",
        placeholder="例: 新宿区、東京都港区六本木...",
        label_visibility="visible",
    )

with col_count:
    max_stores = st.number_input(
        "最大取得数",
        min_value=10,
        max_value=300,
        value=100,
        step=10,
    )

col_chk, col_btn = st.columns([3, 1])

with col_chk:
    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
    exclude_chains = st.checkbox("🍔 大手チェーン店（マクドナルド, スタバ等）を除外する", value=True, help="すき家、マクドナルド、吉野家、コメダ珈琲店などの大手 franchise を除外します。")
    exclude_history = st.checkbox("過去に取得した店舗を除外", value=False, help="履歴ファイル（scrape_history.csv）にある店舗を除外します。")

with col_btn:
    search_clicked = st.button("検索する", use_container_width=True)



# ───────────────────────────────────────────
# 検索処理
# ───────────────────────────────────────────
if search_clicked and area_input:
    st.session_state.search_query = area_input
    
    progress_bar = st.progress(0, text="準備中...")
    status_text = st.empty()
    
    def update_progress(val):
        progress_bar.progress(val, text=f"取得中... {int(val * 100)}%")
    
    def update_status(msg):
        status_text.markdown(f"⏳ **{msg}**")
    
    with st.spinner("店舗リストを検索しています..."):
        # 1. 履歴の読み込み
        seen_urls = history.get_seen_urls() if exclude_history else set()
        
        # 2. スクレイピング実行
        raw_results, total_found_on_site = run_scraper(
            address_query=area_input,
            max_stores=max_stores,
            exclude_chains=exclude_chains,
            progress_callback=update_progress,
            status_callback=update_status,
            exclude_urls=seen_urls
        )
    
    progress_bar.empty()
    status_text.empty()
    
    if raw_results:
        # 3. データの加工と履歴によるフィルタリング
        processed = []
        new_count = 0
        total_found = len(raw_results)
        
        for i, store in enumerate(raw_results):
            url = store.get("url", "")
            is_new = url not in seen_urls
            
            # 除外設定がオンで、かつ既知の店舗ならスキップ
            if exclude_history and not is_new:
                continue
                
            if is_new:
                new_count += 1
            
            raw_phone = store.get("phone", "")
            raw_address = store.get("address", "")
            genre = store.get("genre", "")
            normalized_phone = normalize_phone(raw_phone)
            normalized_address = normalize_address(raw_address, genre=genre)
            
            processed.append({
                "no": len(processed) + 1, # Re-number after filtering
                "store_name": store.get("store_name", ""),
                "url": url,
                "genre": genre,
                "phone_normalized": normalized_phone,
                "phone_raw": raw_phone,
                "phone_issue": detect_phone_issues(raw_phone, normalized_phone),
                "address_normalized": normalized_address,
                "address_raw": raw_address,
                "address_issue": detect_address_issues(raw_address, normalized_address),
                "is_new": is_new
            })
        
        st.session_state.results = processed
        
        # 統計の表示
        if total_found > 0 or total_found_on_site > 0:
            display_total = max(total_found, total_found_on_site)
            cols = st.columns(3)
            cols[0].metric("合計発見数", f"{display_total} 件")
            cols[1].metric("新規店舗数", f"{new_count} 件")
            cols[2].metric("除外済み（履歴）", f"{display_total - new_count} 件")
    else:
        st.session_state.results = []
        st.error("指定された地域で店舗が見つかりませんでした。別の地域名や詳しい住所を試してみてください。")


# ───────────────────────────────────────────
# 結果表示
# ───────────────────────────────────────────
if st.session_state.results is not None:
    data = st.session_state.results
    
    if data:
        # --- 統計カード ---
        total = len(data)
        with_phone = sum(1 for d in data if d["phone_normalized"])
        without_phone = total - with_phone
        phone_issues = sum(1 for d in data if d["phone_issue"])
        
        st.markdown("### 取得結果サマリー")
        cols = st.columns(4)
        with cols[0]:
            st.markdown(f"""
            <div class="stat-card">
                <div class="stat-number">{total}</div>
                <div class="stat-label">総取得店舗数</div>
            </div>
            """, unsafe_allow_html=True)
        with cols[1]:
            st.markdown(f"""
            <div class="stat-card" style="border-bottom: 4px solid #06C167;">
                <div class="stat-number" style="color:#06C167">{with_phone}</div>
                <div class="stat-label">架電可能（電話番号あり）</div>
            </div>
            """, unsafe_allow_html=True)
        with cols[2]:
            st.markdown(f"""
            <div class="stat-card">
                <div class="stat-number" style="color:#E11900">{without_phone}</div>
                <div class="stat-label">電話番号なし（スキップ）</div>
            </div>
            """, unsafe_allow_html=True)
        with cols[3]:
            st.markdown(f"""
            <div class="stat-card">
                <div class="stat-number" style="color:#FFB300">{phone_issues}</div>
                <div class="stat-label">要確認データ</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # --- エクスポートボタン ---
        col_export, col_filter, col_info = st.columns([1, 1, 2])
        
        with col_export:
            # CSV作成
            df = pd.DataFrame([{
                "No.": d["no"],
                "店舗名": d["store_name"],
                "店舗URL": d.get("url", ""),
                "ジャンル": d["genre"],
                "電話番号": d["phone_normalized"],
                "電話番号（元）": d["phone_raw"],
                "電話_メモ": d["phone_issue"],
                "住所": d["address_normalized"],
                "住所（元）": d["address_raw"],
                "住所_メモ": d["address_issue"],
                "新規店舗": "はい" if d["is_new"] else "いいえ",
            } for d in data])
            
            csv_buffer = io.BytesIO()
            df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
            csv_data = csv_buffer.getvalue()
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"ubereats_stores_{st.session_state.search_query}_{timestamp}.csv"
            
            st.download_button(
                "↓ CSVリストをダウンロード",
                data=csv_data,
                file_name=filename,
                mime="text/csv",
                use_container_width=True,
            )
        
        with col_filter:
            show_filter = st.selectbox(
                "表示フィルタ",
                ["すべて表示", "電話番号ありのみ", "要確認のみ", "新規店舗のみ"],
                label_visibility="collapsed",
            )
        
        with col_info:
            st.markdown(
                f'<p style="color:#545454; font-size:0.9rem; margin-top:0.5rem; text-align:right;">'
                f'検索: <strong>{st.session_state.search_query}</strong> ｜ '
                f'取得日時: {datetime.now().strftime("%Y/%m/%d %H:%M")}</p>',
                unsafe_allow_html=True,
            )
        
        # フィルタリング
        filtered_data = data
        if show_filter == "電話番号ありのみ":
            filtered_data = [d for d in data if d["phone_normalized"]]
        elif show_filter == "要確認のみ":
            filtered_data = [d for d in data if d["phone_issue"] or d["address_issue"]]
        elif show_filter == "新規店舗のみ":
            filtered_data = [d for d in data if d["is_new"]]
        
        # --- テーブル描画 (Streamlit components.v1 を使ってHTMLを安全に描画) ---
        table_rows = ""
        for d in filtered_data:
            phone_issue_html = f'<div style="color:#E11900; font-size:12px; margin-top:4px;">⚠️ {d["phone_issue"]}</div>' if d["phone_issue"] else ""
            if d["phone_normalized"]:
                phone_display = f'<a href="tel:{d["phone_normalized"].replace("-", "")}" style="color:#06C167; font-weight:700; font-size:16px; text-decoration:none;">{d["phone_normalized"]}</a>'
            else:
                phone_display = '<span style="color:#A6A6A6;">—</span>'
            
            addr_issue_html = f'<div style="color:#E11900; font-size:12px; margin-top:4px;">⚠️ {d["address_issue"]}</div>' if d["address_issue"] else ""
            addr_display = d["address_normalized"] if d["address_normalized"] else '<span style="color:#A6A6A6;">—</span>'
            
            genre_display = ""
            if d["genre"]:
                tags = [g.strip() for g in d["genre"].replace("•", "/").split("/") if g.strip()]
                genre_display = " ".join(f'<span style="display:inline-block; background:#EEEEEE; color:#545454; padding:2px 8px; border-radius:12px; font-size:12px; margin:2px 4px 2px 0;">{tag}</span>' for tag in tags)
            
            store_name_display = f'<a href="{d.get("url", "")}" target="_blank" style="color: #000000; text-decoration: underline;">{d["store_name"]}</a>' if d.get("url") else d["store_name"]
            
            table_rows += f"""
            <tr style="border-bottom: 1px solid #EEEEEE; transition: background 0.2s;">
                <td style="padding: 16px; text-align: center; color: #A6A6A6; font-size: 14px; width: 50px;">{d["no"]}</td>
                <td style="padding: 16px;"><div style="font-weight: 700; font-size: 15px; margin-bottom: 6px;">{store_name_display}</div>{genre_display}</td>
                <td style="padding: 16px;">
                    {phone_display}
                    {phone_issue_html}
                </td>
                <td style="padding: 16px; font-size: 14px; color: #545454;">
                    <div style="margin-bottom: 4px;">{addr_display}</div>
                    {addr_issue_html}
                </td>
            </tr>
            """
        
        html_table = f"""
        <html>
        <head>
        <style>
            body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; margin: 0; padding: 0; }}
            table {{ width: 100%; border-collapse: collapse; background: #FFFFFF; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
            th {{ background: #F6F6F6; color: #545454; padding: 16px; text-align: left; font-size: 13px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #EEEEEE; }}
            tr:hover {{ background-color: #FAFAFA; }}
        </style>
        </head>
        <body>
        <table>
            <thead>
                <tr>
                    <th style="text-align:center;">No.</th>
                    <th>店舗名 / ジャンル</th>
                    <th>電話番号 (クリックで発信)</th>
                    <th>住所</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
        </body>
        </html>
        """
        
        # HTMLコンポーネントとして描画（動的な高さ調整）
        st.components.v1.html(html_table, height=800, scrolling=True)

# ───────────────────────────────────────────
# フッター
# ───────────────────────────────────────────
st.markdown("""
<div class="disclaimer">
    <strong>免責事項</strong><br>
    本ツールは Uber Eats Japan のウェブサイトから公開情報を取得しています。電話番号・住所は自動正規化されていますが、架電前にご自身で確認をお願いします。大量のリクエストはIP制限の原因となるため、常識の範囲内でご利用ください。
</div>
""", unsafe_allow_html=True)
