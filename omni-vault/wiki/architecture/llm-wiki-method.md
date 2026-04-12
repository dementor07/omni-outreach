---
title: Karpathy LLM Wiki Method
category: architecture
tags: [methodology, llm, workflow, knowledge-base]
sources: [raw/llm-wiki-pattern.md]
updated: 2026-04-12
---

# Karpathy LLM Wiki Method

The "LLM Wiki" or "Karpathy Method" is a foundational paradigm used in this project's documentation via the `omni-vault`.

Instead of relying on RAG (Retrieval-Augmented Generation) where an LLM re-reads source documents from scratch on every query, this method uses the LLM to actively compile, synthesize, and maintain a highly structured markdown wiki.

## Core Philosophy

1. **Compounding Artifact**: The wiki accumulates knowledge over time. When a new source is added, the LLM reads it, updates relevant pages, notes contradictions, and maintains cross-references.
2. **Division of Labor**: 
   - **Human**: Curates sources, asks questions, explores the graph, directs analysis.
   - **LLM**: Does the "grunt work" of summarizing, filing, bookkeeping, and maintaining `[[WikiLinks]]`.
3. **IDE + Codebase Metaphor**: Obsidian acts as the IDE, the LLM is the programmer, and the markdown wiki is the codebase.

## Three-Layer Architecture

1. **`raw/`**: Curated, immutable collection of source documents (articles, papers, raw data). The source of truth.
2. **`wiki/`**: The directory of LLM-generated markdown files (summaries, entities, concepts). The LLM owns and maintains this layer.
3. **`CLAUDE.md` (Schema)**: The configuration file that instructs the LLM on wiki structure, naming conventions, and workflows. 

## Key Operations

- **Ingest**: Drop a source into `raw/`. The LLM reads it, discusses takeaways, writes summary pages, updates existing concept pages, and logs the operation.
- **Query**: Ask the LLM questions. It uses the `index.md` to find relevant pages, synthesizes answers with citations, and optionally creates new wiki pages from valuable insights.
- **Lint**: Periodically have the LLM health-check the wiki (e.g., finding contradictions, orphan pages, or stale claims).

## Special Files
- **`index.md`**: A catalog of everything in the wiki, updated on every ingest. Helps the LLM navigate without vector search overhead at moderate scales.
- **`log.md`**: A chronological, append-only record of wiki operations (ingests, queries, lints). Allows parsing of the wiki's evolution.

## Application in Omni

This entire `omni-vault` is an instantiation of the Karpathy method, actively maintained by the AI agent to persist architectural decisions like the [[sequence-engine]] and [[voice-node-architecture]], preserving knowledge across sessions.
