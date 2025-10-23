from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from core.mongodb import MongoDB
import os
import logging
from dotenv import load_dotenv
import uvicorn
from datetime import datetime
from pathlib import Path


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

env_path = Path('.') / '../.env' 
load_dotenv(dotenv_path=env_path)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Startup: Connect to MongoDB
        mongo_url = "mongodb+srv://hemang:mShTm7WYx7uZTIr4@cluster01.iwtvtik.mongodb.net/kiyo-aipm"
        db_name = "kiyo-aipm"
        
        if not mongo_url or not db_name:
            raise ValueError("MongoDB URL or database name not configured in environment variables")
            
        logger.info(f"Connecting to database: {db_name}")
        await MongoDB.connect_to_mongo(mongo_url=mongo_url, db_name=db_name)
        logger.info("MongoDB connection established successfully")
        
        yield
        
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {str(e)}")
        raise
    finally:
        # Shutdown: Close MongoDB connection
        logger.info("Shutting down application...")
        await MongoDB.close_mongo_connection()
        logger.info("Application shutdown complete")

app = FastAPI(
    title="Project Planner API",
    lifespan=lifespan,
    description="A Project Planning API using Azure OpenAI and MongoDB with AI-powered project planning capabilities",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware (configure as needed for your frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Root endpoint that provides API information and documentation links."""
    return {
        "message": "Welcome to Project Planner API",
        "version": "1.0.0",
        "documentation": {
            "swagger_ui": "/docs",
            "redoc": "/redoc"
        },
        "available_endpoints": {
            "projects": {
                "create": "POST /api/projects - Create a new project",
                "list": "GET /api/projects - List all projects (use ?include_deleted=true to include deleted)",
                "get_description": "GET /api/projects/{project_id}/description - Get project description",
                "update": "PATCH /api/projects/{project_id} - Update project (partial update supported)",
                "delete": "DELETE /api/projects/{project_id} - Soft delete a project"
            },
            "planning": {
                "generate_plan": "GET /api/projects/{project_id}/plan - Generate AI-powered project plan",
                "refine_tasks": "POST /api/refine-tasks/{project_id} - Refine tasks with AI assistance"
            }
        },
        "features": {
            "ai_powered": "Uses Azure OpenAI for intelligent project planning and task breakdown",
            "soft_delete": "Projects are soft-deleted (marked as deleted, not permanently removed)",
            "partial_updates": "PATCH endpoint supports partial updates - only send fields you want to change",
            "plan_generation": "Automatic project plan generation with milestones, tasks, and deliverables",
            "task_refinement": "Break down high-level tasks into detailed subtasks with effort estimates"
        },
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint to verify API and database connectivity."""
    try:
        # Check MongoDB connection
        # --- FIX: Check .client instead of .db ---
        if MongoDB.client is not None:
            await MongoDB.client.admin.command('ping')
            db_status = "connected"
        else:
            db_status = "disconnected"
        
        return {
            "status": "healthy" if db_status == "connected" else "unhealthy",
            "database": db_status,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "database": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

# Include API routes
app.include_router(router, prefix="/api", tags=["Projects"])

def main():
    """Run the application with uvicorn server."""
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    reload = os.getenv("RELOAD", "true").lower() == "true"
    
    logger.info(f"Starting server on {host}:{port}")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )

if __name__ == "__main__":
    main()