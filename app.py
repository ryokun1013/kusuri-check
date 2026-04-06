import pandas as pd
import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import unicodedata
import io  # ← 【修正ポイント】これを追加しました！

st.set_page_config(page_title="医薬品供給状況 自動照合システム", layout="wide")
st.title("💊 医薬品供給状況 自動照合システム (YJコード優先・高精度版)")
st.write("ファイルをアップロードすると、**一番バグの少ない「薬剤コード(YJコード)」を最優先**して厚労省の最新データと自動照合し、危険な順に並び替えます。")

# 1. 厚労省のサイトから最新ExcelのURLを自動で探す
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
    # 【修正ポイント】ダウンロードした生データ(res.content)を、仮想ファイル(io.BytesIO)で包む！
    xl = pd.ExcelFile(io.BytesIO(res.content))
    
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

# 3. 薬剤コード(YJコード)を最優先で探す関数
def get_best_match_keys(u_cols, m_cols):
    u_str = [str(c) for c in u_cols]
    m_str = [str(c) for c in m_cols]

    u_yj = next((c for c in u_str if '薬剤コード' in c or '薬価' in c or 'YJ' in c.upper()), None)
    m_yj = next((c for c in m_str if '薬価' in c or '医薬品コード' in c or 'YJ' in c.upper() or ('コード' in c and 'JAN' not in c.upper())), None)
    if u_yj and m_yj: return u_yj, m_yj, "薬剤コード (YJコード)"

    u_jan = next((c for c in u_str if '商品コード' in c or 'JAN' in c.upper()), None)
    m_jan = next((c for c in m_str if 'JAN' in c.upper() or '商品コード' in c), None)
    if u_jan and m_jan: return u_jan, m_jan, "商品コード (JAN)"

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
                    st.info(f"💡 今回は一番正確な **【{reason}】** を使って照合しました！")
                    
                    user_df['検索用'] = user_df[u_key].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    mhlw_df['照合用'] = mhlw_df[m_key].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    
                    col_status = next((c for c in mhlw_df.columns if '出荷対応' in c or '状況' in c), None)
                    col_resolve = next((c for c in mhlw_df.columns if '解消見込み' in c or '消尽' in c), None)
                    col_improve = next((c for c in mhlw_df.columns if '改善' in c or '増加' in c), None)
                    
                    m_cols_to_bring = ['照合用']
                    for col in [col_status, col_resolve, col_improve]:
                        if col and col not in m_cols_to_bring:
                            m_cols_to_bring.append(col)
                            
                    res = pd.merge(user_df, mhlw_df[m_cols_to_bring], left_on='検索用', right_on='照合用', how='left')
                    res = res.drop(columns=['検索用', '照合用'], errors='ignore')
                    
                    # 危険度順ソート（赤→黄→白）
                    def get_sort_score(status_val):
                        s = str(status_val)
                        if '停止' in s: return 1
                        if '限定' in s or '調整' in s: return 2
                        if s == 'nan' or s == '': return 4
                        return 3
                        
                    if col_status in res.columns:
                        res['sort_score'] = res[col_status].apply(get_sort_score)
                        res = res.sort_values(by='sort_score').drop(columns=['sort_score']).reset_index(drop=True)
                    
                    # 列の順番を「見やすい神配列」にする
                    front_cols = []
                    if col_status in res.columns: front_cols.append(col_status)
                    
                    u_name_col = next((c for c in user_df.columns if '名称' in c or '品名' in c), None)
                    if u_name_col in res.columns: front_cols.append(u_name_col)
                    
                    u_code_col = next((c for c in user_df.columns if 'コード' in c), None)
                    if u_code_col in res.columns and u_code_col not in front_cols: front_cols.append(u_code_col)
                    
                    if col_resolve in res.columns: front_cols.append(col_resolve)
                    if col_improve in res.columns: front_cols.append(col_improve)
                            
                    other_cols = [c for c in res.columns if c not in front_cols]
                    res = res[front_cols + other_cols]
                    
                    # 色付けルール
                    def color_rule(row):
                        status = str(row.get(col_status, ''))
                        if '停止' in status: return ['background-color: #ffadad'] * len(row) # 赤
                        if '限定' in status or '調整' in status: return ['background-color: #ffd6a5'] * len(row) # 黄
                        return [''] * len(row)

                    st.dataframe(res.style.apply(color_rule, axis=1), height=600)
                    st.download_button("この結果を保存する", data=res.to_csv(index=False).encode('utf-8-sig'), file_name="supply_check_result.csv")
                
                else:
                    st.error("⚠️ 照合に失敗しました。")
                    
            except Exception as e:
                st.error(f"システムエラーが発生しました: {e}")
else:
    st.error("厚労省のサイトから最新データが見つかりませんでした。")
