import json
import os
import requests
from datetime import date

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
PRODUCTS_FILE = "products.json"
PRICES_FILE = "prices.json"
STORE_URL = "https://runninglab.my"


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()


# ---------------------------------------------------------------------------
# Shopify API helpers
# ---------------------------------------------------------------------------

def fetch_product(handle):
    """Fetch a single product by handle."""
    url = f"{STORE_URL}/products/{handle}.json"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()["product"]


def fetch_all_store_products():
    """
    Fetch every product in the store using Shopify's paginated products.json.
    Returns a flat list of product dicts.
    """
    all_products = []
    page = 1
    while True:
        url = f"{STORE_URL}/products.json?limit=250&page={page}"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        batch = response.json()["products"]
        if not batch:
            break
        all_products.extend(batch)
        if len(batch) < 250:
            break
        page += 1
    return all_products


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------

def get_min_price(variants):
    """Lowest current price across all variants (sizes)."""
    return min(float(v["price"]) for v in variants)


def get_compare_at_price(variants):
    """
    If the retailer has marked any variants on sale, return the highest
    compare_at_price (the 'was' price) across those variants. Otherwise None.
    """
    caps = [
        float(v["compare_at_price"])
        for v in variants
        if v["compare_at_price"] and float(v["compare_at_price"]) > float(v["price"])
    ]
    return max(caps) if caps else None


# ---------------------------------------------------------------------------
# Product resolution
# ---------------------------------------------------------------------------

def resolve_products(config):
    """
    Expand the config into a flat list of resolved products.
    Each resolved product: { handle, name, url, variants }

    - "handle"         → fetch that one product directly
    - "handle_pattern" → fetch full catalogue (once, cached) and filter by substring
    """
    resolved = []
    catalogue_cache = None  # fetched at most once per run

    for entry in config:

        if "handle" in entry:
            handle = entry["handle"]
            try:
                data = fetch_product(handle)
                resolved.append({
                    "handle": handle,
                    "name": data["title"],
                    "url": f"{STORE_URL}/products/{handle}",
                    "variants": data["variants"],
                })
            except Exception as e:
                print(f"[ERROR] Could not fetch handle '{handle}': {e}")

        elif "handle_pattern" in entry:
            pattern = entry["handle_pattern"]

            # Lazy-load the full catalogue once
            if catalogue_cache is None:
                print("[INFO] Fetching full store catalogue for pattern matching...")
                try:
                    catalogue_cache = fetch_all_store_products()
                    print(f"[INFO] {len(catalogue_cache)} products found in catalogue.")
                except Exception as e:
                    print(f"[ERROR] Could not fetch store catalogue: {e}")
                    catalogue_cache = []

            matches = [p for p in catalogue_cache if pattern in p["handle"]]
            if not matches:
                print(f"[WARN] Pattern '{pattern}' matched no products.")
            for p in matches:
                resolved.append({
                    "handle": p["handle"],
                    "name": p["title"],
                    "url": f"{STORE_URL}/products/{p['handle']}",
                    "variants": p["variants"],
                })

    return resolved


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open(PRODUCTS_FILE) as f:
        config = json.load(f)

    try:
        with open(PRICES_FILE) as f:
            prices = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        prices = {}

    today = str(date.today())

    # Resolve all products from config
    resolved = resolve_products(config)
    resolved_handles = {p["handle"] for p in resolved}

    # Auto-clean: drop prices.json entries no longer in the config
    orphans = [h for h in list(prices) if h not in resolved_handles]
    for h in orphans:
        print(f"[CLEAN] Removing orphaned entry: '{prices[h].get('name', h)}'")
        del prices[h]

    new_alerts = []   # handles that are newly alerting this run
    active_sales = [] # all products currently on sale (for the recap message)

    for product in resolved:
        handle   = product["handle"]
        name     = product["name"]
        url      = product["url"]
        variants = product["variants"]

        current_price     = get_min_price(variants)
        compare_at_price  = get_compare_at_price(variants)

        stored              = prices.get(handle, {})
        baseline_price      = stored.get("baseline_price")
        last_notified_price = stored.get("last_notified_price")

        # First time we've seen this product — set baseline to today's price
        if baseline_price is None:
            baseline_price = current_price
            print(f"[INIT]  Baseline set for '{name}': RM{baseline_price:.2f}")

        # Determine "was" price for display:
        #   prefer the retailer's compare_at_price, fall back to our baseline
        was_price = compare_at_price if compare_at_price else baseline_price

        # Is it currently on sale?
        is_on_sale = (compare_at_price is not None) or (current_price < baseline_price)

        if is_on_sale:
            saving = was_price - current_price
            pct    = (saving / was_price) * 100

            active_sales.append({
                "name":          name,
                "url":           url,
                "current_price": current_price,
                "was_price":     was_price,
                "pct":           pct,
            })

            # Trigger a new alert if never notified, or price dropped further
            is_new = last_notified_price is None or current_price < last_notified_price
            if is_new:
                new_alerts.append(handle)
                last_notified_price = current_price
                print(f"[ALERT] New alert: '{name}' @ RM{current_price:.2f} (was RM{was_price:.2f})")
            else:
                print(f"[SALE]  Ongoing, already notified: '{name}' @ RM{current_price:.2f}")

        else:
            # Sale over — reset so the next sale triggers a fresh alert
            if last_notified_price is not None:
                print(f"[RESET] Sale ended for '{name}', notification state reset.")
            last_notified_price = None
            print(f"[OK]    No sale: '{name}' @ RM{current_price:.2f}")

        prices[handle] = {
            "name":                name,
            "baseline_price":      baseline_price,
            "last_price":          current_price,
            "last_checked":        today,
            "last_notified_price": last_notified_price,
        }

    # Send ONE combined message if anything is newly alerting
    if new_alerts:
        lines = []
        for item in active_sales:
            lines.append(
                f"• <b>{item['name']}</b>\n"
                f"  RM{item['current_price']:.2f} "
                f"(was RM{item['was_price']:.2f}, -{item['pct']:.0f}%)\n"
                f"  {item['url']}"
            )
        message = "🏃 <b>Running Lab — Sale Alert</b>\n\n" + "\n\n".join(lines)
        send_telegram(message)
        print(f"[SENT]  Telegram alert sent. {len(active_sales)} item(s) on sale.")
    else:
        print("No new alerts. No message sent.")

    # Persist updated price history
    with open(PRICES_FILE, "w") as f:
        json.dump(prices, f, indent=2)

    print("Done.")


if __name__ == "__main__":
    main()
