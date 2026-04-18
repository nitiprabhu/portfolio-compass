import requests
from bs4 import BeautifulSoup

def get_tickers(url):
    print(f"Fetching {url}...")
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers)
    soup = BeautifulSoup(r.text, 'html.parser')
    
    # Try multiple ways to find the table
    table = soup.find('table', {'id': 'constituents'})
    if not table:
        table = soup.find('table', class_='wikitable')
        
    if not table:
        print("No table found")
        return []
        
    tickers = []
    for row in table.find_all('tr'):
        cols = row.find_all('td')
        if cols:
            # Ticker is in the first column for S&P 400/600 constituents table
            # BUT sometimes it's the second. Let's look for the one with a link.
            ticker = cols[0].text.strip()
            # Clean up potential extra info
            ticker = ticker.split('\n')[0].strip()
            tickers.append(ticker)
            
    return tickers

mid_url = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
small_url = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"

mid_tickers = get_tickers(mid_url)
small_tickers = get_tickers(small_url)

print(f"Mid Cap Count: {len(mid_tickers)}")
print(f"Small Cap Count: {len(small_tickers)}")
if mid_tickers: print(f"Mid Sample: {mid_tickers[:5]}")
if small_tickers: print(f"Small Sample: {small_tickers[:5]}")
