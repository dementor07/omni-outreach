Show recent service logs:

```
ssh root@193.203.161.15 "journalctl -u outreach-automation --no-pager -n 80"
```

Summarize: any errors or warnings, what the service is currently doing, last successful action.
