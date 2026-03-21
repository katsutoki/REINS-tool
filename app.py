"""
  REINS成約データ お買い得判定ツール
  """

  import os
  import sqlite3
  import unicodedata
  import datetime
  import pandas as pd
  import plotly.graph_objects as go
  import streamlit as st

  # ──────────────────────────────────────────────
  # 設定
  # ──────────────────────────────────────────────
  BASE_DIR = os.path.dirname(os.path.abspath(__file__))
  DB_PATH  = os.path.join(BASE_DIR, "reins_r2_r8.db")

  _CJK_RAD_SUP_MAP = str.maketrans({
      "\u2EC4": "\u897F",
      "\u2ECB": "\u897F",
  })

  def normalize(text: str) -> str:
      text = unicodedata.normalize("NFKC", text)
      return text.translate(_CJK_RAD_SUP_MAP)


  # ──────────────────────────────────────────────
  # データ読み込み（キャッシュ）
  # ──────────────────────────────────────────────
  @st.cache_data
  def load_all() -> pd.DataFrame:
      con = sqlite3.connect(DB_PATH)
      df  = pd.read_sql("SELECT * FROM reins", con)
      con.close()
      df["築年月"] = pd.to_datetime(df["築年月"], format="%Y-%m", errors="coerce")
      df["成約年月日"] = pd.to_datetime(df["成約年月日"], errors="coerce")
      return df


  @st.cache_data
  def get_wards(df: pd.DataFrame):
      return sorted(df["区"].dropna().unique().tolist())


  @st.cache_data
  def get_stations(df: pd.DataFrame, ward: str):
      return sorted(df[df["区"] == ward]["最寄駅"].dropna().unique().tolist())


  # ──────────────────────────────────────────────
  # 同一物件の過去成約事例を検索
  # ──────────────────────────────────────────────
  def find_same_building(df: pd.DataFrame, building_name: str) -> pd.DataFrame:
      """入力した物件名を部分一致で検索して返す。"""
      name = normalize(building_name.strip())
      if not name:
          return pd.DataFrame()
      mask = df["建物名"].fillna("").apply(normalize).str.contains(name, regex=False)
      result = df[mask].copy()
      result["㎡単価_calc"] = result["成約価格(万円)"] / result["専有面積"]
      return result.sort_values("成約年月日", ascending=False)


  # ──────────────────────────────────────────────
  # 類似物件の抽出
  # ──────────────────────────────────────────────
  def extract_walk_minutes(text) -> float:
      """交通列から徒歩分数を抽出する。取得できない場合はNaNを返す。"""
      import re
      if pd.isna(text):
          return float("nan")
      m = re.search(r"徒歩\s*(\d+)分", str(text))
      return float(m.group(1)) if m else float("nan")


  def find_comparables(
      df: pd.DataFrame,
      ward: str,
      station,
      area: float,
      built_year: int,
      area_range: float,
      age_range: int,
      nendo_from: int,
      nendo_to: int,
      walk_max: int = 0,
  ) -> pd.DataFrame:

      mask = (
          (df["区"] == ward) &
          (df["専有面積"] >= area * (1 - area_range / 100)) &
          (df["専有面積"] <= area * (1 + area_range / 100)) &
          (df["年度"] >= nendo_from) &
          (df["年度"] <= nendo_to)
      )

      if station:
          mask &= df["最寄駅"].isin(station)

      if built_year > 0:
          low  = built_year - age_range
          high = built_year + age_range
          mask &= df["築年月"].dt.year.between(low, high, inclusive="both")

      comp = df[mask].copy()
      comp["㎡単価_calc"] = comp["成約価格(万円)"] / comp["専有面積"]

      if walk_max > 0:
          comp["徒歩分数"] = comp["交通"].apply(extract_walk_minutes)
          comp = comp[comp["徒歩分数"] <= walk_max]

      return comp


  # ──────────────────────────────────────────────
  # 判定ロジック
  # ──────────────────────────────────────────────
  VERDICT_LEVELS = [
      (20,   "⭕ かなりお買い得", "#1a9641", "中央値と比べて20%以上安い"),
      (5,    "✅ お買い得",       "#a6d96a", "中央値と比べて5〜20%安い"),
      (-5,   "➡️  適正価格",       "#ffffbf", "中央値と比べて±5%以内"),
      (-20,  "⚠️  やや割高",       "#fdae61", "中央値と比べて5〜20%高い"),
      (None, "🔴 割高",           "#d7191c", "中央値と比べて20%以上高い"),
  ]

  def get_verdict(diff_pct: float):
      for threshold, label, color, desc in VERDICT_LEVELS:
          if threshold is None or diff_pct >= threshold:
              return label, color, desc
      return VERDICT_LEVELS[-1][1], VERDICT_LEVELS[-1][2], VERDICT_LEVELS[-1][3]


  # ──────────────────────────────────────────────
  # 共通表示列
  # ──────────────────────────────────────────────
  SHOW_COLS = ["年度", "成約年月日", "建物名", "所在地", "区", "最寄駅", "交通",
               "専有面積", "間取", "築年月", "成約価格(万円)", "㎡単価_calc", "管理費"]

  def format_table(df: pd.DataFrame) -> pd.DataFrame:
      cols = [c for c in SHOW_COLS if c in df.columns]
      disp = df[cols].copy()
      if "築年月" in disp.columns:
          disp["築年月"] = disp["築年月"].dt.strftime("%Y-%m")
      if "成約年月日" in disp.columns:
          disp["成約年月日"] = disp["成約年月日"].dt.strftime("%Y-%m-%d")
      if "㎡単価_calc" in disp.columns:
          disp["㎡単価_calc"] = disp["㎡単価_calc"].round(1)
      disp.columns = [c.replace("㎡単価_calc", "㎡単価") for c in disp.columns]
      return disp


  # ──────────────────────────────────────────────
  # UI
  # ──────────────────────────────────────────────
  st.set_page_config(page_title="お買い得判定ツール", layout="wide")
  st.title("🏠 REINS成約データ お買い得判定ツール")
  st.caption("平成30年〜令和8年の札幌市マンション成約データをもとに、物件がお買い得かどうかを判定し
  ます。")

  df_all = load_all()

  # ── サイドバー：物件入力 ──
  with st.sidebar:
      st.header("📋 物件情報を入力")

      building_name = st.text_input(
          "物件名（任意）",
          placeholder="例：ライオンズマンション宮の森",
          help="入力すると同一物件の過去成約事例を表示します。部分一致で検索します。"
      )

      wards = get_wards(df_all)
      ward = st.selectbox("区", wards)

      stations = get_stations(df_all, ward)
      station_sel = st.multiselect(
          "最寄駅（最大3つまで選択可）",
          options=stations,
          max_selections=3,
          placeholder="駅を選択（未選択の場合は区全体で比較）"
      )
      station = station_sel if station_sel else None

      area = st.number_input("専有面積（㎡）", min_value=10.0, max_value=300.0, value=70.0,
  step=0.5)

      price = st.number_input("査定・希望価格（万円）", min_value=100, max_value=99999, value=2000,
  step=10)

      walk_max = st.number_input(
          "徒歩分数（分以内）", min_value=0, max_value=30, value=0, step=1,
          help="0を入力すると徒歩分数を絞り込み条件から除外します"
      )

      # 築年数 or 築年（西暦）を選択入力
      st.markdown("**築年の入力方法**")
      built_input_type = st.radio("", ["築年数で入力", "西暦で入力"], horizontal=True,
  label_visibility="collapsed")

      current_year = datetime.date.today().year
      if built_input_type == "築年数で入力":
          built_age = st.number_input("築年数（年）", min_value=0, max_value=80, value=20, step=1,
                                      help="0を入力すると築年を絞り込み条件から除外します")
          built_year = (current_year - built_age) if built_age > 0 else 0
          if built_age > 0:
              st.caption(f"→ 築{built_year}年（西暦）として計算")
      else:
          built_year = st.number_input("築年（西暦）", min_value=1950, max_value=current_year,
                                       value=2000, step=1,
                                       help="0を入力すると築年を絞り込み条件から除外します")

      st.divider()
      st.subheader("🔍 比較条件")
      area_range = st.slider("専有面積の許容範囲（±%）", 5, 50, 20, step=5)
      age_range  = st.slider("築年の許容範囲（±年）",    1, 20, 10, step=1)
      def nendo_label(x):
          if x == 0:
              return "平成30年"
          return f"令和{x}年"

      nendo_from, nendo_to = st.select_slider(
          "対象年度", options=list(range(0, 9)),
          value=(0, 8), format_func=nendo_label
      )

      run = st.button("判定する", type="primary", use_container_width=True)

  # ── メインエリア ──
  if not run:
      st.info("← 左のサイドバーに物件情報を入力し、「判定する」ボタンを押してください。")
      st.stop()

  input_sqm = price / area

  # ────────────────────────────────────────
  # ① 同一物件の過去成約事例
  # ────────────────────────────────────────
  same_bldg = find_same_building(df_all, building_name) if building_name.strip() else pd.DataFrame()

  if not same_bldg.empty:
      st.subheader(f"🏢 「{building_name}」の過去成約事例")

      sb_sqm = same_bldg["㎡単価_calc"].dropna()
      sc1, sc2, sc3, sc4 = st.columns(4)
      sc1.metric("成約件数", f"{len(same_bldg)} 件")
      sc2.metric("㎡単価 中央値", f"{sb_sqm.median():.1f} 万円/㎡" if not sb_sqm.empty else "―")
      sc3.metric("㎡単価 最安値", f"{sb_sqm.min():.1f} 万円/㎡" if not sb_sqm.empty else "―")
      sc4.metric("㎡単価 最高値", f"{sb_sqm.max():.1f} 万円/㎡" if not sb_sqm.empty else "―")

      if not sb_sqm.empty:
          sb_median = sb_sqm.median()
          sb_diff   = (sb_median - input_sqm) / sb_median * 100
          sb_label, sb_color, sb_desc = get_verdict(sb_diff)
          st.markdown(
              f"<div style='background:{sb_color};padding:12px;border-radius:8px;"
              f"text-align:center;font-size:1.2rem;font-weight:bold;color:#222;'>"
              f"同一物件の成約履歴と比較: {sb_label}"
              f"<br><span style='font-size:0.9rem;font-weight:normal;'>{sb_desc}（同物件中央値
  {sb_median:.1f} 万円/㎡）</span>"
              f"</div>",
              unsafe_allow_html=True,
          )
          st.markdown("")

      if len(same_bldg) >= 2:
          fig_trend = go.Figure()
          fig_trend.add_trace(go.Scatter(
              x=same_bldg["成約年月日"],
              y=same_bldg["㎡単価_calc"],
              mode="markers+lines",
              marker=dict(size=8, color="steelblue"),
              line=dict(color="steelblue", width=1, dash="dot"),
              text=same_bldg["専有面積"].apply(lambda x: f"{x}㎡"),
              hovertemplate="<b>%{x|%Y-%m-%d}</b><br>㎡単価:
  %{y:.1f}万円/㎡<br>%{text}<extra></extra>",
          ))
          fig_trend.add_hline(
              y=input_sqm, line_color="red", line_width=2,
              annotation_text=f"入力物件 {input_sqm:.1f}",
              annotation_position="top right",
          )
          fig_trend.update_layout(
              title="同一物件の㎡単価 推移",
              xaxis_title="成約年月日",
              yaxis_title="㎡単価（万円/㎡）",
              height=300,
              margin=dict(t=40, b=30),
          )
          st.plotly_chart(fig_trend, use_container_width=True)

      with st.expander("📋 同一物件の成約履歴一覧", expanded=True):
          st.dataframe(format_table(same_bldg), use_container_width=True, hide_index=True)

      st.markdown("---")

  # ────────────────────────────────────────
  # ② 周辺類似物件との比較・総合判定
  # ────────────────────────────────────────
  st.subheader("📊 周辺類似物件との比較")

  comp = find_comparables(
      df_all, ward, station, area, built_year,
      area_range, age_range, nendo_from, nendo_to,
      walk_max=walk_max
  )

  if len(comp) < 3:
      st.warning(
          f"比較対象物件が{len(comp)}件しかありません。条件を緩めてください。\n"
          "（最寄駅の指定を外す、専有面積の許容範囲を広げる、など）"
      )
      st.stop()

  sqm_series = comp["㎡単価_calc"].dropna()
  median_sqm  = sqm_series.median()
  mean_sqm    = sqm_series.mean()
  p25         = sqm_series.quantile(0.25)
  p75         = sqm_series.quantile(0.75)
  percentile  = (sqm_series < input_sqm).mean() * 100
  diff_pct    = (median_sqm - input_sqm) / median_sqm * 100

  verdict_label, verdict_color, verdict_desc = get_verdict(diff_pct)

  col1, col2, col3 = st.columns(3)
  col1.metric("入力物件の㎡単価", f"{input_sqm:.1f} 万円/㎡")
  col2.metric("周辺成約の中央値（㎡単価）", f"{median_sqm:.1f} 万円/㎡",
              delta=f"{diff_pct:+.1f}%（安い方向がプラス）")
  col3.metric("比較件数", f"{len(comp)} 件")

  st.markdown("---")

  # 判定バナー
  st.markdown(
      f"<div style='background:{verdict_color};padding:18px;border-radius:10px;"
      f"text-align:center;font-size:1.6rem;font-weight:bold;color:#222;'>"
      f"【周辺比較】{verdict_label}<br>"
      f"<span style='font-size:1rem;font-weight:normal;'>{verdict_desc}</span>"
      f"</div>",
      unsafe_allow_html=True,
  )

  st.markdown("")

  with st.expander("📊 詳細な統計", expanded=True):
      mc1, mc2, mc3, mc4, mc5 = st.columns(5)
      mc1.metric("25%タイル", f"{p25:.1f}")
      mc2.metric("中央値",     f"{median_sqm:.1f}")
      mc3.metric("平均",       f"{mean_sqm:.1f}")
      mc4.metric("75%タイル", f"{p75:.1f}")
      mc5.metric("入力物件の安さ順位",
                 f"下位 {percentile:.0f}%",
                 help="値が低いほどお買い得（安い）")

  # ヒストグラム
  st.subheader("📈 ㎡単価の分布（周辺類似物件）")

  fig = go.Figure()
  fig.add_trace(go.Histogram(
      x=sqm_series,
      nbinsx=30,
      name="成約事例",
      marker_color="steelblue",
      opacity=0.75,
  ))
  fig.add_vline(x=input_sqm, line_color="red", line_width=2.5,
                annotation_text=f"入力物件 {input_sqm:.1f}",
                annotation_position="top right")
  fig.add_vline(x=median_sqm, line_color="orange", line_width=1.5,
                line_dash="dash",
                annotation_text=f"中央値 {median_sqm:.1f}",
                annotation_position="top left")
  fig.update_layout(
      xaxis_title="㎡単価（万円/㎡）",
      yaxis_title="件数",
      height=350,
      margin=dict(t=30),
  )
  st.plotly_chart(fig, use_container_width=True)

  with st.expander("🏘️  比較に使った類似物件一覧"):
      st.dataframe(format_table(comp), use_container_width=True, hide_index=True)
