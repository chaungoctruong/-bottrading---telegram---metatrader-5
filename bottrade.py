import MetaTrader5 as mt5
import pandas as pd
import requests
import asyncio
from telegram import Bot
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os


TELEGRAM_TOKEN = "7577745027:AAFK_Wj0BfAoS0CQocMvOGA5FE6IAyM3lFM"
CHAT_ID = 5573261363
message = "Hello Châu Ngọc Trường!"

url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={message}"
response = requests.get(url)
print(response.json())
bot = Bot(token=TELEGRAM_TOKEN)

mt5_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"


mt5.initialize(
    path=r"C:\Program Files\MetaTrader 5\terminal64.exe", 
    data_path=r"C:\MT5_Data_Normal"
)


load_dotenv("bottrade.env.txt")
account = os.getenv("MT5_ACCOUNT")
password = os.getenv("MT5_PASSWORD")
server = os.getenv("MT5_SERVER")
print(f"Account: {account}")
print("Password: [***]")  
print(f"Server: {server}")



if mt5.login(login=int(account), password=password, server=server):
    print(f"Successfully logged into account {account}")
else:
    print(f"Login failed: {mt5.last_error()}")

    

symbol = "EURUSD"
lot = 0.01


def is_trading_time():
    """Check trading hours (Always True for 24/24 operation)."""
    return True
    
async def send_telegram_message(message):
    """Send a message via Telegram."""
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message)
    except Exception as e:
        print(f"Unable to send message via Telegram: {e}")
        

async def log_message(message):
    """Log and send message via Telegram."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    full_message = f"{timestamp} - {message}"
    print(full_message)
    await send_telegram_message(full_message)
    
def wait_for_m5_close():
    now = datetime.now()
    next_close = (now + timedelta(minutes=5 - now.minute % 5)).replace(second=0, microsecond=0)
    wait_time = (next_close - now).total_seconds() + 1
    print(f"Waiting {wait_time} seconds until the M5 candle closes.")
    return wait_time



def get_latest_candles(symbol, timeframe, n=1):
    """Retrieve the latest n candles."""
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
    if rates is None or len(rates) < n:
        print("Not enough candle data available.")
        return None

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True) 
    return df 

def calculate_ema(data, period):
    if data is None or len(data) < period:
        print(f"Not enough data to calculate EMA {period}.")
        return None
    return data['close'].ewm(span=period, adjust=False).mean()

async def detect_trend():
    """Xác định xu hướng dựa trên EMA 50 và EMA 100 trên M1 với xác nhận độ mạnh."""
    try:
        candles_m1 = get_latest_candles(symbol, mt5.TIMEFRAME_M1, 150)
        if candles_m1 is None or len(candles_m1) < 100:
            await log_message("❌ Không có đủ dữ liệu nến M1.")
            return None


        candles_m1['EMA_50'] = calculate_ema(candles_m1, 50)
        candles_m1['EMA_100'] = calculate_ema(candles_m1, 100)

        ema_50_now = candles_m1['EMA_50'].iloc[-1]
        ema_100_now = candles_m1['EMA_100'].iloc[-1]
        ema_50_prev = candles_m1['EMA_50'].iloc[-2]
        ema_100_prev = candles_m1['EMA_100'].iloc[-2]

        if ema_50_now > ema_100_now:
            trend = 'uptrend'
        else:
            trend = 'downtrend'

        ema_gap = abs(ema_50_now - ema_100_now) 
        ema_slope = ema_50_now - ema_50_prev  

        if ema_gap > 0.5 and abs(ema_slope) > 0.2:
            trend_strength = 'strong'
        elif ema_gap > 0.3 and abs(ema_slope) > 0.1:
            trend_strength = 'moderate'
        else:
            trend_strength = 'weak'


        await log_message(f"✅ Xu hướng M1: {trend} ({trend_strength}) | EMA Gap: {ema_gap:.2f} | EMA Slope: {ema_slope:.2f}")

        return trend, trend_strength

    except Exception as e:
        await log_message(f"❌ Lỗi trong detect_trend(): {e}")
        return None

def detect_smc(verbose=True, ob_body_threshold=0.5):
    """
    Detect Break of Structure (BOS) and Order Blocks (OB) using the last 10 candles on M5.

    Parameters:
        verbose (bool): Hiển thị log chi tiết nếu True.
        ob_body_threshold (float): Tỷ lệ thân nến so với phạm vi nến để xác định Order Block.

    Returns:
        dict: Kết quả phân tích BOS và OB kèm thời gian.
    """
    try:
        candles = get_latest_candles(symbol, mt5.TIMEFRAME_M5, 10)
        if candles is None or len(candles) < 10:
            if verbose:
                print("❌ Không đủ dữ liệu nến để phân tích.")
            return None

        highs = candles['high']
        lows = candles['low']
        closes = candles['close']
        opens = candles['open']

        bos = None
        if highs.iloc[-2] > highs.iloc[:-2].max():  
            bos = 'buy'
            if verbose:
                print(f"📈 Bullish BOS: {highs.iloc[-2]} > max({highs.iloc[:-2].max()})")
        elif lows.iloc[-2] < lows.iloc[:-2].min():  
            bos = 'sell'
            if verbose:
                print(f"📉 Bearish BOS: {lows.iloc[-2]} < min({lows.iloc[:-2].min()})")
        else:
            if verbose:
                print("⚠️ Không có BOS.")


        ob = None
        body_size = abs(closes.iloc[-2] - opens.iloc[-2])
        total_range = highs.iloc[-2] - lows.iloc[-2]
        body_ratio = body_size / total_range if total_range > 0 else 0

        if closes.iloc[-2] < opens.iloc[-2] and body_ratio >= ob_body_threshold:
            ob = 'sell'
            if verbose:
                print(f"🔴 Sell Order Block: body ratio {body_ratio:.2f} >= {ob_body_threshold}")
        elif closes.iloc[-2] > opens.iloc[-2] and body_ratio >= ob_body_threshold:
            ob = 'buy'
            if verbose:
                print(f"🟢 Buy Order Block: body ratio {body_ratio:.2f} >= {ob_body_threshold}")
        else:
            if verbose:
                print("⚠️ Không có Order Block mạnh.")

        confirmation = {
            "BOS": bos,
            "Order Block": ob,
            "Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        if verbose:
            print(f"✅ Kết quả phân tích: {confirmation}")
        return confirmation

    except Exception as e:
        print(f"❌ Lỗi trong phân tích SMC: {e}")
        return None
    
    
def get_current_price():
    """Lấy giá hiện tại của symbol đang giao dịch."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print("❌ Không lấy được giá hiện tại.")
        return None
    return tick.ask  

    
    
async def wait_for_entry_and_dca(entry_price, order_type, dca_distance, max_dca_orders=3):
    """
    Đợi giá vượt qua Entry rồi thực hiện DCA theo chiến lược.

    Parameters:
        entry_price (float): Giá vào lệnh ban đầu.
        order_type (str): Loại lệnh ('buy' hoặc 'sell').
        dca_distance (float): Khoảng cách DCA (tính theo pip hoặc giá).
        max_dca_orders (int): Số lệnh DCA tối đa.

    Returns:
        None (Chỉ thực hiện DCA khi đủ điều kiện).
    """
    try:
        dca_count = 0  
        while dca_count < max_dca_orders:
            current_price = get_current_price()  

         
            if order_type == 'buy' and current_price > entry_price:
                dca_price = current_price - dca_distance
                place_trade('buy', dca_price)  
                entry_price = dca_price 
                dca_count += 1
                print(f"✅ DCA Buy tại {dca_price}, Tổng lệnh DCA: {dca_count}")

            elif order_type == 'sell' and current_price < entry_price:
                dca_price = current_price + dca_distance
                place_trade('sell', dca_price)
                entry_price = dca_price
                dca_count += 1
                print(f"✅ DCA Sell tại {dca_price}, Tổng lệnh DCA: {dca_count}")

            await asyncio.sleep(1)  

        print("⚠️ Đã đạt giới hạn DCA, không vào thêm lệnh.")
    
    except Exception as e:
        print(f"❌ Lỗi trong wait_for_entry_and_dca(): {e}")




def get_total_profit():
    if not mt5.initialize():
        print("Unable to connect to MetaTrader 5:", mt5.last_error())
        return
    to_date = datetime.now()
    from_date = to_date - timedelta(days=7)
    history_orders = mt5.history_deals_get(from_date, to_date)
    if history_orders is None:
        print("No transactions found in history or an error occurred:", mt5.last_error())
        mt5.shutdown()
        return
    total_profit = sum(deal.profit for deal in history_orders)
    print(f"Total profit: {total_profit:.2f} USD")
    return total_profit


    
def get_equity_summary():
    """
    Retrieve an equity summary from MetaTrader 5.
    Returns: A dictionary containing information such as Equity, Balance, Floating Profit/Loss, and more.
    """
    if not mt5.initialize():
        print(f"Error initializing MT5: {mt5.last_error()}")
        return None

    account_info = mt5.account_info()
    if account_info is None:
        print("Unable to retrieve account information.")
        return None
    
    equity_summary = {
        "Balance": account_info.balance,
        "Equity": account_info.equity,
        "Floating Profit/Loss": account_info.profit,
        "Margin": account_info.margin,
        "Free Margin": account_info.margin_free,
        "Margin Level (%)": account_info.margin_level,
        "Currency": account_info.currency,
        "Last Updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    print("\n===== Equity Summary =====")
    for key, value in equity_summary.items():
        print(f"{key}: {value}")
    
    return equity_summary






async def place_trade(order_type, lot=0.01, price=None, comment="SMC Trade"):
    """Đặt lệnh Buy hoặc Sell, dùng chung cho cả lệnh chính và DCA."""
    point = mt5.symbol_info(symbol).point
    tick = mt5.symbol_info_tick(symbol)

    if price is None:
        price = tick.ask if order_type == 'buy' else tick.bid

    sl = price - 100 * point if order_type == 'buy' else price + 100 * point
    tp = price + 200 * point if order_type == 'buy' else price - 200 * point

    if abs(price - sl) < 50 * point or abs(price - tp) < 50 * point:
        error_msg = "❌ Lỗi: Khoảng cách SL/TP không hợp lệ."
        print(error_msg)
        await send_telegram_message(error_msg)
        return None

    order = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_BUY if order_type == 'buy' else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 1000,
        "magic": 1,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }

    print(f"📌 Đặt lệnh {order_type.upper()} tại {price}, SL: {sl}, TP: {tp}, Loại: {comment}")

    result = mt5.order_send(order)

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        message = f"📌 **LỆNH MỚI** ({order_type.upper()})\n" \
                  f"💰 Giá vào: {price}\n" \
                  f"📈 SL: {sl} | TP: {tp}\n" \
                  f"🔹 Khối lượng: {lot} lot\n" \
                  f"📌 Loại: {comment}"
        await send_telegram_message(message)
    else:
        error_msg = f"⚠ **LỆNH THẤT BẠI**: {result.comment} (Mã lỗi: {result.retcode})"
        print(error_msg)
        await send_telegram_message(error_msg)

    return result


async def run_bot():
    """Chạy bot để phát hiện tín hiệu SMC, thực hiện giao dịch và DCA nếu có tín hiệu."""
    try:
        if not mt5.symbol_select(symbol, True):
            await log_message(f"Unable to select symbol {symbol}.")
            mt5.shutdown()
            return None

        while is_trading_time():
            await asyncio.sleep(wait_for_m5_close())

            trend, trend_strength = await detect_trend()
            smc_signals = detect_smc()

            if smc_signals is None:
                await log_message("No SMC signal detected.")
                continue

            try:
                current_price = mt5.symbol_info_tick(symbol).ask
                dca_distance = 0.0020  
                max_dca_orders = 10 

    
                if smc_signals['BOS'] == 'buy' and smc_signals['Order Block'] == 'buy' and trend == 'uptrend':
                    await log_message("Executing BUY order...")
                    result = await place_trade('buy', lot)
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        entry_price = result.price
                        await wait_for_entry_and_dca(entry_price, 'buy', dca_distance, max_dca_orders)

                if smc_signals['BOS'] == 'sell' and smc_signals['Order Block'] == 'sell' and trend == 'downtrend':
                    await log_message("Executing SELL order...")
                    result = await place_trade('sell', lot)
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        entry_price = result.price
                        await wait_for_entry_and_dca(entry_price, 'sell', dca_distance, max_dca_orders)

            except Exception as e:
                await log_message(f"Error executing trade: {e}")

            message = "\n===== XAUUSD Report =====\n"
            message += f"BOS: {smc_signals['BOS']}\n"
            message += f"Order Block: {smc_signals['Order Block']}\n"
            message += f"EMA Trend: {trend} ({trend_strength})\n"
            message += f"Current Price: {current_price}\n"
            message += f"Trade Volume: {lot}\n"

            total_profit = get_total_profit()
            if total_profit is not None:
                message += f"\nTotal Profit (7 days): {total_profit:.2f} USD\n"

            equity_info = get_equity_summary()
            if equity_info:
                message += "\nEquity Summary:\n"
                for key, value in equity_info.items():
                    message += f"{key}: {value}\n"

            await log_message(message)

    except asyncio.CancelledError:
        print("Bot stopped gracefully.")
if __name__ == "__main__":
    asyncio.run(run_bot())
