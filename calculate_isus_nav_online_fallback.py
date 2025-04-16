import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup # For parsing HTML
import re # For finding text pattern (less needed now but keep import)
import io
import time
import datetime
import warnings
import os
import sys # To exit script

# Suppress specific FutureWarning from yfinance/pandas if needed
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")

# --- Configuration ---
# URL for the main product page to scrape Shares Outstanding
product_page_url = "https://www.ishares.com/uk/individual/en/products/251393/ishares-msci-usa-islamic-ucits-etf"
# URL for the downloadable holdings CSV
holdings_url = "https://www.ishares.com/uk/individual/en/products/251393/ishares-msci-usa-islamic-ucits-etf/1506575576011.ajax?fileType=csv&fileName=ISUS_holdings&dataType=fund"
# Local fallback CSV file
fallback_holdings_file = 'ISUS_holdings.csv'
# Output files
result_file = "nav_result.txt"
source_file = "source_used.txt"

# Common headers for requests
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# Function to write to a status file, handling potential errors
def write_status_file(filename, content):
    try:
        with open(filename, "w") as f:
            f.write(str(content))
    except IOError as e:
        print(f"Warning: Could not write status to file '{filename}': {e}")

# --- 1. Scrape Shares Outstanding from Product Page ---
total_isus_shares_outstanding = None
print(f"Attempting to scrape Shares Outstanding from {product_page_url}...")
try:
    response = requests.get(product_page_url, headers=REQUEST_HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'lxml') # Use lxml parser

    # --- !!! Selector Fragility Warning !!! ---
    # Using selectors based on the HTML snippet provided by the user.
    # This can STILL BREAK if iShares changes their website HTML/CSS classes.

    # Find the container div using its specific classes
    container_div = soup.find('div', class_='col-sharesOutstanding') # Find the div with this class

    if container_div:
        # Find the 'data' div within the container
        value_div = container_div.find('div', class_='data')
        if value_div:
            shares_text = value_div.get_text(strip=True).replace(',', '')
            # Check if the extracted text consists only of digits
            if shares_text.isdigit():
                total_isus_shares_outstanding = float(shares_text)
                print(f"Successfully scraped Shares Outstanding: {total_isus_shares_outstanding:,.0f}")
            else:
                print(f"Warning: Found 'data' div for Shares Outstanding, but content is not purely numeric: '{shares_text}'")
        else:
            print("Warning: Found 'col-sharesOutstanding' container, but couldn't find the 'data' div inside.")
    else:
        print("Warning: Could not find the container div with class 'col-sharesOutstanding'. Website structure may have changed.")

    # Raise error if scraping failed
    if total_isus_shares_outstanding is None:
         raise ValueError("Failed to find or parse Shares Outstanding value from webpage using specific selectors.")

except requests.exceptions.RequestException as e:
    print(f"FATAL ERROR: Could not fetch product page URL for scraping: {e}")
    write_status_file(result_file, "ERROR")
    sys.exit(1)
except ImportError:
     print("FATAL ERROR: Required libraries for scraping not found (requests, bs4, lxml). Please install them.")
     write_status_file(result_file, "ERROR")
     sys.exit(1)
except Exception as e:
    print(f"FATAL ERROR during scraping for Shares Outstanding: {e}")
    write_status_file(result_file, "ERROR")
    sys.exit(1)


# --- 2. Attempt to Fetch/Load Holdings Data (URL/Fallback CSV) ---
# (This section remains unchanged from the previous version)
holdings_df = None
source_used = "Unknown" # Default source status

# Try fetching from holdings URL first
try:
    print(f"\nAttempting to fetch latest holdings CSV from iShares URL...")
    response = requests.get(holdings_url, headers=REQUEST_HEADERS, timeout=30)
    response.raise_for_status()
    print("Holdings CSV downloaded successfully from URL.")
    try:
        csv_content = response.content.decode('utf-8')
    except UnicodeDecodeError:
        csv_content = response.content.decode('latin-1')

    lines = csv_content.strip().splitlines()
    if len(lines) > 2:
        csv_data_string = "\n".join(lines[2:])
        holdings_df = pd.read_csv(io.StringIO(csv_data_string))
        source_used = "URL"
        print("Parsed holdings data from URL.")
    else:
        print("Warning: Downloaded CSV from URL has fewer than 3 lines. Will try fallback.")
        holdings_df = None

except requests.exceptions.RequestException as e:
    print(f"Warning: Could not fetch holdings CSV from URL: {e}. Will try fallback.")
    holdings_df = None
except Exception as e:
    print(f"Warning: Error processing data from holdings URL: {e}. Will try fallback.")
    holdings_df = None

# Fallback to local file if URL fetch failed
if holdings_df is None:
    print(f"\nAttempting to load holdings from local file: {fallback_holdings_file}")
    if os.path.exists(fallback_holdings_file):
        try:
            holdings_df = pd.read_csv(fallback_holdings_file)
            source_used = "Local File"
            print(f"Successfully loaded holdings from {fallback_holdings_file}.")
        except Exception as e:
            print(f"FATAL ERROR: Failed to read fallback file '{fallback_holdings_file}': {e}")
            write_status_file(source_file, "Error")
            write_status_file(result_file, "ERROR")
            sys.exit(1)
    else:
        print(f"FATAL ERROR: Fallback file '{fallback_holdings_file}' not found and URL fetch failed.")
        write_status_file(source_file, "Error")
        write_status_file(result_file, "ERROR")
        sys.exit(1)

# Write the determined source to the status file
write_status_file(source_file, source_used)

# --- 3. Data Cleaning (Applied to holdings dataframe) ---
# (Cleaning logic remains the same)
try:
    print("\nCleaning holdings data...")
    required_cols = ['Ticker', 'Shares', 'Market Currency', 'Asset Class', 'Market Value']
    if not all(col in holdings_df.columns for col in required_cols):
        print(f"Warning: Missing one or more expected columns: {required_cols}.")
        print(f"Available columns: {holdings_df.columns.tolist()}")

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
    print(f"FATAL ERROR during data cleaning (source: {source_used}): {e}")
    write_status_file(result_file, "ERROR")
    sys.exit(1)


# --- 4. Identify Top 10 Equity Holdings ---
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


# --- 5. Fetch Current FX Rates ---
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


# --- 6. Fetch Current Prices and Calculate Total Asset Value ---
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


# --- 7. Estimate NAV & Save Result ---
# (Logic remains the same, uses scraped shares outstanding)
calculation_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')
print(f"\n--- NAV Calculation Summary ({calculation_time}) ---")
print(f"Holdings Data Source Used: {source_used}")

estimated_nav_per_share_usd = None
final_result_status = "ERROR"

if missing_prices:
    unique_missing = sorted(list(set(missing_prices)))
    print(f"Warning: Could not determine current value for some holdings: {', '.join(unique_missing)}")

# Check if shares outstanding was successfully scraped
if total_isus_shares_outstanding is None or total_isus_shares_outstanding <= 0:
     print("\nError: Invalid or missing Shares Outstanding value from web scraping. Cannot calculate NAV per share.\n")
else:
    print(f"Total Shares Outstanding used (scraped): {total_isus_shares_outstanding:,.0f}")
    estimated_nav_per_share_usd = total_portfolio_value_usd / total_isus_shares_outstanding
    print(f"\nEstimated NAV per Share (USD): {estimated_nav_per_share_usd:.4f}\n")
    if not missing_prices: # Only set status if NAV calculated AND no prices were missing
         final_result_status = f"{estimated_nav_per_share_usd:.4f}"

# --- Save result to file ---
write_status_file(result_file, final_result_status)

print("\nDisclaimer:")
print("- This NAV is an ESTIMATE based on fetched prices from yfinance, scraped shares outstanding, and fetched/fallback holdings data.")
print("- Shares outstanding scraping is FRAGILE and may break if the iShares website changes.")
print("- Fund liabilities (fees, etc.) are NOT included.")
print("- Always refer to the official NAV published by iShares/BlackRock.")

# Optional: Exit with non-zero code if errors occurred
if final_result_status == "ERROR":
    print("\nExiting with status code 1 due to calculation errors or missing data.")
    sys.exit(1)

