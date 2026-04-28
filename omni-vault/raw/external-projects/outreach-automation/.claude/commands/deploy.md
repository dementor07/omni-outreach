Deploy current local changes to the server. Follow these steps exactly:

1. Run `git status` locally to see what needs committing.
2. If there are unstaged changes, show them and ask what to commit.
3. After confirmation, commit (NO co-author tags) and push: `git push origin outreach-threading`
4. SSH pull with stash to handle .env differences:
   ```
   ssh root@193.203.161.15 "cd /home/omni/marketing-automation && git stash && git pull origin outreach-threading && git stash pop 2>/dev/null; echo DONE"
   ```
5. If the pull fails with "divergent branches", run:
   ```
   ssh root@193.203.161.15 "cd /home/omni/marketing-automation && git fetch origin && git reset --hard origin/outreach-threading"
   ```
6. Verify the server has the latest commit:
   ```
   ssh root@193.203.161.15 "cd /home/omni/marketing-automation && git log --oneline -3"
   ```
7. Check service status:
   ```
   ssh root@193.203.161.15 "systemctl status outreach-automation --no-pager -l"
   ```
8. Report: commit hash, server pull status, service status. Remind me to start the service if it's stopped.

Do NOT restart the service automatically.
