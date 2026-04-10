"""Trailing stop ratchet — monitors price and moves HL stop up only.

Checks every 30 seconds. Only moves stop UP, never down.
Trail TIGHTENS as profit grows:
  - Under $100 profit: 1.5% trail
  - $100-$300 profit:  1.0% trail
  - $300-$500 profit:  0.75% trail
  - Over $500 profit:  0.5% trail
"""
import asyncio
import httpx
import time

TRADING_SERVER = "http://localhost:9004"
CHECK_INTERVAL = 30  # seconds

watermark = 0.0
current_sl = 0.0
entry_price = 0.0


def get_trail_pct(pnl: float) -> float:
    """Tighter trail as profit grows."""
    if pnl >= 500:
        return 0.005   # 0.5%
    elif pnl >= 300:
        return 0.0075  # 0.75%
    elif pnl >= 100:
        return 0.01    # 1.0%
    else:
        return 0.015   # 1.5%


async def run():
    global watermark, current_sl, entry_price

    async with httpx.AsyncClient(timeout=10) as client:
        print(f"Ratchet monitor started (adaptive trail, interval={CHECK_INTERVAL}s)", flush=True)

        while True:
            try:
                # Get current position
                resp = await client.get(f"{TRADING_SERVER}/api/position/hl")
                data = resp.json()

                if not data.get("position") or data["position"].get("side") == "flat":
                    if watermark > 0:
                        print(f"[{time.strftime('%H:%M:%S')}] Position closed — resetting", flush=True)
                        watermark = 0
                        current_sl = 0
                        entry_price = 0
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue

                pos = data["position"]
                side = pos["side"]
                entry = float(pos["entryPrice"])
                pnl = float(pos["unrealizedPnl"])
                size = float(pos["size"])
                mark = entry + pnl / size

                if side != "long":
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue

                entry_price = entry

                # Update watermark (only goes up)
                if mark > watermark:
                    watermark = mark

                # Get adaptive trail based on current profit
                trail_pct = get_trail_pct(pnl)

                # Calculate where SL should be
                target_sl = round(watermark * (1 - trail_pct), 2)

                # Only move SL up, never down
                if target_sl > current_sl:
                    resp = await client.post(
                        f"{TRADING_SERVER}/api/risk/hl-stop",
                        json={"price": target_sl}
                    )
                    result = resp.json()
                    if result.get("success"):
                        old_sl = current_sl
                        current_sl = target_sl
                        print(f"[{time.strftime('%H:%M:%S')}] SL RATCHETED: ${old_sl:.2f} → ${target_sl:.2f} "
                              f"(mark=${mark:.2f} wm=${watermark:.2f} P&L=${pnl:.2f} trail={trail_pct*100:.1f}%)",
                              flush=True)
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] SL update failed: {result.get('error','?')}", flush=True)
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] OK: ${mark:.2f} wm=${watermark:.2f} "
                          f"SL=${current_sl:.2f} P&L=${pnl:.2f} trail={trail_pct*100:.1f}%", flush=True)

            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] Error: {e}", flush=True)

            await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(run())
