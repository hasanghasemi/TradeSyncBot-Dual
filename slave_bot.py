import MetaTrader5 as mt5
import time
import os
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SLAVE] [%(levelname)s] %(message)s")

# --- Configuration ---
FILE_PATH = "accounts.json"
SIGNAL_FILE = "signal.json"
SLAVE_PATH = r"E:\Program Files\LiteFinance MT5 Terminal\terminal64.exe"
# ---------------------

if not os.path.exists(FILE_PATH):
    logging.error(f"{FILE_PATH} not found!")
    exit()

with open(FILE_PATH, 'r') as f:
    data = json.load(f)

SLAVE_ACCOUNT = data["account_2"]

def login_slave():
    """Connect and login to Slave terminal."""
    mt5.shutdown()
    time.sleep(1)
    
    if not mt5.initialize(path=SLAVE_PATH):
        logging.error(f"Failed to initialize MT5: {mt5.last_error()}")
        return False
    
    account_info = mt5.account_info()
    if account_info and account_info.login == int(SLAVE_ACCOUNT['login']):
        logging.info(f"Already logged into SLAVE account {SLAVE_ACCOUNT['login']}.")
        return True
    
    authorized = mt5.login(
        login=int(SLAVE_ACCOUNT['login']),
        password=SLAVE_ACCOUNT['password'],
        server=SLAVE_ACCOUNT['server']
    )
    
    if not authorized:
        logging.error(f"Failed to login: {mt5.last_error()}")
        return False
    
    logging.info(f"Logged into SLAVE account {SLAVE_ACCOUNT['login']}.")
    time.sleep(2)
    return True

def find_matching_symbol(master_symbol):
    """Find the equivalent symbol on slave account (with suffix handling)."""
    if mt5.symbol_select(master_symbol, True):
        return master_symbol
    suffixes = ["_i", ".r", "micro", "pro", ".a", ""]
    for suffix in suffixes:
        test_symbol = master_symbol + suffix
        if mt5.symbol_select(test_symbol, True):
            logging.info(f"Matching symbol found: {test_symbol}")
            return test_symbol
    return None

def send_order_with_retry(request):
    """Try different filling modes to overcome the 10030 error."""
    for filling in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
        request['type_filling'] = filling
        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return result
        if result.retcode != 10030:
            return result
        logging.warning(f"Filling mode {filling} unsupported. Trying next...")
    return result

def handle_open(signal):
    """Copy a new trade to the slave account."""
    master_symbol = signal['symbol']
    symbol = find_matching_symbol(master_symbol)
    if not symbol:
        logging.error(f"Symbol {master_symbol} not found on SLAVE.")
        return False
    
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        logging.error(f"Failed to get symbol info for {symbol}.")
        return False
    
    # Round volume to valid step
    volume = round(signal['volume'] / symbol_info.volume_step) * symbol_info.volume_step
    if volume < symbol_info.volume_min:
        volume = symbol_info.volume_min
    
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        logging.error(f"Failed to get tick for {symbol}.")
        return False
    
    order_type = mt5.ORDER_TYPE_BUY if signal['order_type'] == "BUY" else mt5.ORDER_TYPE_SELL
    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    
    request = {
        'action': mt5.TRADE_ACTION_DEAL,
        'symbol': symbol,
        'volume': volume,
        'type': order_type,
        'price': price,
        'sl': signal['sl'],
        'tp': signal['tp'],
        'deviation': 20,
        'magic': signal['master_ticket'],
        'comment': 'Copied trade',
        'type_time': mt5.ORDER_TIME_GTC,
    }
    
    logging.info(f"Opening trade on SLAVE: {request}")
    result = send_order_with_retry(request)
    
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logging.info(f"Trade opened on SLAVE. Ticket: {result.order} (Master: {signal['master_ticket']})")
        return True
    else:
        logging.error(f"Failed to open trade: {result.retcode} - {result.comment}")
        return False

def handle_close(signal):
    """Close the corresponding trade on the slave account."""
    master_ticket = signal['master_ticket']
    
    positions = mt5.positions_get()
    if not positions:
        logging.warning(f"No positions on SLAVE to close (Master ticket: {master_ticket}).")
        return True
    
    position_to_close = None
    for pos in positions:
        if pos.magic == master_ticket:
            position_to_close = pos
            break
    
    if not position_to_close:
        logging.warning(f"No position with Magic {master_ticket} found on SLAVE.")
        return True
    
    symbol = position_to_close.symbol
    close_type = mt5.ORDER_TYPE_SELL if position_to_close.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(symbol)
    price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
    
    request = {
        'action': mt5.TRADE_ACTION_DEAL,
        'position': position_to_close.ticket,
        'symbol': symbol,
        'volume': position_to_close.volume,
        'type': close_type,
        'price': price,
        'deviation': 20,
        'magic': master_ticket,
        'comment': 'Close copied trade',
        'type_time': mt5.ORDER_TIME_GTC,
    }
    
    logging.info(f"Closing trade on SLAVE: {request}")
    result = send_order_with_retry(request)
    
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logging.info(f"Trade closed on SLAVE (Master: {master_ticket})")
        return True
    else:
        logging.error(f"Failed to close: {result.retcode}")
        return False

def handle_modify(signal):
    """Update SL/TP of corresponding trade on slave account."""
    master_ticket = signal['master_ticket']
    
    positions = mt5.positions_get()
    if not positions:
        return False
    
    position = None
    for pos in positions:
        if pos.magic == master_ticket:
            position = pos
            break
    
    if not position:
        logging.warning(f"No position with Magic {master_ticket} to modify.")
        return False
    
    if position.sl == signal['sl'] and position.tp == signal['tp']:
        return True
    
    request = {
        'action': mt5.TRADE_ACTION_SLTP,
        'symbol': position.symbol,
        'position': position.ticket,
        'sl': signal['sl'],
        'tp': signal['tp'],
    }
    
    logging.info(f"Modifying SL/TP on SLAVE: {request}")
    result = mt5.order_send(request)
    
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logging.info(f"SL/TP updated (Master: {master_ticket})")
        return True
    else:
        logging.error(f"Failed to modify: {result.retcode}")
        return False

def process_signals():
    """Read signal.json and process unprocessed signals."""
    if not os.path.exists(SIGNAL_FILE):
        return
    
    try:
        with open(SIGNAL_FILE, 'r') as f:
            signals = json.load(f)
    except:
        return
    
    updated = False
    for signal in signals:
        if signal.get('processed'):
            continue
        
        signal_type = signal['type']
        success = False
        
        if signal_type == "OPEN":
            success = handle_open(signal)
        elif signal_type == "CLOSE":
            success = handle_close(signal)
        elif signal_type == "MODIFY":
            success = handle_modify(signal)
        
        if success:
            signal['processed'] = True
            updated = True
    
    if updated:
        with open(SIGNAL_FILE, 'w') as f:
            json.dump(signals, f, indent=4)

def cleanup_old_signals():
    """Remove processed signals to keep the file small."""
    if not os.path.exists(SIGNAL_FILE):
        return
    try:
        with open(SIGNAL_FILE, 'r') as f:
            signals = json.load(f)
        
        unprocessed = [s for s in signals if not s.get('processed')]
        
        if len(unprocessed) != len(signals):
            with open(SIGNAL_FILE, 'w') as f:
                json.dump(unprocessed, f, indent=4)
            logging.info(f"Cleaned up {len(signals) - len(unprocessed)} processed signals.")
    except:
        pass

if __name__ == "__main__":
    try:
        print("=== SLAVE BOT STARTED ===")
        print(f"Slave Terminal: {SLAVE_PATH}")
        print(f"Signal File: {SIGNAL_FILE}")
        
        if not login_slave():
            print("Could not login to SLAVE.")
            exit()
        
        input("Ensure Algo Trading is GREEN in Slave terminal. Press Enter to start...")
        
        logging.info("Slave bot is running. Waiting for signals...")
        counter = 0
        while True:
            process_signals()
            counter += 1
            if counter >= 60:
                cleanup_old_signals()
                counter = 0
            time.sleep(0.5)
    
    except KeyboardInterrupt:
        logging.info("Slave bot stopped by user.")
    finally:
        mt5.shutdown()