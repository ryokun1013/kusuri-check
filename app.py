import pandas as pd
import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import unicodedata

st.set_page_config(page_title="医薬品供給状況 自動照合システム", layout="wide")
st.title("💊 医薬品供給状況 自動照合システム (完全究極版)")
st.write("どんなエクセル・CSVでも、システムが自動で列を見つけて合体させます。")

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

# 2. 【大進化】厚労省データをどんなに汚くても読み込む
@st.cache_data(ttl=3600)
def load_mhlw_data(url):
    res = requests.get(url)
    xl = pd.ExcelFile(res.content)
    
    target_sheet = xl.sheet_names[0]
    df_raw = xl.parse(target_sheet, header=None, nrows=20)
    
    header_idx = 0
    # 「状況」「販売名」「コード」などのキーワードがある行を無理やり「見出し」と認定する
    for i, row in df_raw.iterrows():
        row_clean = row.astype(str).str.replace(r'\s+', '', regex=True) # 空白を消す
        if row_clean.str.contains('状況|販売名|品名|コード').any():
            header_idx = i
            break
            
    df = xl.parse(target_sheet, header=header_idx)
    # 見出しの改行や空白を徹底的にお掃除
    df.columns = [unicodedata.normalize('NFKC', str(c)).replace('\n', '').replace(' ', '').replace('　', '').strip() for c in df.columns]
    return df

# 3. 超・融通の利く「自動列探し」関数
def get_best_match_keys(u_cols, m_cols):
    u_str = [str(c) for c in u_cols]
    m_str = [str(c) for c in m_cols]

    # JANコード / 商品コード
    u_jan = next((c for c in u_str if '商品コード' in c or 'JAN' in c.upper()), None)
    m_jan = next((c for c in m_str if 'JAN' in c.upper() or '商品コード' in c), None)
    if u_jan and m_jan: return u_jan, m_jan, "商品コード (JAN)"

    # 薬剤コード / 薬価コード
    u_yj = next((c for c in u_str if '薬剤コード' in c or '薬価' in c or 'YJ' in c.upper()), None)
    m_yj = next((c for c in m_str if '薬価' in c or '医薬品コード' in c or 'YJ' in c.upper() or 'コード' in c), None)
    if u_yj and m_yj and m_yj != m_jan: return u_yj, m_yj, "薬剤コード"

    # 名称
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
        with st.spinner('厚労省のデータと照らし合わせています...'):
            try:
                # ① あなたのファイルを読み込む（文字化け・特殊文字対策済み）
                if uploaded_file.name.endswith('.csv'):
                    try:
                        user_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
                    except UnicodeDecodeError:
                        uploaded_file.seek(0)
                        user_df = pd.read_csv(uploaded_file, encoding='cp932')
                else:
                    user_df = pd.read_excel(uploaded_file)
                    
                # ② 厚労省データを読み込む
                mhlw_df = load_mhlw_data(latest_url)
                
                # ③ 全自動で照合キーを決定！
                u_key, m_key, reason = get_best_match_keys(user_df.columns, mhlw_df.columns)
                
                if u_key and m_key:
                    st.info(f"💡 今回は一番正確な **【{reason}】** を使って全自動で照合しました！")
                    
                    # 掃除
                    user_df['検索用'] = user_df[u_key].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    mhlw_df['照合用'] = mhlw_df[m_key].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    
                    # 【大進化】「供給状況」という名前が少し変わってもAIが探す
                    m_status = next((c for c in mhlw_df.columns if '状況' in c or '区分' in c), '供給状況')
                    m_date = next((c for c in mhlw_df.columns if '再開' in c or '予定' in c), '出荷再開予定時期')
                    m_note = next((c for c in mhlw_df.columns if '備考' in c or '理由' in c), '備考')
                    
                    m_cols_to_bring = ['照合用']
                    for col in [m_status, m_date, m_note]:
                        if col in mhlw_df.columns and col not in m_cols_to_bring:
                            m_cols_to_bring.append(col)
                        
                    res = pd.merge(user_df, mhlw_df[m_cols_to_bring], left_on='検索用', right_on='照合用', how='left')
                    res = res.drop(columns=['検索用', '照合用'], errors='ignore')
                    
                    # 色付けのルール
                    def color_rule(row):
                        status = str(row.get(m_status, ''))
                        if '停止' in status: return ['background-color: #ffadad'] * len(row)
                        if '限定' in status or '調整' in status: return ['background-color: #ffd6a5'] * len(row)
                        return [''] * len(row)

                    st.dataframe(res.style.apply(color_rule, axis=1), height=600)
                    
                    # 保存するときも文字化けしないようにutf-8-sigを使用
                    st.download_button("この結果を保存する", data=res.to_csv(index=False).encode('utf-8-sig'), file_name="supply_check_result.csv")
                
                else:
                    st.error("⚠️ 照合に失敗しました。厚労省のエクセル構造が変更された可能性があります。")
                    st.write("▼ デバッグ情報（これを見れば原因がわかります）")
                    st.write("あなたの見出し：", list(user_df.columns))
                    st.write("厚労省の見出し：", list(mhlw_df.columns))
                    
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
else:
    st.error("厚労省のサイトから最新データが見つかりませんでした。")
