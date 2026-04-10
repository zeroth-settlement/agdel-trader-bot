"""Trailing stop ratchet — modifies HL stop in-place as price climbs.

Uses modify_order for atomic stop updates (no cancel gap).
Trail tightens as profit grows:
  <$100: 1.5% | $100-300: 1.0% | $300-500: 0.75% | >$500: 0.5%
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

CHECK_INTERVAL = 30

watermark = 0.0
current_sl = 0.0
tracked_oid = None  # The stop order we're managing


def get_trail_pct(pnl: float) -> float:
    if pnl >= 500: return 0.005
    elif pnl >= 300: return 0.0075
    elif pnl >= 100: return 0.01
    else: return 0.015


async def run():
    global watermark, current_sl, tracked_oid

    env = {}
    with open(os.path.join(os.path.dirname(__file__), '.env')) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            if '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()

    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    from hyperliquid.utils import constants
    from eth_account import Account
    import httpx

    wallet = Account.from_key(env['TRADERBOT_WALLET_PRIVATE_KEY'])
    main_addr = env['HYPERLIQUID_WALLET_ADDRESS']
    info = Info(constants.MAINNET_API_URL)
    exchange = Exchange(wallet, constants.MAINNET_API_URL, account_address=main_addr)

    print(f"Ratchet started (modify_order, adaptive trail, interval={CHECK_INTERVAL}s)", flush=True)

    while True:
        try:
            state = info.user_state(main_addr)
            pos_size = 0
            pos_side = "flat"
            entry = 0
            upnl = 0
            for pos_data in state.get("assetPositions", []):
                p = pos_data.get("position", {})
                if p.get("coin") == "ETH":
                    szi = float(p.get("szi", 0))
                    pos_size = abs(szi)
                    pos_side = "long" if szi > 0 else "short" if szi < 0 else "flat"
                    entry = float(p.get("entryPx", 0))
                    upnl = float(p.get("unrealizedPnl", 0))

            if pos_size == 0 or pos_side != "long":
                if watermark > 0:
                    print(f"[{time.strftime('%H:%M:%S')}] Position closed — resetting", flush=True)
                    watermark = 0
                    current_sl = 0
                    tracked_oid = None
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            mark = entry + upnl / pos_size
            pnl = upnl

            if mark > watermark:
                watermark = mark

            trail_pct = get_trail_pct(pnl)
            target_sl = round(watermark * (1 - trail_pct), 2)

            # Find our stop order if we don't have it tracked
            if not tracked_oid:
                resp = httpx.post("https://api.hyperliquid.xyz/info",
                                  json={"type": "frontendOpenOrders", "user": main_addr})
                stops = [o for o in resp.json() if o.get("orderType") == "Stop Market" and o.get("coin") == "ETH"]
                if stops:
                    # Use the highest trigger stop
                    best = max(stops, key=lambda o: float(o.get("triggerPx", 0)))
                    tracked_oid = best.get("oid")
                    current_sl = float(best.get("triggerPx", 0))
                    print(f"[{time.strftime('%H:%M:%S')}] Found existing stop: oid={tracked_oid} trigger=${current_sl:.2f}", flush=True)

            if target_sl > current_sl and tracked_oid:
                # MODIFY the existing stop — atomic, no gap
                ot = {"trigger": {"triggerPx": target_sl, "isMarket": True, "tpsl": "sl"}}
                limit_px = target_sl - 5  # Limit below trigger for sell stop
                result = exchange.modify_order(tracked_oid, "ETH", False, pos_size, limit_px, ot, reduce_only=True)

                # Extract new OID
                new_oid = None
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                for s in statuses:
                    if "resting" in s:
                        new_oid = s["resting"]["oid"]

                if new_oid:
                    old_sl = current_sl
                    current_sl = target_sl
                    tracked_oid = new_oid
                    print(f"[{time.strftime('%H:%M:%S')}] RATCHET: ${old_sl:.2f} → ${target_sl:.2f} "
                          f"(mark=${mark:.2f} P&L=${pnl:.2f} trail={trail_pct*100:.1f}%)", flush=True)
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] MODIFY FAILED: {result}", flush=True)
                    # Reset tracked_oid so next cycle re-fetches from HL
                    tracked_oid = None

            elif target_sl > current_sl and not tracked_oid:
                # No existing stop — place one
                ot = {"trigger": {"triggerPx": target_sl, "isMarket": True, "tpsl": "sl"}}
                result = exchange.order("ETH", False, pos_size, target_sl, ot, reduce_only=True)
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                for s in statuses:
                    if "resting" in s:
                        tracked_oid = s["resting"]["oid"]
                        current_sl = target_sl
                        print(f"[{time.strftime('%H:%M:%S')}] PLACED: ${target_sl:.2f} oid={tracked_oid}", flush=True)

            else:
                print(f"[{time.strftime('%H:%M:%S')}] OK: ${mark:.2f} wm=${watermark:.2f} "
                      f"SL=${current_sl:.2f} P&L=${pnl:.2f} trail={trail_pct*100:.1f}%", flush=True)

        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Error: {e}", flush=True)

        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(run())
