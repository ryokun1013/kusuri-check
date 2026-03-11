import pandas as pd
import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import unicodedata

st.set_page_config(page_title="医薬品供給状況 自動照合システム", layout="wide")
st.title("💊 医薬品供給状況 自動照合システム")
st.write("ファイルをドラッグ＆ドロップするだけで、厚労省の最新リストと全自動で照らし合わせます。")

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
    
    # 供給状況という文字がある行を見出しとして認識する
    target_sheet = xl.sheet_names[0]
    df_raw = xl.parse(target_sheet, header=None, nrows=15)
    header_idx = 0
    for i, row in df_raw.iterrows():
        if row.astype(str).str.contains('供給状況').any():
            header_idx = i
            break
            
    df = xl.parse(target_sheet, header=header_idx)
    # 全角半角のブレを直し、改行を消す（「ＪＡＮコード」→「JANコード」）
    df.columns = [unicodedata.normalize('NFKC', str(c)).replace('\n', '').strip() for c in df.columns]
    return df

# 3. あなたのファイルの項目名に合わせて、一番正確な照合キーを自動決定する関数
def get_best_match_keys(u_cols, m_cols):
    u_cols_str = [str(c) for c in u_cols]
    
    # 第1候補：商品コード（JAN）で照合
    if '商品コード' in u_cols_str and 'JANコード' in m_cols:
        return '商品コード', 'JANコード', "商品コード (JAN)"
        
    # 第2候補：薬剤コードで照合
    if '薬剤コード' in u_cols_str and '薬価基準収載医薬品コード' in m_cols:
        return '薬剤コード', '薬価基準収載医薬品コード', "薬剤コード"
        
    # 第3候補：薬剤名称で照合
    if '薬剤名称' in u_cols_str and '販売名' in m_cols:
        return '薬剤名称', '販売名', "薬剤名称"
        
    return None, None, None

# 4. メイン処理
latest_url = get_latest_mhlw_url()

if latest_url:
    st.success("✅ 厚労省の最新データの準備が完了しました！")
    uploaded_file = st.file_uploader("あなたのファイル（CSV または Excel）を入れてください", type=["xlsx", "csv"])

    if uploaded_file:
        with st.spinner('厚労省のデータと照らし合わせています...'):
            try:
                # ① あなたのファイルを読み込む（CSVの文字化け対策済み）
                if uploaded_file.name.endswith('.csv'):
                    try:
                        user_df = pd.read_csv(uploaded_file, encoding='utf-8')
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
                    
                    # 照合前に文字のブレ（「.0」がつく問題など）を完全に消し去る
                    user_df['検索用'] = user_df[u_key].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    mhlw_df['照合用'] = mhlw_df[m_key].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    
                    # 厚労省から引っ張ってくる情報を指定
                    target_cols = [m_key, '供給状況', '出荷再開予定時期', '備考']
                    m_cols_to_bring = [c for c in target_cols if c in mhlw_df.columns]
                    if '照合用' not in m_cols_to_bring:
                        m_cols_to_bring.append('照合用')
                        
                    # エクセルを合体させる（VLOOKUP）
                    res = pd.merge(user_df, mhlw_df[m_cols_to_bring], left_on='検索用', right_on='照合用', how='left')
                    
                    # 掃除
                    res = res.drop(columns=['検索用', '照合用'], errors='ignore')
                    
                    # 色付けのルール（供給停止＝赤、調整＝黄色）
                    def color_rule(row):
                        status = str(row.get('供給状況', ''))
                        if '供給停止' in status: return ['background-color: #ffadad'] * len(row)
                        if '限定出荷' in status or '出荷調整' in status: return ['background-color: #ffd6a5'] * len(row)
                        return [''] * len(row)

                    # 結果の表示
                    st.dataframe(res.style.apply(color_rule, axis=1), height=600)
                    
                    # ダウンロードボタン
                    st.download_button("この結果を保存する", data=res.to_csv(index=False).encode('utf_8_sig'), file_name="supply_check_result.csv")
                
                else:
                    st.error("⚠️ 照合に失敗しました。ファイルに「商品コード」「薬剤コード」「薬剤名称」のいずれかの列が含まれているか確認してください。")
                    
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
                st.error("ファイルが壊れているか、厚労省のデータ形式が大幅に変更された可能性があります。")
else:
    st.error("厚労省のサイトから最新データが見つかりませんでした。")
