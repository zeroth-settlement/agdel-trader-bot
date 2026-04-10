"""Trailing stop ratchet — uses StopManager for reliable HL stop updates.

Uses modify_order for atomic updates. Trail tightens with profit.
Checks every 30 seconds.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

CHECK_INTERVAL = 30
watermark = 0.0


async def run():
    global watermark

    # Load env
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
    from stop_manager import StopManager, compute_trailing_sl, compute_trail_pct

    wallet = Account.from_key(env['TRADERBOT_WALLET_PRIVATE_KEY'])
    main_addr = env['HYPERLIQUID_WALLET_ADDRESS']
    info = Info(constants.MAINNET_API_URL)
    exchange = Exchange(wallet, constants.MAINNET_API_URL, account_address=main_addr)

    mgr = StopManager(exchange, info, main_addr, asset="ETH")

    # Sync with whatever stop is already on HL
    if mgr.sync_from_hl():
        print(f"Synced: stop at ${mgr.state.trigger_price:.2f} oid={mgr.state.oid}", flush=True)
    else:
        print("No existing stop found on HL", flush=True)

    print(f"Ratchet started (StopManager, adaptive trail, interval={CHECK_INTERVAL}s)", flush=True)

    while True:
        try:
            # Get position from HL
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
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            mark = entry + upnl / pos_size
            if mark > watermark:
                watermark = mark

            trail_pct = compute_trail_pct(upnl)
            new_sl = compute_trailing_sl(mark, watermark, upnl, mgr.state.trigger_price)

            if new_sl:
                result = mgr.modify(new_sl, size=pos_size)
                if result.get("success"):
                    print(f"[{time.strftime('%H:%M:%S')}] RATCHET: ${result.get('oldTrigger',0):.2f} → ${new_sl:.2f} "
                          f"(mark=${mark:.2f} P&L=${upnl:.2f} trail={trail_pct*100:.1f}%)", flush=True)
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] FAILED: {result.get('error')} — re-syncing", flush=True)
                    mgr.sync_from_hl()
            else:
                # Periodic verify (every 5 min)
                if time.time() - mgr.state.last_verified_at > 300:
                    if mgr.verify():
                        print(f"[{time.strftime('%H:%M:%S')}] VERIFIED: ${mgr.state.trigger_price:.2f} on HL", flush=True)
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] VERIFY FAILED — stop may be missing!", flush=True)

                print(f"[{time.strftime('%H:%M:%S')}] OK: ${mark:.2f} wm=${watermark:.2f} "
                      f"SL=${mgr.state.trigger_price:.2f} P&L=${upnl:.2f} trail={trail_pct*100:.1f}%", flush=True)

        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Error: {e}", flush=True)

        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(run())
