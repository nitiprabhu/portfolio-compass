from scanner import MarketScanner

scanner = MarketScanner()
print("Fetching Small-Cap Tickers...")
tickers = scanner.get_small_cap_tickers()
print(f"Found {len(tickers)} tickers. First 5: {tickers[:5]}")

print("\nRunning quick scan on first 10 assets...")
# Mock the internal logic or just run on a very small set to avoid long wait
results = scanner.run_scan() # This might take too long if it scans 600
# But I changed run_scan to be more aggressive.
