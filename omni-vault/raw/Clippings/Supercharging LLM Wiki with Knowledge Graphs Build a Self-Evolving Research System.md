---
title: "Supercharging LLM Wiki with Knowledge Graphs: Build a Self-Evolving Research System"
source: "https://support.noduslabs.com/hc/en-us/articles/26724863249180-Supercharging-LLM-Wiki-with-Knowledge-Graphs-Build-a-Self-Evolving-Research-System"
author:
  - "[[combining LLM Wiki with knowledge graphs]]"
  - "[[you:]]"
published: 2026-04-11
created: 2026-04-12
description: "Last week, Andrej Karpathy introduced a powerful concept called LLM Wiki — a framework designed to turn your notes, papers, and data into..."
tags:
  - "clippings"
---
Last week, Andrej Karpathy introduced a powerful concept called [**LLM Wiki**](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — a framework designed to turn your notes, papers, and data into a structured, queryable knowledge base. It’s a big step forward for AI-assisted research.

But there’s a catch: while LLM Wiki organizes your knowledge beautifully, it still lacks something crucial: **self-awareness and evolution**. Every time you query it, it behaves like a stateless assistant — retrieving information, generating responses, and then forgetting everything again.

In this guide, we’ll explore how to fix that by integrating **knowledge graphs and network analysis** that will enable us to analyze the structure of our knowledge based and retrieve the key concepts and clusters of ideas from it. Based on these insights, we can then reveal the content gaps and blind spots that we can use to generate new ideas that will make our knowledge more coherent and interconnected, helping us see how to develop the research further. This approach turns LLM Wiki into a dynamic, evolving research system that actually helps you generate new ideas—not just recycle old ones.

## Video Tutorial: Fix Karpathy's LLM Wiki with Knowledge Graphs

![](https://www.youtube.com/watch?v=yYSTsKo8moU)

You can watch the video above for a quick demo and tutorial to set up the LLM wiki on your own computer.

The tools used are:

- [LLM Wiki skill](https://github.com/infranodus/skills/blob/master/skill-llm-wiki/SKILL.md) (will set up the framework for you based on Karpathy's specification but with additional knowledge graph memory capability)
- [InfraNodus VSCode Extension](https://infranodus.com/vscode-extension) (can be used in Cursor or Antigravity to reveal the main topics and gaps in your pages or folders)
- [InfraNodus Obsidian Graph view plugin](https://infranodus.com/obsidian-plugin) (can be used to visualize connections between the pages and to find gaps in your knowledge inside Obsidian)
- [InfraNodus MCP server](https://infranodus.com/mcp) (can be used to add knowledge graph capability to LLM Wiki workflow)

Below we explain how this process works step by step.

## The Core Problem: Static Intelligence

Traditional LLM workflows rely on **retrieval-augmented generation (RAG)**. You upload documents, the model pulls relevant chunks, and generates answers.

Sounds great—but here’s the limitation:

- No memory of past interactions
- No evolving knowledge base
- No awareness of conceptual structure

As Karpathy pointed out, you don’t get a system that **learns with you over time**. You will have to cold-start every time and if you go into your existing chat, as the conversation becomes longer and longer, your context window will be less and less relevant, so you'll get generic results.

## Karpathy’s Solution: LLM Wiki

LLM Wiki improves this by structuring your knowledge into:

- A **raw folder** (papers, notes, data)
- A **wiki layer** (concepts, summaries, connections)
- An **output** folder (where ideas get generated)
- Interlinked pages representing ideas and relationships using \[\[wikilinks\]\] so they are compatible with Obsidian.

This gives you:

- Organized knowledge
- Better navigation
- Context-aware querying

Here's how it looks:

![llm-wiki-structure.png](https://support.noduslabs.com/hc/article_attachments/26725259137692)

### How Does LLM Wiki Work?

LLM Wiki operates through the following process:

1. Ingest raw data, files, notes, into the `raw` / folder in the project
2. Run a series of prompts that extracts the main concepts, relations, sources, and data from them and saves them as separate pages (so we can build \[\[wikilinks\]\] between them) into the `wiki` folder
3. Prompt the user to generate some ideas based on the `wiki` folder and then save these ideas into the `output` folder.
4. Every time there's new raw input data arriving, update the wiki and the output folder so you always have the most up-to-date version of the project.

But even with this structure, there’s still a limitation — your LLM doesn't have a holistic view of the content. Yes, it can scan through the concepts and relations but it won't have a good understsanding of the clusters they form, the concepts that are more central, the existing blind spots and content gaps. This is where knowledge graphs and network analysis can help.

## Enter Knowledge Graphs: Making Your AI Think Structurally

Using tools like [InfraNodus](https://infranodus.com/), you can transform your wiki into a **network of ideas**.

Instead of linear text, you get:

- Nodes = concepts (or pages / \[\[wikilinks\]\]
- Edges = relationships
- Clusters = thematic areas

Because we represent ideas as a network, we can use **graph science metrics** to identify the main concepts and clusters in our knowledge base structure, reveal the gaps between them, and identify how the structure of knowledge can be optimized to make it more connected and coherent.

Note that it's very different from asking your LLM to do that because we are using a reliable [peer-reviewed text network analysis algorithm](https://dl.acm.org/doi/10.1145/3308558.3314123) that is widely applied in network science to optimize interconnected structures. The results are consistent and offer a much higher degree of observability.

The three main capabilities are:  

### 1\. Identify Key Topics Instantly

You can visually see:

- Dominant themes
- Underdeveloped areas
- Emerging patterns
![llm-wiki-knowledge-graph.png](https://support.noduslabs.com/hc/article_attachments/26725242424348)

### 2\. Discover “Knowledge Gaps”

The real magic lies here.

Knowledge graphs reveal:

- **Disconnected clusters**
- **Unexplored relationships**
- **Opportunities for innovation**

These gaps are where **new ideas are born**.

![llm-wiki-content-gaps.png](https://support.noduslabs.com/hc/article_attachments/26725259138460)

### 3\. Steer LLM's Reasoning Across the Ontology Graph

The modified version of the LLM Wiki framework also builds ontology graphs for concepts, relations, and main ideas. This ontology is then used by the model to have the most up-to-date snapshot of the main relations between the concepts in your research project. Advanced network analysis and gap detection algorithms from InfraNodus MCP server can be used to optimize this knowledge base and ontology further and to guide LLMs across your project's data.

## How Knowledge Graphs Improve LLM Wiki

When we add knowledge graphs into the LLM Wiki, we add several new elements into the workflow. They are also reflected in the updated LLM Wiki skill that we published in our GitHub repo at [https://github.com/infranodus/skills/blob/master/skill-llm-wiki/SKILL.md](https://github.com/infranodus/skills/blob/master/skill-llm-wiki/SKILL.md)

Specifically, you get:

- with the [InfraNodus MCP server](https://infranodus.com/mcp) connected to your LLM, you get access to real-time network analysis of the connections in your wiki to identify central concepts, clusters that should be better developed, blind spots, and interesting topics to explore
- the additional `infranodus` folder that stores general ontologies for each folder in your wiki, which act as a living memory that is always accessible to your system. Our LLM Wiki skill will update and rewrite these graphs as the new knowledge arrives, and you can analyze them any time using the InfraNodus [MCP server or the InfraNodus VSCode / Cursor extension](https://infranodus.com/vscode-extension) or the InfraNodus [Obsidian graph view plugin.](https://infranodus.com/obsidian-plugin)

Here's a recommended workflow you can use with the full setup:

### Step 1: Build Your Wiki

- Ingest papers, notes, and data
- Generate structured summaries
- Extract concepts and connections

### Step 2: Visualize the Knowledge

Using InfraNodus:

- Map all concepts into a graph
- Identify clusters (e.g., finance, regression analysis, market flows)
- Spot weak or missing connections

### Step 3: Run Gap Analysis

The system finds:

- Topics that exist but aren’t linked
- Conceptual “blind spots”

### Step 4: Guide the LLM with Structure

Instead of asking generic questions, you:

- Feed the **graph structure** into the LLM
- Highlight specific gaps
- Ask it to connect them

This transforms the output from:

> Generic summaries → **Targeted, original insights**

## Example: From Gap to Insight

Let’s say your graph shows a gap between:

- Financial flows
- Regression analysis

Instead of asking:

> “Explain financial systems”

You ask:

> “How can regression analysis model financial flow dynamics?”

Now the LLM:

- Focuses on a specific conceptual bridge
- Generates a novel research direction
- Produces actionable insight

## Building a “Living Memory” System

One of the most powerful upgrades is integrating graphs **directly into your wiki**.

With this setup:

- Every interaction updates the graph
- New ideas are stored as relationships
- The system evolves over time

You essentially create:

> A **self-improving knowledge engine**

This solves the original problem:  
\- No more stateless interactions  
\- Continuous learning  
\- Structured reasoning

## Automating the Workflow

The system can be fully automated:

1. **Ingest sources** (papers, notes, Dropbox, etc.)
2. **Convert to structured markdown**
3. **Extract concepts and relationships**
4. **Generate knowledge graphs**
5. **Run gap analysis**
6. **Create research questions + ideas**
7. **Store insights in a to-do system**

This mirrors a similar workflow used in competitor research systems, where identifying **content gaps** leads to new strategies and ideas.

## Visual vs. Programmatic Interaction

You have two ways to use the system:

### Visual Mode (Obsidian / IDE plugins)

- Explore graphs interactively
- Click nodes and clusters
- Generate insights visually

### Programmatic Mode (MCP + LLM)

- Let the AI run graph analysis
- Generate insights automatically
- No manual visualization required

Both approaches work—but understanding the structure gives you **far more control**.

## Why This Matters

By combining LLM Wiki with knowledge graphs, you:

- Move from **information retrieval → insight generation**
- Guide AI with **structure, not just prompts**
- Create a system that **thinks with you over time**

This is a shift from asking AI questions about your data to collaborating with an evolving intelligence system.

## Final Thoughts

LLM Wiki is a powerful foundation. But on its own, it’s still limited by the nature of LLMs.

Adding knowledge graphs transforms it into something far more interesting:

> A **self-aware research system** that not only stores knowledge—but actively helps you expand it.

If you work with research, content, or complex ideas, this approach can dramatically improve how you:

- Generate insights
- Discover opportunities
- Build original thinking

Try it using the tools below and let us know your experience:

- [LLM Wiki skill](https://github.com/infranodus/skills/blob/master/skill-llm-wiki/SKILL.md) (will set up the framework for you based on Karpathy's specification but with additional knowledge graph memory capability)
- [InfraNodus VSCode Extension](https://infranodus.com/vscode-extension) (can be used in Cursor or Antigravity to reveal the main topics and gaps in your pages or folders)
- [InfraNodus Obsidian Graph view plugin](https://infranodus.com/obsidian-plugin) (can be used to visualize connections between the pages and to find gaps in your knowledge inside Obsidian)
- [InfraNodus MCP server](https://infranodus.com/mcp) (can be used to add knowledge graph capability to LLM Wiki workflow)