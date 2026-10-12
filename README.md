# TradeSyncBot-Dual

A high-performance copy trading bot for MetaTrader 5 using **dual Python clients**.

## ??? Architecture

Unlike v1 (which switched between two terminals), this version runs **two independent Python scripts**:

- **`master_bot.py`**: Monitors the Master account and writes signals to `signal.json`.
- **`slave_bot.py`**: Reads `signal.json` and executes trades on the Slave account.

## ? Benefits

- ? **Faster:** No login/logout delays.
- ??? **More Stable:** Each bot is independent.
- ?? **Scalable:** Easily extendable to multiple slave accounts.
- ?? **Cleaner:** Separation of concerns.

## ?? How to Run

1. Open both MT5 terminals (Master on C, Slave on E) and ensure Algo Trading is green.
2. In one CMD window: `python master_bot.py`
3. In another CMD window: `python slave_bot.py`
4. Open a trade on Master ? it will automatically be copied to Slave.

## ?? Warning

- Never upload `accounts.json` to GitHub.
- Test on demo accounts first.