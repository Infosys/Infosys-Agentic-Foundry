# Vault Management

The Vault is a secure storage system designed to manage sensitive information such as API keys, URLs, and other credentials that are required by tools within the platform. Instead of hardcoding sensitive values directly into tools, the Vault provides a secure way to store and retrieve these values using secret names.



## Overview

The Vault serves as a centralized repository for managing secrets, providing two distinct storage options:

- **Private Vault**: Personal storage accessible only to the individual user
- **Public Vault**: Shared storage accessible across the organization

## Key Features

- **Secure Storage**: Safely store API keys, URLs, and other sensitive data
- **Masked Display**: Values are displayed with masking for security
- **Easy Retrieval**: Access stored values using simple function calls
- **Access Control**: Separate private and public storage with appropriate permissions

## Vault Sections

### Private Vault

The Private Vault is designed for personal, sensitive information that should only be accessible to the individual user account.

**Characteristics:**

- Personal storage space
- Only the owner can view and access stored values
- Ideal for personal API keys, private URLs, and user-specific credentials
- Enhanced security through user-level isolation

**Use Cases:**

- Personal API keys (e.g., OpenAI API key, personal weather service key)
- Private database connection strings
- User-specific authentication tokens
- Personal service URLs

### Public Vault

The Public Vault is designed for shared information that can be accessed by all users within the organization.

**Characteristics:**

- Organization-wide accessible storage
- All users can view and access stored values
- Suitable for common endpoints, shared API keys, and public resources
- Facilitates collaboration and standardization

**Use Cases:**

- Shared API endpoints
- Common service URLs
- Organization-wide API keys
- Standard configuration values

## Creating Vault Entries

**Adding a New Secret**

1. **Select Vault Type**: Choose between Private or Public vault
2. **Enter Name**: Provide a descriptive name for your secret (e.g., `weather_api_key`, `database_url`)
3. **Enter Value**: Input the actual value (API key, URL, etc.)
4. **Save**: Store the secret in the selected vault

**Example:**

```yaml
Name: weather_api_key
Value: sk-1234567890abcdef
Type: Private
```

## In Tool Development

When developing tools that require sensitive information, use the appropriate retrieval functions instead of hardcoding values.

**Private Vault Retrieval**

Use `get_user_secrets()` to retrieve values from the private vault:

```python
# Syntax: get_user_secrets('secret_name', 'default_value')
api_key = get_user_secrets('weather_api_key', 'no_api_key_found')
database_url = get_user_secrets('personal_db_url', 'localhost:5432')
auth_token = get_user_secrets('personal_auth_token', 'default_token')
```

**Public Vault Retrieval**

Use `get_public_secrets()` to retrieve values from the public vault:

```python
# Syntax: get_public_secrets('secret_name', 'default_value')
base_url = get_public_secrets('weather_api_base_url', 'https://default-weather-api.com')
shared_endpoint = get_public_secrets('common_endpoint', 'https://api.example.com')
org_api_key = get_public_secrets('organization_api_key', 'default_key')
```

## Practical Examples

**Weather Tool Implementation**

```python
def get_weather_data(city):
    # Retrieve API key from private vault
    api_key = get_user_secrets('weather_api_key', 'no_api_key_found')
    
    # Retrieve base URL from public vault
    base_url = get_public_secrets('weather_api_base_url', 'https://api.openweathermap.org')
    
    # Use the retrieved values
    endpoint = f"{base_url}/data/2.5/weather"
    params = {
        'q': city,
        'appid': api_key,
        'units': 'metric'
    }
    
    response = requests.get(endpoint, params=params)
    return response.json()
```

**Database Connection Tool**

```python
def connect_to_database():
    # Private database credentials
    db_username = get_user_secrets('db_username', 'default_user')
    db_password = get_user_secrets('db_password', 'default_pass')
    
    # Shared database host from public vault
    db_host = get_public_secrets('shared_db_host', 'localhost')
    db_port = get_public_secrets('shared_db_port', '5432')
    
    connection_string = f"postgresql://{db_username}:{db_password}@{db_host}:{db_port}/mydb"
    return connection_string
```

## Security Features

**Masked Display**

For security purposes, stored values are displayed with masking in the user interface:

```yaml
Name: weather_api_key
Value: sk-123***********def
Type: Private
```

**Access Control**

- **Private Vault**: Only the owner can access their private secrets
- **Public Vault**: All organization members can access public secrets
- **No Cross-Access**: Users cannot access other users' private secrets

## Using Tools Created by Other Users

When you want to use a tool that was created by another user, you need to understand how the Vault system works in this scenario.

**Key Points**

- Each user has their own private vault that others cannot access
- If a tool uses private vault keys, you must create your own keys with the same names
- The tool will work for you once you provide your own values for the required keys

**Process**

1. **Identify Required Keys**: Check the tool documentation or code to see what vault keys it uses
2. **Create Your Own Keys**: Add the same key names to your vault with your own values
3. **Use the Tool**: The tool will now work with your provided values

**Example Scenario**

If another user created a weather tool that uses:

```python
api_key = get_user_secrets('weather_api_key', 'no_api_key_found')
base_url = get_public_secrets('weather_service_url', 'https://default-api.com')
```

For you to use this tool:

**Check the tool requirements**: The tool needs:

- Private key: `weather_api_key`
- Public key: `weather_service_url`

**Create your own vault entries**:

- Add `weather_api_key` to your private vault with your own API key
- If `weather_service_url` doesn't exist in public vault, request admin to add it

**Tool usage**: The tool will now use your API key and work for your account

**Important Notes**

!!! warning "Private Keys"
    You must create your own private keys with the exact same names

!!! info "Public Keys"
    These are shared across the organization, so they should already exist

!!! tip "Key Names Must Match"
    The key names in your vault must exactly match what the tool expects

!!! danger "Your Own Values"
    Use your own API keys, credentials, and URLs - never share private credentials

## Step-by-Step Guide: Using Someone Else's Tool

**Step 1: Tool Analysis**

```python
# Example: Someone shared a translation tool
def translate_text(text, target_language):
    api_key = get_user_secrets('translation_api_key', 'no_key')
    endpoint = get_public_secrets('translation_endpoint', 'default_url')
    # ... rest of the tool code
```

**Step 2: Identify Requirements**

From the code above, you need:

- **Private**: `translation_api_key` (your personal API key)
- **Public**: `translation_endpoint` (shared endpoint URL)

**Step 3: Set Up Your Vault**

1. Go to your Private Vault
2. Add new entry:
   - **Name**: `translation_api_key`
   - **Value**: `your-actual-translation-api-key-here`
3. Check if `translation_endpoint` exists in Public Vault
4. If missing, contact admin to add it

**Step 4: Test the Tool**

Run the tool to verify it works with your credentials.

## Tool Documentation Best Practices

**For Tool Creators**

Always document the required vault keys in your tool description:

```markdown
## Required Vault Keys

### Private Keys
- `weather_api_key`: Your OpenWeatherMap API key
- `personal_db_password`: Your database password

### Public Keys
- `weather_base_url`: Weather service endpoint (admin managed)
- `shared_db_host`: Database host address (admin managed)
```

**For Tool Users**

Before using any tool, check the documentation for required vault keys and ensure you have all necessary credentials.

## Common Scenarios

**Scenario 1: Using a Shared Weather Tool**

**Tool Requirements:**

- **Private**: `openweather_api_key`
- **Public**: `weather_service_endpoint`

**Your Setup:**

1. Obtain your own OpenWeatherMap API key
2. Add to Private Vault: `openweather_api_key` = `your-api-key`
3. Verify Public Vault has: `weather_service_endpoint`
4. Use the tool with your credentials

**Scenario 2: Database Analysis Tool**

**Tool Requirements:**

- **Private**: `db_username`, `db_password`
- **Public**: `analytics_db_host`, `analytics_db_port`

**Your Setup:**

1. Get database credentials from your admin
2. Add to Private Vault:
   - `db_username` = `your-db-username`
   - `db_password` = `your-db-password`
3. Check Public Vault for connection details
4. Tool connects using your credentials to shared database

**Scenario 3: AI Service Integration**

**Tool Requirements:**

- **Private**: `openai_api_key`, `anthropic_api_key`
- **Public**: `ai_service_baseurl`

**Your Setup:**

1. Get API keys from respective AI service providers
2. Add to Private Vault with exact key names
3. Tool uses your API keys with shared endpoint configuration

---

