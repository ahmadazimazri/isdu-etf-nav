import pandas as pd
import yfinance as yf
# requests is no longer needed for holdings, but yfinance might use it
# import requests
import io
import time
import datetime
import warnings
import os
import sys # To exit script

# Suppress specific FutureWarning from yfinance/pandas if needed
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")

# --- Configuration ---
# ** IMPORTANT: Update this filename if you saved the XLSX with a different name **
holdings_excel_file = 'ISUS_holdings.xlsx' # Input Excel file (.xlsx format)
holdings_sheet_name = 'Holdings' # Sheet name (assuming it's still 'holdings')
header_row_index = 7 # Header starts at row 8 (0-indexed, assuming same as before)
shares_outstanding_cell_row = 5 # Cell C6 -> row index 5 (assuming same)
shares_outstanding_cell_col = 2 # Cell C6 -> col index 2 (assuming same)

result_file = "nav_result.txt" # File to save the final NAV result

# Function to write to a status file, handling potential errors
def write_status_file(filename, content):
    try:
        with open(filename, "w") as f:
            f.write(str(content))
    except IOError as e:
        print(f"Warning: Could not write status to file '{filename}': {e}")

# --- 1. Load Data from Excel File ---
holdings_df = None
total_isus_shares_outstanding = None

print(f"Attempting to load data from Excel file: {holdings_excel_file}")
if not os.path.exists(holdings_excel_file):
    print(f"FATAL ERROR: Excel file not found at '{holdings_excel_file}'")
    write_status_file(result_file, "ERROR")
    sys.exit(1)

try:
    # --- Read Shares Outstanding from Cell C6 (Revised Method) ---
    print("Reading Shares Outstanding value...")
    # Read the first 3 columns (A:C) of the target row (row 6 / index 5)
    shares_row_df = pd.read_excel(
        holdings_excel_file,
        engine='openpyxl',
        sheet_name=holdings_sheet_name,
        header=None, # Read without assuming headers for this specific read
        usecols="A:C", # Read columns A, B, C (indices 0, 1, 2)
        skiprows=shares_outstanding_cell_row, # Skip rows 0-4 to get to row 6
        nrows=1 # Read only this one row
    )

    # Check if the read was successful and has enough columns
    if not shares_row_df.empty and shares_row_df.shape[1] > shares_outstanding_cell_col:
        # Access the value using iloc[row_index, col_index]
        # Since we read only 1 row, row_index is 0. Target col_index is 2 (C).
        shares_val = shares_row_df.iloc[0, shares_outstanding_cell_col]

        # Clean the extracted value (remove commas, convert to number)
        if isinstance(shares_val, (int, float)):
             total_isus_shares_outstanding = float(shares_val)
        elif isinstance(shares_val, str):
             cleaned_shares_val = shares_val.replace(',', '')
             if cleaned_shares_val.replace('.', '', 1).isdigit():
                 total_isus_shares_outstanding = float(cleaned_shares_val)
             else:
                 raise ValueError(f"Non-numeric string found in cell C6: '{shares_val}'")
        else:
             if pd.isna(shares_val):
                 raise ValueError("Cell C6 (Shares Outstanding) is empty or NaN.")
             else:
                 raise ValueError(f"Unexpected data type in cell C6: {type(shares_val)}")
        print(f"Successfully read Shares Outstanding: {total_isus_shares_outstanding:,.0f}")
    else:
        # Raise error if reading failed or didn't return enough columns
        raise ValueError(f"Could not read cell C6 (Row index {shares_outstanding_cell_row}, Col index {shares_outstanding_cell_col}). DataFrame shape: {shares_row_df.shape}")

    # --- Read Holdings Table ---
    print(f"Reading holdings table from sheet '{holdings_sheet_name}'...")
    # Headers start at row 8 (index 7)
    holdings_df = pd.read_excel(
        holdings_excel_file,
        engine='openpyxl',
        sheet_name=holdings_sheet_name,
        header=header_row_index
    )
    print(f"Successfully read holdings table.")

except ImportError:
     print("FATAL ERROR: 'openpyxl' library not found. Please install it (pip install openpyxl) and add to requirements.txt")
     write_status_file(result_file, "ERROR")
     sys.exit(1)
except ValueError as e:
    print(f"FATAL ERROR: Problem extracting data from Excel: {e}")
    write_status_file(result_file, "ERROR")
    sys.exit(1)
except Exception as e:
    print(f"FATAL ERROR reading Excel file '{holdings_excel_file}': {e}")
    write_status_file(result_file, "ERROR")
    sys.exit(1)


# --- 2. Data Cleaning (Applied to holdings dataframe) ---
# (Cleaning logic remains the same as before)
try:
    print("\nCleaning holdings data...")
    required_cols = ['Ticker', 'Shares', 'Market Currency', 'Asset Class', 'Market Value']
    if not all(col in holdings_df.columns for col in required_cols):
        print(f"Warning: Missing one or more expected columns: {required_cols}.")
        print(f"Available columns: {holdings_df.columns.tolist()}")
        print("Attempting to proceed, but calculations might fail.")

    cols_to_clean = ['Market Value', 'Weight (%)', 'Notional Value', 'Shares', 'Price']
    for col in cols_to_clean:
        if col in holdings_df.columns:
            holdings_df[col] = holdings_df[col].astype(str).str.replace(',', '', regex=False)
            if '%' in col:
                 holdings_df[col] = holdings_df[col].str.replace('%', '', regex=False)
            holdings_df[col] = pd.to_numeric(holdings_df[col], errors='coerce')

    holdings_df.dropna(subset=['Ticker', 'Shares', 'Market Currency', 'Asset Class'], inplace=True)
    holdings_df['Shares'] = pd.to_numeric(holdings_df['Shares'], errors='coerce')
    holdings_df.dropna(subset=['Shares'], inplace=True)
    print("Holdings data cleaned.")

except Exception as e:
    print(f"FATAL ERROR during data cleaning: {e}")
    write_status_file(result_file, "ERROR")
    sys.exit(1)


# --- 3. Identify Top 10 Equity Holdings ---
# (Logic remains the same)
top_10_equities = []
try:
    if 'Market Value' in holdings_df.columns:
        holdings_df['Market Value'] = pd.to_numeric(holdings_df['Market Value'], errors='coerce')
        equities_df = holdings_df[holdings_df['Asset Class'] == 'Equity'].copy()
        if not equities_df.empty and not equities_df['Market Value'].isnull().all():
             top_10_equities = equities_df.nlargest(10, 'Market Value')['Ticker'].tolist()
             print(f"\nIdentified Top 10 Holdings (by initial Market Value): {top_10_equities}")
        else:
            print("Warning: No equity holdings with valid Market Value found to determine top 10.")
    else:
        print("Warning: 'Market Value' column not found, cannot determine top 10.")
except Exception as e:
    print(f"Warning: Could not determine top 10 holdings due to data issue: {e}")


# --- 4. Fetch Current FX Rates ---
# (Logic remains the same)
print("\nFetching current FX rates...")
current_eur_usd_rate = None
current_gbp_usd_rate = None
try:
    eur_usd_ticker = yf.Ticker("EURUSD=X")
    eur_usd_info = eur_usd_ticker.history(period="1d")
    if not eur_usd_info.empty:
        current_eur_usd_rate = eur_usd_info['Close'].iloc[-1]
        print(f"  Current EUR/USD rate: {current_eur_usd_rate:.4f}")
    else:
        print("  Warning: Could not fetch EUR/USD rate.")
    time.sleep(0.2)

    gbp_usd_ticker = yf.Ticker("GBPUSD=X")
    gbp_usd_info = gbp_usd_ticker.history(period="1d")
    if not gbp_usd_info.empty:
        current_gbp_usd_rate = gbp_usd_info['Close'].iloc[-1]
        print(f"  Current GBP/USD rate: {current_gbp_usd_rate:.4f}")
    else:
        print("  Warning: Could not fetch GBP/USD rate.")
except Exception as e:
    print(f"  Warning: Error fetching FX rates: {e}")


# --- 5. Fetch Current Prices and Calculate Total Asset Value ---
# (Logic remains the same)
total_portfolio_value_usd = 0.0
missing_prices = []
processed_count = 0

print("\nFetching current prices and calculating total value...")
print("(Displaying details only for Top 10 equities)")

now_utc = datetime.datetime.now(datetime.timezone.utc)
us_eastern_time = now_utc.astimezone(datetime.timezone(datetime.timedelta(hours=-4), name="EDT")) # Approx ET
print(f"Current time: {us_eastern_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
# ... (market open/closed logic remains same) ...

for index, row in holdings_df.iterrows():
    ticker = row.get('Ticker', 'N/A')
    shares = row.get('Shares')
    currency = row.get('Market Currency', 'N/A')
    asset_class = row.get('Asset Class', 'N/A')

    if pd.isna(shares) or ticker == 'N/A' or currency == 'N/A' or asset_class == 'N/A':
        continue

    current_price_usd = None
    holding_value_usd = 0
    print_details = ticker in top_10_equities

    if asset_class == 'Equity':
        if not print_details and processed_count % 25 == 0:
             print(f"  Processing other holdings... ({processed_count+1}/{len(holdings_df)})")
        try:
            if not isinstance(ticker, str) or len(ticker) > 10 or ' ' in ticker:
                 print(f"  Skipping invalid ticker: {ticker}")
                 continue

            stock_ticker = yf.Ticker(ticker)
            info = stock_ticker.info
            current_price_usd = info.get('currentPrice') or info.get('regularMarketPrice')
            if current_price_usd is None:
                hist = stock_ticker.history(period="1d")
                if not hist.empty:
                    current_price_usd = hist['Close'].iloc[-1]

            if current_price_usd is not None:
                holding_value_usd = shares * current_price_usd
                total_portfolio_value_usd += holding_value_usd
                if print_details:
                     print(f"  -> {ticker}: Shares: {shares:,.2f}, Price: {current_price_usd:.2f} USD, Value: {holding_value_usd:,.2f} USD")
            else:
                missing_prices.append(str(ticker))
                if print_details:
                     print(f"  -> Warning: Could not retrieve price for {ticker}")
            time.sleep(0.2)
        except Exception as e:
            missing_prices.append(str(ticker))
            if print_details:
                print(f"  -> Error fetching price for {ticker}: {e}")

    elif asset_class == 'Cash':
        cash_amount = row.get('Market Value')
        if pd.isna(cash_amount):
            print(f"  Warning: Missing 'Market Value' for Cash row with currency {currency}. Skipping.")
            continue

        print(f"  Processing Cash: {cash_amount:,.2f} {currency}")
        if currency == 'USD':
            holding_value_usd = cash_amount
            total_portfolio_value_usd += holding_value_usd
        elif currency == 'EUR':
            if current_eur_usd_rate is not None:
                holding_value_usd = cash_amount * current_eur_usd_rate
                total_portfolio_value_usd += holding_value_usd
                print(f"    Converted Value: {holding_value_usd:,.2f} USD")
            else:
                print(f"    Warning: Cannot convert EUR cash, missing FX rate.")
                missing_prices.append(f"{currency} Cash")
        elif currency == 'GBP':
            if current_gbp_usd_rate is not None:
                holding_value_usd = cash_amount * current_gbp_usd_rate
                total_portfolio_value_usd += holding_value_usd
                print(f"    Converted Value: {holding_value_usd:,.2f} USD")
            else:
                print(f"    Warning: Cannot convert GBP cash, missing FX rate.")
                missing_prices.append(f"{currency} Cash")
        else:
             print(f"    Warning: Unhandled cash currency {currency}")
             missing_prices.append(f"{currency} Cash")
    processed_count += 1


# --- 6. Estimate NAV & Save Result ---
# (Logic remains the same)
calculation_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')
print(f"\n--- NAV Calculation Summary ({calculation_time}) ---")
print(f"Holdings Data Source: Excel File ('{holdings_excel_file}')")

estimated_nav_per_share_usd = None
final_result_status = "ERROR"

if missing_prices:
    unique_missing = sorted(list(set(missing_prices)))
    print(f"Warning: Could not determine current value for some holdings: {', '.join(unique_missing)}")

if total_isus_shares_outstanding is None or total_isus_shares_outstanding <= 0:
     print("\nError: Invalid or missing Shares Outstanding value from Excel. Cannot calculate NAV per share.\n")
else:
    print(f"Total Shares Outstanding used (from Excel C6): {total_isus_shares_outstanding:,.0f}")
    estimated_nav_per_share_usd = total_portfolio_value_usd / total_isus_shares_outstanding
    print(f"\nEstimated NAV per Share (USD): {estimated_nav_per_share_usd:.4f}\n")
    if not missing_prices:
         final_result_status = f"{estimated_nav_per_share_usd:.4f}"

# --- Save result to file ---
write_status_file(result_file, final_result_status)

print("\nDisclaimer:")
print("- This NAV is an ESTIMATE based on fetched prices from yfinance and data from the provided Excel file.")
print("- Fund liabilities (fees, etc.) are NOT included.")
print("- Always refer to the official NAV published by iShares/BlackRock.")

# Optional: Exit with non-zero code if errors occurred
if final_result_status == "ERROR":
    print("\nExiting with status code 1 due to calculation errors or missing data.")
    sys.exit(1)

