"""Spike Catcher — detects rapid price spikes and alerts when momentum stalls.

Watches 1m candles for:
- SPIKE UP: $10+ move in 2 candles → wait for stall → alert to sell the top
- SPIKE DOWN: $10+ drop in 2 candles → wait for stall → alert to buy the dip

A "stall" = candle body < 30% of the average spike candle body.

Sends ntfy push notification when spike + stall detected.
"""
import asyncio
import os
import sys
import time
from collections import deque

sys.path.insert(0, os.path.dirname(__file__))

TRADING_SERVER = "http://localhost:9004"
CHECK_INTERVAL = 10  # Check every 10 seconds for responsiveness
SPIKE_THRESHOLD = 10.0  # $10 minimum spike
SPIKE_CANDLES = 2  # Over 2 candles
STALL_BODY_RATIO = 0.30  # Stall candle body < 30% of avg spike candle
COOLDOWN = 300  # 5 min between alerts
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

# Load from .env if not in environment
if not NTFY_TOPIC:
    try:
        with open(os.path.join(os.path.dirname(__file__), '.env')) as f:
            for line in f:
                if line.strip().startswith('NTFY_TOPIC='):
                    NTFY_TOPIC = line.strip().split('=', 1)[1]
    except:
        pass

last_alert_time = 0
prev_candles = deque(maxlen=10)


async def run():
    global last_alert_time
    import httpx

    print(f"Spike catcher started (threshold=${SPIKE_THRESHOLD}, interval={CHECK_INTERVAL}s)", flush=True)

    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                resp = await client.get(f"{TRADING_SERVER}/api/candles?timeframe=1m&limit=5")
                data = resp.json()
                candles = data.get("candles", [])

                if len(candles) < 4:
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue

                # Get last 4 candles: [older, spike1, spike2, current/stall candidate]
                recent = candles[-4:]
                c1, c2, c3, c4 = recent

                # Check for SPIKE UP: c2+c3 moved up $10+
                spike_up_move = c3.get("c", 0) - c2.get("o", 0)
                spike_up_bodies = [abs(c.get("c", 0) - c.get("o", 0)) for c in [c2, c3]]
                avg_spike_body = sum(spike_up_bodies) / len(spike_up_bodies) if spike_up_bodies else 1

                stall_body = abs(c4.get("c", 0) - c4.get("o", 0))
                is_stall = avg_spike_body > 0 and stall_body / avg_spike_body < STALL_BODY_RATIO

                now = time.time()

                if spike_up_move >= SPIKE_THRESHOLD and is_stall and now - last_alert_time > COOLDOWN:
                    price = c4.get("c", 0)
                    peak = max(c3.get("h", 0), c4.get("h", 0))
                    print(f"[{time.strftime('%H:%M:%S')}] SPIKE UP DETECTED: +${spike_up_move:.2f} in 2 candles, "
                          f"stall body=${stall_body:.2f} vs avg=${avg_spike_body:.2f} → SELL THE TOP @ ${price:.2f}",
                          flush=True)
                    last_alert_time = now
                    await send_alert(client, "Spike UP — Sell the Top",
                                     f"Price spiked +${spike_up_move:.1f} in 2 candles then stalled. "
                                     f"Peak: ${peak:.2f}. Consider taking profit or tightening stop.",
                                     price)

                # Check for SPIKE DOWN: c2+c3 dropped $10+
                spike_down_move = c2.get("o", 0) - c3.get("c", 0)
                if spike_down_move >= SPIKE_THRESHOLD and is_stall and now - last_alert_time > COOLDOWN:
                    price = c4.get("c", 0)
                    bottom = min(c3.get("l", 0), c4.get("l", 0))

                    # Check if we have an open long — dip is an add opportunity
                    has_long = False
                    try:
                        pos_resp = await client.get(f"{TRADING_SERVER}/api/position/hl")
                        pos_data = pos_resp.json().get("position")
                        if pos_data and pos_data.get("side") == "long":
                            has_long = True
                            pos_entry = pos_data.get("entryPrice", 0)
                            pos_size = pos_data.get("size", 0)
                    except:
                        pass

                    if has_long:
                        discount = ((pos_entry - price) / pos_entry * 100) if pos_entry else 0
                        print(f"[{time.strftime('%H:%M:%S')}] DIP while LONG: -${spike_down_move:.2f}, "
                              f"stalled @ ${price:.2f} — {discount:.1f}% below entry. ADD opportunity.",
                              flush=True)
                        last_alert_time = now
                        await send_alert(client, "Dip While Long — Add Opportunity",
                                         f"Price dipped -${spike_down_move:.1f} then stalled. "
                                         f"You're long {pos_size} ETH @ ${pos_entry:.2f}. "
                                         f"Current: ${price:.2f} ({discount:.1f}% below entry). "
                                         f"Momentum stalled — potential add to position at discount. "
                                         f"Check SL distance before adding.",
                                         price)
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] SPIKE DOWN DETECTED: -${spike_down_move:.2f} in 2 candles, "
                              f"stall body=${stall_body:.2f} → BUY THE DIP @ ${price:.2f}",
                              flush=True)
                        last_alert_time = now
                        await send_alert(client, "Spike DOWN — Buy the Dip",
                                         f"Price dropped -${spike_down_move:.1f} in 2 candles then stalled. "
                                         f"Bottom: ${bottom:.2f}. Potential bounce entry.",
                                         price)

            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] Error: {e}", flush=True)

            await asyncio.sleep(CHECK_INTERVAL)


async def send_alert(client, title, message, price):
    if not NTFY_TOPIC:
        return
    try:
        await client.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            content=f"{message}\n\nPrice: ${price:,.2f}".encode(),
            headers={"Title": f"⚡ {title}", "Priority": "urgent", "Tags": "chart_with_upwards_trend"},
        )
        print(f"  → ntfy sent", flush=True)
    except Exception as e:
        print(f"  → ntfy failed: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
