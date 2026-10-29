import requests

# response = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()
# print(response)


URL = "https://open.er-api.com/v6/latest/USD"

def fetch_rate():
    try:
        response = requests.get(URL, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        print(f"Error: request failed ({e})")
        return None
 
    ngn_rate = data.get("rates", {}).get("NGN")
    time = data.get("time_last_update_utc")
    if ngn_rate is None:
        print("Error: NGN rate not found in response")
        return None
    return ngn_rate, time



# def format_message():

# print(fetch_rate())

if __name__ == "__main__":
    rate, time = fetch_rate()
    # rate = fetch_rate
    if rate is not None:
        print(f"USD/NGN: {rate:,.2f}\nRate updated at: (upadated {time})")
        # print(f"{rate}")
