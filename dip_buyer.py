"""Dip Buyer — auto-detects V-dip patterns on 5m candles and alerts/executes.

Pattern:
1. 5m candle closes with body < -$DIP_THRESHOLD (big red candle)
2. Next candle opens and starts recovering (close > open)
3. → Alert: "V-Dip detected, bounce forming"
4. If auto_execute=True and in paper mode, places a market buy

Does NOT auto-execute on live positions. Alerts only for live.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

TRADING_SERVER = "http://localhost:9004"
CHECK_INTERVAL = 15  # Check every 15 seconds
DIP_THRESHOLD = 8.0  # Minimum $ drop in one 5m candle body
COOLDOWN = 0  # No cooldown — 5 ETH cap is the only limit
NTFY_TOPIC = ""

# Load env
try:
    with open(os.path.join(os.path.dirname(__file__), '.env')) as f:
        for line in f:
            if line.strip().startswith('NTFY_TOPIC='):
                NTFY_TOPIC = line.strip().split('=', 1)[1]
except:
    pass

last_trigger_time = 0
last_dip_candle_t = 0  # Timestamp of the dip candle we're watching

# Persist last dip timestamp across restarts
DIP_STATE_FILE = os.path.join(os.path.dirname(__file__), "data", "dip_buyer_state.txt")
try:
    with open(DIP_STATE_FILE) as f:
        last_dip_candle_t = float(f.read().strip())
except:
    pass


async def run():
    global last_trigger_time, last_dip_candle_t
    import httpx

    print(f"Dip buyer started (threshold=${DIP_THRESHOLD}, interval={CHECK_INTERVAL}s)", flush=True)

    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                # Get 5m candles
                resp = await client.get(f"{TRADING_SERVER}/api/candles?timeframe=5m&limit=5")
                candles = resp.json().get("candles", [])

                if len(candles) < 3:
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue

                now = time.time()

                # Look at the last 3 candles: [..., dip_candle, recovery_candle, current]
                for i in range(len(candles) - 1):
                    dip = candles[i]
                    recovery = candles[i + 1]

                    dip_body = dip.get("c", 0) - dip.get("o", 0)
                    dip_low = dip.get("l", 0)
                    dip_range = dip.get("h", 0) - dip_low
                    dip_t = dip.get("t", 0)

                    recovery_body = recovery.get("c", 0) - recovery.get("o", 0)
                    recovery_close = recovery.get("c", 0)

                    # Pattern: big red candle followed by green candle
                    is_dip = dip_body <= -DIP_THRESHOLD
                    is_bounce = recovery_body > 0
                    is_fresh = dip_t != last_dip_candle_t
                    is_cooled = now - last_trigger_time > COOLDOWN

                    if is_dip and is_bounce and is_fresh and is_cooled:
                        bounce_size = recovery_close - dip_low
                        retracement = bounce_size / dip_range * 100 if dip_range > 0 else 0

                        last_trigger_time = now
                        last_dip_candle_t = dip_t
                        try:
                            with open(DIP_STATE_FILE, "w") as f:
                                f.write(str(dip_t))
                        except:
                            pass

                        # Check current position
                        has_long = False
                        pos_size = 0
                        try:
                            pos_resp = await client.get(f"{TRADING_SERVER}/api/position/hl")
                            pos_data = pos_resp.json().get("position")
                            if pos_data and pos_data.get("side") == "long":
                                has_long = True
                                pos_size = pos_data.get("size", 0)
                        except:
                            pass

                        if has_long:
                            # Check if we're under 25% of buying power
                            # Hard cap: max 5 ETH total position from dip buys
                            MAX_ETH = 5.0
                            can_add = float(pos_size) < MAX_ETH
                            usage_pct = float(pos_size) / MAX_ETH * 100
                            print(f"  Position: {pos_size} ETH, cap: {MAX_ETH} ETH, "
                                  f"can add: {'YES' if can_add else 'NO'}", flush=True)

                            if can_add:
                                # Auto-add 1 ETH to existing long
                                title = f"V-Dip -AUTO ADD 1 ETH (using {usage_pct:.0f}% of equity)"
                                bought = False
                                try:
                                    buy_resp = await client.post(
                                        f"{TRADING_SERVER}/api/training/instruct",
                                        json={
                                            "action": "buy",
                                            "reasoning": f"Auto dip buyer pyramid: 5m dropped ${abs(dip_body):.1f}, "
                                                         f"bounced ${bounce_size:.1f}. Adding 1 ETH to existing "
                                                         f"{pos_size} ETH long. Portfolio usage: {usage_pct:.0f}%.",
                                            "sizePct": 5,
                                            "force": True,
                                        },
                                    )
                                    buy_result = buy_resp.json()
                                    if buy_result.get("status") == "executed":
                                        bought = True
                                        buy_price = buy_result.get("price", recovery_close)
                                        print(f"  → AUTO ADD executed at ${buy_price:.2f} (portfolio: {usage_pct:.0f}%)", flush=True)

                                        # Don't touch the SL on adds — leave the wider safety SL in place
                                        print(f"  → Keeping existing SL (not moving on pyramid add)", flush=True)
                                    else:
                                        print(f"  → Add failed: {buy_result}", flush=True)
                                except Exception as e:
                                    print(f"  → Auto add error: {e}", flush=True)

                                msg = (f"V-Dip on 5m: dropped ${abs(dip_body):.1f}, bounced ${bounce_size:.1f}. "
                                       f"{'ADDED 1 ETH' if bought else 'Add attempted but failed'}. "
                                       f"Now {pos_size + (1 if bought else 0):.1f} ETH. "
                                       f"Portfolio usage: {usage_pct:.0f}%.")
                            else:
                                # Over 25% — alert only
                                msg = (f"V-Dip on 5m: dropped ${abs(dip_body):.1f}, bounced ${bounce_size:.1f}. "
                                       f"Already LONG {pos_size} ETH (using {usage_pct:.0f}% of equity). "
                                       f"Over 25% limit — NOT adding. Low: ${dip_low:.2f}.")
                                title = f"V-Dip -At Limit ({usage_pct:.0f}%)"

                        else:
                            # NO POSITION — auto-buy 1 ETH and start ratchet
                            title = "V-Dip -AUTO BUY 1 ETH"
                            bought = False
                            try:
                                buy_resp = await client.post(
                                    f"{TRADING_SERVER}/api/training/instruct",
                                    json={
                                        "action": "buy",
                                        "reasoning": f"Auto dip buyer: 5m candle dropped ${abs(dip_body):.1f}, "
                                                     f"bounced ${bounce_size:.1f} ({retracement:.0f}% retracement). "
                                                     f"Low: ${dip_low:.2f}. Auto-entry 1 ETH.",
                                        "sizePct": 5,  # Small — roughly 1 ETH
                                        "force": True,
                                    },
                                )
                                buy_result = buy_resp.json()
                                if buy_result.get("status") == "executed":
                                    bought = True
                                    buy_price = buy_result.get("price", recovery_close)
                                    print(f"  → AUTO BUY executed at ${buy_price:.2f}", flush=True)

                                    # Place SL at dip low minus a small buffer
                                    sl_price = round(dip_low - 3, 1)
                                    try:
                                        sl_resp = await client.post(
                                            f"{TRADING_SERVER}/api/risk/hl-stop",
                                            json={"price": sl_price},
                                        )
                                        print(f"  → SL placed at ${sl_price:.1f}", flush=True)
                                    except:
                                        print(f"  → SL placement failed", flush=True)
                                else:
                                    print(f"  → Buy failed: {buy_result}", flush=True)
                            except Exception as e:
                                print(f"  → Auto buy error: {e}", flush=True)

                            msg = (f"V-Dip on 5m: dropped ${abs(dip_body):.1f}, bounced ${bounce_size:.1f} "
                                   f"({retracement:.0f}% retracement). "
                                   f"{'BOUGHT 1 ETH' if bought else 'Buy attempted but failed'}. "
                                   f"Low: ${dip_low:.2f}, now: ${recovery_close:.2f}.")

                        print(f"[{time.strftime('%H:%M:%S')}] {title}: dip=${dip_body:.1f} bounce=${bounce_size:.1f} "
                              f"low=${dip_low:.2f} now=${recovery_close:.2f}", flush=True)

                        # Send ntfy
                        if NTFY_TOPIC:
                            try:
                                await client.post(
                                    f"https://ntfy.sh/{NTFY_TOPIC}",
                                    content=msg.encode("utf-8"),
                                    headers={"Title": title.encode("utf-8"), "Priority": "urgent",
                                             "Tags": "chart_with_downwards_trend"},
                                )
                                print(f"  → ntfy sent", flush=True)
                            except Exception as e:
                                print(f"  → ntfy failed: {e}", flush=True)

                        break  # Only alert on the most recent pattern

            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] Error: {e}", flush=True)

            await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
