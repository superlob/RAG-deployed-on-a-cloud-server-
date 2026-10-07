# CLAUDE.md

## Module: Chunking and Embedding

Implement document preprocessing, chunking, and embedding functionality based on the documents uploaded in Module 2.

### Features

- Process documents uploaded in Module 2 before chunking.
- Extract usable text content from PDF and Word documents.
- Remove or ignore images and other unsupported or difficult-to-process content.
- Use a Document-aware + Recursive/Sentence chunking strategy.
- Generate embeddings for document chunks using the embedding model provided by the user.
- Store embeddings together with the corresponding document and chunk metadata.
- Provide frontend controls for users to select and trigger embedding for their uploaded documents.
- Display the embedding status of each document.
- When a document is deleted, delete all corresponding chunks and embedding vectors as well.

### Chunking Strategy

Use a two-stage chunking strategy:

1. Document-aware preprocessing
   - Identify document structure such as titles, headings, sections, and paragraphs.
   - Keep section information as metadata whenever possible.
   - Do not include images or unsupported complex content in the processed text.

2. Recursive/Sentence chunking
   - Split the text within each document section.
   - Prefer sentence or paragraph boundaries.
   - Use recursive splitting when a section or text block exceeds the configured chunk size.
   - Avoid cutting sentences or meaningful text fragments unnecessarily.
   - Support configurable chunk size and overlap.

Each chunk should retain sufficient metadata to trace it back to the original document and its position in the document.

### Embedding

- Use the embedding model provided by the user.
- Generate one embedding vector for each document chunk.
- Store the embedding vector together with the document ID, chunk ID, chunk content, and relevant metadata.
- The embedding implementation should be replaceable so that the embedding model can be changed later without redesigning the entire module.

### Frontend Requirements

- Provide a document management interface showing:
  - Filename
  - File type
  - Upload time
  - Processing/embedding status
- Allow users to select a document and trigger embedding.
- Clearly indicate whether a document is:
  - Not processed
  - Processing
  - Embedded
  - Failed
- Provide appropriate feedback during embedding and when errors occur.
- Users should only be able to operate on their own documents.

### Backend Requirements

- Backend handles document preprocessing, chunking, embedding generation, and vector storage.
- Documents and their chunks must remain associated with the uploading user.
- Enforce user data isolation according to the project's Row-Level Security (RLS) requirements.
- Deleting a document must also delete all associated chunks and embedding vectors.
- Avoid leaving orphaned chunks or vectors after document deletion.
- Use the existing database and vector-storage architecture defined by the project.
- Do not implement RAG retrieval or LLM answer generation in this module.

### Validation

- Test PDF preprocessing.
- Test Word document preprocessing.
- Verify that images and unsupported content are excluded from the processed text.
- Verify that document structure and section metadata are preserved where possible.
- Test Document-aware + Recursive/Sentence chunking.
- Verify chunk size and overlap behavior.
- Test embedding generation using the user-provided embedding model.
- Verify that embeddings are correctly stored and associated with the corresponding document and chunk.
- Test frontend embedding controls and status display.
- Test document deletion and verify that all associated chunks and embeddings are deleted.
- Verify that one user cannot access or modify another user's documents, chunks, or embeddings.