---
title: "Using agents in Visual Studio Code"
source: "https://code.visualstudio.com/docs/copilot/agents/overview#_hand-off-a-session-to-another-agent"
author:
  - "[[Microsoft]]"
published: 2021-11-03
created: 2026-04-13
description: "Learn about different types of AI agents in VS Code, including local agents, Copilot CLI for running in the background, and cloud agents."
tags:
  - "clippings"
---
Explore Agentic Development - [Join a GitHub Copilot Dev Day near you!](https://aka.ms/githubcopilotdevdays)

An agent is an AI assistant that works autonomously to complete a coding task. Give it a high-level goal, and it breaks the goal into steps, edits files across your project, runs commands, and self-corrects when something goes wrong. For example, instead of suggesting a fix for a failing test, an agent identifies the root cause across files, updates the code, reruns the tests, and commits the changes.

VS Code lets you run agents the way that fits your workflow. Work with them interactively in the editor, or let them run autonomously in the background from the CLI. Agents can run on your machine, in a remote cloud environment, or through a third-party provider like Anthropic or OpenAI. You decide how much autonomy to give them, from approving every tool call to letting them work fully on their own, and you can create custom agents to tailor their behavior to your project.

You monitor and interact with all your sessions from a single [sessions list](https://code.visualstudio.com/docs/copilot/chat/chat-sessions#_sessions-list) in the Chat view, regardless of where they run.

Understand the agent loop, how agents plan and execute tasks, and how memory and subagents work.

![Screenshot of an agent session in VS Code showing code changes and chat interaction.](https://code.visualstudio.com/assets/docs/copilot/agents-overview/chat-sessions-view.png)

Screenshot of an agent session in VS Code showing code changes and chat interaction.

> [!note] Note
> Tip
> 
> Enable agents in your VS Code settings (). Your organization might also disable agents - contact your admin to enable this functionality.

## Types of agents

Agents run in different environments depending on when you need results and how much oversight you want. The two key dimensions are *where* the agent runs (your machine or the cloud) and *how* you interact with it (interactively or autonomously in the background).

- [**Local**](https://code.visualstudio.com/docs/copilot/agents/local-agents): use the VS Code agent loop to run the agent interactively in the editor with full access to your workspace, tools, and models.
- [**Copilot CLI**](https://code.visualstudio.com/docs/copilot/agents/copilot-cli): use the Copilot CLI to run in the background on your machine, optionally using Git worktrees for isolation.
- [**Cloud**](https://code.visualstudio.com/docs/copilot/agents/cloud-agents): use GitHub Copilot to run remotely and integrate with GitHub pull requests for team collaboration.
- [**Third-party**](https://code.visualstudio.com/docs/copilot/agents/third-party-agents): use the third-party agent harness and SDK from Anthropic and OpenAI to run either locally on your machine or in the cloud.

Select the agent type from the agent target dropdown in the Chat view.

![Screenshot showing agent target dropdown in the Chat view.](https://code.visualstudio.com/assets/docs/copilot/agents-overview/agent-type-dropdown.png)

Screenshot showing agent target dropdown in the Chat view.

### Which agent type should I use?

Use the following table to find the right agent type for your task:

| I want to... | Use |
| --- | --- |
| Brainstorm, explore, or iterate on an idea interactively | [Local agent](https://code.visualstudio.com/docs/copilot/agents/local-agents) |
| Get answers about my codebase | [Local agent](https://code.visualstudio.com/docs/copilot/agents/local-agents) (Ask) |
| Create a structured implementation plan | [Local agent](https://code.visualstudio.com/docs/copilot/agents/local-agents) (Plan) |
| Fix an issue that needs editor context (test failures, linting errors, debug output) | [Local agent](https://code.visualstudio.com/docs/copilot/agents/local-agents) |
| Build and test web apps with the integrated browser *(Experimental)* | [Local agent](https://code.visualstudio.com/docs/copilot/agents/local-agents). See the [browser agent testing guide](https://code.visualstudio.com/docs/copilot/guides/browser-agent-testing-guide). |
| Use specific VS Code extension tools or MCP servers | [Local agent](https://code.visualstudio.com/docs/copilot/agents/local-agents) |
| Implement a well-defined task while I keep working | [Copilot CLI](https://code.visualstudio.com/docs/copilot/agents/copilot-cli) or [Cloud agent](https://code.visualstudio.com/docs/copilot/agents/cloud-agents) |
| Explore multiple variants or proof of concepts | [Copilot CLI](https://code.visualstudio.com/docs/copilot/agents/copilot-cli) or [Cloud agent](https://code.visualstudio.com/docs/copilot/agents/cloud-agents) |
| Create a PR for team review and collaboration | [Cloud agent](https://code.visualstudio.com/docs/copilot/agents/cloud-agents) |
| Assign a GitHub issue to an agent | [Cloud agent](https://code.visualstudio.com/docs/copilot/agents/cloud-agents) |
| Use a specific AI provider (Anthropic, OpenAI) | [Third-party agent](https://code.visualstudio.com/docs/copilot/agents/third-party-agents) |

## Choose an agent

If the agent type is *where* the agent runs, the agent determines *how* to perform the task based on its role or persona. For example, an agent with a code reviewer persona focuses on reviewing code changes for quality and style and providing feedback, instead of making code changes. The agent's definition determines which tools it can use, how it executes tasks, and potential handoff points to other agents.

Select an agent from the agents dropdown in the Chat view. You can switch between agents at any time during a session.

![Screenshot showing the Chat view with the agent picker expanded, displaying different agent options.](https://code.visualstudio.com/assets/docs/copilot/customization/chat-mode-dropdown.png)

Screenshot showing the Chat view with the agent picker expanded, displaying different agent options.

VS Code has three [built-in agents](https://code.visualstudio.com/docs/copilot/agents/local-agents):

- **Agent**: autonomously plans and implements changes across files, runs terminal commands, and invokes tools.
- **Plan**: creates a structured, step-by-step implementation plan before writing any code. Hands the plan off to an implementation agent when it looks right.
- **Ask**: answers questions about coding concepts, your codebase, or VS Code itself without making file changes.

For more specialized workflows, create your own [custom agents](https://code.visualstudio.com/docs/copilot/customization/custom-agents) that define a specific role, available tools, and a language model.

## Choose a permission level

Agents perform tasks autonomously, but you can control how much autonomy they have for invoking tools and terminal commands. Giving agents more autonomy can increase efficiency but may reduce oversight. The permissions picker in the Chat view lets you choose a permission level for each session, from approving every tool call to letting the agent work fully on its own.

| Permission level | Description |
| --- | --- |
| **Default Approvals** | Uses the approvals as specified in VS Code settings. By default, only read-only and safe tools don't require explicit approval. |
| **Bypass Approvals** | Auto-approves all tool calls without confirmation dialogs. The agent might ask clarifying questions as it works. |
| **Autopilot** (Preview) | Auto-approves all tool calls, auto-responds to questions, and the agent continues working autonomously until the task is complete. |

Learn more about [permission levels and Autopilot](https://code.visualstudio.com/docs/copilot/agents/agent-tools#_permission-levels).

## Hand off a session to another agent

You can hand off an existing task from one agent to another agent to take advantage of their unique strengths. For example, create a plan with a local agent, hand off to Copilot CLI for proof of concepts, and then continue with a cloud agent to submit a pull request for team review.

To hand off a local agent session, select a different agent type from the session type dropdown in the chat input box. VS Code creates a new session, carrying over the full conversation history and context. The original session is archived after handoff.

![Screenshot showing the session type dropdown for handing off to another agent.](https://code.visualstudio.com/assets/docs/copilot/background-agents/continue-in-cli.png)

Screenshot showing the session type dropdown for handing off to another agent.

In a Copilot CLI session, delegate to a cloud agent by entering the `/delegate` command in the chat input box. You can provide additional instructions after the `/delegate` command.

### Assign a coding task to an agent

If you install the [GitHub Pull Requests](https://marketplace.visualstudio.com/items?itemName=GitHub.vscode-pull-request-github) extension, you can assign an agent to implement `TODO` comments in your code.

![Screenshot of assigning a TODO comment to Copilot coding agent.](https://code.visualstudio.com/assets/docs/copilot/agents-overview/assign-todo-to-agent.png)

Screenshot of assigning a TODO comment to Copilot coding agent.

On GitHub.com, or by using the GitHub Pull Requests extension, you can assign GitHub issues to Copilot coding agent by assigning the issue to `copilot` or by mentioning it in an issue comment or pull request to ask for a code review.

## Related resources

- [Manage chat sessions](https://code.visualstudio.com/docs/copilot/chat/chat-sessions): Create, switch between, and organize your agent sessions.
- [Agents tutorial](https://code.visualstudio.com/docs/copilot/agents/agents-tutorial): Hands-on tutorial for working with different agent types.
- [Tools](https://code.visualstudio.com/docs/copilot/agents/agent-tools): Extend agents with built-in, MCP, and extension tools.
- [Hooks](https://code.visualstudio.com/docs/copilot/customization/hooks): Execute custom commands at lifecycle events for automation and policy enforcement.
- [Custom agents](https://code.visualstudio.com/docs/copilot/customization/custom-agents): Create your own AI agents and extensions.