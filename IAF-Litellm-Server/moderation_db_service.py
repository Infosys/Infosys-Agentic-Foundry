"""
RAI Moderation Database Service

This module handles all database operations for storing RAI moderation logs
in PostgreSQL with connection pooling and error handling.
Simple JSON storage - no complex data extraction needed.
"""

import asyncpg
import json
from typing import Optional, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager
import logging

from constants import (
    POSTGRESQL_HOST,
    POSTGRESQL_PORT,
    POSTGRESQL_USER,
    POSTGRESQL_PASSWORD,
    DATABASE,
    CURRENT_POOL_CONFIG,
    DB_CONNECTION_TIMEOUT
)

logger = logging.getLogger(__name__)


class ModerationDatabaseService:
    """Service for managing RAI moderation logs in PostgreSQL"""
    
    def __init__(self):
        """Initialize the database service"""
        self._pool: Optional[asyncpg.Pool] = None
        self._is_initialized = False
    
    async def initialize(self):
        """Initialize the database connection pool and create table if not exists"""
        if self._is_initialized:
            return
        
        try:
            self._pool = await asyncpg.create_pool(
                host=POSTGRESQL_HOST,
                port=POSTGRESQL_PORT,
                user=POSTGRESQL_USER,
                password=POSTGRESQL_PASSWORD,
                database=DATABASE,
                min_size=CURRENT_POOL_CONFIG["min_size"],
                max_size=CURRENT_POOL_CONFIG["max_size"],
                max_queries=CURRENT_POOL_CONFIG["max_queries"],
                max_inactive_connection_lifetime=CURRENT_POOL_CONFIG["max_inactive_connection_lifetime"],
                command_timeout=DB_CONNECTION_TIMEOUT
            )
            self._is_initialized = True
            logger.info(f"Database pool initialized with {CURRENT_POOL_CONFIG['min_size']}-{CURRENT_POOL_CONFIG['max_size']} connections")
            
            # Create table if not exists
            await self._create_table_if_not_exists()
            
        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise
    
    async def _create_table_if_not_exists(self):
        """Create rai_moderation_logs table if it doesn't exist"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS rai_moderation_logs (
            id SERIAL PRIMARY KEY,    
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
            check_type VARCHAR(30) NOT NULL,
            content TEXT NOT NULL,    
            overall_status VARCHAR(20) NOT NULL,
            jailbreak_status VARCHAR(20),
            jailbreak_score NUMERIC(5, 4),
            toxicity_status VARCHAR(20),
            toxicity_score NUMERIC(5, 4),
            severe_toxicity_score NUMERIC(5, 4),
            obscene_score NUMERIC(5, 4),
            threat_score NUMERIC(5, 4),
            insult_score NUMERIC(5, 4),
            identity_attack_score NUMERIC(5, 4),
            sexual_explicit_score NUMERIC(5, 4),
            profanity_status VARCHAR(20),
            profane_words_found TEXT[],
            pii_status VARCHAR(20),
            pii_entities_detected TEXT[],
            pii_entities_blocked TEXT[],
            prompt_injection_status VARCHAR(20),
            prompt_injection_score NUMERIC(5, 4),
            restricted_topic_status VARCHAR(20),
            restricted_topics_detected JSONB,
            refusal_status VARCHAR(20),
            refusal_score NUMERIC(5, 4),
            custom_theme_status VARCHAR(20),
            custom_theme_score NUMERIC(5, 4),
            full_response JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        try:
            async with self.get_connection() as conn:
                await conn.execute(create_table_sql)
                logger.info("Table rai_moderation_logs created or already exists")
        except Exception as e:
            logger.error(f"Failed to create rai_moderation_logs table: {e}")
            raise
    
    async def close(self):
        """Close the database connection pool"""
        if self._pool:
            await self._pool.close()
            self._is_initialized = False
            logger.info("Database pool closed")
    
    @asynccontextmanager
    async def get_connection(self):
        """Get a connection from the pool"""
        if not self._is_initialized:
            await self.initialize()
        
        async with self._pool.acquire() as connection:
            yield connection
    
    def _extract_moderation_data(self, moderation_result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and parse moderation data from RAI API response"""
        moderation_results = moderation_result.get('moderationResults', {})
        summary = moderation_results.get('summary', {})
        
        # Extract individual check results
        jailbreak = moderation_results.get('jailbreakCheck', {})
        toxicity = moderation_results.get('toxicityCheck', {})
        profanity = moderation_results.get('profanityCheck', {})
        restricted_topic = moderation_results.get('restrictedtopic', {})
        prompt_injection = moderation_results.get('promptInjectionCheck', {})
        privacy = moderation_results.get('privacyCheck', {})
        refusal = moderation_results.get('refusalCheck', {})
        custom_theme = moderation_results.get('customThemeCheck', {})
        
        # Extract toxicity scores from the nested structure
        toxicity_scores = {}
        if toxicity.get('toxicityScore'):
            scores_list = toxicity['toxicityScore'][0].get('toxicScore', []) if toxicity['toxicityScore'] else []
            for score_item in scores_list:
                metric_name = score_item.get('metricName', '')
                if metric_name == 'toxicity':
                    toxicity_scores['toxicity_score'] = score_item.get('metricScore')
                elif metric_name == 'severe_toxicity':
                    toxicity_scores['severe_toxicity_score'] = score_item.get('metricScore')
                elif metric_name == 'obscene':
                    toxicity_scores['obscene_score'] = score_item.get('metricScore')
                elif metric_name == 'threat':
                    toxicity_scores['threat_score'] = score_item.get('metricScore')
                elif metric_name == 'insult':
                    toxicity_scores['insult_score'] = score_item.get('metricScore')
                elif metric_name == 'identity_attack':
                    toxicity_scores['identity_attack_score'] = score_item.get('metricScore')
                elif metric_name == 'sexual_explicit':
                    toxicity_scores['sexual_explicit_score'] = score_item.get('metricScore')
        
        # Extract PII detection results
        pii_entities_detected = privacy.get('entitiesRecognised', [])
        pii_entities_blocked = privacy.get('entitiesConfiguredToBlock', [])
        
        return {
            # Overall status
            'overall_status': summary.get('status', 'UNKNOWN'),
            
            # Jailbreak
            'jailbreak_status': jailbreak.get('result'),
            'jailbreak_score': float(jailbreak.get('jailbreakSimilarityScore', 0)) if jailbreak.get('jailbreakSimilarityScore') else None,
            
            # Toxicity
            'toxicity_status': toxicity.get('result'),
            'toxicity_score': toxicity_scores.get('toxicity_score'),
            'severe_toxicity_score': toxicity_scores.get('severe_toxicity_score'),
            'obscene_score': toxicity_scores.get('obscene_score'),
            'threat_score': toxicity_scores.get('threat_score'),
            'insult_score': toxicity_scores.get('insult_score'),
            'identity_attack_score': toxicity_scores.get('identity_attack_score'),
            'sexual_explicit_score': toxicity_scores.get('sexual_explicit_score'),
            
            # Profanity
            'profanity_status': profanity.get('result'),
            'profane_words_found': profanity.get('profaneWordsIdentified', []),
            
            # PII Detection and Blocking
            'pii_status': privacy.get('result'),
            'pii_entities_detected': pii_entities_detected,
            'pii_entities_blocked': pii_entities_blocked,
            
            # Prompt Injection
            'prompt_injection_status': prompt_injection.get('result'),
            'prompt_injection_score': float(prompt_injection.get('injectionConfidenceScore', 0)) if prompt_injection.get('injectionConfidenceScore') else None,
            
            # Restricted Topic
            'restricted_topic_status': restricted_topic.get('result'),
            'restricted_topics_detected': json.dumps(restricted_topic.get('topicScores', [])) if restricted_topic.get('topicScores') else None,
            
            # Refusal
            'refusal_status': refusal.get('result'),
            'refusal_score': float(refusal.get('refusalSimilarityScore', 0)) if refusal.get('refusalSimilarityScore') else None,
            
            # Custom Theme
            'custom_theme_status': custom_theme.get('result'),
            'custom_theme_score': float(custom_theme.get('customSimilarityScore', 0)) if custom_theme.get('customSimilarityScore') else None,
        }
    
    async def save_moderation_log(
        self,
        check_type: str,
        content: str,
        moderation_result: Dict[str, Any]
    ) -> Optional[int]:
        """
        Save a moderation log entry to the database
        
        Args:
            check_type: Type of check ('pre-call' or 'post-call')
            content: The content that was moderated
            moderation_result: Full moderation result from RAI API
            
        Returns:
            The ID of the inserted record, or None if failed
        """
        try:
            extracted_data = self._extract_moderation_data(moderation_result)
            
            query = """
                INSERT INTO rai_moderation_logs (
                    timestamp, check_type, content, overall_status,
                    jailbreak_status, jailbreak_score,
                    toxicity_status, toxicity_score, severe_toxicity_score,
                    obscene_score, threat_score, insult_score,
                    identity_attack_score, sexual_explicit_score,
                    profanity_status, profane_words_found,
                    pii_status, pii_entities_detected, pii_entities_blocked,
                    prompt_injection_status, prompt_injection_score,
                    restricted_topic_status, restricted_topics_detected,
                    refusal_status, refusal_score,
                    custom_theme_status, custom_theme_score,
                    full_response
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
                    $21, $22, $23, $24, $25, $26, $27, $28
                ) RETURNING id
            """
            
            async with self.get_connection() as conn:
                record_id = await conn.fetchval(
                    query,
                    datetime.utcnow(),
                    check_type,
                    content,
                    extracted_data['overall_status'],
                    extracted_data['jailbreak_status'],
                    extracted_data['jailbreak_score'],
                    extracted_data['toxicity_status'],
                    extracted_data['toxicity_score'],
                    extracted_data['severe_toxicity_score'],
                    extracted_data['obscene_score'],
                    extracted_data['threat_score'],
                    extracted_data['insult_score'],
                    extracted_data['identity_attack_score'],
                    extracted_data['sexual_explicit_score'],
                    extracted_data['profanity_status'],
                    extracted_data['profane_words_found'],
                    extracted_data['pii_status'],
                    extracted_data['pii_entities_detected'],
                    extracted_data['pii_entities_blocked'],
                    extracted_data['prompt_injection_status'],
                    extracted_data['prompt_injection_score'],
                    extracted_data['restricted_topic_status'],
                    extracted_data['restricted_topics_detected'],
                    extracted_data['refusal_status'],
                    extracted_data['refusal_score'],
                    extracted_data['custom_theme_status'],
                    extracted_data['custom_theme_score'],
                    json.dumps(moderation_result)
                )
                
                logger.info(f"Saved moderation log with ID: {record_id}")
                return record_id
                
        except Exception as e:
            logger.error(f"Failed to save moderation log: {e}")
            return None
    
    async def ensure_table_exists(self):
        """Ensure the rai_moderation_logs table exists"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS rai_moderation_logs (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
            check_type VARCHAR(30) NOT NULL,
            content TEXT NOT NULL,
            overall_status VARCHAR(20) NOT NULL,
            jailbreak_status VARCHAR(20),
            jailbreak_score NUMERIC(5, 4),
            toxicity_status VARCHAR(20),
            toxicity_score NUMERIC(5, 4),
            severe_toxicity_score NUMERIC(5, 4),
            obscene_score NUMERIC(5, 4),
            threat_score NUMERIC(5, 4),
            insult_score NUMERIC(5, 4),
            identity_attack_score NUMERIC(5, 4),
            sexual_explicit_score NUMERIC(5, 4),
            profanity_status VARCHAR(20),
            profane_words_found TEXT[],
            pii_status VARCHAR(20),
            pii_entities_detected TEXT[],
            pii_entities_blocked TEXT[],
            prompt_injection_status VARCHAR(20),
            prompt_injection_score NUMERIC(5, 4),
            restricted_topic_status VARCHAR(20),
            restricted_topics_detected JSONB,
            refusal_status VARCHAR(20),
            refusal_score NUMERIC(5, 4),
            custom_theme_status VARCHAR(20),
            custom_theme_score NUMERIC(5, 4),
            full_response JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_moderation_timestamp ON rai_moderation_logs(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_moderation_check_type ON rai_moderation_logs(check_type);
        CREATE INDEX IF NOT EXISTS idx_moderation_overall_status ON rai_moderation_logs(overall_status);
        CREATE INDEX IF NOT EXISTS idx_moderation_created_at ON rai_moderation_logs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_moderation_full_response_gin ON rai_moderation_logs USING GIN (full_response);
        CREATE INDEX IF NOT EXISTS idx_restricted_topics_gin ON rai_moderation_logs USING GIN (restricted_topics_detected);
        """
        
        try:
            async with self.get_connection() as conn:
                await conn.execute(create_table_sql)
                logger.info("Ensured rai_moderation_logs table exists")
        except Exception as e:
            logger.error(f"Failed to create table: {e}")
            raise


# Global instance
_db_service: Optional[ModerationDatabaseService] = None


def get_moderation_db_service() -> ModerationDatabaseService:
    """Get or create the global database service instance"""
    global _db_service
    if _db_service is None:
        _db_service = ModerationDatabaseService()
    return _db_service
