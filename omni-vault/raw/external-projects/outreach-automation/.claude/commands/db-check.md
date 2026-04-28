Run a database health check. Execute these four queries in parallel via SSH:

1. Queue health:
```
ssh root@193.203.161.15 "PGPASSWORD='Omni@123leads' psql -h 193.203.161.15 -U leadgenemail -d marketing_automation -c \"SELECT task_type, status, COUNT(*) FROM dispatcher_queue GROUP BY task_type, status ORDER BY task_type, status;\""
```

2. Pipeline funnel:
```
ssh root@193.203.161.15 "PGPASSWORD='Omni@123leads' psql -h 193.203.161.15 -U leadgenemail -d marketing_automation -c \"SELECT campaign_id, COUNT(*) total, SUM(CASE WHEN accepted_at IS NOT NULL THEN 1 ELSE 0 END) accepted, SUM(CASE WHEN first_message_sent_at IS NOT NULL THEN 1 ELSE 0 END) first_msg, SUM(CASE WHEN followup_1_sent_at IS NOT NULL THEN 1 ELSE 0 END) fu1, SUM(CASE WHEN followup_2_sent_at IS NOT NULL THEN 1 ELSE 0 END) fu2, SUM(CASE WHEN followup_3_sent_at IS NOT NULL THEN 1 ELSE 0 END) fu3 FROM lead_full_stats GROUP BY campaign_id;\""
```

3. Recent failures:
```
ssh root@193.203.161.15 "PGPASSWORD='Omni@123leads' psql -h 193.203.161.15 -U leadgenemail -d marketing_automation -c \"SELECT failure_reason, COUNT(*) FROM dispatcher_queue WHERE status='failed' GROUP BY failure_reason ORDER BY COUNT(*) DESC LIMIT 10;\""
```

4. Upcoming queued tasks:
```
ssh root@193.203.161.15 "PGPASSWORD='Omni@123leads' psql -h 193.203.161.15 -U leadgenemail -d marketing_automation -c \"SELECT task_type, COUNT(*), MIN(scheduled_at), MAX(scheduled_at) FROM dispatcher_queue WHERE status='queued' GROUP BY task_type ORDER BY task_type;\""
```

Present a clear dashboard: queue state, pipeline funnel, failures, upcoming scheduled tasks.
