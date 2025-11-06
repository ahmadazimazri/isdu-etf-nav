import pandas as pd
import yfinance as yf
import requests
import io
import time
import datetime
import warnings
import os # For checking fallback file existence
import sys # To exit script

# Suppress specific FutureWarning from yfinance/pandas if needed
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")

# --- Configuration ---
holdings_url = "https://www.ishares.com/uk/individual/en/products/251393/ishares-msci-usa-islamic-ucits-etf/1506575576011.ajax?fileType=csv&fileName=ISUS_holdings&dataType=fund"
fallback_holdings_file = 'ISUS_holdings.csv' # Local fallback file name
result_file = "nav_result.txt" # File to save the final NAV result
source_file = "source_used.txt" # File to save the data source used

# !! IMPORTANT !!: Update with the LATEST shares outstanding for ISUS
# Find this on the iShares website or reliable financial data source.
# Using value user provided in reverted code - VERIFY THIS VALUE.
total_isus_shares_outstanding = 3410000

# Function to write to a status file, handling potential errors
def write_status_file(filename, content):
    try:
        with open(filename, "w") as f:
            f.write(str(content))
        # print(f"Status written to {filename}: {content}") # Optional debug
    except IOError as e:
        print(f"Warning: Could not write status to file '{filename}': {e}")

# --- 1. Attempt to Fetch/Load Holdings Data ---
holdings_df = None
source_used = "Unknown" # Default source status

# Try fetching from URL first
try:
    print(f"Attempting to fetch latest holdings from iShares URL...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(holdings_url, headers=headers, timeout=30)
    response.raise_for_status() # Check for HTTP errors

    print("Holdings data downloaded successfully from URL.")
    # Decode the content
    try:
        csv_content = response.content.decode('utf-8')
    except UnicodeDecodeError:
        print("UTF-8 decode failed, trying latin-1...")
        csv_content = response.content.decode('latin-1')

    # Split into lines and skip the first two lines
    lines = csv_content.strip().splitlines()

    if len(lines) > 2:
        # Assume the 3rd line (index 2) is the header row for pandas
        csv_data_string = "\n".join(lines[2:])
        # Read the processed string data using pandas
        holdings_df = pd.read_csv(io.StringIO(csv_data_string))
        source_used = "URL" # Set source
        print("Parsed holdings data from URL.")
    else:
        print("Warning: Downloaded CSV from URL has fewer than 3 lines. Will try fallback.")
        holdings_df = None # Ensure df is None to trigger fallback

except requests.exceptions.RequestException as e:
    print(f"Warning: Could not fetch holdings data from URL: {e}. Will try fallback.")
    holdings_df = None
except Exception as e:
    print(f"Warning: Error processing data from URL: {e}. Will try fallback.")
    holdings_df = None

# Fallback to local file if URL fetch failed or resulted in invalid data
if holdings_df is None:
    print(f"\nAttempting to load holdings from local file: {fallback_holdings_file}")
    if os.path.exists(fallback_holdings_file):
        try:
            holdings_df = pd.read_csv(fallback_holdings_file)
            source_used = "Local File" # Set source
            print(f"Successfully loaded holdings from {fallback_holdings_file}.")
        except Exception as e:
            print(f"FATAL ERROR: Failed to read fallback file '{fallback_holdings_file}': {e}")
            write_status_file(source_file, "Error") # Write error status for source
            write_status_file(result_file, "ERROR")
            sys.exit(1) # Exit with non-zero code on fatal error
    else:
        print(f"FATAL ERROR: Fallback file '{fallback_holdings_file}' not found and URL fetch failed.")
        write_status_file(source_file, "Error") # Write error status for source
        write_status_file(result_file, "ERROR")
        sys.exit(1) # Exit with non-zero code on fatal error

# Write the determined source to the status file
write_status_file(source_file, source_used)

# --- 2. Data Cleaning (Applied to whichever source was successful) ---
try:
    print("\nCleaning holdings data...")
    # Apply cleaning logic
    cols_to_clean = ['Market Value', 'Weight (%)', 'Notional Value', 'Shares', 'Price']
    for col in cols_to_clean:
        if col in holdings_df.columns:
            holdings_df[col] = holdings_df[col].astype(str).str.replace(',', '', regex=False)
            if '%' in col:
                 holdings_df[col] = holdings_df[col].str.replace('%', '', regex=False)
            holdings_df[col] = pd.to_numeric(holdings_df[col], errors='coerce')

    required_cols = ['Ticker', 'Shares', 'Market Currency', 'Asset Class', 'Market Value']
    if not all(col in holdings_df.columns for col in required_cols):
        raise ValueError(f"Loaded data source ('{source_used}') is missing required columns. Found: {holdings_df.columns.tolist()}")

    holdings_df.dropna(subset=required_cols, inplace=True)
    holdings_df['Shares'] = pd.to_numeric(holdings_df['Shares'], errors='coerce')
    holdings_df.dropna(subset=['Shares'], inplace=True)
    print("Holdings data cleaned.")

except Exception as e:
    print(f"FATAL ERROR during data cleaning (source: {source_used}): {e}")
    write_status_file(result_file, "ERROR")
    sys.exit(1)


# --- 3. Identify Top 10 Equity Holdings ---
top_10_equities = []
try:
    # Ensure Market Value is numeric before sorting
    holdings_df['Market Value'] = pd.to_numeric(holdings_df['Market Value'], errors='coerce')
    equities_df = holdings_df[holdings_df['Asset Class'] == 'Equity'].copy()
    if not equities_df.empty and not equities_df['Market Value'].isnull().all():
         top_10_equities = equities_df.nlargest(10, 'Market Value')['Ticker'].tolist()
         print(f"\nIdentified Top 10 Holdings (by initial Market Value): {top_10_equities}")
    else:
        print("Warning: No equity holdings with valid Market Value found to determine top 10.")
except Exception as e:
    print(f"Warning: Could not determine top 10 holdings due to data issue: {e}")


# --- 4. Fetch Current FX Rates ---
print("\nFetching current FX rates...")
current_eur_usd_rate = None
current_gbp_usd_rate = None
try:
    # Fetch EUR to USD rate
    eur_usd_ticker = yf.Ticker("EURUSD=X")
    eur_usd_info = eur_usd_ticker.history(period="1d")
    if not eur_usd_info.empty:
        current_eur_usd_rate = eur_usd_info['Close'].iloc[-1]
        print(f"  Current EUR/USD rate: {current_eur_usd_rate:.4f}")
    else:
        print("  Warning: Could not fetch EUR/USD rate.")
    time.sleep(0.2) # Small delay

    # Fetch GBP to USD rate
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
total_portfolio_value_usd = 0.0
missing_prices = []
processed_count = 0

print("\nFetching current prices and calculating total value...")
print("(Displaying details only for Top 10 equities)")

# Market time check
now_utc = datetime.datetime.now(datetime.timezone.utc)
us_eastern_time = now_utc.astimezone(datetime.timezone(datetime.timedelta(hours=-4), name="EDT")) # Approx ET
print(f"Current time: {us_eastern_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
if 9 <= us_eastern_time.hour < 16 and us_eastern_time.weekday() < 5 :
    print("US Markets likely open - prices may be intra-day.")
else:
    print("US Markets likely closed - prices likely represent last closing price.")


for index, row in holdings_df.iterrows():
    ticker = row.get('Ticker', 'N/A') # Use .get for safety if column missing
    shares = row.get('Shares')
    currency = row.get('Market Currency', 'N/A')
    asset_class = row.get('Asset Class', 'N/A')

    # Skip if essential data missing after cleaning
    if pd.isna(shares) or ticker == 'N/A' or currency == 'N/A' or asset_class == 'N/A':
        continue

    current_price_usd = None
    holding_value_usd = 0
    print_details = ticker in top_10_equities

    if asset_class == 'Equity':
        if not print_details and processed_count % 25 == 0:
             print(f"  Processing other holdings... ({processed_count+1}/{len(holdings_df)})")

        try:
            # Skip fetching if ticker looks invalid
            if not isinstance(ticker, str) or len(ticker) > 10 or ' ' in ticker:
                 print(f"  Skipping invalid ticker: {ticker}")
                 continue

            stock_ticker = yf.Ticker(ticker)
            info = stock_ticker.info
            current_price_usd = info.get('currentPrice') or info.get('regularMarketPrice')

            if current_price_usd is None: # Fallback to previous close
                hist = stock_ticker.history(period="1d")
                if not hist.empty:
                    current_price_usd = hist['Close'].iloc[-1]

            if current_price_usd is not None:
                holding_value_usd = shares * current_price_usd
                total_portfolio_value_usd += holding_value_usd
                if print_details:
                     print(f"  -> {ticker}: Shares: {shares:,.2f}, Price: {current_price_usd:.2f} USD, Value: {holding_value_usd:,.2f} USD")
            else:
                missing_prices.append(str(ticker)) # Convert potential non-strings
                if print_details:
                     print(f"  -> Warning: Could not retrieve price for {ticker}")

            time.sleep(0.2) # Pause briefly

        except Exception as e:
            missing_prices.append(str(ticker)) # Convert potential non-strings
            if print_details:
                print(f"  -> Error fetching price for {ticker}: {e}")

    elif asset_class == 'Cash':
        cash_amount = row.get('Market Value') # Using Market Value col for cash amount
        if pd.isna(cash_amount):
             print(f"  Warning: Missing 'Market Value' for Cash row with currency {currency}. Skipping.")
             continue

        print(f"  Processing Cash: {cash_amount:,.2f} {currency}")
        if currency == 'USD':
            holding_value_usd = cash_amount
            total_portfolio_value_usd += holding_value_usd
        elif currency == 'EUR':
            if current_eur_usd_rate is not None:
                holding_value_usd = cash_amount * current_eur_usd_rate # Multiply EUR amount by EUR->USD rate
                total_portfolio_value_usd += holding_value_usd
                print(f"    Converted Value: {holding_value_usd:,.2f} USD")
            else:
                print(f"    Warning: Cannot convert EUR cash, missing FX rate.")
                missing_prices.append(f"{currency} Cash")
        elif currency == 'GBP':
            if current_gbp_usd_rate is not None:
                holding_value_usd = cash_amount * current_gbp_usd_rate # Multiply GBP amount by GBP->USD rate
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
calculation_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')
print(f"\n--- NAV Calculation Summary ({calculation_time}) ---")
print(f"Holdings Data Source Used: {source_used}") # Indicate source used

estimated_nav_per_share_usd = None # Initialize variable
final_result_status = "ERROR" # Default status for result file

if missing_prices:
    unique_missing = sorted(list(set(missing_prices)))
    print(f"Warning: Could not determine current value for some holdings: {', '.join(unique_missing)}")
    # Keep final_result_status as "ERROR" if prices are missing

if total_isus_shares_outstanding > 0:
    estimated_nav_per_share_usd = total_portfolio_value_usd / total_isus_shares_outstanding
    print(f"Total Shares Outstanding used (hardcoded): {total_isus_shares_outstanding:,}")
    # --- FINAL RESULT ---
    print(f"\nEstimated NAV per Share (USD): {estimated_nav_per_share_usd:.4f}\n")
    # Set status to the calculated value only if prices weren't missing
    if not missing_prices:
         final_result_status = f"{estimated_nav_per_share_usd:.4f}"
else:
    print("\nError: Total shares outstanding is zero or invalid. Cannot calculate NAV per share.\n")
    # Keep final_result_status as "ERROR"

# --- Save result to file ---
write_status_file(result_file, final_result_status)


print("\nDisclaimer:")
print("- This NAV is an ESTIMATE based on fetched prices (possibly delayed/closing) from yfinance and specified shares outstanding.")
print("- Holdings data attempted from iShares URL, with local file fallback.")
print("- Fund liabilities (fees, etc.) are NOT included in this calculation.")
print("- Always refer to the official NAV published by iShares/BlackRock.")

# Optional: Exit with non-zero code if errors occurred
if final_result_status == "ERROR":
    print("\nExiting with status code 1 due to calculation errors or missing data.")
    sys.exit(1)
