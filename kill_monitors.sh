#!/bin/bash
# EMERGENCY: Kill all trading monitors
echo "Killing all monitors..."
pkill -f ratchet_monitor.py 2>/dev/null
pkill -f dip_buyer.py 2>/dev/null  
pkill -f spike_catcher.py 2>/dev/null
pkill -f conviction_tracker.py 2>/dev/null
pkill -f overnight_ratchet.py 2>/dev/null
echo "All monitors killed."
echo "Trading server still running but NO automated actions."
