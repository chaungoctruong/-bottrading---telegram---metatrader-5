import MetaTrader5 as mt5
import pandas as pd
import requests
import asyncio
from telegram import Bot
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import ta 


TELEGRAM_TOKEN = "7577745027:AAFK_Wj0BfAoS0CQocMvOGA5FE6IAyM3lFM"
CHAT_ID = -1002465190892 
bot = Bot(token=TELEGRAM_TOKEN)


message = "Hello Châu Ngọc Trường!"
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={message}"
response = requests.get(url)
print(response.json())



mt5_path = r"C:\Program Files (x86)\MetaTrader 5 EXNESS\terminal64.exe"
if not mt5.initialize(path=mt5_path):
    print("❌ MT5 Initialization failed:", mt5.last_error())
    exit()
else:
    print("✅ MT5 Initialized successfully")

env_file = "mt5.env.txt"
if not os.path.exists(env_file):
    print(f"❌ Không tìm thấy file {env_file}. Kiểm tra lại!")
    exit()

load_dotenv(env_file)
account = os.getenv("MT5_ACCOUNT")
password = os.getenv("MT5_PASSWORD")
server = os.getenv("MT5_SERVER")

if not account or not password or not server:
    print("❌ Thiếu thông tin đăng nhập. Kiểm tra lại file mt5.env.txt!")
    exit()

print(f"Account: {account}")
print("Password: [***]") 
print(f"Server: {server}")

try:
    account = int(account)
except ValueError:
    print("❌ Lỗi: Số tài khoản không hợp lệ. Kiểm tra lại trong mt5.env.txt!")
    exit()

if mt5.login(login=account, password=password, server=server):
    print(f"✅ Successfully logged into account {account}")
else:
    print(f"❌ Login failed: {mt5.last_error()}")

symbol = "XAUUSDm"
lot = 0.02




def is_trading_time():
    """Kiểm tra giờ giao dịch (Luôn đúng cho hoạt động 24/24)."""
    return True





def get_candles(symbol, timeframe, count=1):
    try:
        candles = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if candles is None or len(candles) < count:
            print(f"⚠️ Không thể lấy đủ dữ liệu ({len(candles) if candles is not None else 0}/{count}) cho {symbol} với khung thời gian {timeframe}.")
            return [] if count > 1 else None
        else:
            df = pd.DataFrame(candles)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True)
            return df
    except Exception as e:
        print(f"❌ Lỗi khi lấy dữ liệu nến: {e}")
        return [] if count > 1 else None


def wait_for_m5_close():
    now = datetime.now()
    minutes_to_next_close = 5 - (now.minute % 5)
    next_close = now.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_next_close)
    wait_time = max(0, (next_close - now).total_seconds())
    return wait_time


def calculate_ema(data, period):
    if data is None or len(data) < period:
        print(f"Not enough data to calculate EMA {period}.")
        return None
    return data['close'].ewm(span=period, adjust=False).mean()


def is_pin_bar(candle):
    if isinstance(candle, pd.Series): 
        body = abs(candle['close'] - candle['open'])
        if body == 0:
            return None, None

        lower_wick = abs(candle['low'] - min(candle['open'], candle['close']))
        upper_wick = abs(candle['high'] - max(candle['open'], candle['close']))

        if upper_wick >= 1.5 * body and lower_wick <= 0.5 * body:
            return "sell", candle
        elif lower_wick >= 1.5 * body and upper_wick <= 0.5 * body:
            return "buy", candle
    else:
        print("Invalid candle format:", candle)
    return None, None


async def find_pin_bar_signal(candles):
    if isinstance(candles, list):
        candles = pd.DataFrame(candles)

    pin_bars = []

    for _, candle in candles.iterrows():
        pin_bar_type, pin_bar_candle = is_pin_bar(candle)
        if pin_bar_type:
            pin_bars.append((pin_bar_type, pin_bar_candle))

    if len(pin_bars) >= 2:
        last_two = pin_bars[-2:]
        type1, _ = last_two[0]
        type2, latest_candle = last_two[1]

        if type1 == type2:
            await log_message(
                f"🔹 2 nến PinBar phát hiện và cùng hướng: {type2.capitalize()} - "
                f"Open: {latest_candle['open']}, Close: {latest_candle['close']}, "
                f"Low: {latest_candle['low']}, High: {latest_candle['high']}"
            )
            return type2
        else:
            await log_message("⚠️ Phát hiện ≥2 Pin Bars nhưng không cùng hướng.")
    return None




def check_rsi_m5(data: pd.DataFrame, period: int = 14, lookback_candles: int = 15):
    """
    Tính RSI trên khung M5 và kiểm tra tín hiệu mua/bán dựa trên vùng hồi.
    - Mua khi RSI quá bán (<30) và hồi lên 35.
    - Bán khi RSI quá mua (>70) và giảm xuống 65.
    """
    try:
        if not isinstance(data, pd.DataFrame):
            return {"status": "❌ Dữ liệu không hợp lệ (không phải DataFrame)", "RSI": None}

        if data is None or data.empty:
            return {"status": "❌ Dữ liệu thiếu", "RSI": None}

        if "close" not in data:
            return {"status": "❌ Không tìm thấy cột 'close'", "RSI": None}

        df = data[["close"]].dropna().copy()

        min_candles_needed = period + lookback_candles
        if len(df) < min_candles_needed:
            return {"status": f"⚠️ Dữ liệu nến không đủ ({len(df)}/{min_candles_needed})", "RSI": None}

        df["RSI"] = ta.momentum.RSIIndicator(close=df["close"], window=period).rsi()


        df.dropna(subset=["RSI"], inplace=True)
        if df.empty or df["RSI"].isna().all():
            return {"status": "⚠️ RSI không hợp lệ hoặc dữ liệu bị lỗi", "RSI": None}

        latest_rsi = df["RSI"].iloc[-1]
        prev_rsi = df["RSI"].iloc[-2] if len(df) > 1 else None 
        rsi_history = df["RSI"].iloc[-lookback_candles:].tolist()

        buy_signal = prev_rsi is not None and prev_rsi < 30 and latest_rsi >= 35
        sell_signal = prev_rsi is not None and prev_rsi > 70 and latest_rsi <= 65
        


        if buy_signal:
            status = "🟢 QUÁ BÁN & HỒI LÊN 35 - Tín hiệu MUA"
            recommendation = "✅ RSI vượt 35, có thể vào lệnh MUA"
        elif sell_signal:
            status = "🔴 QUÁ MUA & GIẢM XUỐNG 65 - Tín hiệu BÁN"
            recommendation = "✅ RSI giảm dưới 65, có thể vào lệnh BÁN"
        elif latest_rsi > 70:
            status = "🔴 RSI QUÁ MUA - Cẩn trọng khi vào lệnh BÁN"
            recommendation = "⚠️ RSI vẫn cao, chờ xác nhận giảm dưới 65"
        elif latest_rsi > 65:
            status = "🟠 RSI VẪN CAO - Theo dõi xu hướng"
            recommendation = "🔍 RSI chưa đủ điều kiện bán, chờ tín hiệu rõ hơn"
        elif latest_rsi < 30:
            status = "🟢 RSI QUÁ BÁN - Cẩn trọng khi vào lệnh MUA"
            recommendation = "⚠️ RSI vẫn thấp, chờ xác nhận tăng trên 35"
        elif latest_rsi < 35:
            status = "🔵 RSI VẪN THẤP - Theo dõi xu hướng"
            recommendation = "🔍 RSI chưa đủ điều kiện mua, chờ tín hiệu rõ hơn"
        else:
            status = "⚪ RSI Trung Lập - Không giao dịch"
            recommendation = "🚫 Không vào lệnh"

        return {
            "status": status,
            "RSI": round(latest_rsi, 2),
            "RSI_History": [round(rsi, 2) for rsi in rsi_history],
            "recommendation": recommendation
            
            
        }

    except Exception as e:
        return {"status": "❌ Lỗi trong quá trình tính RSI", "RSI": None, "error_message": str(e)}
    
    
async def detect_smc():
    """Detect Break of Structure (BOS) and Order Blocks for the last 5 candles."""
    try:
        candles = get_candles(symbol, mt5.TIMEFRAME_M5, 5)
        if candles is None or len(candles) < 5:
            print("Not enough candle data for analysis.")
            return None

        highs = candles['high']
        lows = candles['low']
        closes = candles['close']
        opens = candles['open']

        bos = None
        if highs.iloc[-2] > highs.iloc[-3] and highs.iloc[-3] > highs.iloc[-4]:
            print("Bullish BOS detected.")
            bos = 'buy'
        elif lows.iloc[-2] < lows.iloc[-3] and lows.iloc[-3] < lows.iloc[-4]:
            print("Bearish BOS detected.")
            bos = 'sell'
        else:
            print("No BOS detected.")

        ob = None
        if closes.iloc[-2] < opens.iloc[-2]:
            print("Sell Order Block detected.")
            ob = 'sell'
        elif closes.iloc[-2] > opens.iloc[-2]:
            print("Buy Order Block detected.")
            ob = 'buy'
        else:
            print("No Order Block detected.")

        confirmation = {
            "BOS": bos,
            "Order Block": ob,
            "Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        print(f"SMC Analysis: {confirmation}")
        return confirmation

    except Exception as e:
        print(f"Error in SMC analysis: {e}")
        return None

    
async def detect_trend():
    """Determine trend based on EMA 9-21 on M1."""
    try:
        candles_m1 = get_candles(symbol, mt5.TIMEFRAME_M1, 50)
        if candles_m1 is None or len(candles_m1) < 50:
            await log_message("❌ Không có đủ dữ liệu nến M1.")
            return None

        candles_m1['EMA_9'] = calculate_ema(candles_m1, 9)
        candles_m1['EMA_21'] = calculate_ema(candles_m1, 21)

        if candles_m1['EMA_9'].isna().any() or candles_m1['EMA_21'].isna().any():
            await log_message("⚠️ EMA M1 có giá trị NaN, kiểm tra dữ liệu đầu vào.")
            return None

        trend_m1 = 'uptrend' if candles_m1['EMA_9'].iloc[-1] > candles_m1['EMA_21'].iloc[-1] else 'downtrend'
        await log_message(f"📊 Xu hướng M1: {trend_m1} (EMA 9: {candles_m1['EMA_9'].iloc[-1]:.5f}, EMA 21: {candles_m1['EMA_21'].iloc[-1]:.5f})")

        return trend_m1

    except Exception as e:
        await log_message(f"❌ Lỗi trong detect_trend(): {e}")
        return None


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


def get_total_profit():
    if not mt5.initialize():
        print("Không thể kết nối với MetaTrader 5:", mt5.last_error())
        return
    to_date = datetime.now()
    from_date = to_date - timedelta(days=7)
    history_orders = mt5.history_deals_get(from_date, to_date)
    if history_orders is None:
        print("Không tìm thấy giao dịch nào trong lịch sử hoặc đã xảy ra lỗi:", mt5.last_error())
        mt5.shutdown()
        return
    total_profit = sum(deal.profit for deal in history_orders)
    print(f"Total profit: {total_profit:.2f} USD")
    return total_profit


    
def get_equity_summary():
    """ Truy xuất tóm tắt vốn chủ sở hữu từ MetaTrader 5."""
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
    
    print("\n===== Tóm tắt vốn chủ sở hữu =====")
    for key, value in equity_summary.items():
        print(f"{key}: {value}")
    
    return equity_summary



def get_open_orders_count():
    """Lấy số lượng lệnh mua và bán mở cho ký hiệu hiện tại."""
    positions = mt5.positions_get(symbol=symbol)  
    if positions is None:
        print("No positions found.")
        return {'buy': 0, 'sell': 0}
    buy_count = sum(1 for pos in positions if pos.type == mt5.ORDER_TYPE_BUY)
    sell_count = sum(1 for pos in positions if pos.type == mt5.ORDER_TYPE_SELL)

    print(f"Open orders - Buy: {buy_count}, Sell: {sell_count}")
    return {'buy': buy_count, 'sell': sell_count}



def get_open_position_price(order_type):
    """Nhận giá mở của lệnh mua hoặc bán hiện tại, nếu có."""
    positions = mt5.positions_get(symbol=symbol)
    
    if positions is None or len(positions) == 0:
        print(f"No open {order_type} orders.")
        return None  

    for pos in positions:
        if (order_type == 'buy' and pos.type == mt5.ORDER_TYPE_BUY) or \
           (order_type == 'sell' and pos.type == mt5.ORDER_TYPE_SELL):
            print(f"Open price of the current {order_type} order: {pos.price_open}")
            return pos.price_open

    print(f"No current {order_type} orders.")
    return None



  

async def execute_trade(order_type, lot):
    """Đặt lệnh mua/bán XAUUSDm, SL 5000 point, TP 5000 point, và dời SL về entry khi đủ điều kiện."""
    
    symbol = "XAUUSDm"  

    tick_info = mt5.symbol_info_tick(symbol)
    if not tick_info:
        error_msg = f"❌ Không thể lấy giá hiện tại của {symbol}."
        print(error_msg)
        await send_telegram_message(error_msg)
        return None

    price = tick_info.ask if order_type == 'buy' else tick_info.bid
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        error_msg = f"❌ Không thể lấy thông tin symbol {symbol}."
        print(error_msg)
        await send_telegram_message(error_msg)
        return None

    point = symbol_info.point
    sl = price - (5000 * point) if order_type == 'buy' else price + (5000 * point)
    tp = price + (10000 * point) if order_type == 'buy' else price - (10000 * point)

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
        "comment": "SMC Trade",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }

    print(f"🟢 Gửi lệnh: {order_type.upper()}, Lot: {lot}, Giá: {price}, SL: {sl}, TP: {tp}")

    result = mt5.order_send(order)

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        message = f"📌 **Lệnh MỚI** ({order_type.upper()})\n" \
                  f"💰 Giá vào: {price}\n" \
                  f"📈 SL: {sl} | TP: {tp}\n" \
                  f"🔹 Khối lượng: {lot} lot"
        await send_telegram_message(message)

        for _ in range(30):  
            moved = await move_sl_to_breakeven(result.order, price, min_pips=5000)
            if moved:
                break
            await asyncio.sleep(5)  

        return result.order 
    else:
        error_msg = f"❌ **Lệnh thất bại**: {result.comment} (Mã lỗi: {result.retcode})"
        print(error_msg)
        await send_telegram_message(error_msg)
        return None



async def move_sl_to_breakeven(ticket, entry_price, min_pips=5000, check_interval=5):
    """Dời Stop Loss về mức entry khi giá chạy ít nhất min_pips pip."""
    
    while True: 
        position = mt5.positions_get(ticket=ticket)
        if not position:
            print(f"❌ Không tìm thấy lệnh {ticket}.")
            return False

        position = position[0]

        tick_info = mt5.symbol_info_tick(position.symbol)
        if not tick_info:
            print(f"❌ Không lấy được giá cho {position.symbol}")
            return False

        point = mt5.symbol_info(position.symbol).point  
        min_distance = min_pips * point  
        current_price = tick_info.bid if position.type == mt5.ORDER_TYPE_BUY else tick_info.ask

        if position.sl == entry_price:
            print(f"✅ SL đã ở Entry cho lệnh {ticket}, không cần cập nhật.")
            return True  

        if (position.type == mt5.ORDER_TYPE_BUY and current_price >= entry_price + min_distance) or \
           (position.type == mt5.ORDER_TYPE_SELL and current_price <= entry_price - min_distance):

            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": position.ticket,  
                "sl": entry_price,
                "tp": position.tp,
                "symbol": position.symbol,
                "type_time": mt5.ORDER_TIME_GTC,  
                "type_filling": mt5.ORDER_FILLING_FOK  
            }

            result = mt5.order_send(request)

            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                message = f"✅ SL đã dời về Entry cho lệnh {ticket}"
                print(message)
                await send_telegram_message(message)
                return True
            else:
                print(f"❌ Lỗi khi dời SL: {result.comment if result else 'Không có phản hồi từ MT5'}")
                return False

        print(f"⚠️ Giá chưa chạy đủ {min_pips} pip để dời SL về entry. Kiểm tra lại sau {check_interval} giây...")
        await asyncio.sleep(check_interval)  
        
async def check_and_move_sl_loop(check_interval=5):
    """Kiểm tra liên tục tất cả lệnh mở và dời SL khi đủ điều kiện."""
    while True:
        try:
            positions = mt5.positions_get()
            if not positions:
                await asyncio.sleep(check_interval)
                continue

            for position in positions:
                ticket = position.ticket
                entry_price = position.price_open
                asyncio.create_task(move_sl_to_breakeven(ticket, entry_price, min_pips=5000))


        except Exception as e:
            await log_message(f"❌ Lỗi trong quá trình kiểm tra và dời SL: {e}")

        await asyncio.sleep(check_interval)

async def run_bot():
    """Chạy bot để phát hiện tín hiệu và thực hiện giao dịch."""
    try:
        symbol = "XAUUSDm"

        if not mt5.symbol_select(symbol, True):
            await log_message(f"❌ Không thể chọn symbol {symbol}.")
            mt5.shutdown()
            return

        await log_message("🚀 Bot giao dịch đang chạy...")
        
        asyncio.create_task(check_and_move_sl_loop())
        
        rsi_history = []  
        previous_rsi = None 
         
        while is_trading_time():

            open_orders_count = get_open_orders_count() or {'buy': 0, 'sell': 0}
            if open_orders_count['buy'] >= 1 and open_orders_count['sell'] >= 1:
                await asyncio.sleep(1)
                continue  

            trend = await detect_trend()
            if trend not in ['uptrend', 'downtrend']:
                await log_message("⚠️ Không xác định được xu hướng, bỏ qua lệnh.")
                await asyncio.sleep(1)
                continue
            

            candles_m5 = get_candles (symbol, mt5.TIMEFRAME_M5, 50)
            rsi_data = check_rsi_m5(candles_m5)
            if not rsi_data or "status" not in rsi_data:
                await log_message("⚠️ Không thể lấy dữ liệu RSI, bỏ qua lệnh.")
                await asyncio.sleep(1)
                continue

            current_rsi = rsi_data.get("RSI")
            if current_rsi is None:
                await log_message("⚠️ RSI không hợp lệ, bỏ qua lệnh.")
                await asyncio.sleep(1)
                continue

    
            rsi_history.append(current_rsi)  
            if len(rsi_history) > 15:
                
                rsi_history.pop(0)
            if previous_rsi is not None:
                rsi_buy_signal = any(rsi < 30 for rsi in rsi_history) and current_rsi >= 35
                rsi_sell_signal = any(rsi > 70 for rsi in rsi_history) and current_rsi <= 65
            else:
                rsi_buy_signal = rsi_sell_signal = False


                
          
            smc_analysis = await detect_smc()
            if smc_analysis:
                smc_bos = smc_analysis["BOS"]
                smc_ob = smc_analysis["Order Block"]
            else:
                smc_bos = smc_ob = None
                await log_message("⚠️ Không thể phân tích SMC. Sử dụng tín hiệu Pin Bar nếu có.")
                
            
            
            pin_bar_signal = await find_pin_bar_signal(candles_m5.iloc[-5:])
            if pin_bar_signal:
                await log_message(f"✅ có thể Vào lệnh theo tín hiệu Pin Bar: {pin_bar_signal.upper()}")
            else:
                await log_message("ℹ️ Không có tín hiệu Pin Bar đủ điều kiện.")
                  
        
                
                
            wait_time = wait_for_m5_close()
            await asyncio.sleep(wait_time)
            


            tick_info = mt5.symbol_info_tick(symbol)
            if not tick_info:
                await log_message(f"❌ Không thể lấy giá hiện tại của {symbol}.")
                await asyncio.sleep(1)
                continue

            current_price = tick_info.ask
            equity_info = get_equity_summary()
            lot = 0.02

      
            if equity_info["Free Margin"] < 2 * lot:
                await log_message("❌ Không đủ margin để vào lệnh.")
                await asyncio.sleep(1)
                continue
            

            

            try:
               
                if smc_bos == 'buy' and smc_ob == 'buy' and rsi_buy_signal and trend == 'uptrend' and open_orders_count['buy'] < 1:
                    await log_message("🟢 Đặt lệnh Buy XAUUSD...")
                    ticket = await execute_trade('buy', lot)
                    if ticket and isinstance(ticket, int):
                        await move_sl_to_breakeven(ticket, current_price)

                elif smc_bos == 'sell' and smc_ob == 'sell' and rsi_sell_signal and trend == 'downtrend' and open_orders_count['sell'] < 1:
                    await log_message("🔴 Đặt lệnh Sell XAUUSD...")
                    ticket = await execute_trade('sell', lot)
                    if ticket is not None and isinstance(ticket, int):
                        await move_sl_to_breakeven(ticket, current_price)
                        
                        
                elif pin_bar_signal == "buy" and rsi_buy_signal and trend == 'uptrend' and open_orders_count['buy'] < 1:
                    await log_message("🟢 Đặt lệnh Buy XAUUSD (Tín hiệu Pin Bar)...")
                    ticket = await execute_trade('buy', lot)
                    if ticket and isinstance(ticket, int):
                        await move_sl_to_breakeven(ticket, current_price)
                        
                elif pin_bar_signal == "sell" and rsi_sell_signal and trend == 'downtrend' and open_orders_count['sell'] < 1:
                    await log_message("🔴 Đặt lệnh Sell XAUUSD (Tín hiệu Pin Bar)...")
                    ticket = await execute_trade('sell', lot)
                    if ticket is not None and isinstance(ticket, int):
                        await move_sl_to_breakeven(ticket, current_price)
                        
                        
            except Exception as e:
                await log_message(f"❌ Lỗi khi đặt lệnh: {e}")

            previous_rsi = current_rsi 

    
            message = (
                "\n===== 📊 XAUUSD 📊 =====\n"
                f"   - BOS: {smc_bos}\n"
                f"   - Order Block: {smc_ob}\n"
                f"🔹 EMA Trend: {trend}\n"
                f"🔹 Pin Bar Signal: {pin_bar_signal}\n" 
                f"🔹 Giá hiện tại: {current_price}\n"
                f"🔹 Số lệnh mở: {open_orders_count}\n"
                f"🔹 RSI M5: {rsi_data['RSI']} ({rsi_data['status']})\n"
                
                f"📊 Lịch sử RSI: {', '.join(map(str, rsi_data['RSI_History']))}\n"
                f"📌 Khuyến nghị: {rsi_data['recommendation']}\n"  

            )
            
            
            total_profit = get_total_profit()
            if total_profit is not None:
                message += f"\n💰 Tổng lợi nhuận 7 ngày: {total_profit:.2f} USD\n"


            if equity_info:
                message += "\n📌 Tóm tắt vốn:\n"
                for key, value in equity_info.items():
                    message += f"🔸 {key}: {value}\n"

            await log_message(message)

    except asyncio.CancelledError:
        print("🚨 Bot đã bị hủy. Đóng bot an toàn...")

if __name__ == "__main__":
    asyncio.run(run_bot())