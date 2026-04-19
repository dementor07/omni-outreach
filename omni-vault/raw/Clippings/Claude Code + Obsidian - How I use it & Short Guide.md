---
title: "Claude Code + Obsidian - How I use it & Short Guide"
source: "https://www.reddit.com/r/ClaudeAI/comments/1qr19df/claude_code_obsidian_how_i_use_it_short_guide/"
author:
  - "[[Conscious-Drawer-364]]"
published: 2026-01-30
created: 2026-04-13
description: "Cluade Code <3 Obsidian EDIT 20/03/26: CPR Skills for Claude Code are now live here https://github.com/EliaAlberti/cpr-compress-p"
tags:
  - "clippings"
---
![r/ClaudeAI - Cluade Code <3 Obsidian](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-jsgje5a9jggg1.gif?width=1080&crop=smart&auto=webp&s=c303766f1c8117a7b6f0e945e8a2905e288f66e3)

Cluade Code <3 Obsidian

**EDIT 20/03/26:** **CPR Skills** for Claude Code are now live here [https://github.com/EliaAlberti/cpr-compress-preserve-resume/tree/main](https://github.com/EliaAlberti/cpr-compress-preserve-resume/tree/main) Go and grab the **/compress, /preserve and /resume** skills which I talked about and explained in this article.

Read more about them here [https://www.reddit.com/r/ClaudeAI/comments/1rzr5uw/cpr\_for\_claude\_code\_3\_skills\_1\_memory/](https://www.reddit.com/r/ClaudeAI/comments/1rzr5uw/cpr_for_claude_code_3_skills_1_memory/)

Please consider a ⭐️ on the repo if you found it useful, it would mean a lot! 🙂

I've spent the last year trying to solve a problem that's been bugging me since I started taking notes seriously.

You capture information. Meetings, ideas, project details, random thoughts. It all goes somewhere and then... it kind of disappears into the void. You know it's there. You just can't find it when you need it or worse, you forget it exists entirely.

I tried tagging systems. Folder structures. Daily notes. Weekly reviews. Some of it helped. Most of it became another thing to maintain.

Then I connected Claude Code to my Obsidian vault and I didn't just connect it, I built a system around it. Custom skills. Session memory. Automatic syncing. The whole package.

Now when I start a work session, my AI assistant already knows what I was doing yesterday. It can search through months of notes in seconds. It creates and organises files without me touching anything and when I'm done, it saves everything we discussed so future me (or future AI) can pick up exactly where I left off.

Here's how to build one.

# Part 1 - The Philosophy

Before we get into setup, I want to explain the thinking behind it. Because the tools only matter if the structure makes sense.

# Write Once, Surface Everywhere

Here's the core idea:

You should never have to enter the same information twice.

When you create a meeting note, you add some basic info at the top such as date, attendees, which project it relates to. That's it.

From that moment, the note automatically shows up in:

- The project's page (under "Related Meetings")
- Your daily note (under "Today's Meetings")
- The person's profile if you track stakeholders
- Any dashboard that queries for meetings

You didn't link anything manually. You didn't copy and paste. The structure does the work.

Write once. Surface everywhere

![r/ClaudeAI - Write once. Surface everywhere.](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-uf0u3augjggg1.gif?width=1080&crop=smart&auto=webp&s=33fdce6dd91da83c441779cab1dfc21d5dcd64aa)

Write once. Surface everywhere.

This is called a **"proactive vault"**. Instead of you organising information, the vault organises itself based on metadata you add once.

# The Three Layers

The system has three layers:

- **Capture** - Where content lands first. Inbox folder, quick note, voice memos
- **Process** - Where content gets structured. Project folders, meeting notes with proper metadata
- **Surface** - Where the content appears when needed. Dashboard, projects hubs, search results

Most people only think about capture. They get content in, but never build the processing and surfacing layers. So their notes become a graveyard.

# Part 2 - The Physical Setup

Now let's make it real. Two places, two purposes, your Desktop for speed, your Obsidian vault for search. Here's how they fit together.

# Your Desktop (Quick Access)

I keep a working folder on my Desktop for active projects. This is where files such as screenshots, exports, meeting recordings etc land during the day.

Desktop/
├── +Inbox/                    # Quick drop-off (process daily)
├── Projects/
│   ├── Project-Alpha/
│   │   ├── UI-Design/21\_01\_26/
│   │   ├── Meetings/20\_01\_26/
│   │   └── Ready-to-Dev/
│   └── Project-Beta/
├── Meetings/
│   ├── Team-Standups/
│   └── Client-Calls/
└── Voice-Notes/![r/ClaudeAI - One folder per project.](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-udgx3ecmjggg1.gif?width=1080&crop=smart&auto=webp&s=e6761121695543fe4734827d9a3b09c7db5270cb)

One folder per project.

One folder per project.

# Your Obsidian Vault (Searchable Archive)

The vault mirrors this structure but adds the magic such as metadata, queries, and connections.

Vault/
├── +Inbox/                    # Quick capture
├── Areas/
│   ├── Work/
│   │   ├── Projects/
│   │   │   ├── Project-Alpha/
│   │   │   │   ├── Project-Alpha.md    # Main project file
│   │   │   │   ├── Assets/
│   │   │   │   └── Meetings/
│   │   │   └── Project-Beta/
│   │   ├── Meetings/
│   │   ├── Session-Logs/       # AI conversation history
│   │   └── \_Index.md           # Area hub with queries
│   ├── Personal/
│   └── Health/
├── Calendar/
│   ├── Daily/                  # YYYY-MM-DD.md
│   ├── Weekly/
│   └── Monthly/
├── System/
│   ├── Templates/
│   └── Dashboards/
└── CLAUDE.md                   # Project memory file

The key insight:

**Desktop is for speed, Vault is for search.**

They stay synced.

![r/ClaudeAI - Your knowledge, organized.](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-lbzdcftvjggg1.gif?width=1080&crop=smart&auto=webp&s=1222aa4c75acce7b404ce0b7b1959e503769ea9e)

Your knowledge, organized.

Your knowledge, organised.

# Part 3 - Setting Up Claude Code

Alright, the structure's in place. Time to bring in the AI. This part's quick, install, connect, confirm. You'll be talking to your vault in ten minutes or less.

# Installation

You need **Node.js** first. Check if you have it:

npm install -g /claude-code

If you see a version number (like v20.11.0), you're set. If you get an error grab it from [nodejs.org](http://nodejs.org/)

Then install Claude Code:

npm install -g u/anthropic-ai/claude-code

Launch it with by typing **claude**. First time, it'll open a browser for authentication. One time occurrence.

![r/ClaudeAI - One command. Ready to go.](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-whfgn4wyjggg1.gif?width=1080&crop=smart&auto=webp&s=efbcad75fac5f6d3678fd6e4c0f7b53b70dbf513)

One command. Ready to go.

One command. Ready to go.

# Connecting to Obsidian

Obsidian needs a plugin to let Claude Code talk to it.

1. Open Obsidian → Settings → Community Plugins
2. Search for **"Local REST API"** → Install → Enable
3. In plugin settings, generate an API key (copy it)
![r/ClaudeAI - Connect your tools.](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-nkg0qi24kggg1.gif?width=1080&crop=smart&auto=webp&s=f4b9a478479d70995bc9b6c2cad8b51a5a14e530)

Connect your tools.

Connect your tools.

Now tell Claude Code about it. Create or edit this file:

- **Mac/Linux:** ~/.claude/settings.json
- **Windows:** %USERPROFILE%\\.claude\\settings.json{ "mcpServers": { "obsidian": { "command": "npx", "args": \["-y", "obsidian-mcp"\], "env": { "OBSIDIAN\_API\_KEY": "your-api-key-here" } } } }

Restart Claude Code. Ask "Can you see my Obsidian vault?" and it should confirm.

![r/ClaudeAI - Your AI, connected.](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-ggpocbq6kggg1.gif?width=1080&crop=smart&auto=webp&s=34404791e55c244cb7167bd74fa8b3ed28b6ede5)

Your AI, connected.

Your AI, connected.

# Part 4: The Memory System

Here's the problem with AI assistants: context fades. Start a new session, and you're back to explaining your project from scratch.

Had a great session solving a complex problem? You remember it. The AI doesn't. Figured out how something works? Made important decisions? Unless you wrote them down somewhere and remember to paste them in next time, that context is gone.

I fixed this with three custom skills.

# Skill 1: /resume - Load Context

When I start a new session, I don't start from zero. I run **/resume** and Claude immediately knows:

- What I was working on recently
- Key decisions I've made
- The current state of my projects
- Any pending tasks

It reads from two places:

1. [**CLAUDE.md**](http://claude.md/) - A file in my vault that stores permanent project memory
2. **Session logs** - Saved summaries of recent conversations

Here's the logic:

**/resume** is project-aware. It detects which project folder you're in and loads the right context. Working on Project Alpha? It loads that [CLAUDE.md](http://claude.md/) and those session logs. Switch to a different project? Different context.

And it gets better. You can search by topic:

- **/resume** - Load last 3 sessions
- **/resume 10** - Load last 10 sessions
- **/resume auth** - Load recent sessions + search for anything about "auth"
- **/resume 5 jira** - Last 5 sessions + search for "jira" mentions

So when you're picking up work from two weeks ago, you don't scroll through logs. You just ask for what you need.

![r/ClaudeAI - Your AI remembers](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-zkccm0abkggg1.gif?width=1080&crop=smart&auto=webp&s=b6042d207c741c680744322fc6f5f9043f1d2f78)

Your AI remembers

# Skill 2: /compress - Save Session

Before ending a productive session, I run **/compress** to:

- See a multi-select of what to preserve: key learnings, solutions & fixes, decisions made, files modified, setup & config, pending tasks, errors & workarounds
- Create a searchable session log with a summary and the full conversation
- Save it to the right location based on which project you're in

That last point matters. For my main vault, it writes to both Desktop (quick access while working) and the Vault (searchable long-term). For other projects, it creates a **CC-Session-Logs** folder right in the project directory. No cross contamination.

![r/ClaudeAI - Your Work, preserved.](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-yx4y1axckggg1.gif?width=1080&crop=smart&auto=webp&s=761565373cb681d89092a3dd758f321078ca5f93)

Your Work, preserved.

Your Work, preserved.

The session log format looks like this:

\# Session: 21-01-2026 14:30 - project-alpha-auth-fix

## Quick Reference
\*\*Topics:\*\* authentication, API integration, error handling
\*\*Projects:\*\* Project-Alpha
\*\*Outcome:\*\* Fixed auth flow, documented edge cases

## Decisions Made
- Using JWT instead of session tokens
- 15-minute expiry with silent refresh

## Key Learnings
- The API returns 403 for expired tokens, not 401

## Pending Tasks
- \[ \] Add refresh token logic
- \[ \] Update error messages

---

## Raw Session Log
\[Full conversation archived below for searchability\]

The Quick Reference section is designed for AI scanning. When **/resume** runs, it reads these summaries first (fast, low token use). If it needs more detail, it can dig into the raw log.

Now when I run **/resume** next week and ask "what did we decide about authentication?", it finds this instantly.

# Skill 3: /preserve - Update Memory

Some learnings are permanent. Not session specific, but things I want Claude to always know about my project.

**/preserve** takes key insights and adds them to [CLAUDE.md](http://claude.md/) - the persistent memory file.

Things like:

- Project conventions and standards
- Architecture decisions
- Key file paths
- Common workflows

But here's the thing about memory files: they can grow forever and eventually become too big to be useful. So **/preserve** has auto-archive logic built in.

When [CLAUDE.md](http://claude.md/) exceeds **280 lines**, it kicks in:

1. Identifies what can be safely archived (completed projects, old session notes, sections marked as archivable)
2. Protects core sections that should never move (Approach, Key Paths, Skills, MCP Tools)
3. Moves old content to a separate [CLAUDE-Archive.md](http://claude-archive.md/) file
4. Keeps the main file lean and relevant

This way, Claude always has quick access to what matters now, but nothing is ever lost.

![r/ClaudeAI - Your AI's project memory.](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-uxcizk4hkggg1.gif?width=1080&crop=smart&auto=webp&s=8f5e11f76cbb5c01b8779a020eaa8afa90cfc71a)

Your AI's project memory.

# Part 5: Custom Skills for Daily Work

Beyond the memory system, I've built skills for common tasks. Here's the pattern explained.

# Creating a Skill

Skills live in ~/.claude/commands/ as markdown files. Each one is basically a prompt template which can get more complex over time, if and when you need it to.

Example of a simple **/daily-note** skill:

\# Daily Note Creator

Create or open today's daily note at Calendar/Daily/YYYY-MM-DD.md

Include:
- Top 3 priorities (ask me)
- Meetings scheduled today (check calendar folder)
- Links to active projects
- Quick capture section

If the note exists, open it and summarise what's there.

When you type **/daily-note**, Claude reads this file and executes it.

![r/ClaudeAI - Your Ai, extensible.](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-r9gd08sjkggg1.gif?width=1080&crop=smart&auto=webp&s=ef5186b76142557e86b30ce955990b16ff4e6861)

Your Ai, extensible.

Your Ai, extensible.

# Skills I Use Daily

- **/resume** - Load context from memory + recent sessions
- **/compress** - Save current session before ending
- **/preserve** - Add permanent learnings to [CLAUDE.md](http://claude.md/)
- **/daily-note** - Create/open today's note with structure
- **/meeting-note** - Process a meeting transcript into structured note
- **/inbox-process** - Go through +Inbox folder, file things properly
- **/weekly-review** - Summarise the week, prep for next

You don't need all of these on day one. Start with the memory system ( /resume, /compress, /preserve ) and add others as you feel the need.

# Making Skills Project-Aware

One thing I learned the hard way: global skills can cause cross-contamination. If you have multiple projects with their own session logs and [CLAUDE.md](http://claude.md/) files, you need skills that know which project they're in. The pattern I use:

\# Step 1: Detect Project
Check current working directory (pwd).

If pwd starts with "/path/to/main-vault":
  → This is Main Vault mode
  → Session logs go to Desktop AND Vault
  → Use vault-specific CLAUDE.md

Otherwise:
  → This is External Project mode
  → Session logs go to {project\_root}/CC-Session-Logs/
  → Use project-local CLAUDE.md

This way, the same **/compress** skill works correctly whether you're in your personal vault, a work project, or a side project. Each gets its own memory.

# Part 6: The Frontmatter System

This is what makes "write once, surface everywhere" work.

Every note has metadata at the top. Obsidian calls this **"frontmatter"**. It looks like this:

\---
type: meeting
date: 2026-01-21
project: Project-Alpha
attendees: \[Sarah, Mike, Dan\]
status: completed
---

Then in your project file, you add a query:

TABLE date, attendees
FROM "Areas/Work"
WHERE project = "Project-Alpha" AND type = "meeting"
SORT date DESC

This automatically shows all meetings related to Project-Alpha. You never manually link them.

![r/ClaudeAI - Tag once. Query everywhere.](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-yislxi0nkggg1.gif?width=1080&crop=smart&auto=webp&s=2a66b1581529f1e8de1d2faa4a66d878b9130269)

Tag once. Query everywhere.

Tag once. Query everywhere.

# Standard Frontmatter Fields

- **type** - What kind of note. Meeting, project, note, session, daily
- **date** - When created/occurred. YYYY-MM-DD
- **project** - Which project it relates to. Project nam
- **status** - Current state. Active, completed, on-hold, archived
- **tags** - Additional categorisation. Tag1, tag2\]

Once you standardise this, Claude Code can create notes with the right frontmatter automatically. And your queries just work.

# Part 7: Daily Operations

Here's what my actual day looks like with this system:

# 🌅 Morning (5 min)

**/resume**

Claude loads recent context, reminds me of pending tasks I tell it my priorities for today It updates my daily note

# 🌆 During the Day

- Files land in Desktop/+Inbox/ or I quick-capture to vault
- For focused work sessions, I talk through problems with Claude
- It creates notes, searches past work, and updates files as needed

# 🌇 Ending a Work Session

**/compress**

Claude asks what to save Creates session log I close knowing nothing's lost

# 🌃 End of Day (2 min)

- Quick look at daily note, what got done?
- Anything to carry forward to tomorrow?

# 📆 Weekly (15 min)

**/weekly-review**

Claude summarises the week from daily notes + session logs Shows what got completed Highlights decisions made Lists open items

![r/ClaudeAI - Your morning routine.](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-at4p0a6qkggg1.gif?width=1080&crop=smart&auto=webp&s=c408a426abc9e838c8da065f8ab679e7a2c62939)

Your morning routine.

Your morning routine.

# Part 8: Making It Your Own

I've shown you my system. But the beauty of this approach is that it adapts to how you work.

Start Simple Don't try to build everything at once. Here's the order I'd suggest:

1. **Week 1** - Install Claude Code, connect to Obsidian, play with basic commands
2. **Week 2** - Set up the memory system (/resume, /compress, /preserve)
3. **Week 3** - Establish your folder structure and frontmatter standards
4. **Week 4** - Add custom skills based on what you find yourself doing repeatedly

# What Makes It Stick

The systems that last are the ones that reduce friction, not add it.

If capturing a meeting note takes more effort than not capturing it, you won't do it. If finding old information is harder than just figuring it out again, you'll keep reinventing wheels.

This system works because Claude handles the tedious parts. You just talk, and structured notes appear. You just ask, and past context resurfaces.

![r/ClaudeAI - Your knowledge, accessible.](https://preview.redd.it/claude-code-obsidian-how-i-use-it-short-guide-v0-t0qfhj4skggg1.gif?width=1080&crop=smart&auto=webp&s=6ce910351eb8acf0071e70d5026433e3bcd14c8c)

Your knowledge, accessible.

Your knowledge, accessible.

# Quick Reference

# Config Location:

- **Mac/Linux:** ~/.claude/settings.json
- **Windows:** %USERPROFILE%\\.claude\\settings.json
- **Skills Location:** ~/.claude/commands/

# Core Skills:

- **/resume** - Load context
- **/compress** - Save session
- **/preserve** - Update permanent memory

# What Would Help You Most?

I could go deeper on any of this. The skill templates, the Dataview queries, the folder structures, connecting to other tools like Jira or GitHub.

But I'd rather know what would actually be useful to **you**.

What's the workflow that eats your time right now? Drop it in the comments. I'll use the answers to figure out what to cover next.

If you build this system, I'd genuinely like to hear how it goes. What worked, what didn't, what you changed to make it yours.

---

## Comments

> **ClaudeAI-mod-bot** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2krwzc/) · 1 points
> 
> **If this post is showcasing a project you built with Claude, please change the post flair to Built with Claude so that it can be easily found by others.**

> **GuitarAgitated8107** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2kteyw/) · 38 points
> 
> This is way too long, just pure Claude Code working on the directories is enough for me.
> 
> > **loddy71** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2l0hwv/) · 12 points
> > 
> > I have to agree, as someone who is very new to both CC and obsidian, this post frazzled my brain after just part one. I've seen people say that using Obsidian is very personal to you and the way to get to know it is just start building with your own use cases, and this post made that hit home even more for me. Sorry OP.
> > 
> > > **Accomplished\_Ad\_4604** · [2026-04-09](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/of997p0/) · 1 points
> > > 
> > > i saw the post , scrolled down and only thing matters is the local rest api , enabled , copied api + server , gave it to claude , it connected and started working on it , ignored the rest of the post
> 
> > **Apprehensive\_Age9264** · [2026-03-02](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o86i81o/) · 2 points
> > 
> > can you give some tips?

> **Aygle1409** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2mj3ga/) · 8 points
> 
> Short guide they said

> **OhNoesRain** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2ncoxw/) · 8 points
> 
> I already use claude code with obsidian and really am loving it. Your skills were really interesting!
> 
> > **Conscious-Drawer-364** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2ngt63/) · 4 points
> > 
> > Thanks! 👍

> **manummasson** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2kw1qt/) · 11 points
> 
> Hey I was also obsessed with the idea of Claude code + obsidian, so I built an interactive graph view for Obsidian vaults where I could also spawn claude within [https://github.com/voicetreelab/voicetree](https://github.com/voicetreelab/voicetree)
> 
> Some of your workflows looks really useful, I'll be trying them out. Would love to chat more
> 
> Some questions.
> 
> Why require an obisdian plugin to let claude "talk" to obsidian? It's all just local markdown files, Claude can search and edit those directly.
> 
> > **Conscious-Drawer-364** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2kwzmb/) · 3 points
> > 
> > Wow that's impressive! I've just briefly looked at the repo (and starred it of course) and I'm definitely going to try it out and let you know my thoughts :) I genuinely Love the graph view and I'm already thinking of few questions but first I'm going to try it out properly.
> > 
> > As for the obsidian plugin honestly, fair point. For basic read/write you absolutely can just point Claude at the vault folder. The MCP connection adds Obsidian's own search (which understands frontmatter, tags, and internal links in ways raw file grep doesn't) and lets Claude interact with a running instance.
> > 
> > But if working with the files directly does the job for you, that's a totally valid approach too.
> > 
> > > **agnostic\_universe** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2leg74/) · 2 points
> > > 
> > > I am building a similar workflow, and I used the local API plugin so I could host obsidian in a separate docker VM as my source or truth, and use that to sync with my phone.
> > > 
> > > **manummasson** · [2026-01-31](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2pfb6w/) · 2 points
> > > 
> > > Ah okay that makes sense re obsidian's own search being superior. I've been playing around as well with creating local embeddings using chromadb for every markdown note, which can give semantic based search. Would be interesting to combine these semantic results with Obsidian's standard search results.
> > > 
> > > Will love to hear your feedback on the tool and what features you would want to make it a goto.

> **Flashy-Bandicoot889** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2mdio9/) · 11 points
> 
> This was written by Claude.
> 
> > **stubble** · [2026-03-10](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o9qh6yy/) · 4 points
> > 
> > How can you tell? Are you suggesting that OP didn't spend hours, nay, days crafting each word like it was a piece of poetry?
> > 
> > > **Flashy-Bandicoot889** · [2026-03-11](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o9udk5n/) · 4 points
> > > 
> > > Pretty easy to tell. Might not have been Claude, but clearly AI-generated slop.
> 
> > **Flat-Bookkeeper-8645** · [2026-04-08](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/oez7fyq/) · 3 points
> > 
> > Get used to it man. Nothing will be fully written by humans soon. The sentiment behind it is though
> > 
> > **Left-Priority-5460** · [2026-04-09](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/of8dfxt/) · 1 points
> > 
> > So?

> **wmalexander** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2l3bhx/) · 5 points
> 
> Excellent post thank you. Obsidian + Claude Code has been massive for me - I’ve learned some new things from your post. Thanks.
> 
> > **Conscious-Drawer-364** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2l4x1w/) · 4 points
> > 
> > I genuinely couldn't be happier you found it useful. It's precisely the reason why I wrote it. Thank you for checking it out and enjoy !
> > 
> > > **prototype\_\_** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2l9eyd/) · 2 points
> > > 
> > > I've not used Claude code myself but I use Claude desktop with filesystem MCP to write doco and configs to an obsidian vault. So very handy.

> **fishcasa** · [2026-02-28](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o7wy08g/) · 5 points
> 
> Have you seen the new Obsidian CLI? Minimally alternative to Local Rest Plugin, maybe some new functionality opportunities.  
> [https://help.obsidian.md/cli](https://help.obsidian.md/cli)

> **Slow\_Character\_4675** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2lnge1/) · 4 points
> 
> Great system. I went down the same path and hit two walls:
> 
> 1. **The manual memory loop** — forgetting to compress/save context at the end meant losing everything. I ended up automating it: agents write to a shared brain (SQLite + MCP) without me triggering anything.
> 2. **Single session bottleneck** — with 5+ projects, one terminal wasn't enough. Running multiple agents in parallel with isolated sessions but shared knowledge was the unlock.
> 
> Your "write once, surface everywhere" with Dataview is clever. The frontmatter approach scales well for surfacing context.
> 
> I've been building something on top of the Claude Agent SDK that handles this — multi-agent orchestration with automatic memory sharing. Happy to share more if you're curious.
> 
> > **Conscious-Drawer-364** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2lubap/) · 3 points
> > 
> > Thanks for the feedback. Yes please, what you built sounds actually great particularly the automation you created for compressing context. It’s a very good idea to have it automated so feel free to share your findings!
> > 
> > I’ve been playing around with similar framework [https://github.com/EliaAlberti/superbeads-universal-framework](https://github.com/EliaAlberti/superbeads-universal-framework)
> > 
> > > **Slow\_Character\_4675** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2lvtqm/) · 2 points
> > > 
> > > Thanks! Here's the quick version of what I built:
> > > 
> > > It's called **Quack** — a native macOS app (Tauri/Rust) that sits on top of the Claude Agent SDK. The core ideas:
> > > 
> > > - **Multiple agents per project** running in parallel, each with its own isolated session (no context bleed between them)
> > > - **Shared brain** (SQLite + MCP) that all agents read/write to automatically — no manual compress/save step needed
> > > - **Visual sidebar** showing all agents grouped by project, so you can monitor 10+ agents at a glance instead of juggling terminal tabs
> > > - **Effort control per agent** — set low/medium/high thinking intensity depending on the task
> > > 
> > > The automatic memory was the biggest unlock. Agents save patterns, decisions, and gotchas as they work. Next session, any agent on that project already has the context.
> > > 
> > > Still in alpha but using it daily across 5 projects: [quack.build](https://quack.build/)
> > > 
> > > I'll check out superbeads — the universal framework angle is interesting, especially if it handles cross-project context. That's been one of the harder problems to solve cleanly.

> **Abalone\_Spirited** · [2026-02-05](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o3pbasp/) · 4 points
> 
> Drop the GitHub link!

> **StoutMatt** · [2026-02-28](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o7vg9c3/) · 4 points
> 
> Saved it for later, will check out sometime when I have time. J/k (sortof) thanks for the post, looks useful.

> **philnexes** · [2026-03-05](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o8r6yj3/) · 4 points
> 
> Hey!
> 
> Great job, thanks for this, I'll definitely take some inspiration from your workflow here.
> 
> Cheers!
> 
> > **Conscious-Drawer-364** · [2026-03-05](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o8skhjs/) · 2 points
> > 
> > Thank you 🙂

> **HubesMA** · [2026-03-07](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o93xxqd/) · 4 points
> 
> Nice workflow and thank's for the detailed explanation. I'll defenitely grab some steps for my vault management. Awesome!
> 
> > **Conscious-Drawer-364** · [2026-03-08](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o98hmer/) · 2 points
> > 
> > Thank you glad you found it useful 🙂👍🏻

> **Marcelo\_FD** · [2026-03-22](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/obt9l0k/) · 4 points
> 
> Duude Thanks a lot for spending the time to explain it here. I started to follow your text today, but I'll definently need some morentimento digest it all. Great work!
> 
> > **Conscious-Drawer-364** · [2026-03-22](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/obtab1x/) · 1 points
> > 
> > Thank you! I’m genuinely glad you found it useful. Let me know if you check out the skills here [https://github.com/EliaAlberti/cpr-compress-preserve-resume](https://github.com/EliaAlberti/cpr-compress-preserve-resume)

> **Grawlix\_TNN** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2l404a/) · 3 points
> 
> This is EXACTLY the system I ended up creating for myself, right down to the yaml frontmatter and everything. Clearly I am not ever in possession of an original idea lol.
> 
> > **Conscious-Drawer-364** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2l46z2/) · 2 points
> > 
> > lol I wouldn’t say that but rather Great minds think alike 😉
> > 
> > > **Grawlix\_TNN** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2l4qgh/) · 2 points
> > > 
> > > I'll take it! Seriously though, this has changed my life. I'm able to organise my life with near perfect context retention. The universal template keeps everything cross-linked and accessible and mitigates drift. Just needs some maintenance every now and then, and even that can be automated. 🤌

> **heathbar1\_** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2l6ruc/) · 3 points
> 
> I basically have this setup it’s such a life changer for sure especially when you can use your phone to record quick thoughts.

> **hiiwave** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2m0fge/) · 3 points
> 
> Looks interesting. The short guide isn't short though lol, thanks for sharing!
> 
> > **Conscious-Drawer-364** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2m7gvg/) · 2 points
> > 
> > 😅 fair enough I guess. It looked short to me but once you get going it's pretty straight forward. Thanks for the feedback!

> **Momar89** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2mj6zf/) · 3 points
> 
> Is anyone concerned about having all of your vault info shared with Claude? Aren't the training off your conversations which will include the contents of your obsidian vault?
> 
> > **mostmortal** · [2026-02-25](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o78w4pw/) · 2 points
> > 
> > Right. Privacy, security and IP are important to me.
> > 
> > Gemini with Google Workspace claims to not train on your data. But if the tech giant decides to just lie and use it anyway (likely) or if Gemini just decides to change its own rules (perhaps even more likely) then that claim is worthless.
> > 
> > Only a local LLM can be genuinely secure imo. And even then, I want to give it read-only access to my vault. Just with a subfolder it can write to.

> **PureV2** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2ndhsb/) · 3 points
> 
> Claude tells me the following:
> 
> ***The honest assessment:***
> 
> *This is a good starting point for someone building from scratch. For you, it's more useful as validation of the approach than as a template to copy. Your existing vault structure and skill system already implement the core ideas—you're past the "should I do this" stage and into optimization.*
> 
> *The auto-archive logic and project-awareness patterns are worth stealing if you haven't implemented them. The rest is infrastructure you've already built.*
> 
> So, dont mind if I do :P  
> Thanks

> **C0ntr0lledCha0s** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2nrppj/) · 3 points
> 
> This is a great idea, I had the same thought about doing this for logseq which is another PKM tool. 
> 
> The only reason I mention logseq is they have been working on a database version of the markdown tool and so should be more compatible with ai, instead of having unstructured formatter types (e.g. project, status, people etc.) you can define a class (person) and the related properties (date of birth etc.). As it's a database it can also have vectorized search for fast retrieval of info.
> 
> Great to see another user building meaningful ai integrations into their PKM workflows!

> **Conscious-Drawer-364** · [2026-03-21](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/obnvpuo/) · 3 points
> 
> # 🩺 CPR for Claude Code, Three skills. One Memory.
> 
> **/preserve** saves key learnings to a persistent memory file. Architecture decisions, conventions, project status. The things Claude should always know, not just in this session, in every session.
> 
> **/compress** captures the full conversation into a structured, searchable log before I close out. Decisions, solutions, errors, files touched. All timestamped and scannable.
> 
> **/resume** loads it all back. Recent sessions, permanent memory, pending tasks. One command and I'm back to full speed.
> 
> The real shift isn't saving time on setup. It's that your Claude Code actually compounds knowledge. Session after session, it gets better at helping you because it remembers what worked, what failed, and why you chose A over B.
> 
> Three markdown files. No plugins. No dependencies. Five minutes to set up.
> 
> [https://github.com/EliaAlberti/cpr-compress-preserve-resume](https://github.com/EliaAlberti/cpr-compress-preserve-resume)

> **emptyharddrive** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2ll14e/) · 5 points
> 
> TL;DR: The OP's post is amazingly complex and unnecessary. Wow! Move along, nothing to see here!
> 
> For those who think otherwise:
> 
> An Obsdian vault is just a mass of markdown text files, raw text. Putting claude in front of the vault folder is enough to get whatever you want out of it by just asking it to search through the vault. But that is token-inefficient.
> 
> If you want to optimize it you can use a mix of [ripgrep](https://pypi.org/project/ripgrep/) & [fts5](https://sqlite.org/fts5.html) tools in front of your vault, I've written one which I host on GitHub, but there are many others and you can make your own and they all have similar names. The approach gets you answers without using many tokens. ripgrep and fts5 do most of the work and AI just sifts/sorts the clippings provided into that most aligns with the question asked.
> 
> A step further would be to create and maintain embeddings, which is how NotebookLM does it. But that takes effort and maintenance and sometimes the juice isn't worth the squeeze unless you have a LOT of data.
> 
> But what the OP is doing is an exercise in tedium, frustration and /command chaos. No thank you.
> 
> > **ricardo\_wiseverge** · [2026-02-01](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2w9p50/) · 3 points
> > 
> > Can you expand a bit on how would you do it?
> > 
> > > **emptyharddrive** · [2026-02-01](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2wjd4l/) · 2 points
> > > 
> > > [The project is here to download if you like](https://github.com/seqis/AI-grep).
> > > 
> > > It's basically a portable, drop-in search tool that indexes any directory for AI/LLM workflows. It can do multiple directories (called mount points) and be used as 1 DB to search any of the "mounts" (directories). It can index Obsidian vaults with their wiki-links, codebases and docs, as core use cases. I care about token savings: find relevant files without reading whole files. It's also faster than Claude doing a search for content manually on your drive.
> > > 
> > > It builds a SQLite FTS5 of the folder and sub-dirs, and indexes with incremental updates and can extract text from Office docs and PDFs. Relevant files are chunked and sent off to AI to sort and rank based on the question asked. That means I can search a big vault or any folder without opening whole files. ([AI-grep on GitHub](https://github.com/seqis/AI-grep)).
> > > 
> > > Run setup once then stats and toc give a quick overview before you pull real text. Then search, get and context grab only needed lines.  
> > > That helps with Obsidian vaults because wiki links and markdown stay searchable without opening every note.
> > > 
> > > For unrelated folders mount each path with the same tool and apply a short name to it (an alias) then you can unmount any or list what you have indexed. Results return JSON, which AI likes, so it is meant for an agent to use. Search runs across every mounted source so notes and code show up together and AI decides matching context based on the question asked.
> > > 
> > > When files change, every new query can do a re-index which takes a few seconds.
> > > 
> > > Honestly, if you point your Claude or CODEX to it it'll instantly know how to deploy it and you can ask it to suggest custom /commands to call the tool.
> 
> > **Thin\_Beat\_9072** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2nrylj/) · 2 points
> > 
> > it's not gonna be hard at all to upload markdown content and frontmatter data into a db for rag. OP wanted it to be easy so people can get started right now and can move to better infra when needed imo.

> **codefame** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2optrz/) · 2 points
> 
> This is all awesome. I started with the same setup but moved to CC -> Mem via webhook on Stop command. Very simple to set up and their RAG implementation has been solid.

> **bstric15** · [2026-01-31](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2usifi/) · 2 points
> 
> Thanks for posting this, I've been thinking about a similar system!
> 
> How do you manage the file system? Mainly the overall valut Vs each project specific context? Mainly, I would work with Claude in many different projects, but want to somehow automatically include their learnings into the central valut. Do you have an automation script, hooks etc that write automatically into the central Vault or does Claude do it for you? If Claude, wouldn't that I crease the token usage?
> 
> > **Conscious-Drawer-364** · [2026-01-31](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2vl5so/) · 3 points
> > 
> > Thank you for checking it out! Here's how I actually handle it.
> > 
> > Each project gets its own [CLAUDE.md](http://claude.md/) on Desktop (Desktop/Projects/Project-Alpha/CLAUDE.md). That's the working memory Claude loads with /resume when I'm in that folder.
> > 
> > The Vault is where everything gets archived. When I run /compress at end of day, Claude writes the session log directly to the Vault (Vault/CC-Session-Logs/). Same with meeting notes, decisions, etc Claude writes them straight to the Vault so there's no manual syncing. Claude just writes to both places depending on the command. [CLAUDE.md](http://claude.md/) stays local to the project. Everything else goes to the searchable archive.
> > 
> > Token usage, yeah, it adds a bit when Claude reads [CLAUDE.md](http://claude.md/) at session start, but we're talking maybe 1k tokens max for a well-maintained project memory file. The time saved not having to explaining context again pays for itself in one session.
> > 
> > The automation is just the skills (/compress, /preserve, /resume). No separate scripts needed the MCP plugin lets Claude write files, so the skills handle the routing. Hope it helps :)
> > 
> > > **bstric15** · [2026-01-31](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2voksn/) · 2 points
> > > 
> > > Ah, that's a good idea. So you have skills (commands) that instruct Claude to write to central repo And what about beyond session logs? For example, I want to use it in learning projects, and then "send over" concepts covered and docs over to the central repo and make the connections. Would you put the connection instructions in your commands inside projects, r have an archiver agent in the central valut?
> > > 
> > > > **Conscious-Drawer-364** · [2026-02-01](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2vrudw/) · 3 points
> > > > 
> > > > For concepts and learnings that cross projects, I use frontmatter + a /preserve skill.
> > > > 
> > > > So when you're working and Claude creates a note about say "how React Server Components work" you tag it with frontmatter (type: concept, topic: react, project: Project-Alpha). That note lives in the Vault.
> > > > 
> > > > Then your central "React" page has a Dataview query that auto-surfaces anything tagged topic: react. The connection happens automatically and you don't need to route it manually.
> > > > 
> > > > The /preserve skill is what updates your permanent memory files (CLAUDE.md or domain-specific pages in the Vault). I use it for "this decision/pattern matters beyond this session" stuff.
> > > > 
> > > > You could also build a dedicated /archive skill that takes the current session's learnings and writes them to topic-specific files in the Vault. I haven't needed that yet because frontmatter + queries handle most of it, but if you're doing heavy learning across projects that might be worth it.
> > > > 
> > > > The beauty is the skills are just markdown files so you can customise them however your brain works, some people probably do want an "archiver agent" setup. I lean on metadata doing the work for me.
> > > > 
> > > > > **bstric15** · [2026-02-01](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2vsctl/) · 2 points
> > > > > 
> > > > > That makes sense! Do you have a git repo by any chance with these skills?
> > > > > 
> > > > > > **Conscious-Drawer-364** · [2026-02-02](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o35ni5t/) · 3 points
> > > > > > 
> > > > > > Sorry for late reply mate. No I haven't set one up yet but I'll do! Currently the skills are hard-coded to y config / structure hence why they're not out there yet but I'll make sure to make them available and will make a post when I do 👍

> **Fresh-Minimum3516** · [2026-02-06](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o3xl4fk/) · 2 points
> 
> Did I miss the custom skills and commands implementation?
> 
> > **Conscious-Drawer-364** · [2026-02-07](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o4253tw/) · 2 points
> > 
> > Nope you didn’t , working on it 👍

> **aimericg** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2l0iam/) · 2 points
> 
> Thanks for sharing these skills, I needed that!
> 
> > **Conscious-Drawer-364** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2l3rtx/) · 1 points
> > 
> > Thank you for checking it out

> **TeeRKee** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2l23ys/) · 2 points
> 
> Very cool.

> **Thin\_Beat\_9072** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2nr6bu/) · 1 points
> 
> do you use the graph feature? I have a research content generation knowledge base and the time lapse of it looks very cool. there's over 50k tag linked! had to upload and share timelapse lol. Do you plan on building any service or apps around this? it definitely works at scale [https://www.youtube.com/watch?v=gqyg1E6Lviw](https://www.youtube.com/watch?v=gqyg1E6Lviw)

> **seraph-70** · [2026-01-31](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2tbnpm/) · 1 points
> 
> is there a reason you decided to use an MCP or plugin I can't tell instead of just opening claude in the vault directory?

> **Timo425** · [2026-01-31](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2v634z/) · 1 points
> 
> I already use obsidian to hold a lot of context that i use with ai agents, i even have files like [CLAUDE.md](http://claude.md/) symlinked from obsidian to the folder where its supposed to be so that i can access it from other devices as well. but im not reading all that, sorry OP.

> **stubble** · [2026-03-10](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o9qgw6b/) · 1 points
> 
> You could have included the only bit that's important to get it all to work..
> 
> What should be put in the Claude desktop JSON file?
> 
> It just says 'tell it about the API key.
> 
> ¯⁠\\⁠(⁠°⁠\_⁠o⁠)⁠/⁠¯

> **0bjective-Guest** · [2026-03-17](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/oazemvs/) · 1 points
> 
> guys, maybe a stupid question but how is the privacy when doing such a thing? I understand that obsidian runs locally and is end-to-end encrypted but the moment claude joins the chat, how much does anthropic know about your personal projects/life and so on?

> **queue\_tip\_** · [2026-03-24](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/oc5gz0v/) · 1 points
> 
> How are you using the different types in the frontmatter?

> **HauntingAnteater9034** · [2026-03-27](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/ocs8p85/) · 1 points
> 
> I am now trying to use obsidan and claude code, what a supper experience

> **Global\_Lifeguard\_708** · [2026-03-31](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/odkc5zi/) · 1 points
> 
> where is the [CLAUDE.md](http://claude.md/) file ?

> **lsrFredgrub** · [2026-04-10](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/ofcdwuq/) · 1 points
> 
> How did you create the videos? They look so smooth !
> 
> > **Conscious-Drawer-364** · [2026-04-10](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/ofgq8oj/) · 1 points
> > 
> > Thank you! I used Claude code and Remotion [https://www.remotion.dev/docs/ai/claude-code](https://www.remotion.dev/docs/ai/claude-code)

> **zamufn** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2l043c/) · 1 points
> 
> Great post. Thanks!

> **soober** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2m5dsw/) · 1 points
> 
> Is it possible to adopt to Gemini ?
> 
> > **Conscious-Drawer-364** · [2026-01-30](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/o2nhjb3/) · 2 points
> > 
> > I think it’d need to be fine tuned for Gemini but try to feed it the article and see what it says 👍

> **dror88** · [2026-04-12](https://reddit.com/r/ClaudeAI/comments/1qr19df/comment/ofuhxj5/) · 1 points
> 
> How do you create these short videos?