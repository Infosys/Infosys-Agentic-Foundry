# Files

This section is used to upload different types of files that may be required by the tools to perform its operation. This may include files such as Database Files (.db), Excel Sheets (.xlsx), Word Documents (.docx), PDF Files (.pdf) and any other files required by your agent.

**Supported database files include SQLite (.db, .sqlite) and PostgreSQL dump files (.sql).**

## Uploading Files

The file upload functionality provides a convenient way to make your data and documents available to the system:

- **Upload Methods**: You can upload your files either by clicking the "Browse" button to select files from your computer or by using the drag and drop feature directly into the "Upload" window.
- **File Storage**: After uploading, all files will be automatically saved in the `user_uploads` directory within the system.
- **File Access**: To access any uploaded file through any tool or agent, use the standardized path format: `user_uploads/filename.extension`.

!!! info
    Both single and multiple file uploads are supported.

### Upload Guidelines

- Ensure files are in supported formats for optimal compatibility
- File names should be descriptive and avoid special characters
- Large files may take longer to upload depending on your connection speed
- The system will validate file types before completing the upload

## Viewing, Downloading and Deleting Files

The file management interface provides comprehensive control over your uploaded content:

- **View Files**: Click the "View" button to see a list of all uploaded files with their details including file name, size, and upload date
- **Download Files**: Use the "Download" button to retrieve a copy of any uploaded file to your local machine
- **Delete Files**: Remove unwanted files by clicking the "Delete" button - this action will permanently remove the file from the system