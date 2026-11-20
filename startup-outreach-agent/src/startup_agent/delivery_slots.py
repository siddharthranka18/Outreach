"""Stable Oracle delivery identities; explicit override always takes precedence."""
from datetime import datetime,timedelta,timezone

def oracle_delivery_slot(now=None):
    india=timezone(timedelta(hours=5,minutes=30))
    now=(now or datetime.now(india)).astimezone(india)
    clock=now.hour*60+now.minute
    if clock>=18*60+15: slot='1815'
    elif clock>=9*60+15:slot='0915'
    else:
        now-=timedelta(days=1);slot='1815'
    return now.strftime('%Y%m%d')+slot
