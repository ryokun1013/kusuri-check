import pandas as pd
import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import unicodedata

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

# 3. 厚労省データを「賢く」読み込む関数（全角半角のズレなどを自動修正）
@st.cache_data(ttl=3600)
def load_mhlw_data(url):
    res = requests.get(url)
    xl = pd.ExcelFile(res.content)
    
    # 「供給状況」という文字があるシートと行を自動で探す
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
    
    # 列名を綺麗にする（「ＪＡＮコード」を「JANコード」に修正など）
    df.columns = [unicodedata.normalize('NFKC', str(c)).replace('\n', '').strip() for c in df.columns]
    return df

# 4. メイン処理
latest_url = get_latest_mhlw_url()

if latest_url:
    st.info("✅ 厚労省の最新データを自動で準備しました！下の枠にファイルを入れてください。")
    
    uploaded_file = st.file_uploader("在庫ファイル（Excel または CSV）を選んでください", type=["xlsx", "csv"])

    if uploaded_file:
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
            with st.spinner('厚労省のデータを解析中...'):
                mhlw_df = load_mhlw_data(latest_url)
            
            # --- 💡 自由に照合できるUI ---
            st.write("---")
            st.markdown("### 🔍 どの項目で照合しますか？")
            
            col1, col2 = st.columns(2)
            with col1:
                # ユーザー側のキー列を選択
                user_key = st.selectbox("① あなたのファイルの【照合キー】になる列：", user_df.columns)
            with col2:
                # 厚労省側のキー列を選択
                mhlw_options = []
                if 'JANコード' in mhlw_df.columns: mhlw_options.append('JANコード (商品コードなどと照合)')
                if '薬価基準収載医薬品コード' in mhlw_df.columns: mhlw_options.append('薬価基準収載医薬品コード (薬剤コードと照合)')
                if '販売名' in mhlw_df.columns: mhlw_options.append('販売名 (薬剤名称と照合)')
                mhlw_options.extend([c for c in mhlw_df.columns if c not in ['JANコード', '薬価基準収載医薬品コード', '販売名']])
                
                mhlw_key_display = st.selectbox("② 厚労省データの【どれ】と突き合わせますか？：", mhlw_options)
                mhlw_key = mhlw_key_display.split(' ')[0] # 実際の列名を抽出

            # ボタンを押したら合体する
            if st.button("✨ この条件で照合スタート！"):
                # 型を合わせて合体（エラー防止のため文字として比較）
                user_df['検索用キー'] = user_df[user_key].astype(str).str.replace('.0', '', regex=False).str.strip()
                mhlw_df['照合用キー'] = mhlw_df[mhlw_key].astype(str).str.replace('.0', '', regex=False).str.strip()
                
                # 持ってくる列
                target_cols = [mhlw_key, '供給状況', '出荷再開予定時期', '備考']
                available_cols = [c for c in target_cols if c in mhlw_df.columns]
                if '照合用キー' not in available_cols:
                    available_cols.append('照合用キー')
                    
                res = pd.merge(user_df, mhlw_df[available_cols], left_on='検索用キー', right_on='照合用キー', how='left')
                
                # 作業用の列をお掃除
                res = res.drop(columns=['検索用キー', '照合用キー'], errors='ignore')
                
                # 色塗りルール
                def color_rule(row):
                    status = str(row.get('供給状況', ''))
                    if '供給停止' in status: return ['background-color: #ffadad'] * len(row)
                    if '限定出荷' in status or '出荷調整' in status: return ['background-color: #ffd6a5'] * len(row)
                    return [''] * len(row)

                st.subheader("📊 照合完了！結果を確認してください")
                st.dataframe(res.style.apply(color_rule, axis=1), height=500)
                
                st.download_button("結果を保存する", data=res.to_csv(index=False).encode('utf_8_sig'), file_name="check_result.csv")
                
        except Exception as e:
            st.error(f"データの読み込み中にエラーが発生しました: {e}")
            st.error("💡 ヒント：ファイルの中身や列名が特殊な可能性があります。")
else:
    st.error("厚労省の最新データが見つかりませんでした。")
