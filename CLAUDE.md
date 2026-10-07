# CLAUDE.md

RAG app with chat (default) and document ingestion interfaces.

## Stack
- Frontend: React + Vite + Tailwind + shadcn/ui
- Backend: Python + FastAPI
- Database: PostgreSQL on a cloud server + pgvector
- LLM: Models provided by Alibaba Cloud Bailian
- Observability: LangSmith

## Rules
-Store environment variables such as API keys and host IPs in rag.env. When these values are required, ask the user to provide them; never guess, hardcode, or fabricate them.
-Use uv for project and dependency management; install and manage all Python dependencies with uv

## Planning
- Save all plans to `.agent/plans/` folder
- Naming convention:Naming convention: {module-name}.md,Example: authentication.md.
- Plans should be detailed enough to execute without ambiguity
- Each task in the plan must include at least one validation test to verify it works
- Assess complexity and single-pass feasibility - can an agent realistically complete this in one go?
- Include a complexity indicator at the top of each plan:
  - ✅ **Simple** - Single-pass executable, low risk
  - ⚠️ **Medium** - May need iteration, some complexity
  - 🔴 **Complex** - Break into sub-plans before executing

## Development Flow
1. **Plan** - Identify the current module to implement.Read and follow the CLAUDE.md inside the corresponding module directory. Create a detailed plan and save it to .agent/plans/
2. **Build** - Do not assume that the entire plan must be completed in a single Build cycle.Before starting each Build cycle, read PROGRESS.md to understand the current implementation status.
3. **Validate** - Test and verify the implementation works correctly. Use browser testing where applicable via an appropriate MCP
4. **Iterate** - Fix any issues found during validation
5. **Progress** - After completing each Build cycle or task, update PROGRESS.md to accurately reflect the current implementation status.
6. **Module Completion** - When the current module is fully implemented and validated, stop the workflow. Do not automatically start planning or implementing the next module. 
