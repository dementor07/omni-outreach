Run tests on the server. Execute these in sequence:

1. Claude message generation test:
```
ssh root@193.203.161.15 "cd /home/omni/marketing-automation && python3 test_claude.py first_message CAMPAIGN_1"
```

2. Import smoke test:
```
ssh root@193.203.161.15 "cd /home/omni/marketing-automation && python3 -c 'import runner; import outbound_dispatcher; import db; print(\"All imports OK\")'"
```

3. DB connectivity:
```
ssh root@193.203.161.15 "cd /home/omni/marketing-automation && python3 -c 'from db import fetch_one; r = fetch_one(\"SELECT COUNT(*) as c FROM lead_full_stats\"); print(f\"Leads in DB: {r[\\\"c\\\"]}\")'"
```

Report which tests passed, which failed, and any error output.
