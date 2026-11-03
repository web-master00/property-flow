from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import logging
from asyncio import Lock
from ..config import settings

logger = logging.getLogger(__name__)

class DatabasePool:
    def __init__(self):
        self.engine = None
        self.session_factory = None
        self._initialize_lock = Lock()
        
    async def initialize(self):
        """Initialize the async pool once, safely under concurrent requests."""
        if self.session_factory is not None:
            return

        async with self._initialize_lock:
            if self.session_factory is not None:
                return

            raw_database_url = settings.database_url
            if raw_database_url.startswith(("postgresql://", "postgres://")):
                _, remainder = raw_database_url.split("://", 1)
                database_url = f"postgresql+asyncpg://{remainder}"
            else:
                database_url = raw_database_url

            try:
                engine = create_async_engine(
                    database_url,
                    pool_size=settings.database_pool_size,
                    max_overflow=settings.database_max_overflow,
                    pool_timeout=settings.database_pool_timeout,
                    pool_recycle=settings.database_pool_recycle,
                    pool_pre_ping=True,
                    echo=False,
                )
                self.engine = engine
                self.session_factory = async_sessionmaker(
                    bind=engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                )
                logger.info("Database connection pool initialized")
            except Exception:
                self.engine = None
                self.session_factory = None
                logger.exception("Database pool initialization failed")
                raise

    async def close(self):
        """Close database connections"""
        if self.engine:
            await self.engine.dispose()
        self.engine = None
        self.session_factory = None
    
    def get_session(self) -> AsyncSession:
        """Get database session from pool"""
        if not self.session_factory:
            raise RuntimeError("Database pool not initialized")
        return self.session_factory()

# Global database pool instance
db_pool = DatabasePool()

async def get_db_session() -> AsyncSession:
    """Dependency to get database session"""
    async with db_pool.get_session() as session:
        yield session
