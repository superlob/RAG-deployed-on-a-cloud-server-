# Module: Chatting Interface

## 1. Features

* Build a unified chat interface using React, Vite, Tailwind CSS, and shadcn/ui.
* Use the CloseAI API proxy with the gpt-6-luna model through direct SDK calls. Do not use LangChain or LangGraph.
* Use LLM Tool Calling to decide whether to invoke Retrieval. No manual Chat/RAG mode selector.
* Stream responses via SSE.
* Store conversations and messages in PostgreSQL.
* Display retrieved document sources when available.

## 2. Context Management

* Include system instructions, the most recent 10 completed conversation turns, and the current user message.
* Each turn consists of one user message and its corresponding assistant response.
* Keep complete conversation history in PostgreSQL.
* If the token budget is exceeded, remove the oldest complete turns first whenever possible. Preserve the current user message.
* Include tool calls and tool results in the context when required.

## 3. Retrieval Integration

* Let the LLM decide whether to invoke Retrieval based on the user's message and conversation history.
* Call the Retrieval module through its defined interface. Do not implement retrieval logic in this module.
* Use a mock Retrieval tool for testing. Actual integration will be completed in the Retrieval module.

## 4. Database and Security

* Inspect the existing schema before making database changes.
* Apply PostgreSQL RLS to all user-owned data tables.
* Users must only access their own conversations, messages.
* Use parameterized SQL and validate conversation ownership.

## 5. Validation

Test conversation management, history trimming, SSE streaming, tool calling, Retrieval integration, error handling, and user-data isolation. Distinguish mocked tests from live integration tests.



