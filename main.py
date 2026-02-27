import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.classifier import classifier
from app.database import Base, SessionLocal, engine
from app.fetcher import FetcherService
from app.routes.articles import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    logger.info("Creating database tables if they don't exist...")
    Base.metadata.create_all(bind=engine)

    logger.info("Starting background RSS fetcher...")
    import asyncio
    fetcher = FetcherService()
    task = asyncio.create_task(fetcher.run(SessionLocal, classifier))

    yield

    # --- Shutdown ---
    logger.info("Shutting down background fetcher...")
    task.cancel()


app = FastAPI(
    title="IT News Classification API",
    description="Aggregates and classifies IT news for IT managers.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)