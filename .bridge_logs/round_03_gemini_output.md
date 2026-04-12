I will read the content of `frontend/src/pages/RetellFlowEditor.tsx` to prepare for the requested edits.
I will update the imports in `frontend/src/pages/RetellFlowEditor.tsx` to include the necessary `ReactFlow` components and remove the unused `NodeProps`.
I will now add the `globalPrompt` and `globalPromptSaving` state variables to `frontend/src/pages/RetellFlowEditor.tsx`.
I will update the `fetchFlow` function to set the `globalPrompt`, and add the `onConnect` handler and `handleSaveGlobalPrompt` function in `frontend/src/pages/RetellFlowEditor.tsx`.
I will now add the `onConnect` prop and the Global Prompt `Panel` to the `ReactFlow` component in `frontend/src/pages/RetellFlowEditor.tsx`.
I will now verify the changes by running the TypeScript compiler in the `frontend` directory to ensure there are no errors in `RetellFlowEditor.tsx`.
I will run the TypeScript compiler in the `frontend` directory using the `dir_path` parameter to avoid shell-specific command separator issues.
I will try to run the TypeScript compiler again in the `frontend` directory, this time without any shell-specific syntax to see if it clears the confirmation issue.
I will check the `frontend/package.json` file to determine the version of `@xyflow/react` and understand why the TypeScript compiler is failing.
I will now fix the TypeScript errors in `frontend/src/pages/RetellFlowEditor.tsx` by adding explicit type annotations to `useNodesState` and `useEdgesState`, and by correctly casting the node data in the `onNodeClick` handler.
I will read the `frontend/src/pages/RetellFlowEditor.tsx` file again to ensure I have the correct content and formatting before attempting to fix the TypeScript errors.
I will re-apply Edit 2 to add the `globalPrompt` and `globalPromptSaving` state variables to `frontend/src/pages/RetellFlowEditor.tsx`.
I will re-apply Edit 3 with the necessary type fixes, updating `fetchFlow`, adding the `onConnect` handler, and fixing the type in `onNodeClick` in `frontend/src/pages/RetellFlowEditor.tsx`.
I will read the remaining part of the `frontend/src/pages/RetellFlowEditor.tsx` file to identify and fix any additional TypeScript errors, specifically in `handlePublish` and `updateSelectedNode`.
I will now update the `frontend/src/pages/RetellFlowEditor.tsx` file with all the requested changes, including the necessary TypeScript fixes, by writing the entire file to ensure consistency and correctness.
I will now re-verify the changes by running the TypeScript compiler in the `frontend` directory to ensure that all errors in `RetellFlowEditor.tsx` have been resolved.
I have successfully completed all the requested changes and verified them with the TypeScript compiler. I will now stage the changes and commit them.
I will stage the changes and then commit them with a descriptive message to confirm the completion of the `RetellFlowEditor` implementation.
I will commit the staged changes with a message detailing the completion of the `RetellFlowEditor` implementation, including the global prompt and `onConnect` functionality.
I have completed the task.

- Fixed `NodeProps` import error in `RetellFlowEditor.tsx`.
- Added `globalPrompt` state and a dedicated `Panel` in the `ReactFlow` canvas.
- Wired up `onConnect` to enable drawing edges between nodes.
- Fixed TypeScript inference and casting errors.
- Verified that `npx tsc --noEmit` produces no errors.
- Committed the changes.

Summary of changes in `frontend/src/pages/RetellFlowEditor.tsx`:
- Updated `@xyflow/react` imports to include `Connection`, `addEdge`, and `Panel`.
- Added `globalPrompt` and `globalPromptSaving` state variables.
- Updated `fetchFlow` to load the global prompt from the backend.
- Implemented `onConnect` using `addEdge`.
- Added `handleSaveGlobalPrompt` to persist the global prompt via `PATCH`.
- Added a floating `Panel` to edit and save the global prompt.
- Added explicit type annotations to `useNodesState<Node>` and `useEdgesState<Edge>` to fix inference issues.
- Fixed type casting in `onNodeClick` and `handlePublish`.
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
Error executing tool run_shell_command: Tool execution for "Shell" requires user confirmation, which is not supported in non-interactive mode.
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
Error executing tool replace: Error: Failed to edit, could not find the string to replace.
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