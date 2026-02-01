import requests

print("--- Searchfox Debug ---")
base = "https://searchfox.org/mozilla-central"
query = "test"

# Try raw HTML again, check if results are further down?
# (We only printed 2000 chars) -> skipping this for now.

# Try possible JSON endpoints
endpoints = [
    f"{base}/search?q={query}&format=json",
    f"{base}/search/json?q={query}",
    f"{base}/api/search?q={query}"
]

for url in endpoints:
    print(f"Testing {url}")
    try:
        resp = requests.get(url)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
             ct = resp.headers.get('content-type', '')
             print(f"Content-Type: {ct}")
             if 'json' in ct:
                 print("JSON FOUND!")
                 print(resp.json())
             else:
                 print("Not JSON")
    except Exception as e:
        print(e)
