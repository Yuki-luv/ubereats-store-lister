"""
住所・電話番号の正規化モジュール
Uber Eats から取得したデータの表記ゆれを修正する
"""
import re


# 日本の市外局番パターン（主要なもの）
# 市外局番の桁数でグルーピング
AREA_CODES_2DIGIT = {"03", "06", "04", "011"}  # 2桁市外局番
AREA_CODES_3DIGIT = {
    "011", "015", "017", "018", "019",
    "022", "023", "024", "025", "026", "027", "028", "029",
    "042", "043", "044", "045", "046", "047", "048", "049",
    "052", "053", "054", "055", "058", "059",
    "072", "073", "075", "076", "077", "078", "079",
    "082", "083", "084", "086", "087", "088", "089",
    "092", "093", "095", "096", "097", "098", "099",
}
MOBILE_PREFIXES = {"070", "080", "090", "050"}
FREEPHONE_PREFIXES = {"0120", "0800"}


def normalize_phone(raw_phone: str) -> str:
    """
    電話番号を正規化する。
    - 国番号 81 → 先頭 0 に変換
    - +81 プレフィックス除去
    - ハイフン挿入
    
    Args:
        raw_phone: 元の電話番号文字列
    
    Returns:
        正規化済みの電話番号（ハイフン付き）
    """
    if not raw_phone:
        return ""
    
    # 数字以外を除去
    digits = re.sub(r'[^\d]', '', str(raw_phone))
    
    if not digits:
        return ""
    
    # 国番号 81 で始まる場合 → 0 に変換
    if digits.startswith("81") and len(digits) > 10:
        digits = "0" + digits[2:]
    
    # 0 で始まらない場合は 0 を付加（日本の電話番号として）
    if not digits.startswith("0"):
        digits = "0" + digits
    
    # ハイフンを挿入
    return _insert_hyphens(digits)


def _insert_hyphens(digits: str) -> str:
    """電話番号にハイフンを挿入する"""
    
    # フリーダイヤル（0120-XXX-XXX）
    if digits.startswith("0120"):
        if len(digits) == 10:
            return f"{digits[:4]}-{digits[4:7]}-{digits[7:]}"
        return digits
    
    # フリーコール（0800-XXX-XXXX）
    if digits.startswith("0800"):
        if len(digits) == 11:
            return f"{digits[:4]}-{digits[4:7]}-{digits[7:]}"
        return digits
    
    # 携帯電話（070/080/090/050-XXXX-XXXX）
    prefix3 = digits[:3]
    if prefix3 in MOBILE_PREFIXES:
        if len(digits) == 11:
            return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
        return digits
    
    # 固定電話 - 2桁市外局番（03, 06 等 → 03-XXXX-XXXX）
    prefix2 = digits[:2]
    if prefix2 in AREA_CODES_2DIGIT:
        if len(digits) == 10:
            return f"{digits[:2]}-{digits[2:6]}-{digits[6:]}"
        return digits
    
    # 固定電話 - 3桁市外局番（045, 078 等 → 045-XXX-XXXX）
    prefix3 = digits[:3]
    if prefix3 in AREA_CODES_3DIGIT:
        if len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        return digits
    
    # 固定電話 - 4桁市外局番（その他 → 0XXX-XX-XXXX）
    if digits.startswith("0") and len(digits) == 10:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    
    # パターンに一致しない場合はそのまま返す
    return digits


def normalize_address(raw_address: str, genre: str = "") -> str:
    """
    住所を正規化する。
    - 末尾の国名・国コードを除去
    - ジャンル（カテゴリ）文字列の混入を除去
    - 全角・半角の統一
    - 余計なスペースの除去
    
    Args:
        raw_address: 元の住所文字列
        genre: 店舗のジャンル文字列（住所から除去するため）
    
    Returns:
        正規化済みの住所
    """
    if not raw_address:
        return ""
    
    addr = str(raw_address).strip()
    
    # ジャンル文字列が住所に混入している場合、それを除去する
    if genre:
        # " / " で分割されたジャンルを個別にチェックして除去
        genre_parts = [g.strip() for g in genre.split('/') if g.strip()]
        # 長いジャンル名から順にチェック（部分一致による誤削除防止）
        genre_parts.sort(key=len, reverse=True)
        for g in genre_parts:
            if not g: continue
            g_escaped = re.escape(g)
            # 1. 行頭または行末にあるジャンル名を除去
            addr = re.sub(rf'^{g_escaped}\s*|\s*{g_escaped}$', '', addr)
            # 2. 空白で囲まれたジャンル名を除去
            addr = re.sub(rf'\s+{g_escaped}\s+', ' ', addr)
            # 3. カンマや中黒の前後にあるジャンル名を除去
            addr = re.sub(rf'[,・]\s*{g_escaped}', '', addr)
            addr = re.sub(rf'{g_escaped}\s*[,・]', '', addr)
            # 4. 完全に独立した文字列（住所そのものがジャンル名になってしまっている場合）
            if addr == g:
                addr = ""

    # 末尾の国名・国コードを除去
    addr = re.sub(r',?\s*(Japan|JP|JPN|日本)\s*$', '', addr, flags=re.IGNORECASE)
    
    # 先頭の郵便番号パターンを整形（〒XXX-XXXX）
    addr = re.sub(r'^〒?\s*(\d{3})-?(\d{4})\s*', r'〒\1-\2 ', addr)
    
    # 半角数字はそのまま（住所の番地は半角が見やすい）
    # 全角スペースを半角に統一
    addr = addr.replace('\u3000', ' ')
    
    # 連続するスペースを1つにする
    addr = re.sub(r'\s+', ' ', addr)
    
    # 末尾のカンマ・余計な文字を除去
    addr = addr.rstrip(', ')
    
    return addr.strip()


def detect_phone_issues(raw_phone: str, normalized_phone: str) -> str:
    """
    電話番号の問題点を検出する
    
    Returns:
        問題点の説明（問題がない場合は空文字列）
    """
    if not raw_phone:
        return "⚠ 電話番号なし"
    
    digits = re.sub(r'[^\d]', '', str(raw_phone))
    
    if len(digits) < 10:
        return "⚠ 桁数不足"
    
    if len(digits) > 11:
        return "⚠ 桁数過多"
    
    if not normalized_phone.startswith("0"):
        return "⚠ 形式不明"
    
    return ""


def detect_address_issues(raw_address: str, normalized_address: str) -> str:
    """
    住所の問題点を検出する
    
    Returns:
        問題点の説明（問題がない場合は空文字列）
    """
    if not raw_address:
        return "⚠ 住所なし"
    
    issues = []
    
    # レビュー数や評価などの誤認チェック
    if re.search(r'\(\d+\+?\)', raw_address) or re.search(r'^\d\.\d', raw_address):
        issues.append("⚠ レビュー数混入の疑い")
    
    # 極端に短い住所
    if len(normalized_address) < 5 and normalized_address:
        issues.append("⚠ 住所不足の疑い")

    return " / ".join(issues) if issues else ""
