# File Upload System

Flexible file upload system with S3 and local storage support.

## Features

- Upload files via multipart form data
- Auto file type detection (image, document, video, audio)
- Image dimension extraction
- 10MB max file size
- UUID-based naming to prevent conflicts
- AWS S3 or local filesystem storage
- Generic attachment to any model (comments, exercises, etc)

## Storage Configuration

### Local Storage (Development)

Default. Files stored in `media/` directory.

### AWS S3 (Production)

Set environment variables in `.env`:

```bash
AWS_STORAGE_ENABLED=true
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_STORAGE_BUCKET_NAME=your_bucket_name
AWS_S3_REGION_NAME=eu-west-1
AWS_S3_CUSTOM_DOMAIN=cdn.example.com  # Optional CloudFront
```

## API Endpoints

### Upload File
```
POST /api/files/upload/
Content-Type: multipart/form-data

file: <file>
content_type: comment  # Optional
object_id: 123  # Optional
```

### List Files
```
GET /api/files/
GET /api/files/?content_type=comment&object_id=123
```

### Get File
```
GET /api/files/{id}/
```

### Delete File
```
DELETE /api/files/{id}/
```

## Usage with Comments

Frontend example:
```typescript
// Upload file
const response = await fileAPI.upload(file);

// Add comment with attachment
await api.post(`/exercises/${id}/comment/`, {
  content: 'Check this image',
  file_ids: [response.id]
});
```

Backend handles attaching files to comments automatically.

## Supported File Types

- Images: jpg, jpeg, png, gif, webp, svg
- Documents: pdf, doc, docx, txt, md
- Videos: mp4, webm, avi, mov
- Audio: mp3, wav, ogg
- Archives: zip, tar, gz

## File Validation

- Max size: 10MB
- Allowed MIME types validated
- Invalid files rejected with 400 error

## Models

### FileAttachment
- `id`: UUID primary key
- `file`: File field
- `file_name`: Original filename
- `file_size`: Size in bytes
- `file_type`: Auto-detected type
- `mime_type`: MIME type
- `uploaded_by`: User FK
- `uploaded_at`: Timestamp
- `width/height`: For images only
- Generic FK for attachment to any model

## Security

- Authentication required for uploads
- File size limits enforced
- MIME type validation
- UUID filenames prevent overwrites
- S3 uses AWS_DEFAULT_ACL=None (private by default)
