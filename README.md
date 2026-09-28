# Nansen Smart Money Scanner

A multi-chain smart-money research scanner built with the Nansen API.

## What it does

The scanner discovers tokens using Nansen Token Screener, validates smart-money holders through Nansen TGM Holders, analyzes accumulation activity, calculates a research score, and sends high-score signals to Telegram.

## Pipeline

Nansen Token Screener
        ↓
Smart-Money Candidate Discovery
        ↓
Nansen TGM Holders
        ↓
7D / 30D Accumulation Analysis
        ↓
Liquidity + Market Cap Checks
        ↓
Signal Score
        ↓
Telegram Alert

## Supported Chains

- Ethereum
- Solana
- BNB Chain
- Base

## Nansen API Integration

The project uses:

- `/token-screener`
- `/tgm/holders`

Nansen data drives the core discovery and signal logic.

## Scoring

Signals are scored from 0 to 100 using:

- Smart-money accumulation over 7 days
- Smart-money accumulation over 30 days
- Estimated accumulation value
- Existing smart-money holdings
- Token liquidity
- Market capitalization
- Excessive recent price movement
- Distribution pressure

## Telegram Alerts

Signals above the configured threshold are sent to Telegram.

Example:

NANSEN SMART MONEY SIGNAL

Token: BP
Chain: Solana
Score: 91/100

TGM Smart Money
- Holders: 20
- Accumulating 7D: 15
- Accumulating 30D: 19

The system also includes duplicate-signal protection.

## Security

API credentials are loaded from environment variables and are never stored in the repository.

Required variables:

NANSEN_API_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID

## Run

```bash
export NANSEN_API_KEY="your_key"
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"

python scanner.py
