import os
import asyncio
import asyncpg
import numpy as np
from typing import List, Dict, Any
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from src.utils.postgres_vector_store_jsonb import PostgresVectorStoreJSONB
from src.utils.remote_model_client import get_remote_models
from src.storage import get_storage_client
from telemetry_wrapper import logger as log
from dotenv import load_dotenv
from src.utils.secrets_handler import current_user_email

load_dotenv()

DOWNLOAD_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'downloaded_kbs'))
STORAGE_PROVIDER = os.getenv("STORAGE_PROVIDER")

async def get_db_pool() -> asyncpg.Pool:
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'port': int(os.getenv('POSTGRESQL_PORT', '5432')),
        'database': os.getenv('DATABASE', 'agentic_workflow_as_service_database'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', 'postgres'),
        'min_size': 1,
        'max_size': 10
    }
    
    try:
        pool = await asyncpg.create_pool(**db_config)
        log.info("Database pool created successfully for knowledge base operations")
        return pool
    except Exception as e:
        log.error(f"Failed to create database pool: {e}")
        raise


async def check_kb_exists(kb_name: str, pool: asyncpg.Pool) -> tuple:
    try:
        async with pool.acquire() as conn:
            all_kbs = await conn.fetch("SELECT knowledgebase_name, knowledgebase_id FROM knowledgebase_table")
            log.info(f"DEBUG: All KBs in database: {[(r['knowledgebase_name'], r['knowledgebase_id']) for r in all_kbs]}")
            
            result = await conn.fetchrow("""
                SELECT k.knowledgebase_id, 
                       (SELECT COUNT(*) FROM vector_embeddings_jsonb v WHERE v.kb_id = k.knowledgebase_id) as chunk_count
                FROM knowledgebase_table k
                WHERE k.knowledgebase_name = $1
            """, kb_name)
            
            log.info(f"DEBUG: Query result for KB '{kb_name}': {result}")
        
        if not result:
            log.warning(f"KB '{kb_name}' not found in database")
            return None, 0
        
        kb_id = result['knowledgebase_id']
        chunk_count = result['chunk_count']
        log.info(f"KB '{kb_name}' found with ID '{kb_id}' and {chunk_count} chunks")
        
        return kb_id, chunk_count
    except Exception as e:
        log.error(f"Error checking KB '{kb_name}': {e}", exc_info=True)
        return None, 0


async def semantic_retrieval(
    query: str,
    kb_id: str,
    pool: asyncpg.Pool,
    top_k: int = 5
) -> List[Dict[str, Any]]:
    try:
        model_server = os.getenv('MODEL_SERVER_URL', 'http://localhost:5000')
        embedding_model, _ = get_remote_models(model_server)
        
        log.info(f"Generating embedding for query: {query[:50]}...")
        query_embedding = embedding_model.encode([query], convert_to_numpy=True)[0]
        
        vector_store = PostgresVectorStoreJSONB(pool=pool)
        results = await vector_store.semantic_search(
            query_embedding=query_embedding,
            kb_id=kb_id,
            top_k=top_k
        )
        
        log.info(f"Semantic search returned {len(results)} results")
        return results
        
    except Exception as e:
        log.error(f"Error during semantic search: {e}")
        return []


def download_kb_from_storage(kb_name: str):
    """
    Downloads all files for a given knowledge base from cloud storage.
    """
    if not STORAGE_PROVIDER:
        log.warning("STORAGE_PROVIDER environment variable is not set. Skipping download.")
        return

    file_paths={}

    try:
        storage_client = get_storage_client(STORAGE_PROVIDER)
        
        # Define the local directory for this specific KB
        local_kb_path = os.path.join(DOWNLOAD_BASE_DIR, kb_name)
        os.makedirs(local_kb_path, exist_ok=True)

        log.info(f"Listing files in cloud storage for KB '{kb_name}'...")
        file_keys = storage_client.list_files(prefix=f"{kb_name}/")

        if not file_keys:
            log.warning(f"No files found in cloud storage for knowledge base '{kb_name}'.")
            return

        log.info(f"Found {len(file_keys)} files. Starting download to '{local_kb_path}'...")

        for file_key in file_keys:
            # Prevent downloading "directory" markers if the provider returns them
            if file_key.endswith('/'):
                continue
            
            local_file_path = os.path.join(local_kb_path, os.path.basename(file_key))
            
            # Download the file
            try:
                downloader = storage_client.download_file(file_key)
                with open(local_file_path, 'wb') as f:
                    f.write(downloader.readall())
                log.info(f"Successfully downloaded '{file_key}' to '{local_file_path}'")
                file_paths[file_key] = local_file_path
            except Exception as e:
                log.error(f"Error downloading '{file_key}': {e}", exc_info=True)

        return file_paths
    except Exception as e:
        log.error(f"Failed to download knowledge base '{kb_name}' from storage: {e}", exc_info=True)
        # We can choose to raise or just log the error. For now, we log and continue.
        # This allows the retriever to still try and use the DB even if download fails.




# Define the download directory outside the src folder
# This resolves to the root of the 'Infyagentframework' project


#kb_list=['namankb']






@tool
def knowledgebase_retriever(query: str, knowledgebase_names: list) -> str:
    """This tool retrieves information from specified knowledge bases to answer the query."""
    log.info(f"Knowledgebase retriever called with query: {query[:50]}... for KBs: {knowledgebase_names}")
    
    try:
        llm = AzureChatOpenAI(
            azure_endpoint=os.getenv('AZURE_ENDPOINT'),
            azure_deployment='gpt-4o',
            api_version=os.getenv('OPENAI_API_VERSION'),
            temperature=0,
            api_key=os.getenv('AZURE_OPENAI_API_KEY')
        )
    except Exception as e:
        log.error(f"Failed to initialize LLM: {e}")
        return f"Error: Failed to initialize LLM - {str(e)}"
    
    if isinstance(knowledgebase_names, str):
        kb_list = [knowledgebase_names]
    else:
        kb_list = knowledgebase_names
    
    async def _async_retrieval():
        pool = None
        try:
            pool = await get_db_pool()
            results = {}
            
            for kb_name in kb_list:
                try:
                    kb_id, chunk_count = await check_kb_exists(kb_name, pool)
                    
                    if not kb_id or chunk_count == 0:
                        results[kb_name] = f"Knowledge base '{kb_name}' not found or is empty."
                        log.warning(f"KB '{kb_name}' not found or empty (chunks: {chunk_count})")
                        continue
                    
                    search_results = await semantic_retrieval(
                        query=query,
                        kb_id=kb_id,
                        pool=pool,
                        top_k=5
                    )
                    
                    if not search_results:
                        results[kb_name] = f"No relevant information found in '{kb_name}' for your query."
                        continue
                    
                    context_parts = []
                    for i, doc in enumerate(search_results):
                        metadata = doc.get('metadata', {})
                        file_name = metadata.get('file', 'unknown')
                        page_number = metadata.get('page_number', 'N/A')
                        chunk_text = doc['text']
                        
                        context_parts.append(
                            f"Chunk {i+1} (File: {file_name}, Page: {page_number}):\n{chunk_text}"
                        )
                    
                    context = "\n\n".join(context_parts)
                    
                    prompt = f"""Based on the following information from the knowledge base, answer the query comprehensively.

Query: {query}

Retrieved Information:
{context}

Answer (provide a detailed response based on the information above):"""
                    
                    response = llm.invoke(prompt)
                    results[kb_name] = response.content
                    log.info(f"Successfully generated answer for KB '{kb_name}'")
                    
                except Exception as kb_error:
                    log.error(f"Error processing KB '{kb_name}': {kb_error}")
                    results[kb_name] = f"Error processing '{kb_name}': {str(kb_error)}"
            
            return results
            
        except Exception as e:
            log.error(f"Error in async retrieval: {e}")
            return {"error": f"Failed to retrieve information: {str(e)}"}
        
        finally:
            if pool:
                await pool.close()
                log.info("Database pool closed")
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    results = loop.run_until_complete(_async_retrieval())
    
    if len(results) == 1:
        # Single KB - return the result directly
        return list(results.values())[0]
    else:
        # Multiple KBs - format with headers
        formatted_output = []
        for kb_name, result in results.items():
            formatted_output.append(f"=== Results from '{kb_name}' ===\n{result}")


        #downloading KB's present inside list
        for kb_name in kb_list:
            download_kb_from_storage(kb_name)

        return "\n\n".join(formatted_output)
