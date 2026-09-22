# dashboard.py
# ============================================================
# Current Month Payment Dashboard
# - Site open karte hi Excel file upload karne ka option aayega
# - CA = BILL_DATE current month wale bills ka sum
# - Total Paid = LAST_PAY_DATE current month wali payments ka sum
# ============================================================
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="Payment Dashboard", layout="wide")

# ================== CONFIG ==================
BILL_DATE_COL = "BILL_DATE"              # CA ke liye
DATE_COL      = "LAST_PAY_DATE"          # Paid ke liye
CATEGORY_COL  = "TARIFF_TYPE"
AMOUNT_COL    = "LAST_PAYMENT_AMOUNT"    # ya "TOTAL_PAY_AMT"
LOAD_COL      = "SANCTION_LOAD"
LOAD_UOM_COL  = "SANCTION_LOAD_UOM"
CA_COL        = "CA"
SDO_CODE_COL  = "SDO_CODE"
SDO_NAME_COL  = "SDO_NAME"

EXTRA_COLS = ["PAYMENT_MODE", "DIV_NAME", "SUPPLY_TYPE",
              SDO_CODE_COL, SDO_NAME_COL]

TARIFF_MERGE = {"HV1": "HV", "HV2": "HV"}

HV_TARIFFS         = {"HV1", "HV2"}
EXCLUDED_FROM_LOAD = {"LMV3", "LMV4", "LMV5", "LMV7", "LMV8", "LMV10"}

LOAD_ORDER = [
    "HV CONNECTION",
    ">= 10 KW/KVA/BHP",
    "5-9 KW/KVA/BHP",
    "< 5 KW/KVA/BHP",
]

CRORE = 1_00_00_000
# ============================================


# ================== PREPARE ==================
@st.cache_data(show_spinner="Data process ho raha hai...")
def prepare(df: pd.DataFrame, year: int, month: int, merge_tuple: tuple):
    """
    Do alag dataframes banata hai:
      df_paid : LAST_PAY_DATE current month me ho (Total Paid ke liye)
      df_bill : BILL_DATE current month me ho (CA ke liye)
    Dono me LOAD_CATEGORY aur TARIFF_MERGE apply hote hain.
    """
    df = df.copy()

    # Date parse
    df[DATE_COL]      = pd.to_datetime(df[DATE_COL], errors="coerce")
    df[BILL_DATE_COL] = pd.to_datetime(df[BILL_DATE_COL], errors="coerce")

    # ---------- LOAD CATEGORY (dono ke liye) ----------
    tariff = df[CATEGORY_COL].astype(str).str.strip().str.upper()
    load   = df[LOAD_COL] if LOAD_COL in df.columns else pd.Series(pd.NA, index=df.index)

    is_hv       = tariff.isin(HV_TARIFFS)
    is_excluded = tariff.isin(EXCLUDED_FROM_LOAD)
    is_eligible = ~is_hv & ~is_excluded

    load_cat = pd.Series([None] * len(df), index=df.index, dtype="object")
    load_cat[is_hv] = "HV CONNECTION"
    load_cat[is_eligible & (load >= 10)] = ">= 10 KW/KVA/BHP"
    load_cat[is_eligible & (load >= 5) & (load < 10)] = "5-9 KW/KVA/BHP"
    load_cat[is_eligible & (load < 5) & load.notna()] = "< 5 KW/KVA/BHP"

    df["LOAD_CATEGORY"] = load_cat

    # Tariff merge
    if merge_tuple:
        df[CATEGORY_COL] = df[CATEGORY_COL].replace(dict(merge_tuple))

    # ---------- PAID filter ----------
    df_paid = df.dropna(subset=[DATE_COL])
    df_paid = df_paid[df_paid[AMOUNT_COL].fillna(0) > 0]
    mask_paid = (df_paid[DATE_COL].dt.year == year) & (df_paid[DATE_COL].dt.month == month)
    df_paid = df_paid.loc[mask_paid]

    # ---------- BILL filter (CA ke liye) ----------
    df_bill = df.dropna(subset=[BILL_DATE_COL])
    mask_bill = (df_bill[BILL_DATE_COL].dt.year == year) & (df_bill[BILL_DATE_COL].dt.month == month)
    df_bill = df_bill.loc[mask_bill]

    return df_paid, df_bill


# ================== SUMMARY (CA + Paid separate sources) ==================
def make_summary(df_paid: pd.DataFrame, df_bill: pd.DataFrame,
                 group_col: str, order: list | None = None) -> pd.DataFrame:
    """
    df_paid : jis month me payment hui (Total Paid)
    df_bill : jis month me bill bana (CA)
    """
    # CA per group (bill month ke hisaab se)
    if not df_bill.empty and CA_COL in df_bill.columns:
        ca = (df_bill.groupby(group_col, as_index=False, observed=True)
                     .agg(CA_Total=(CA_COL, "sum")))
    else:
        ca = pd.DataFrame({group_col: [], "CA_Total": []})

    # Paid per group
    if not df_paid.empty:
        paid = (df_paid.groupby(group_col, as_index=False, observed=True)
                       .agg(Total_Paid=(AMOUNT_COL, "sum"),
                            Txns=(AMOUNT_COL, "size")))
    else:
        paid = pd.DataFrame({group_col: [], "Total_Paid": [], "Txns": []})

    # Merge
    s = pd.merge(ca, paid, on=group_col, how="outer").fillna(0)
    s["CA_Cr"]    = s["CA_Total"] / CRORE
    s["Total_Cr"] = s["Total_Paid"] / CRORE
    s["Txns"]     = s["Txns"].astype(int)

    if order:
        s["__o"] = s[group_col].map({c: i for i, c in enumerate(order)})
        s = s.sort_values("__o").drop(columns="__o")
    else:
        s = s.sort_values("Total_Paid", ascending=False)
    return s


def show_4col_table(df_paid: pd.DataFrame, df_bill: pd.DataFrame,
                    group_col: str, title: str, key: str,
                    order: list | None = None, chart: bool = True):
    st.subheader(title)
    if df_paid.empty and df_bill.empty:
        st.info("Koi data nahi.")
        return

    s = make_summary(df_paid, df_bill, group_col, order=order)
    display = s[[group_col, "CA_Cr", "Total_Cr", "Txns"]].rename(columns={
        "CA_Cr":    "Current Assessment (Cr.)",
        "Total_Cr": "Total Paid (Cr.)",
        "Txns":     "Total Paid Count",
    })

    totals = pd.DataFrame([{
        group_col: "TOTAL",
        "Current Assessment (Cr.)": s["CA_Cr"].sum(),
        "Total Paid (Cr.)":         s["Total_Cr"].sum(),
        "Total Paid Count":         int(s["Txns"].sum()),
    }])
    display_full = pd.concat([display, totals], ignore_index=True)

    col1, col2 = st.columns([1.2, 1])
    with col1:
        st.dataframe(
            display_full.style
              .format({
                  "Current Assessment (Cr.)": "₹ {:,.2f}",
                  "Total Paid (Cr.)":         "₹ {:,.2f}",
                  "Total Paid Count":         "{:,}",
              })
              .apply(
                  lambda r: ["font-weight: bold"] * len(r)
                  if r[group_col] == "TOTAL" else [""] * len(r),
                  axis=1
              ),
            use_container_width=True, hide_index=True, height=400
        )
    with col2:
        if chart and not s.empty:
            fig = px.bar(s, x=group_col, y="Total_Cr",
                         text_auto=".3s", color=group_col, height=400)
            fig.update_layout(showlegend=False, xaxis_title="",
                              yaxis_title="Total Paid (Cr.)")
            st.plotly_chart(fig, use_container_width=True, key=f"bar_{key}")


# ================== MAIN ==================
def main():
    st.title("💰 Current Month Payment Dashboard")

    # ============ FILE UPLOAD ============
    with st.sidebar:
        st.header("📂 Excel File Upload")
        uploaded = st.file_uploader(
            "Apni .xlsx ya .csv file chunein",
            type=["xlsx", "xls", "csv"],
            help="File upload karte hi dashboard ban jayega."
        )

    if uploaded is None:
        st.info("👈 **Shuru karne ke liye left sidebar me apni Excel file upload karein.**")
        st.markdown("""
        ### Kaise use karein?
        1. Left side me **"Browse files"** button dabayein
        2. Apni `data.xlsx` file chunein
        3. Dashboard turant ban jayega

        ### Important logic
        - **Current Assessment (CA)** → un bills ka sum jinka **`BILL_DATE`** current month me hai
        - **Total Paid** → un payments ka sum jinki **`LAST_PAY_DATE`** current month me hai
        - Dono alag-alag source se aate hain, isliye alag dikh sakte hain.
        """)
        st.stop()

    # File padho
    with st.spinner("File load ho rahi hai..."):
        if uploaded.name.lower().endswith((".xlsx", ".xls")):
            df_all = pd.read_excel(uploaded)
        else:
            df_all = pd.read_csv(uploaded)

    st.success(f"✅ File load ho gayi: **{uploaded.name}** — {len(df_all):,} rows, {len(df_all.columns)} columns")

    # Column check
    required = [BILL_DATE_COL, DATE_COL, CATEGORY_COL, AMOUNT_COL, CA_COL]
    missing = [c for c in required if c not in df_all.columns]
    if missing:
        st.error(f"❌ Ye columns file me nahi mile: {missing}")
        st.write("**File me ye columns hain:**")
        st.write(list(df_all.columns))
        st.stop()

    today = datetime.today()
    merge_tuple = tuple(sorted(TARIFF_MERGE.items()))
    df_paid, df_bill = prepare(df_all, today.year, today.month, merge_tuple)

    if df_paid.empty and df_bill.empty:
        st.warning(f"{today.strftime('%B %Y')} me koi record nahi mila.")
        st.stop()

    # ---------- KPI ----------
    total_paid = float(df_paid[AMOUNT_COL].sum()) if not df_paid.empty else 0.0
    total_ca   = float(df_bill[CA_COL].sum())     if not df_bill.empty else 0.0
    txns       = len(df_paid)
    avg_pay    = total_paid / txns if txns else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Month", today.strftime("%B %Y"))
    c2.metric("Current Assessment", f"₹ {total_ca / CRORE:,.2f} Cr.",
              help="Bill date current month wale bills ka sum (CA)")
    c3.metric("Total Paid", f"₹ {total_paid / CRORE:,.2f} Cr.",
              help="Payment date current month wali payments ka sum")
    c4.metric("Transactions", f"{txns:,}")
    c5.metric("Avg / Txn", f"₹ {avg_pay / CRORE:,.4f} Cr.")

    st.divider()

    # ---------- TABS ----------
    tab1, tab2, tab3, tab4 = st.tabs(
        ["📋 Tariff Type", "⚡ Load wise", "🏢 SDO wise", "📊 Extra"]
    )

    # TAB 1: TARIFF
    with tab1:
        show_4col_table(df_paid, df_bill, CATEGORY_COL,
                        "Tariff Type wise", key="tariff")
        with st.expander("🥧 Share by Tariff (Paid)"):
            s = make_summary(df_paid, df_bill, CATEGORY_COL)
            if not s.empty:
                fig = px.pie(s, names=CATEGORY_COL, values="Total_Cr", hole=0.4)
                st.plotly_chart(fig, use_container_width=True, key="pie_tariff")
        with st.expander("⬇️ Download CSV"):
            csv = make_summary(df_paid, df_bill, CATEGORY_COL).to_csv(index=False).encode("utf-8")
            st.download_button("Tariff wise CSV", csv,
                               "tariff_wise.csv", "text/csv", key="dl_tariff")

    # TAB 2: LOAD
    with tab2:
        if not df_paid.empty and "LOAD_CATEGORY" in df_paid.columns:
            df_p_load = df_paid.dropna(subset=["LOAD_CATEGORY"])
            df_b_load = df_bill.dropna(subset=["LOAD_CATEGORY"]) if not df_bill.empty else df_bill
            show_4col_table(df_p_load, df_b_load, "LOAD_CATEGORY",
                            "Load Category wise",
                            key="load", order=LOAD_ORDER)
            with st.expander("🥧 Share by Load Category"):
                s = make_summary(df_p_load, df_b_load, "LOAD_CATEGORY", order=LOAD_ORDER)
                if not s.empty:
                    fig = px.pie(s, names="LOAD_CATEGORY", values="Total_Cr", hole=0.4)
                    st.plotly_chart(fig, use_container_width=True, key="pie_load")
            excl_mask  = df_paid["LOAD_CATEGORY"].isna()
            excl_count = int(excl_mask.sum())
            excl_amt   = float(df_paid.loc[excl_mask, AMOUNT_COL].sum())
            st.caption(
                f"⚠️ Excluded from load buckets (LMV3/4/5/7/8/10 ya load NaN): "
                f"**{excl_count:,}** paid txns, **₹ {excl_amt / CRORE:,.2f} Cr.** — "
                f"ye sirf Tariff tab me dikhte hain."
            )
            with st.expander("⬇️ Download CSV"):
                csv = (make_summary(df_p_load, df_b_load, "LOAD_CATEGORY", order=LOAD_ORDER)
                       .to_csv(index=False).encode("utf-8"))
                st.download_button("Load wise CSV", csv,
                                   "load_wise.csv", "text/csv", key="dl_load")
        else:
            st.info("SANCTION_LOAD column nahi mila.")

    # TAB 3: SDO
    with tab3:
        if SDO_CODE_COL in df_all.columns:
            show_4col_table(df_paid, df_bill, SDO_CODE_COL,
                            "SDO Code wise", key="sdo")
            if SDO_NAME_COL in df_all.columns:
                with st.expander("📋 SDO Code + Name combined"):
                    if not df_bill.empty:
                        ca = (df_bill.groupby([SDO_CODE_COL, SDO_NAME_COL], as_index=False)
                                       .agg(CA_Total=(CA_COL, "sum")))
                    else:
                        ca = pd.DataFrame(columns=[SDO_CODE_COL, SDO_NAME_COL, "CA_Total"])
                    if not df_paid.empty:
                        paid = (df_paid.groupby([SDO_CODE_COL, SDO_NAME_COL], as_index=False)
                                         .agg(Total_Paid=(AMOUNT_COL, "sum"),
                                              Txns=(AMOUNT_COL, "size")))
                    else:
                        paid = pd.DataFrame(columns=[SDO_CODE_COL, SDO_NAME_COL, "Total_Paid", "Txns"])
                    s = pd.merge(ca, paid, on=[SDO_CODE_COL, SDO_NAME_COL],
                                 how="outer").fillna(0)
                    s["CA_Cr"]    = s["CA_Total"] / CRORE
                    s["Total_Cr"] = s["Total_Paid"] / CRORE
                    s["Txns"]     = s["Txns"].astype(int)
                    s = s.sort_values("Total_Cr", ascending=False)
                    out = s[[SDO_CODE_COL, SDO_NAME_COL,
                             "CA_Cr", "Total_Cr", "Txns"]].rename(columns={
                        "CA_Cr":    "Current Assessment (Cr.)",
                        "Total_Cr": "Total Paid (Cr.)",
                        "Txns":     "Total Paid Count",
                    })
                    st.dataframe(
                        out.style.format({
                            "Current Assessment (Cr.)": "₹ {:,.2f}",
                            "Total Paid (Cr.)":         "₹ {:,.2f}",
                            "Total Paid Count":         "{:,}",
                        }),
                        use_container_width=True, hide_index=True
                    )
            with st.expander("🥧 Share by SDO Code"):
                s = make_summary(df_paid, df_bill, SDO_CODE_COL)
                if not s.empty:
                    fig = px.pie(s, names=SDO_CODE_COL, values="Total_Cr", hole=0.4)
                    st.plotly_chart(fig, use_container_width=True, key="pie_sdo")
            with st.expander("⬇️ Download CSV"):
                csv = make_summary(df_paid, df_bill, SDO_CODE_COL).to_csv(index=False).encode("utf-8")
                st.download_button("SDO wise CSV", csv,
                                   "sdo_wise.csv", "text/csv", key="dl_sdo")
        else:
            st.info("SDO_CODE column nahi mila.")

    # TAB 4: EXTRA
    with tab4:
        if "PAYMENT_MODE" in df_all.columns:
            show_4col_table(df_paid, df_bill, "PAYMENT_MODE",
                            "Payment Mode wise", key="pm")
        if "DIV_NAME" in df_all.columns:
            show_4col_table(df_paid, df_bill, "DIV_NAME",
                            "Division wise", key="div")
        if "SUPPLY_TYPE" in df_all.columns:
            show_4col_table(df_paid, df_bill, "SUPPLY_TYPE",
                            "Supply Type wise", key="sup")

    # ---------- RAW ----------
    with st.expander(f"🔍 Raw data — Paid (top 500 of {txns:,})"):
        st.dataframe(df_paid.head(500), use_container_width=True)
    with st.expander(f"🔍 Raw data — Bill (top 500 of {len(df_bill):,})"):
        st.dataframe(df_bill.head(500), use_container_width=True)


if __name__ == "__main__":
    main()