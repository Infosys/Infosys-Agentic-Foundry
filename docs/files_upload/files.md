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

---


## Cloud Storage Integration (Blob Storage)

- When IAF is deployed on a hyperscaler, files uploaded are stored in a pod's local filesystem. Kubernetes has a pod-based architecture, so when multiple pods (instances of deployment) exist, a file uploaded in one pod is not visible to others. Additionally, if a pod crashes or restarts, the file is lost.

- To address this situation, an `object storage approach` is used where uploaded files are stored in a central cloud storage associated with that hyperscaler. This ensures that files are accessible across all pods and persist even if pods restart.

- For `Azure`, files are stored in `Blob Storage` inside a container.

**Configuration**

In the `.env` file, set the `STORAGE_PROVIDER` variable to specify the hyperscaler:

```bash
STORAGE_PROVIDER=azure   # Currently only 'azure' is supported
```

!!! danger "Provider Support"
    Currently, only `Azure` is supported. AWS and GCP are not supported at this time.

**Implementation Details**

The cloud storage integration is implemented using a `actory module-based approac`:

- A `storage` folder is created inside the `src` directory in the project
- A base class contains abstract methods for all file access operations
- Each hyperscaler has its own file where these methods are overridden accordingly
- Users can modify, remove, or add more methods according to their needs

**Setup for Azure Blob Storage**

To use Azure Blob Storage, you need to create and store two secrets in the Vault:

**1. AZURE_CONNECTION_STRING**  

   - Authentication credential for Azure
   - Secret and confidential access key
   - Obtained from Azure subscription settings

**2. AZURE_CONTAINER_NAME**  

   - The container where files will be stored (similar to a directory)
   - Can be stored in Vault or kept in the `.env` file

**Usage**

When a user uploads a file and `STORAGE_PROVIDER` is set (e.g., `azure`), the file is automatically uploaded to the specified cloud storage container.

**Verifying Files in Azure Portal:**

- Navigate to the Azure Portal
- Go to `Data Storage` section
- Click on `Containers`
- Select your container name
- All uploaded files will be visible there

!!! Info
    This approach ensures file persistence, cross-pod accessibility, and eliminates the risk of data loss due to pod failures.

---