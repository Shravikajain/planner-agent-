from contextlib import asynccontextmanager
from fastapi import FastAPI
from api.routes import router
from core.mongodb import MongoDB
import os
import logging
from dotenv import load_dotenv
import uvicorn
from datetime import datetime


# Configure logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Startup: Connect to MongoDB
        mongo_url = os.getenv("MONGODB_URL")
        db_name = os.getenv("MONGODB_DB_NAME")
        
        if not mongo_url or not db_name:
            raise ValueError("MongoDB URL or database name not configured in environment variables")
            
        logging.info(f"Connecting to database: {db_name}")
        await MongoDB.connect_to_mongo(mongo_url=mongo_url, db_name=db_name)
        logging.info("MongoDB connection established successfully")
        
        yield
    except Exception as e:
        logging.error(f"Failed to connect to MongoDB: {str(e)}")
        raise
    finally:
        # Shutdown: Close MongoDB connection
        await MongoDB.close_mongo_connection()

app = FastAPI(
    title="Project Planner API",
    lifespan=lifespan,
    description="A Project Planning API using OpenAI GPT-5 and MongoDB",
    version="1.0.0"
)

@app.get("/")
async def root():
    """Root endpoint that redirects to API documentation."""
    return {
        "message": "Welcome to Project Planner API",
        "documentation": "/docs",
        "available_endpoints": {
            "Generate Plan": "/api/generate-plan",
            "Refine Tasks": "/api/refine-tasks/{project_id}"
        }
    }

app.include_router(router, prefix="/api")

def main():
    """Run the application with uvicorn server."""
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )

if __name__ == "__main__":
    main()
