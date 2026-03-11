import pandas as pd
import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import unicodedata

st.set_page_config(page_title="医薬品供給状況 自動照合システム", layout="wide")
st.title("💊 医薬品供給状況 自動照合システム (完全並び替え版)")
st.write("ファイルをアップロードすると、一番左側に供給状況・再開見込みを配置し、**「供給停止(赤) → 出荷調整(黄) → 通常」の順に自動で並び替えて**表示します。")

# 1. 厚労省のサイトから最新ExcelのURLを探す
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

# 2. 厚労省データを読み込み、列名を綺麗にする
@st.cache_data(ttl=3600)
def load_mhlw_data(url):
    res = requests.get(url)
    xl = pd.ExcelFile(res.content)
    
    target_sheet = xl.sheet_names[0]
    df_raw = xl.parse(target_sheet, header=None, nrows=20)
    
    header_idx = 0
    for i, row in df_raw.iterrows():
        row_clean = row.astype(str).str.replace(r'\s+', '', regex=True)
        if row_clean.str.contains('状況|販売名|品名|コード').any():
            header_idx = i
            break
            
    df = xl.parse(target_sheet, header=header_idx)
    df.columns = [unicodedata.normalize('NFKC', str(c)).replace('\n', '').replace(' ', '').replace('　', '').strip() for c in df.columns]
    return df

# 3. 超・融通の利く「自動列探し」関数
def get_best_match_keys(u_cols, m_cols):
    u_str = [str(c) for c in u_cols]
    m_str = [str(c) for c in m_cols]

    u_jan = next((c for c in u_str if '商品コード' in c or 'JAN' in c.upper()), None)
    m_jan = next((c for c in m_str if 'JAN' in c.upper() or '商品コード' in c), None)
    if u_jan and m_jan: return u_jan, m_jan, "商品コード (JAN)"

    u_yj = next((c for c in u_str if '薬剤コード' in c or '薬価' in c or 'YJ' in c.upper()), None)
    m_yj = next((c for c in m_str if '薬価' in c or '医薬品コード' in c or 'YJ' in c.upper() or 'コード' in c), None)
    if u_yj and m_yj and m_yj != m_jan: return u_yj, m_yj, "薬剤コード"

    u_name = next((c for c in u_str if '薬剤名称' in c or '薬品名' in c or '商品名' in c or '販売名' in c or '名称' in c), None)
    m_name = next((c for c in m_str if '販売名' in c or '品名' in c or '名称' in c or '医薬品名' in c), None)
    if u_name and m_name: return u_name, m_name, "薬剤名称"

    return None, None, None

# 4. メイン処理
latest_url = get_latest_mhlw_url()

if latest_url:
    st.success("✅ 厚労省の最新データの準備が完了しました！")
    uploaded_file = st.file_uploader("あなたのファイル（CSV または Excel）を入れてください", type=["xlsx", "csv"])

    if uploaded_file:
        with st.spinner('データを照合し、見やすく並び替えています...'):
            try:
                # ① ファイル読み込み
                if uploaded_file.name.endswith('.csv'):
                    try:
                        user_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
                    except UnicodeDecodeError:
                        uploaded_file.seek(0)
                        user_df = pd.read_csv(uploaded_file, encoding='cp932')
                else:
                    user_df = pd.read_excel(uploaded_file)
                    
                # ② 厚労省データ読み込み
                mhlw_df = load_mhlw_data(latest_url)
                
                # ③ 全自動照合
                u_key, m_key, reason = get_best_match_keys(user_df.columns, mhlw_df.columns)
                
                if u_key and m_key:
                    st.info(f"💡 今回は **【{reason}】** を使って照合しました！")
                    
                    user_df['検索用'] = user_df[u_key].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    mhlw_df['照合用'] = mhlw_df[m_key].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    
                    # ユーザーが指定した「左に持ってくる3つの列」をキーワードで探す
                    col_status = next((c for c
