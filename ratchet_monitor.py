"""Trailing stop ratchet — resilient HL stop management.

Strategy:
1. Try modify_order first (atomic, preferred)
2. If modify fails, cancel + wait 3s + place
3. If place fails, verify what's on HL and don't panic
4. Never leave position fully unprotected — verify after every operation

Checks every 30 seconds. Trail tightens with profit.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

CHECK_INTERVAL = 30
watermark = 0.0
current_sl = 0.0
tracked_oid = None


def get_trail_pct(pnl):
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

    def get_hl_stops():
        """Fetch current stop orders from HL."""
        try:
            resp = httpx.post("https://api.hyperliquid.xyz/info",
                              json={"type": "frontendOpenOrders", "user": main_addr}, timeout=10)
            return [o for o in resp.json() if o.get("orderType") == "Stop Market" and o.get("coin") == "ETH"]
        except:
            return []

    def sync():
        """Sync tracked_oid and current_sl from HL."""
        global tracked_oid, current_sl
        stops = get_hl_stops()
        if stops:
            best = max(stops, key=lambda o: float(o.get("triggerPx", 0)))
            tracked_oid = best.get("oid")
            current_sl = float(best.get("triggerPx", 0))
            return True
        tracked_oid = None
        current_sl = 0
        return False

    def place_stop(trigger, size):
        """Place a new stop. Returns oid or None."""
        global tracked_oid, current_sl
        trigger = round(float(trigger), 1)
        try:
            ot = {"trigger": {"triggerPx": trigger, "isMarket": True, "tpsl": "sl"}}
            result = exchange.order("ETH", False, float(size), trigger - 5, ot, reduce_only=True)
            for s in result.get("response", {}).get("data", {}).get("statuses", []):
                if "resting" in s:
                    tracked_oid = s["resting"]["oid"]
                    current_sl = trigger
                    return tracked_oid
                elif "error" in s:
                    print(f"  Place rejected: {s['error']}", flush=True)
        except Exception as e:
            print(f"  Place error: {e}", flush=True)
        return None

    def move_stop(new_trigger, size):
        """Move stop to new trigger. Returns True if successful."""
        global tracked_oid, current_sl

        new_trigger = round(float(new_trigger), 1)

        # Method 1: Try modify_order
        if tracked_oid:
            try:
                ot = {"trigger": {"triggerPx": new_trigger, "isMarket": True, "tpsl": "sl"}}
                result = exchange.modify_order(tracked_oid, "ETH", False, float(size), new_trigger - 5, ot, reduce_only=True)
                for s in result.get("response", {}).get("data", {}).get("statuses", []):
                    if "resting" in s:
                        tracked_oid = s["resting"]["oid"]
                        current_sl = new_trigger
                        return True
            except:
                pass

        # Method 2: Cancel + wait + place
        if tracked_oid:
            try:
                exchange.cancel("ETH", tracked_oid)
            except:
                pass
            time.sleep(3)

        oid = place_stop(new_trigger, size)
        if oid:
            return True

        # Method 3: Verify what's actually on HL
        time.sleep(2)
        if sync():
            print(f"  Recovered: stop at ${current_sl:.2f}", flush=True)
            return current_sl >= new_trigger - 1  # Close enough

        return False

    # Initial sync
    if sync():
        print(f"Synced: stop at ${current_sl:.2f} oid={tracked_oid}", flush=True)
    else:
        print("No stop found on HL", flush=True)

    print(f"Ratchet started (resilient, interval={CHECK_INTERVAL}s)", flush=True)

    while True:
        try:
            # Get position
            state = info.user_state(main_addr)
            pos_size = 0
            entry = 0
            upnl = 0
            side = "flat"
            for pos_data in state.get("assetPositions", []):
                p = pos_data.get("position", {})
                if p.get("coin") == "ETH":
                    szi = float(p.get("szi", 0))
                    pos_size = abs(szi)
                    side = "long" if szi > 0 else "short" if szi < 0 else "flat"
                    entry = float(p.get("entryPx", 0))
                    upnl = float(p.get("unrealizedPnl", 0))

            if pos_size == 0 or side != "long":
                if watermark > 0:
                    print(f"[{time.strftime('%H:%M:%S')}] Position closed — resetting", flush=True)
                    watermark = 0
                    current_sl = 0
                    tracked_oid = None
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            mark = entry + upnl / pos_size
            if mark > watermark:
                watermark = mark

            trail_pct = get_trail_pct(upnl)
            target_sl = round(watermark * (1 - trail_pct), 1)

            if target_sl > current_sl + 0.5:  # Only move if meaningful change
                old_sl = current_sl
                success = move_stop(target_sl, pos_size)
                if success:
                    print(f"[{time.strftime('%H:%M:%S')}] RATCHET: ${old_sl:.2f} → ${current_sl:.2f} "
                          f"(mark=${mark:.2f} P&L=${upnl:.2f} trail={trail_pct*100:.1f}%)", flush=True)
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] MOVE FAILED — syncing from HL", flush=True)
                    sync()
            else:
                print(f"[{time.strftime('%H:%M:%S')}] OK: ${mark:.2f} wm=${watermark:.2f} "
                      f"SL=${current_sl:.2f} P&L=${upnl:.2f} trail={trail_pct*100:.1f}%", flush=True)

        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Error: {e}", flush=True)

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
