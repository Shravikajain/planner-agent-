from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional, Dict, Any, List
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import logging
from fastapi import HTTPException
import asyncio
from datetime import datetime
from motor.core import AgnosticDatabase
from bson import ObjectId

logger = logging.getLogger(__name__)

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __get_pydantic_json_schema__(cls, field_schema, **kwargs):
        field_schema.update(type="string")
        return field_schema

class MongoDB:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AgnosticDatabase] = None

    @classmethod
    async def connect_to_mongo(cls, mongo_url: str, db_name: str):
        """Connect to MongoDB."""
        try:
            logger.info(f"Attempting to connect to MongoDB database: {db_name}")
            logger.info(f"Connection URL pattern: {mongo_url.split('@')[-1].split('/')[0]}")

            # Configure client with retries and reasonable timeouts
            cls.client = AsyncIOMotorClient(
                mongo_url,
                serverSelectionTimeoutMS=30000,    # 30 second timeout
                connectTimeoutMS=30000,
                socketTimeoutMS=45000,
                retryWrites=True,
                retryReads=True
            )
            
            # Verify the connection with retries
            for attempt in range(3):
                try:
                    await cls.client.admin.command('ping')
                    cls.db = cls.client[db_name]
                    logger.info("Successfully connected to MongoDB")
                    
                    # Test collections access
                    projects_count = await cls.db.projects.count_documents({})
                    plans_count = await cls.db.project_plans.count_documents({})
                    logger.info(f"Found {projects_count} projects and {plans_count} plans")
                    
                    return
                except Exception as e:
                    if attempt == 2:  # Last attempt
                        raise
                    logger.warning(f"Connection attempt {attempt + 1} failed: {str(e)}. Retrying...")
                    await asyncio.sleep(1)

        except Exception as e:
            error_msg = f"Failed to connect to MongoDB: {str(e)}"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)

    @classmethod
    async def close_mongo_connection(cls):
        """Close MongoDB connection."""
        if cls.client is not None:
            cls.client.close()
            logger.info("MongoDB connection closed")

    @classmethod
    async def get_project(cls, project_id: str) -> Dict[str, Any]:
        """Get a project by ID."""
        try:
            if cls.db is None:
                raise HTTPException(status_code=500, detail="Database connection not initialized")
                
            obj_id = ObjectId(project_id)
            project = await cls.db.projects.find_one({"_id": obj_id})
            if project:
                project["_id"] = str(project["_id"])
                return project
            return None
        except Exception as e:
            logger.error(f"Error fetching project {project_id}: {e}")
            raise

    @classmethod
    async def store_project_plan(cls, project_id: str, plan: Dict[str, Any]) -> bool:
        """Store or update a project plan."""
        try:
            if cls.db is None:
                raise HTTPException(status_code=500, detail="Database connection not initialized")
                
            plan["updated_at"] = datetime.utcnow()
            if "created_at" not in plan:
                plan["created_at"] = plan["updated_at"]

            result = await cls.db.project_plans.update_one(
                {"project_id": project_id},
                {"$set": plan},
                upsert=True
            )
            
            logger.info(f"Successfully stored plan for project {project_id}")
            return True
        except Exception as e:
            logger.error(f"Error storing project plan for {project_id}: {e}")
            raise

    @classmethod
    async def create_project(cls, project_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new project."""
        try:
            if cls.db is None:
                raise HTTPException(status_code=500, detail="Database connection not initialized")

            # Handle tasks conversion if present and valid
            if "tasks" in project_data and project_data["tasks"]:
                try:
                    project_data["tasks"] = [
                        ObjectId(task_id) if ObjectId.is_valid(task_id) else task_id
                        for task_id in project_data["tasks"]
                    ]
                except:
                    # If conversion fails, keep original task IDs
                    pass

            # Handle user ID - keep as string if not a valid ObjectId
            if "user" in project_data:
                try:
                    if ObjectId.is_valid(project_data["user"]):
                        project_data["user"] = ObjectId(project_data["user"])
                except:
                    # If conversion fails, keep original user ID
                    pass

            # Add timestamps
            project_data["created_at"] = datetime.utcnow()
            project_data["updated_at"] = project_data["created_at"]

            # Insert the project
            result = await cls.db.projects.insert_one(project_data)
            
            # Get the created project
            created_project = await cls.db.projects.find_one({"_id": result.inserted_id})
            if created_project:
                created_project["_id"] = str(created_project["_id"])
                
                # Convert ObjectIds back to strings where they exist
                if "user" in created_project and isinstance(created_project["user"], ObjectId):
                    created_project["user"] = str(created_project["user"])
                if "tasks" in created_project:
                    created_project["tasks"] = [
                        str(task_id) if isinstance(task_id, ObjectId) else task_id
                        for task_id in created_project["tasks"]
                    ]
                
                logger.info(f"Successfully created project: {created_project['title']}")
                return created_project
            
            raise HTTPException(status_code=500, detail="Failed to retrieve created project")
        except Exception as e:
            logger.error(f"Error creating project: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @classmethod
    async def close_mongo_connection(cls):
        """Close MongoDB connection."""
        if cls.client is not None:
            cls.client.close()
            logger.info("MongoDB connection closed")

    @classmethod
    async def close_mongo_connection(cls):
        """Close MongoDB connection."""
        if cls.client is not None:
            cls.client.close()
            logger.info("MongoDB connection closed")
