import os
import json
import time
import requests
from datetime import datetime

API_KEY = os.getenv("NANSEN_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api.nansen.ai/api/v1"

CHAINS = ["ethereum", "solana", "bnb", "base"]

ALERT_THRESHOLD = 60

MIN_MARKET_CAP = 250_000
MIN_LIQUIDITY = 50_000

STATE_FILE = "signals.json"
LOG_FILE = "scanner.log"


def log(msg):
    line = f"[{datetime.utcnow().isoformat()}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def post(endpoint, payload):
    if not API_KEY:
        log("ERROR: NANSEN_API_KEY missing")
        return None

    headers = {
        "apikey": API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        r = requests.post(
            BASE_URL + endpoint,
            headers=headers,
            json=payload,
            timeout=30
        )

        if r.status_code != 200:
            log(f"NANSEN {endpoint} -> HTTP {r.status_code}")
            try:
                log(str(r.json())[:500])
            except Exception:
                log(r.text[:500])
            return None

        return r.json()

    except Exception as e:
        log(f"NANSEN ERROR {endpoint}: {e}")
        return None


# ============================================================
# NANSEN TOKEN SCREENER
# ============================================================

def discover_tokens():
    payload = {
        "chains": CHAINS,
        "timeframe": "24h",
        "pagination": {
            "page": 1,
            "per_page": 50
        },
        "filters": {
            "only_smart_money": True,
            "market_cap_usd": {
                "min": MIN_MARKET_CAP
            },
            "liquidity": {
                "min": MIN_LIQUIDITY
            },
            "token_age_days": {
                "min": 1,
                "max": 365
            }
        },
        "order_by": [
            {
                "field": "volume",
                "direction": "DESC"
            }
        ]
    }

    result = post("/token-screener", payload)

    if not result:
        return []

    data = result.get("data", [])

    tokens = []

    for x in data:
        tokens.append({
            "chain": x.get("chain"),
            "token_address": x.get("token_address"),
            "token_symbol": x.get("token_symbol") or "UNKNOWN",
            "market_cap_usd": float(x.get("market_cap_usd") or 0),
            "liquidity": float(x.get("liquidity") or 0),
            "price_change_24h": float(x.get("price_change_24h") or 0),
            "volume_24h_usd": float(x.get("volume") or 0),
            "token_age_days": float(x.get("token_age_days") or 0),
        })

    log(f"DISCOVERY: {len(tokens)} Nansen smart-money candidates")

    return tokens


# ============================================================
# NANSEN TGM HOLDERS
# ============================================================

def get_holders(chain, address):

    payload = {
        "chain": chain,
        "token_address": address,
        "aggregate_by_entity": False,
        "label_type": "smart_money",
        "pagination": {
            "page": 1,
            "per_page": 20
        },
        "filters": {
            "include_smart_money_labels": [
                "30D Smart Trader",
                "Fund"
            ]
        },
        "premium_labels": False,
        "order_by": [
            {
                "field": "value_usd",
                "direction": "DESC"
            }
        ]
    }

    result = post("/tgm/holders", payload)

    if not result:
        return []

    return result.get("data", [])


# ============================================================
# HOLDER ANALYSIS
# ============================================================

def analyze_holders(holders):

    accumulation_7d = 0
    accumulation_30d = 0

    total_value = 0
    estimated_accumulation_usd = 0

    positive_7d_usd = 0
    positive_30d_usd = 0

    negative_7d_usd = 0
    negative_30d_usd = 0

    labels = {}
    addresses = set()

    for h in holders:

        address = h.get("address")

        if address:
            addresses.add(address)

        value = float(h.get("value_usd") or 0)

        change_7d = float(h.get("balance_change_7d") or 0)
        change_30d = float(h.get("balance_change_30d") or 0)

        total_value += value

        if change_7d > 0:
            accumulation_7d += 1
            positive_7d_usd += change_7d

        elif change_7d < 0:
            negative_7d_usd += abs(change_7d)

        if change_30d > 0:
            accumulation_30d += 1
            positive_30d_usd += change_30d

        elif change_30d < 0:
            negative_30d_usd += abs(change_30d)

        # Estimate USD accumulation using current value /
        # current token amount as an approximate price.
        amount = float(
            h.get("balance") or
            h.get("token_amount") or
            0
        )

        if amount > 0 and change_30d > 0:
            estimated_price = value / amount
            estimated_accumulation_usd += (
                estimated_price * change_30d
            )

        label = (
            h.get("address_label")
            or h.get("entity_name")
            or "Unknown"
        )

        labels[label] = labels.get(label, 0) + 1

    return {
        "holders": len(holders),
        "addresses": addresses,

        "accumulation_7d": accumulation_7d,
        "accumulation_30d": accumulation_30d,

        "total_value": total_value,
        "estimated_accumulation_usd":
            estimated_accumulation_usd,

        "positive_7d_usd": positive_7d_usd,
        "positive_30d_usd": positive_30d_usd,

        "negative_7d_usd": negative_7d_usd,
        "negative_30d_usd": negative_30d_usd,

        "labels": labels,
    }


# ============================================================
# SCORING
# ============================================================

def calculate_score(token, stats):

    score = 0

    holders = stats["holders"]
    acc7 = stats["accumulation_7d"]
    acc30 = stats["accumulation_30d"]

    total_value = stats["total_value"]
    estimated_acc = stats["estimated_accumulation_usd"]

    liquidity = token["liquidity"]
    market_cap = token["market_cap_usd"]

    price_change = token["price_change_24h"]

    # --------------------------------------------------------
    # Smart-money participation
    # --------------------------------------------------------

    if acc7 >= 10:
        score += 30
    elif acc7 >= 6:
        score += 24
    elif acc7 >= 3:
        score += 17
    elif acc7 >= 1:
        score += 8

    # --------------------------------------------------------
    # 30D confirmation
    # --------------------------------------------------------

    if acc30 >= 15:
        score += 20
    elif acc30 >= 10:
        score += 16
    elif acc30 >= 5:
        score += 11
    elif acc30 >= 2:
        score += 6
    elif acc30 >= 1:
        score += 3

    # --------------------------------------------------------
    # Smart-money capital
    # --------------------------------------------------------

    if estimated_acc >= 1_000_000:
        score += 18
    elif estimated_acc >= 250_000:
        score += 14
    elif estimated_acc >= 50_000:
        score += 9
    elif estimated_acc > 0:
        score += 3

    # --------------------------------------------------------
    # Existing smart-money holdings
    # --------------------------------------------------------

    if total_value >= 10_000_000:
        score += 10
    elif total_value >= 5_000_000:
        score += 8
    elif total_value >= 1_000_000:
        score += 5
    elif total_value >= 250_000:
        score += 3

    # --------------------------------------------------------
    # Liquidity
    # --------------------------------------------------------

    if liquidity >= 2_000_000:
        score += 10
    elif liquidity >= 500_000:
        score += 7
    elif liquidity >= 100_000:
        score += 4

    # --------------------------------------------------------
    # Market cap
    # --------------------------------------------------------

    if 5_000_000 <= market_cap <= 500_000_000:
        score += 5
    elif market_cap > 0:
        score += 2

    # --------------------------------------------------------
    # Excessive recent pump penalty
    # --------------------------------------------------------

    if price_change >= 100:
        score -= 15
    elif price_change >= 50:
        score -= 10
    elif price_change >= 25:
        score -= 5

    # --------------------------------------------------------
    # Heavy 30D distribution penalty
    # --------------------------------------------------------

    positive = stats["positive_30d_usd"]
    negative = stats["negative_30d_usd"]

    if positive > 0 and negative > positive * 1.5:
        score -= 10

    return max(0, min(100, score))


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram credentials missing")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }

    try:
        r = requests.post(
            url,
            json=payload,
            timeout=20
        )

        if r.status_code == 200:
            return True

        log(f"Telegram HTTP {r.status_code}: {r.text[:300]}")

    except Exception as e:
        log(f"Telegram error: {e}")

    return False


# ============================================================
# STATE / DUPLICATES
# ============================================================

def load_state():

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):

    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                state,
                f,
                indent=2,
                ensure_ascii=False
            )
    except Exception as e:
        log(f"State save error: {e}")


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def build_message(token, stats, score):

    symbol = token["token_symbol"]
    chain = token["chain"]

    mc = token["market_cap_usd"]
    liq = token["liquidity"]

    return f"""🧠 NANSEN SMART MONEY SIGNAL

🪙 {symbol}
⛓️ {chain}

🎯 Score: {score}/100

👥 TGM Smart Money
• Holders: {stats['holders']}
• Accumulating 7D: {stats['accumulation_7d']}
• Accumulating 30D: {stats['accumulation_30d']}

💰 Smart Money Holdings
• Current value: ${stats['total_value']:,.0f}
• Est. 30D accumulation: ${stats['estimated_accumulation_usd']:,.0f}

📊 Market
• Market Cap: ${mc:,.0f}
• Liquidity: ${liq:,.0f}
• 24H price: {token['price_change_24h']:.1f}%

🔎 Source: Nansen Token Screener + TGM Holders

⚠️ Research signal only.
Not a price prediction or trading recommendation.
"""


# ============================================================
# MAIN SCANNER
# ============================================================

def main():

    log("=" * 70)
    log("NANSEN SMART MONEY SCANNER START")
    log("=" * 70)

    tokens = discover_tokens()

    if not tokens:
        log("No discovery results.")
        return

    state = load_state()

    candidates = []

    # Limit deep TGM calls to top 20 candidates.
    # This keeps API usage controlled.
    tokens = tokens[:20]

    log(f"Deep TGM validation: {len(tokens)} tokens")

    for i, token in enumerate(tokens, 1):

        symbol = token["token_symbol"]
        chain = token["chain"]
        address = token["token_address"]

        print()
        print(
            f"[{i}/{len(tokens)}] "
            f"Checking {symbol} ({chain})..."
        )

        holders = get_holders(chain, address)

        if not holders:
            print("   TGM holders: 0")
            continue

        stats = analyze_holders(holders)

        if stats["accumulation_30d"] < 2:
            print(
                f"   Skip: only "
                f"{stats['accumulation_30d']} "
                f"30D accumulating wallets"
            )
            continue

        score = calculate_score(token, stats)

        print(f"   TGM holders: {stats['holders']}")
        print(
            f"   Accumulating 7D: "
            f"{stats['accumulation_7d']}"
        )
        print(
            f"   Accumulating 30D: "
            f"{stats['accumulation_30d']}"
        )
        print(
            f"   Est. accumulation: "
            f"${stats['estimated_accumulation_usd']:,.0f}"
        )
        print(f"   Score: {score}/100")

        candidates.append({
            "token": token,
            "stats": stats,
            "score": score
        })

        time.sleep(0.3)

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print()
    print("=" * 70)
    print("TOP NANSEN SMART MONEY SIGNALS")
    print("=" * 70)

    for c in candidates[:10]:

        token = c["token"]
        stats = c["stats"]

        print(
            f"{token['token_symbol']:15} "
            f"{token['chain']:8} "
            f"Score={c['score']:3} "
            f"7D={stats['accumulation_7d']:2} "
            f"30D={stats['accumulation_30d']:2} "
            f"Est=${stats['estimated_accumulation_usd']:,.0f}"
        )

    print()
    print("=" * 70)
    print("TELEGRAM ALERTS")
    print("=" * 70)

    for c in candidates:

        if c["score"] < ALERT_THRESHOLD:
            continue

        token = c["token"]
        stats = c["stats"]

        key = (
            f"{token['chain']}:"
            f"{token['token_address']}"
        )

        previous = state.get(key)

        # Avoid repeating the same alert.
        if previous and previous >= c["score"]:
            print(
                f"🔕 DUPLICATE: "
                f"{token['token_symbol']} "
                f"{c['score']}/100"
            )
            continue

        message = build_message(
            token,
            stats,
            c["score"]
        )

        if send_telegram(message):

            print(
                f"🚨 ALERT: "
                f"{token['token_symbol']} "
                f"{c['score']}/100"
            )

            state[key] = c["score"]
            save_state(state)

    log("SCAN COMPLETED")


if __name__ == "__main__":
    main()
