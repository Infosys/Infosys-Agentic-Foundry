# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from motor.motor_asyncio import AsyncIOMotorClient
 
class MultiDBConnectionManager:
    def __init__(self):
        self.sql_engines = {}
        self.sql_sessions = {}
        self.mongo_clients = {}
        self.mongo_databases = {}

    # SQL management
    def add_sql_database(self, db_key, db_url, pool_size=20, max_overflow=10):
        if db_key in self.sql_engines:
            return  # already exists
        engine = create_engine(db_url, pool_size=pool_size, max_overflow=max_overflow, echo=False, future=True)
        Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        self.sql_engines[db_key] = engine
        self.sql_sessions[db_key] = Session
        print(f"[SQL] Initialized engine for '{db_key}'")

    def get_sql_session(self, db_key):
        if db_key not in self.sql_sessions:
            raise Exception(f"No SQL session found for key '{db_key}'")
        return self.sql_sessions[db_key]()

    def dispose_sql_engine(self, db_key):
        # if db_key in self.sql_engines:
        #     self.sql_engines[db_key].dispose()
        #     print(f"[SQL] Disposed engine for '{db_key}'")
        if db_key in self.sql_sessions:
            session = self.sql_sessions[db_key]()
            session.close()
            del self.sql_sessions[db_key]

        if db_key in self.sql_engines:
            self.sql_engines[db_key].dispose()
            del self.sql_engines[db_key]
            print(f"[SQL] Disposed engine for '{db_key}'")

    # MongoDB management
    def add_mongo_database(self, db_key, uri, db_name, max_pool_size=30):
        if db_key in self.mongo_clients:
            return  # already exists
        client = AsyncIOMotorClient(uri, maxPoolSize=max_pool_size)
        self.mongo_clients[db_key] = client
        self.mongo_databases[db_key] = client[db_name]
        print(f"[MongoDB] Initialized client for '{db_key}'")

    def get_mongo_database(self, db_key):
        if db_key not in self.mongo_databases:
            raise Exception(f"No MongoDB database found for key '{db_key}'")
        return self.mongo_databases[db_key]

    async def close_mongo_client(self, db_key):
        if db_key in self.mongo_clients:
            self.mongo_clients[db_key].close()
            print(f"[MongoDB] Closed client for '{db_key}'")

    async def close_all(self):
        for key, engine in self.sql_engines.items():
            engine.dispose()
            print(f"[SQL] Disposed engine for '{key}'")
        for key, client in self.mongo_clients.items():
            client.close()
            print(f"[MongoDB] Closed client for '{key}'")


# ✅ Singleton instance
_connection_manager = MultiDBConnectionManager()

def get_connection_manager():
    return _connection_manager
