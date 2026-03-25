# 👟 Shoe Sale Tracker

A lightweight GitHub Actions bot that monitors shoe store product pages for price drops and notifies you via Telegram — automatically, every day.

---

## How It Works

1. **Scheduled daily run** — A GitHub Actions workflow triggers once a day at your configured time
2. **Price check** — It visits each product URL listed in your config file and scrapes the current price
3. **Comparison** — Compares today's price against a stored baseline for each product (or basket of products)
4. **Telegram alert** — If any price has dropped, you get a Telegram message with the details
5. **History commit** — Updated price data is committed back to the repo, keeping your history up to date

---

## Features

- 🕐 Configurable daily schedule via cron
- 🛍️ Track individual products or a basket of products
- 📉 Detects price drops against a stored baseline
- 📲 Instant Telegram notifications when sales are found
- 🗂️ Price history stored directly in the repo (no external database needed)
