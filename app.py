import pandas as pd
import streamlit as st
import requests
from bs4 import BeautifulSoup
import re

# 1. サイトの設定
st.set_page_config(page_title="最新 医薬品供給状況チェッカー", layout="wide")
st.title("💊 医薬品供給状況 リアルタイム照合ツール")
st.write("厚労省の最新リストとあなたの在庫を自動で照合します。")

# 2. 厚労省のサイトから最新ExcelのURLを探す（自動巡回）
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

# 3. メインの処理
latest_url = get_latest_mhlw_url()

if latest_url:
    # ユーザーが在庫ファイルをアップロード
    uploaded_file = st.file_uploader("自分の在庫エクセル（Excel）を選んでください", type=["xlsx"])

    if uploaded_file:
        # 厚労省データの読み込み
        mhlw_df = pd.read_excel(latest_url, sheet_name='全品目', header=2)
        mhlw_df['JANコード'] = mhlw_df['JANコード'].astype(str)

        # 自分の在庫データの読み込み
        user_df = pd.read_excel(uploaded_file)
        user_df['JANコード'] = user_df['JANコード'].astype(str)

        # 合体（VLOOKUPのようにJANコードで繋ぐ）
        res = pd.merge(user_df, mhlw_df[['JANコード', '供給状況', '出荷再開予定時期', '備考']], on='JANコード', how='left')

        # 色塗りのルール
        def color_rule(row):
            status = str(row['供給状況'])
            if '供給停止' in status: return ['background-color: #ffadad'] * len(row) # 赤
            if '限定出荷' in status or '出荷調整' in status: return ['background-color: #ffd6a5'] * len(row) # 黄
            return [''] * len(row)

        # 結果表示
        st.subheader("📊 照合完了！結果を確認してください")
        st.dataframe(res.style.apply(color_rule, axis=1), height=500)
        
        # ダウンロード
        st.download_button("結果を保存する", data=res.to_csv(index=False).encode('utf_8_sig'), file_name="check_result.csv")
else:
    st.error("厚労省の最新データが見つかりませんでした。")
