"""
Author: Richard Baldwin
Date:   2024
Email: eyeclept@pm.me

Description: Application configuration for different environments
"""

import os


class Config:
    """
    Input: None
    Output: None
    Details: Base configuration with defaults
    """
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-key-change-in-production')
    
    # Database
    MARIADB_HOST = os.getenv('MARIADB_HOST', 'localhost')
    MARIADB_PORT = os.getenv('MARIADB_PORT', 3306)
    MARIADB_USER = os.getenv('MARIADB_USER', 'shse')
    MARIADB_PASSWORD = os.getenv('MARIADB_PASSWORD', 'password')
    MARIADB_DATABASE = os.getenv('MARIADB_DATABASE', 'shse')
    
    # Elasticsearch
    ES_HOST = os.getenv('ES_HOST', 'localhost')
    ES_PORT = os.getenv('ES_PORT', 9200)
    ES_SCHEME = os.getenv('ES_SCHEME', 'http')
    
    # Redis
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = os.getenv('REDIS_PORT', 6379)
    REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
    
    # Nutch
    NUTCH_HOST = os.getenv('NUTCH_HOST', 'localhost')
    NUTCH_PORT = os.getenv('NUTCH_PORT', 8080)
    
    # Ollama
    OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'localhost')
    OLLAMA_PORT = os.getenv('OLLAMA_PORT', 11434)
    OLLAMA_EMBEDDING_MODEL = os.getenv('OLLAMA_EMBEDDING_MODEL', 'nomic-embed-text')
    OLLAMA_GENERATIVE_MODEL = os.getenv('OLLAMA_GENERATIVE_MODEL', 'llama3')
    
    # Authentication
    SSO_ENABLED = os.getenv('SSO_ENABLED', 'false').lower() == 'true'
    AUTH_LOCAL_ENABLED = os.getenv('AUTH_LOCAL_ENABLED', 'true').lower() == 'true'
    SSO_PROVIDER_URL = os.getenv('SSO_PROVIDER_URL', '')
    SSO_CLIENT_ID = os.getenv('SSO_CLIENT_ID', '')
    SSO_CLIENT_SECRET = os.getenv('SSO_CLIENT_SECRET', '')
    
    # TLS
    INTERNAL_TLS_VERIFY = os.getenv('INTERNAL_TLS_VERIFY', 'false').lower() == 'true'
    
    # Flask
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')


class DevelopmentConfig(Config):
    """
    Input: None
    Output: None
    Details: Development environment configuration
    """
    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    """
    Input: None
    Output: None
    Details: Testing environment configuration
    """
    TESTING = True
    MARIADB_DATABASE = 'shse_test'


class ProductionConfig(Config):
    """
    Input: None
    Output: None
    Details: Production environment configuration
    """
    DEBUG = False
    TESTING = False


def get_config(env='development'):
    """
    Input: env (str) - 'development', 'testing', or 'production'
    Output: Config class
    Details: Returns appropriate config class based on environment
    """
    config_map = {
        'development': DevelopmentConfig,
        'testing': TestingConfig,
        'production': ProductionConfig,
    }
    return config_map.get(env, DevelopmentConfig)
