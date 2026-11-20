from datetime import datetime,timezone
from startup_agent.delivery_slots import oracle_delivery_slot

def test_oracle_slots_are_stable_across_retries_and_midnight():
    assert oracle_delivery_slot(datetime(2026,11,20,3,45,tzinfo=timezone.utc))=='202611200915'
    assert oracle_delivery_slot(datetime(2026,11,20,4,15,tzinfo=timezone.utc))=='202611200915'
    assert oracle_delivery_slot(datetime(2026,11,20,12,45,tzinfo=timezone.utc))=='202611201815'
    assert oracle_delivery_slot(datetime(2026,11,20,23,0,tzinfo=timezone.utc))=='202611201815'
