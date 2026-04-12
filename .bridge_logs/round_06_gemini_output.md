I will start by researching the files to locate the exact lines for these fixes.

I will use `grep` to confirm the presence of `ConnectionLineType` in `frontend/src/pages/RetellFlowEditor.tsx`.

I will check `frontend/src/pages/Campaigns.tsx` for `useMemo` and `ConnectionLineType` to verify the location of Fix A.

I will search for `ConnectionLineType` in all files to ensure I correctly identify its usage and location for the fix.

I will check `frontend/src/pages/Campaigns.tsx` for the usage of `useMemo` to determine if it should be removed.

I will check `frontend/src/pages/RetellFlowEditor.tsx` for the usage of `useMemo` to determine if it should be removed.

I will use `powershell` to display the first 40 lines of `frontend/src/pages/RetellFlowEditor.tsx` with line numbers to ensure I have the exact content.

I will run `git status` to check for any local changes and ensure my view of the codebase is up to date.

I will now begin applying the bug fixes, starting with `frontend/src/pages/RetellFlowEditor.tsx`.

I will now perform Fix B by removing the `setNodes` call within `onConnect` in `frontend/src/pages/RetellFlowEditor.tsx` and updating its dependency array.

I will now perform Fix C by updating the `handlePublish` payload in `frontend/src/pages/RetellFlowEditor.tsx` to include only `global_prompt`, `nodes`, and `start_node_id`.

I will now perform Fix D by filtering the request body in `backend/app/routers/accounts.py` to only include `global_prompt`, `nodes`, and `start_node_id` before sending it to the Retell API.

I will check `frontend/src/pages/Campaigns.tsx` for the usage of `useMemo` and then update the `useEffect` dependency array.

I will use `powershell` to `grep` for `ConnectionLineType` in `frontend/src/pages/RetellFlowEditor.tsx` to confirm its presence or absence once and for all.

I will check `frontend/src/pages/Campaigns.tsx` for any usage of `useMemo` to determine if the import is truly unused.

I will now update `frontend/src/pages/Campaigns.tsx` by removing the unused `useMemo` import and fixing the `useEffect` dependency array by removing `toast`.

I will now remove `toast` from the dependency array of the `useEffect` in `frontend/src/pages/Campaigns.tsx`.

I will now adjust Fix D in `backend/app/routers/accounts.py` to use a safer allow-list for the payload.

I have completed the bug fixes according to the Round 6 spec.

Fix Summary:
- **Fix A — TypeScript build error (`RetellFlowEditor.tsx` & `Campaigns.tsx`):** Removed unused `useMemo` from `RetellFlowEditor.tsx` and `Campaigns.tsx`. (Note: `ConnectionLineType` was not found in `RetellFlowEditor.tsx` and is used in `Campaigns.tsx`).
- **Fix B — Dead code in `onConnect` (`RetellFlowEditor.tsx`):** Removed the unnecessary `setNodes` call that updated `n.data.edges` and removed `setNodes` from the dependency array.
- **Fix C — Forbidden fields in Retell PATCH body (frontend) (`RetellFlowEditor.tsx`):** Updated `handlePublish` to send an explicit payload containing only `global_prompt`, `nodes`, and `start_node_id`, avoiding forbidden read-only fields.
- **Fix D — Backend filtering (`accounts.py`):** Added an allow-list filter in `update_voice_agent_flow` to ensure only `global_prompt`, `nodes`, and `start_node_id` are forwarded to Retell AI.
- **Fix E — Stale prompt shown when switching agents (`Campaigns.tsx`):** Verified `setAgentPrompt(null)` is called at the start of the effect and removed `toast` from the dependency array to avoid unnecessary re-triggers.

I will now commit the changes.

I will now add the changes to the git index and then commit them with a descriptive message.

I'll run `git status` to confirm the successful commit of the Round 6 bug fixes.

I have implemented the five targeted bug fixes from the Round 6 spec.

- **Fix A:** Removed unused `useMemo` from `RetellFlowEditor.tsx` and `Campaigns.tsx`.
- **Fix B:** Removed dead code in `onConnect` (`RetellFlowEditor.tsx`) that was updating `n.data.edges` and updated its dependency array.
- **Fix C:** Replaced the `...flow` spread in `handlePublish` (`RetellFlowEditor.tsx`) with an explicit payload containing only `global_prompt`, `nodes`, and `start_node_id`.
- **Fix D:** Implemented a defensive allow-list in `backend/app/routers/accounts.py` for the Retell flow update endpoint.
- **Fix E:** Ensured `setAgentPrompt(null)` is called at the start of the agent prompt loading effect and removed `toast` from the dependency array.

```bash
git add -A && git commit -m "feat: implement Round 6 bug-fixes"
```
YOLO mode is enabled. All tool calls will be automatically approved.
YOLO mode is enabled. All tool calls will be automatically approved.
C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11
var consoleProcessList = getConsoleProcessList(shellPid);
                         ^

Error: AttachConsole failed
    at Object.<anonymous> (C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11:26)
    at Module._compile (node:internal/modules/cjs/loader:1546:14)
    at Object..js (node:internal/modules/cjs/loader:1689:10)
    at Module.load (node:internal/modules/cjs/loader:1318:32)
    at Function._load (node:internal/modules/cjs/loader:1128:12)
    at TracingChannel.traceSync (node:diagnostics_channel:315:14)
    at wrapModuleLoad (node:internal/modules/cjs/loader:218:24)
    at Function.executeUserEntryPoint [as runMain] (node:internal/modules/run_main:170:5)
    at node:internal/main/run_main_module:36:49

Node.js v22.11.0
C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11
var consoleProcessList = getConsoleProcessList(shellPid);
                         ^

Error: AttachConsole failed
    at Object.<anonymous> (C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11:26)
    at Module._compile (node:internal/modules/cjs/loader:1546:14)
    at Object..js (node:internal/modules/cjs/loader:1689:10)
    at Module.load (node:internal/modules/cjs/loader:1318:32)
    at Function._load (node:internal/modules/cjs/loader:1128:12)
    at TracingChannel.traceSync (node:diagnostics_channel:315:14)
    at wrapModuleLoad (node:internal/modules/cjs/loader:218:24)
    at Function.executeUserEntryPoint [as runMain] (node:internal/modules/run_main:170:5)
    at node:internal/main/run_main_module:36:49

Node.js v22.11.0
C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11
var consoleProcessList = getConsoleProcessList(shellPid);
                         ^

Error: AttachConsole failed
    at Object.<anonymous> (C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11:26)
    at Module._compile (node:internal/modules/cjs/loader:1546:14)
    at Object..js (node:internal/modules/cjs/loader:1689:10)
    at Module.load (node:internal/modules/cjs/loader:1318:32)
    at Function._load (node:internal/modules/cjs/loader:1128:12)
    at TracingChannel.traceSync (node:diagnostics_channel:315:14)
    at wrapModuleLoad (node:internal/modules/cjs/loader:218:24)
    at Function.executeUserEntryPoint [as runMain] (node:internal/modules/run_main:170:5)
    at node:internal/main/run_main_module:36:49

Node.js v22.11.0
C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11
var consoleProcessList = getConsoleProcessList(shellPid);
                         ^

Error: AttachConsole failed
    at Object.<anonymous> (C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11:26)
    at Module._compile (node:internal/modules/cjs/loader:1546:14)
    at Object..js (node:internal/modules/cjs/loader:1689:10)
    at Module.load (node:internal/modules/cjs/loader:1318:32)
    at Function._load (node:internal/modules/cjs/loader:1128:12)
    at TracingChannel.traceSync (node:diagnostics_channel:315:14)
    at wrapModuleLoad (node:internal/modules/cjs/loader:218:24)
    at Function.executeUserEntryPoint [as runMain] (node:internal/modules/run_main:170:5)
    at node:internal/main/run_main_module:36:49

Node.js v22.11.0
C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11
var consoleProcessList = getConsoleProcessList(shellPid);
                         ^

Error: AttachConsole failed
    at Object.<anonymous> (C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11:26)
    at Module._compile (node:internal/modules/cjs/loader:1546:14)
    at Object..js (node:internal/modules/cjs/loader:1689:10)
    at Module.load (node:internal/modules/cjs/loader:1318:32)
    at Function._load (node:internal/modules/cjs/loader:1128:12)
    at TracingChannel.traceSync (node:diagnostics_channel:315:14)
    at wrapModuleLoad (node:internal/modules/cjs/loader:218:24)
    at Function.executeUserEntryPoint [as runMain] (node:internal/modules/run_main:170:5)
    at node:internal/main/run_main_module:36:49

Node.js v22.11.0
C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11
var consoleProcessList = getConsoleProcessList(shellPid);
                         ^

Error: AttachConsole failed
    at Object.<anonymous> (C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11:26)
    at Module._compile (node:internal/modules/cjs/loader:1546:14)
    at Object..js (node:internal/modules/cjs/loader:1689:10)
    at Module.load (node:internal/modules/cjs/loader:1318:32)
    at Function._load (node:internal/modules/cjs/loader:1128:12)
    at TracingChannel.traceSync (node:diagnostics_channel:315:14)
    at wrapModuleLoad (node:internal/modules/cjs/loader:218:24)
    at Function.executeUserEntryPoint [as runMain] (node:internal/modules/run_main:170:5)
    at node:internal/main/run_main_module:36:49

Node.js v22.11.0
C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11
var consoleProcessList = getConsoleProcessList(shellPid);
                         ^

Error: AttachConsole failed
    at Object.<anonymous> (C:\Users\navij\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11:26)
    at Module._compile (node:internal/modules/cjs/loader:1546:14)
    at Object..js (node:internal/modules/cjs/loader:1689:10)
    at Module.load (node:internal/modules/cjs/loader:1318:32)
    at Function._load (node:internal/modules/cjs/loader:1128:12)
    at TracingChannel.traceSync (node:diagnostics_channel:315:14)
    at wrapModuleLoad (node:internal/modules/cjs/loader:218:24)
    at Function.executeUserEntryPoint [as runMain] (node:internal/modules/run_main:170:5)
    at node:internal/main/run_main_module:36:49

Node.js v22.11.0