import pandas as pd
import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import unicodedata

# 1. サイトの設定
st.set_page_config(page_title="最新 医薬品供給状況チェッカー", layout="wide")
st.title("💊 医薬品供給状況 完全オートマ照合ツール")
st.write("ファイルをアップロードするだけで、AI（プログラム）が最適な列を勝手に判断して照合します。")

# 2. 厚労省のサイトから最新ExcelのURLを探す
@st.cache_data(ttl=3600)
def get_latest_mhlw_url():
    url_page = "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/kouhatu-iyaku/04_00003.html"
    res = requests.get(url_page)
    soup = BeautifulSoup(res.text, 'html.parser')
    links = soup.find_all('a', href=re.compile(r'.*\.xlsx$'))
    if links:
        path = links[0].get('href')
        return "https://www.mhlw.go.jp" + path if not path.startswith('http') else path
    return None

# 3. 厚労省データを賢く読み込む関数
@st.cache_data(ttl=3600)
def load_mhlw_data(url):
    res = requests.get(url)
    xl = pd.ExcelFile(res.content)
    
    target_sheet = xl.sheet_names[0]
    for sheet in xl.sheet_names:
        df_temp = xl.parse(sheet, nrows=15)
        if df_temp.astype(str).apply(lambda x: x.str.contains('供給状況').any()).any():
            target_sheet = sheet
            break
            
    df_raw = xl.parse(target_sheet, header=None, nrows=15)
    header_idx = 0
    for i, row in df_raw.iterrows():
        if row.astype(str).str.contains('供給状況').any():
            header_idx = i
            break
            
    df = xl.parse(target_sheet, header=header_idx)
    df.columns = [unicodedata.normalize('NFKC', str(c)).replace('\n', '').strip() for c in df.columns]
    return df

# 4. 最適な照合列を「全自動で見つける」関数
def find_best_match_columns(user_cols, mhlw_cols):
    u_cols = [str(c) for c in user_cols]
    m_cols = [str(c) for c in mhlw_cols]
    
    # 第1優先：JANコード（一番正確）
    mhlw_jan = next((c for c in m_cols if 'JAN' in c.upper()), None)
    user_jan = next((c for c in u_cols if 'JAN' in c.upper() or '商品コード' in c), None)
    if mhlw_jan and user_jan: return user_jan, mhlw_jan, "JANコード/商品コード"

    # 第2優先：薬剤コード（薬価基準収載医薬品コード）
    mhlw_code = next((c for c in m_cols if '薬価' in c or '医薬品コード' in c), None)
    user_code = next((c for c in u_cols if '薬剤コード' in c or 'YJ' in c.upper() or '薬価' in c), None)
    if mhlw_code and user_code: return user_code, mhlw_code, "薬剤コード/薬価コード"

    # 第3優先：名前（少しブレる可能性があるが最終手段）
    mhlw_name = next((c for c in m_cols if '販売名' in c or '品名' in c), None)
    user_name = next((c for c in u_cols if '名称' in c or '薬品名' in c or '商品名' in c or '販売名' in c), None)
    if mhlw_name and user_name: return user_name, mhlw_name, "薬剤名称/販売名"

    return None, None, None

# 5. メイン処理
latest_url = get_latest_mhlw_url()

if latest_url:
    st.info("✅ 厚労省の最新データを準備完了！在庫ファイル（Excel/CSV）を入れてください。")
    
    uploaded_file = st.file_uploader("ここにファイルをドラッグ＆ドロップ", type=["xlsx", "csv"])

    if uploaded_file:
        with st.spinner('全自動で照合中...'):
            try:
                # ユーザーデータの読み込み
                if uploaded_file.name.endswith('.csv'):
                    try:
                        user_df = pd.read_csv(uploaded_file, encoding='utf-8')
                    except UnicodeDecodeError:
                        uploaded_file.seek(0)
                        user_df = pd.read_csv(uploaded_file, encoding='cp932')
                else:
                    user_df = pd.read_excel(uploaded_file)
                    
                # 厚労省データの読み込み
                mhlw_df = load_mhlw_data(latest_url)
                
                # 全自動で列を決定する
                user_key, mhlw_key, match_reason = find_best_match_columns(user_df.columns, mhlw_df.columns)
                
                if user_key and mhlw_key:
                    st.success(f"✨ 自動判定成功！ あなたの「**{user_key}**」と厚労省の「**{mhlw_key}**」を使って照合しました！（基準：{match_reason}）")
                    
                    # データを綺麗にして合体
                    user_df['検索用キー'] = user_df[user_key].astype(str).str.replace('.0', '', regex=False).str.strip()
                    mhlw_df['照合用キー'] = mhlw_df[mhlw_key].astype(str).str.replace('.0', '', regex=False).str.strip()
                    
                    target_cols = [mhlw_key, '供給状況', '出荷再開予定時期', '備考']
                    available_cols = [c for c in target_cols if c in mhlw_df.columns]
                    if '照合用キー' not in available_cols:
                        available_cols.append('照合用キー')
                        
                    res = pd.merge(user_df, mhlw_df[available_cols], left_on='検索用キー', right_on='照合用キー', how='left')
                    res = res.drop(columns=['検索用キー', '照合用キー'], errors='ignore')
                    
                    # 色塗りルール
                    def color_rule(row):
                        status = str(row.get('供給状況', ''))
                        if '供給停止' in status: return ['background-color: #ffadad'] * len(row)
                        if '限定出荷' in status or '出荷調整' in status: return ['background-color: #ffd6a5'] * len(row)
                        return [''] * len(row)

                    st.dataframe(res.style.apply(color_rule, axis=1), height=600)
                    st.download_button("結果を保存する", data=res.to_csv(index=False).encode('utf_8_sig'), file_name="check_result.csv")
                
                else:
                    st.error("⚠️ 自動照合に失敗しました。ファイルに「商品コード」「薬剤コード」「薬剤名称」などの列が含まれているか確認してください。")
                    
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
else:
    st.error("厚労省のデータが見つかりませんでした。")
