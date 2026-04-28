Check server health. Run these three commands in parallel:

1. `ssh root@193.203.161.15 "systemctl status outreach-automation --no-pager -l"`
2. `ssh root@193.203.161.15 "journalctl -u outreach-automation --no-pager -n 30"`
3. `ssh root@193.203.161.15 "cd /home/omni/marketing-automation && git log --oneline -3 && echo '---' && git status --short"`

Present a summary: is the service running, any errors in recent logs, what commit is deployed.
