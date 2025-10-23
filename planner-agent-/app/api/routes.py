from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, List
from core.planner import PlannerAgent
from core.mongodb import MongoDB
from api.models import   ProjectCreate , ProjectUpdate
import os
import logging
from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime


logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/projects", response_model=Dict[str, Any])
async def create_project(project: ProjectCreate) -> Dict[str, Any]:
    """Create a new project."""
    try:
        logger.info(f"Creating new project: {project.title}")
        # Convert the Pydantic model to dict
        project_data = project.dict(exclude_unset=True)
        
        # Create the project
        created_project = await MongoDB.create_project(project_data)
        logger.info(f"Successfully created project with ID: {created_project['_id']}")
        return created_project
    except Exception as e:
        logger.error(f"Error creating project: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/projects/{project_id}/description", response_model=Dict[str, Any])
async def get_project_description(project_id: str) -> Dict[str, Any]:
    """Get the description of a specific project by its ID."""
    try:
        # --- FIX: Check if the database is connected ---
        if MongoDB.db is None:
            logger.error("MongoDB connection not initialized")
            raise HTTPException(status_code=500, detail="Database connection not initialized")
        
        # Convert string ID to MongoDB ObjectId
        try:
            obj_id = ObjectId(project_id)
        except InvalidId:
            logger.error(f"Invalid ObjectId format: {project_id}")
            raise HTTPException(status_code=400, detail="Invalid project ID format")

        # Get project from MongoDB
        project = await MongoDB.db.projects.find_one(
            {"_id": obj_id},
            {"description": 1, "title": 1}  # Only retrieve description and title fields
        )

        if not project:
            logger.error(f"Project not found with ID: {project_id}")
            raise HTTPException(status_code=404, detail="Project not found")

        return {
            "id": str(project["_id"]),
            "title": project.get("title", "Untitled Project"),
            "description": project.get("description", "No description available")
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving project description: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/projects", response_model=List[Dict[str, Any]])
async def list_projects():
    """List all projects from the database."""
    try:
        logger.info("Attempting to fetch projects from database")
        if  MongoDB.db is None :
            logger.error("MongoDB connection not initialized")
            raise HTTPException(status_code=500, detail="Database connection not initialized")
        # Fetch all projects from MongoDB
        projects = []
        logger.info("Starting database query...")
        async for project in MongoDB.db.projects.find():
            logger.debug(f"Found project with ID: {project.get('_id')}")
            # Convert ObjectId to string
            project_id = str(project["_id"])
            project["_id"] = project_id
            
            # Check if project has a plan using the ObjectId
            has_plan = await MongoDB.db.project_plans.find_one({
                "project_id": project_id
            }) is not None
            
            # Add plan status to project
            project["has_plan"] = has_plan
            projects.append(project)
        
        logger.info(f"Found {len(projects)} projects in database")
        return projects
    except Exception as e:
        logger.error(f"Error listing projects: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def get_planner_agent() -> PlannerAgent:
    """Dependency to get PlannerAgent instance."""
    try:
        return PlannerAgent()
    except ValueError as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Failed to initialize OpenAI configuration"
        )

@router.get("/projects/{project_id}/plan", response_model=Dict[str, Any])
async def generate_plan_for_existing_project(
    project_id: str,
    planner: PlannerAgent = Depends(get_planner_agent)
) -> Dict[str, Any]:
    """Generate a project plan for an existing project in the database."""
    try:
        if MongoDB.db is None:
            logger.error("MongoDB connection not initialized")
            raise HTTPException(status_code=500, detail="Database connection not initialized")
        # Convert string ID to MongoDB ObjectId
        try:
            obj_id = ObjectId(project_id)
        except InvalidId:
            logger.error(f"Invalid ObjectId format: {project_id}")
            raise HTTPException(status_code=400, detail="Invalid project ID format")

        # Get existing plan if it exists
        existing_plan = await MongoDB.db.project_plans.find_one({"project_id": project_id})
        if existing_plan:
            logger.info(f"Found existing plan for project: {project_id}")
            if "_id" in existing_plan:
                del existing_plan["_id"]
            return existing_plan

        # Get project data if it exists
        project = await MongoDB.db.projects.find_one({"_id": obj_id})
        
        # Create a minimal project context even if no data is found
        project_context = {
            "_id": project_id,
            "title": project.get("title", "Untitled Project"),
            "description": project.get("description", "Project details not available"),
            "status": project.get("status", "planning"),
            "tags": project.get("tags", []),
            "team": project.get("team", []),
            "deadline": project.get("deadline", None),
            "resources": project.get("resources", []),
            "progress": project.get("progress", 0)
        } if project else {
            "_id": project_id,
            "title": "Untitled Project",
            "description": "Project details to be determined",
            "status": "planning",
            "tags": [],
            "team": [],
            "progress": 0
        }

        # Generate new plan using whatever context we have
        plan = await planner.generate_project_plan(project_context)
        
        if "error" in plan:
            logger.error(f"Plan generation error: {plan.get('error')}")
            raise HTTPException(status_code=500, detail=plan.get("message", "Failed to generate plan"))
        
        # Basic validation of plan structure
        if not isinstance(plan, dict):
            raise HTTPException(status_code=500, detail="Invalid plan format generated")
        
        # Ensure minimum plan structure
        plan = {
            "project_summary": plan.get("project_summary", "Project summary to be determined"),
            "key_features_deliverables": plan.get("key_features_deliverables", []),
            "major_milestones": plan.get("major_milestones", []),
            "high_level_tasks": plan.get("high_level_tasks", [])
        }
        
        # Store the plan
        await MongoDB.store_project_plan(project_id, plan)
        logger.info(f"Successfully generated and stored plan for project: {project_id}")
        
        return plan

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating plan for project {project_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/refine-tasks/{project_id}", response_model=Dict[str, Any])
async def refine_project_tasks(
    project_id: str,
    planner: PlannerAgent = Depends(get_planner_agent)
) -> Dict[str, Any]:
    """Refine the tasks in an existing project plan."""
    try:
        logger.info(f"Looking up project plan with ID: {project_id}")
        
        # --- FIX: Check if the database is connected ---
        if MongoDB.db is None:
            logger.error("MongoDB connection not initialized")
            raise HTTPException(status_code=500, detail="Database connection not initialized")
        
        # --- FIX: Validate ObjectId format ---
        try:
            obj_id = ObjectId(project_id)
        except InvalidId:
            logger.error(f"Invalid ObjectId format: {project_id}")
            raise HTTPException(status_code=400, detail="Invalid project ID format")

        # First check if the project exists
        project = await MongoDB.db.projects.find_one({"_id": obj_id})
        if not project:
            raise HTTPException(
                status_code=404,
                detail=f"No project found with ID: {project_id}. Please create a project first."
            )
        
        # Get the existing plan from MongoDB
        existing_plan = await MongoDB.db.project_plans.find_one({"project_id": project_id})
        
        # Get high-level tasks to refine
        if existing_plan and "high_level_tasks" in existing_plan:
            tasks_to_refine = existing_plan["high_level_tasks"]
        else:
            # If no plan exists, create initial tasks from project details
            tasks_to_refine = [
                {
                    "task_name": "Project Setup",
                    "description": f"Initial setup for {project.get('title', 'the project')}",
                    "dependencies": []
                }
            ]
        
        # Refine the tasks
        refined_plan = await planner.refine_project_tasks(project_id, tasks_to_refine)
        
        if "error" in refined_plan:
            logger.error(f"Error refining tasks: {refined_plan.get('message', 'Unknown error')}")
            raise HTTPException(status_code=500, detail=refined_plan.get('message', 'Failed to refine tasks'))
        
        logger.info(f"Successfully refined tasks for project: {project_id}")
        return refined_plan

    except HTTPException:
        # Re-raise HTTPException directly
        raise
    except Exception as e:
        # Log the unexpected error before raising
        logger.error(f"Unexpected error refining tasks for project {project_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/projects/{project_id}", response_model=Dict[str, Any])
async def update_project_details(
    project_id: str,
    update: ProjectUpdate
) -> Dict[str, Any]:
    """Update details of an existing project."""
    try:
        # Get update data, excluding fields that were not set
        update_data = update.dict(exclude_unset=True)

        if not update_data:
            raise HTTPException(status_code=400, detail="No update data provided")

        logger.info(f"Updating project {project_id} with data: {update_data.keys()}")

        updated_project = await MongoDB.update_project(project_id, update_data)

        if not updated_project:
            raise HTTPException(status_code=404, detail="Project not found")

        return updated_project

    except InvalidId:
        logger.error(f"Invalid ObjectId format: {project_id}")
        raise HTTPException(status_code=400, detail="Invalid project ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating project {project_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/projects/{project_id}", response_model=Dict[str, Any])
async def delete_project(project_id: str) -> Dict[str, Any]:
    """Soft delete a project by setting its status to 'deleted'."""
    try:
        logger.info(f"Attempting to soft delete project: {project_id}")

        deleted_project = await MongoDB.soft_delete_project(project_id)

        if not deleted_project:
            raise HTTPException(status_code=404, detail="Project not found")

        logger.info(f"Successfully soft-deleted project: {project_id}")
        return deleted_project

    except InvalidId:
        logger.error(f"Invalid ObjectId format: {project_id}")
        raise HTTPException(status_code=400, detail="Invalid project ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error soft-deleting project {project_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))