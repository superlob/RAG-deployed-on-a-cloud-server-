# CLAUDE.md

## Module: Document Ingestion

Implement the document upload and document management functionality.

### Features

- Users can upload documents through a drag-and-drop interface.
- Support PDF and Word (`.doc`, `.docx`) files.
- Store uploaded files in PostgreSQL.
- Users can view a list of their own uploaded documents.
- Users can delete their own documents.
- Users can view basic document information, such as filename, file type, file size, and upload time.

### Requirements

- Frontend provides the drag-and-drop upload interface and document management UI.
- Backend handles file upload, storage, retrieval, and deletion.
- Store document files and their metadata in PostgreSQL.
- Each document must be associated with the user who uploaded it.
- Users must only be able to view and delete their own documents.
- Follow the project's Row-Level Security (RLS) requirements.
- Use the existing PostgreSQL database configured by the project.
- Do not implement document parsing, text chunking, embedding generation, vector storage, or RAG retrieval in this module.


### Validation

- Test uploading PDF files.
- Test uploading Word files.
- Test drag-and-drop upload.
- Test displaying the user's uploaded documents.
- Test deleting a document.
- Verify that a user cannot view or delete another user's documents.
- Verify that uploaded files and their metadata are correctly stored in PostgreSQL.