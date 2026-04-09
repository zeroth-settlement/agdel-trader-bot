"""Trailing stop ratchet — monitors price and moves HL stop up only.

Checks every 60 seconds. Only moves stop UP, never down.
Uses 1.5% trailing distance from the highest price seen.
"""
import asyncio
import httpx
import time
import os

TRADING_SERVER = "http://localhost:9004"
TRAIL_PCT = 0.015  # 1.5% trailing distance
CHECK_INTERVAL = 60  # seconds

watermark = 0.0
current_sl = 0.0

async def run():
    global watermark, current_sl
    
    async with httpx.AsyncClient(timeout=10) as client:
        print(f"Ratchet monitor started (trail={TRAIL_PCT*100}%, interval={CHECK_INTERVAL}s)")
        
        while True:
            try:
                # Get current position
                resp = await client.get(f"{TRADING_SERVER}/api/position/hl")
                data = resp.json()
                
                if not data.get("position") or data["position"].get("side") == "flat":
                    print(f"[{time.strftime('%H:%M:%S')}] No position — waiting")
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                
                pos = data["position"]
                side = pos["side"]
                entry = float(pos["entryPrice"])
                pnl = float(pos["unrealizedPnl"])
                size = float(pos["size"])
                mark = entry + pnl / size
                
                if side != "long":
                    print(f"[{time.strftime('%H:%M:%S')}] Position is {side}, ratchet only works for longs")
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                
                # Update watermark (only goes up)
                if mark > watermark:
                    watermark = mark
                
                # Calculate where SL should be
                target_sl = round(watermark * (1 - TRAIL_PCT), 2)
                
                # Only move SL up, never down
                if target_sl > current_sl:
                    # Move the stop on HL
                    resp = await client.post(
                        f"{TRADING_SERVER}/api/risk/hl-stop",
                        json={"price": target_sl}
                    )
                    result = resp.json()
                    if result.get("success"):
                        old_sl = current_sl
                        current_sl = target_sl
                        print(f"[{time.strftime('%H:%M:%S')}] SL RATCHETED: ${old_sl:.2f} → ${target_sl:.2f} (mark=${mark:.2f}, watermark=${watermark:.2f}, P&L=${pnl:.2f})")
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] SL update failed: {result.get('error','?')}")
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] OK: mark=${mark:.2f} watermark=${watermark:.2f} SL=${current_sl:.2f} P&L=${pnl:.2f}")
                    
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] Error: {e}")
            
            await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(run())
