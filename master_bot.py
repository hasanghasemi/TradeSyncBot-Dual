import MetaTrader5 as mt5
import time
import os
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [MASTER] [%(levelname)s] %(message)s")

# --- Configuration ---
FILE_PATH = "accounts.json"
SIGNAL_FILE = "signal.json"
MASTER_PATH = r"C:\Program Files\LiteFinance MT5 Terminal\terminal64.exe"
# ---------------------

if not os.path.exists(FILE_PATH):
    logging.error(f"{FILE_PATH} not found!")
    exit()

with open(FILE_PATH, 'r') as f:
    data = json.load(f)

MASTER_ACCOUNT = data["account_1"]

def login_master():
    """Connect and login to Master terminal."""
    mt5.shutdown()
    time.sleep(1)
    
    if not mt5.initialize(path=MASTER_PATH):
        logging.error(f"Failed to initialize MT5: {mt5.last_error()}")
        return False
    
    account_info = mt5.account_info()
    if account_info and account_info.login == int(MASTER_ACCOUNT['login']):
        logging.info(f"Already logged into MASTER account {MASTER_ACCOUNT['login']}.")
        return True
    
    authorized = mt5.login(
        login=int(MASTER_ACCOUNT['login']),
        password=MASTER_ACCOUNT['password'],
        server=MASTER_ACCOUNT['server']
    )
    
    if not authorized:
        logging.error(f"Failed to login: {mt5.last_error()}")
        return False
    
    logging.info(f"Logged into MASTER account {MASTER_ACCOUNT['login']}.")
    time.sleep(2)
    return True

def write_signal(signal_type, trade):
    """Write a signal to signal.json for the slave bot to read."""
    signal = {
        "type": signal_type,
        "master_ticket": trade.ticket,
        "symbol": trade.symbol,
        "volume": trade.volume,
        "order_type": "BUY" if trade.type == mt5.ORDER_TYPE_BUY else "SELL",
        "sl": trade.sl,
        "tp": trade.tp,
        "price_open": trade.price_open,
        "timestamp": datetime.now().isoformat(),
        "processed": False
    }
    
    # Read existing signals if any
    signals = []
    if os.path.exists(SIGNAL_FILE):
        try:
            with open(SIGNAL_FILE, 'r') as f:
                signals = json.load(f)
        except:
            signals = []
    
    signals.append(signal)
    
    with open(SIGNAL_FILE, 'w') as f:
        json.dump(signals, f, indent=4)
    
    logging.info(f"Signal written: {signal_type} - Ticket {trade.ticket} ({trade.symbol})")

def monitor():
    if not login_master():
        return
    
    # Initial snapshot
    monitored_trades = {trade.ticket: trade for trade in mt5.positions_get() or []}
    logging.info(f"Monitoring started. Current open trades: {len(monitored_trades)}")

    while True:
        try:
            current_trades = mt5.positions_get() or []
            current_dict = {trade.ticket: trade for trade in current_trades}

            # 1. Detect new trades
            new_tickets = set(current_dict.keys()) - set(monitored_trades.keys())
            for ticket in new_tickets:
                trade = current_dict[ticket]
                logging.info(f"NEW TRADE detected: {trade.symbol} Ticket {ticket}")
                write_signal("OPEN", trade)

            # 2. Detect closed trades
            closed_tickets = set(monitored_trades.keys()) - set(current_dict.keys())
            for ticket in closed_tickets:
                prev_trade = monitored_trades[ticket]
                logging.info(f"CLOSED TRADE detected: {prev_trade.symbol} Ticket {ticket}")
                write_signal("CLOSE", prev_trade)

            # 3. Detect SL/TP modifications
            for ticket, trade in current_dict.items():
                if ticket in monitored_trades:
                    prev = monitored_trades[ticket]
                    if trade.sl != prev.sl or trade.tp != prev.tp:
                        logging.info(f"MODIFIED TRADE: {trade.symbol} Ticket {ticket} (SL/TP changed)")
                        write_signal("MODIFY", trade)

            monitored_trades = current_dict
            time.sleep(1)  # Check every second

        except KeyboardInterrupt:
            logging.info("Master bot stopped by user.")
            break
        except Exception as e:
            logging.error(f"Error in monitor loop: {e}")
            time.sleep(2)
    
    mt5.shutdown()

if __name__ == "__main__":
    try:
        print("=== MASTER BOT STARTED ===")
        print(f"Master Terminal: {MASTER_PATH}")
        print(f"Signal File: {SIGNAL_FILE}")
        input("Ensure Algo Trading is GREEN in Master terminal. Press Enter to start...")
        monitor()
    except KeyboardInterrupt:
        logging.info("Stopped.")
    finally:
        mt5.shutdown()