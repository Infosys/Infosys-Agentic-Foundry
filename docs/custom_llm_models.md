# Adding Custom LLM Models

This guide provides step-by-step instructions on how to integrate a new LLM provider into the framework. You will need to make changes in two files:

1. **`.env`** — Define your connection credentials and model names.
2. **`src/models/model_service.py`** — Register the new provider in the model service.

---

## Prerequisites

- API key (and optionally base URL, API version, or any other credentials) for the LLM provider you want to add.
- The list of model deployment names available under your provider account.
- If the provider is supported by LangChain, identify the corresponding LangChain chat model class (e.g., `ChatAnthropic`, `ChatMistralAI`, `ChatGroq`, etc.). If not, you will need a custom chat model class that inherits from LangChain's `BaseChatModel`.

---

## 1. Add Environment Variables in `.env`

Open the `.env` file at the project root and add a new section for your LLM provider. You need to define:

| Variable | Purpose | Required |
|----------|---------|----------|
| API Key | Authentication credential for the provider | Yes |
| Base URL / Endpoint | The API endpoint (if the provider requires one) | Depends on provider |
| API Version | API version string (if the provider requires one) | Depends on provider |
| Models list | Comma-separated list of model deployment names available under this provider | Yes |

**Naming Convention**

Use a consistent prefix for all keys related to your provider. 
!!! example
    if you are adding **Anthropic Claude** then use the prefix `ANTHROPIC_`:

```dotenv
# ─── Anthropic Claude Configuration ───
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx
ANTHROPIC_MODELS=claude-3-5-sonnet-20241022,claude-3-opus-20240229,claude-3-haiku-20240307
```

If your provider requires additional connection parameters (base URL, API version, region, etc.), add those as well:

```dotenv
# ─── Example: Provider with Base URL and API Version ───
MY_PROVIDER_API_KEY=your-api-key-here
MY_PROVIDER_BASE_URL=https://api.myprovider.com/v1
MY_PROVIDER_API_VERSION=2025-01-01
MY_PROVIDER_MODELS=model-a,model-b,model-c
```

**Reference: Existing Provider Configurations**

Below are the existing provider configurations in the `.env` file for reference:

```dotenv
# ─── Azure OpenAI ───
AZURE_OPENAI_API_KEY=your-azure-key
AZURE_ENDPOINT=https://your-resource.openai.azure.com/
OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_MODELS=gpt-4,gpt-4o,gpt-4o-mini

# ─── Google Generative AI ───
GOOGLE_API_KEY=your-google-key
GOOGLE_GENAI_MODELS=gemini-1.5-pro,gemini-1.5-flash

# ─── OpenAI (Direct) ───
OPENAI_API_KEY=your-openai-key
OPENAI_BASE_URL_ENDPOINT=https://api.openai.com/v1
OPENAI_MODELS=gpt-4o,gpt-4-turbo

# ─── GPT-OSS ───
GPT_OSS_BASE_URL_ENDPOINT=https://your-oss-endpoint.com
GPT_OSS_MODELS=your-oss-model
```

!!! warning "Important"
    The models key (e.g., `ANTHROPIC_MODELS`) must contain a **comma-separated list** of the exact model deployment names your provider supports. These names are what you will use when requesting a model from the framework.

---

## 2. Update the `ModelService` Constructor

Open `src/models/model_service.py` and make the following changes:

**2.1 Add the Import**

At the top of the file, import the LangChain chat model class for your provider.

**Option A — LangChain has a built-in class for your provider:**

LangChain provides built-in chat model classes for many popular providers. Install the provider's LangChain package and import it.

```python
# Example: Anthropic
from langchain_anthropic import ChatAnthropic

# Example: Mistral
from langchain_mistralai import ChatMistralAI

# Example: Groq
from langchain_groq import ChatGroq

# Example: Cohere
from langchain_cohere import ChatCohere

# Example: AWS Bedrock
from langchain_aws import ChatBedrock

# Example: NVIDIA NIM
from langchain_nvidia_ai_endpoints import ChatNVIDIA
```

!!! Note
    You will also need to install the corresponding pip package. For example:
    `pip install langchain-anthropic` or `pip install langchain-mistralai`

**Option B — You have a custom chat model class:**

If your LLM provider is not supported by LangChain natively, you can create a custom chat model class by inheriting from LangChain's `BaseChatModel`. The custom class must implement the required methods such as `_generate`, `_stream`, `bind_tools`, and define the `_llm_type` property. Once you have built your custom class, place it in an appropriate module inside the project and import it:

```python
from your_module.your_custom_chat_model import YourCustomChatModel
```

**2.2 Add Configuration Attributes in `__init__`**

Inside the `ModelService.__init__` method, add a new configuration block for your provider. Follow the existing pattern:

1. Read your environment variables using `os.getenv()`.
2. Initialize the models list as empty.
3. Only populate the models list if the required credentials are present.
4. Use the `convert_string_to_list()` helper to parse the comma-separated models string.

```python
def __init__(self, chat_state_history_manager: ChatStateHistoryManagerRepository = None):
    # ... existing code ...

    # ─── Your New Provider Configuration ───
    self.__my_provider_api_key = os.getenv("MY_PROVIDER_API_KEY", None)
    self.__my_provider_base_url = os.getenv("MY_PROVIDER_BASE_URL", None)       # if needed
    self.__my_provider_api_version = os.getenv("MY_PROVIDER_API_VERSION", None)  # if needed
    self.my_provider_models = []
    if self.__my_provider_api_key:  # add other required checks as applicable
        self.my_provider_models = self.convert_string_to_list(
            os.getenv("MY_PROVIDER_MODELS", "")
        )
```

!!! Tip
    Use `self.__` (name mangling) for sensitive values like API keys and `self.` for non-sensitive values like the models list.

**2.3 Add Your Models to `available_models`**

In the same `__init__` method, append your new models list to `self.available_models`. Find the existing line and add your list:

```python
    self.available_models = (
        self.azure_openai_models
        + self.azure_openai_gpt_5_models
        + self.google_genai_models
        + self.gpt_oss_models
        + self.openai_models
        + self.my_provider_models       # ← Add your new list here
    )
```

---

## 3. Add a Loading Block in `_load_llm_instance`

Inside the `_load_llm_instance` method, add a new `if` block that checks whether the requested `model_name` belongs to your provider's models list. If it does, validate the required credentials and return an instance of the chat model class.

Insert the new block **before** the final error-raising lines at the end of the method:

```python
async def _load_llm_instance(self, model_name: str, temperature: float = 0):
    # ... existing if blocks for Azure, Google, OpenAI, GPT-OSS ...

    # ─── Your New Provider ───
    if model_name in self.my_provider_models:
        if not self.__my_provider_api_key:
            log.error("MY_PROVIDER_API_KEY environment variable is not set.")
            raise ValueError("MY_PROVIDER_API_KEY is not set in environment variables.")

        log.info(f"Loading My Provider model: {model_name}")
        return MyProviderChatModel(
            api_key=self.__my_provider_api_key,
            # base_url=self.__my_provider_base_url,      # if needed
            # api_version=self.__my_provider_api_version, # if needed
            model=model_name,
            temperature=temperature,
        )

    # This must remain at the very end
    log.error(f"Invalid model name: {model_name}")
    raise ValueError("Invalid model name specified")
```

!!! warning "Important"
    The constructor parameters (`api_key`, `model`, `temperature`, etc.) vary across different LangChain chat model classes. Refer to the specific class documentation to use the correct parameter names.

---

## 4. Install the Required Package

If you are using a LangChain built-in provider class, install it via pip:

```bash
pip install langchain-anthropic      # for Anthropic Claude
pip install langchain-mistralai      # for Mistral AI
pip install langchain-groq           # for Groq
pip install langchain-cohere         # for Cohere
pip install langchain-aws            # for AWS Bedrock
pip install langchain-nvidia-ai-endpoints  # for NVIDIA NIM
pip install langchain-together       # for Together AI
pip install langchain-fireworks      # for Fireworks AI
```

Also add the package to `requirements.txt` so it is installed during deployment.

---

## 5. Verify the Integration

After making the above changes:

1. **Restart the application** to ensure the new environment variables are loaded.
2. Call the `/utility/get/models` API endpoint to confirm your new models appear in the available models list.
3. Test model invocation by selecting one of your new model names in an agent configuration or API call.

---

## Complete Example: Adding Anthropic Claude

Below is a full worked example showing all changes needed to add Anthropic Claude support.

!!! Example

    **`.env`**

    ```dotenv
    # ─── Anthropic Claude Configuration ───
    ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx
    ANTHROPIC_MODELS=claude-3-5-sonnet-20241022,claude-3-opus-20240229,claude-3-haiku-20240307
    ```

    **`src/models/model_service.py`**

    **Import:**

    ```python
    from langchain_anthropic import ChatAnthropic
    ```

    **Constructor (inside `__init__`):**

    ```python
    # Anthropic Claude configuration
    self.__anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", None)
    self.anthropic_models = []
    if self.__anthropic_api_key:
        self.anthropic_models = self.convert_string_to_list(
            os.getenv("ANTHROPIC_MODELS", "")
        )
    ```

    **Available models list:**

    ```python
    self.available_models = (
        self.azure_openai_models
        + self.azure_openai_gpt_5_models
        + self.google_genai_models
        + self.gpt_oss_models
        + self.openai_models
        + self.anthropic_models
    )
    ```

    **Loading block (inside `_load_llm_instance`):**

    ```python
    if model_name in self.anthropic_models:
        if not self.__anthropic_api_key:
            log.error("ANTHROPIC_API_KEY environment variable is not set.")
            raise ValueError("ANTHROPIC_API_KEY is not set in environment variables.")

        log.info(f"Loading Anthropic model: {model_name}")
        return ChatAnthropic(
            api_key=self.__anthropic_api_key,
            model=model_name,
            temperature=temperature,
            max_retries=10,
        )
    ```

---

## Using a Custom Chat Model Class

If your LLM provider does not have a LangChain integration, you can create a custom chat model class. At a high level, your custom class should:

1. **Inherit from `BaseChatModel`** (from `langchain_core.language_models.chat_models`).
2. **Implement `_generate`** — Makes the API call and returns a `ChatResult`.
3. **Implement `_stream`** (optional) — For streaming responses, yields `ChatGenerationChunk` objects.
4. **Implement `bind_tools`** (optional) — For tool/function calling support, injects tool descriptions into the system prompt and parses tool call responses.
5. **Define `_llm_type`** property — Returns a string identifier for your model type.
6. **Handle authentication** — Validate API credentials in a model validator or constructor.

Once your custom class is ready, import it in `model_service.py` and return its instance from the `_load_llm_instance` method just like any other provider.

---

## Summary of Changes

| File | What to Change |
|------|---------------|
| `.env` | Add API key, base URL (if needed), API version (if needed), and comma-separated models list using a consistent prefix |
| `src/models/model_service.py` | **Import** — Add the chat model class import |
| | **`__init__`** — Read env vars, create models list, add to `available_models` |
| | **`_load_llm_instance`** — Add an `if` block to validate credentials and return the model instance |
| `requirements.txt` | Add the pip package for the LangChain provider integration (if applicable) |

---

## Popular LangChain Provider Classes Reference

| Provider | Pip Package | Class Name | Key Env Variables |
|----------|-------------|------------|-------------------|
| Anthropic Claude | `langchain-anthropic` | `ChatAnthropic` | `ANTHROPIC_API_KEY` |
| Mistral AI | `langchain-mistralai` | `ChatMistralAI` | `MISTRAL_API_KEY` |
| Groq | `langchain-groq` | `ChatGroq` | `GROQ_API_KEY` |
| Cohere | `langchain-cohere` | `ChatCohere` | `COHERE_API_KEY` |
| AWS Bedrock | `langchain-aws` | `ChatBedrock` | `AWS_REGION`, AWS credentials |
| NVIDIA NIM | `langchain-nvidia-ai-endpoints` | `ChatNVIDIA` | `NVIDIA_API_KEY` |
| Together AI | `langchain-together` | `ChatTogether` | `TOGETHER_API_KEY` |
| Fireworks AI | `langchain-fireworks` | `ChatFireworks` | `FIREWORKS_API_KEY` |
| Ollama (Local) | `langchain-ollama` | `ChatOllama` | `OLLAMA_BASE_URL` |
| Hugging Face | `langchain-huggingface` | `ChatHuggingFace` | `HUGGINGFACEHUB_API_TOKEN` |
