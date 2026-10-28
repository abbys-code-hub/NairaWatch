import requests

response = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()
print(response)