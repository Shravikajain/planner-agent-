from typing import Dict, Any, Optional, List
import json
from datetime import datetime
from langchain_openai import AzureChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema.output_parser import StrOutputParser
from core.mongodb import MongoDB
import logging
import asyncio
from langchain_core.runnables import RunnablePassthrough
import os
from openai import RateLimitError, APIError
import tenacity

logger = logging.getLogger(__name__)

class PlannerAgent:
    def __init__(self):
        """Initialize the PlannerAgent with Azure OpenAI configuration."""
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        endpoint = os.getenv("AZURE_API_ENDPOINT")
        deployment = os.getenv("AZURE_DEPLOYMENT_NAME")

        if not all([api_key, endpoint, deployment]):
            raise ValueError("Missing required Azure OpenAI configuration. Check AZURE_OPENAI_API_KEY, AZURE_API_ENDPOINT, and AZURE_DEPLOYMENT_NAME environment variables.")

        # Configure Azure OpenAI with correct deployment name
        try:
            self.llm = AzureChatOpenAI(
                azure_endpoint=endpoint,
                openai_api_version="2023-05-15",  # Using stable API version
                deployment_name=deployment,     # Using deployment name from environment
                openai_api_key=api_key,
                temperature=0.7,
                max_tokens=2000
            )
        except Exception as e:
            logger.error(f"Failed to initialize Azure OpenAI: {str(e)}")
            available_models = "gpt-35-turbo, gpt-35-turbo-16k, gpt-4-32k"  # Common Azure OpenAI deployments
            raise ValueError(f"Failed to initialize Azure OpenAI. Please check if the deployment '{deployment}' exists. Common deployment names are: {available_models}")
        self.output_parser = StrOutputParser()

    async def generate_project_plan(self, project_details: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a detailed project plan."""
        try:
            # Extract project details with defaults
            context = {
                "title": project_details.get("title", "Untitled Project"),
                "description": project_details.get("description", ""),
                "status": project_details.get("status", "planning"),
                "team_size": len(project_details.get("team", [])),
                "progress": project_details.get("progress", 0),
                "tags": ", ".join(project_details.get("tags", [])),
                "deadline": project_details.get("deadline", "Not specified")
            }
            
            # Create the prompt template
            prompt_template = """You are a project planning AI assistant. You MUST respond with ONLY valid JSON - no other text before or after.

Project Details:
Title: {title}
Description: {description}
Status: {status}
Team Size: {team_size} members
Current Progress: {progress}%
Tags: {tags}
Deadline: {deadline}

Generate a project plan in this EXACT JSON structure:
{{
    "project_summary": "<detailed overview>",
    "key_features_deliverables": [
        "<feature 1>",
        "<feature 2>",
        "<feature 3>"
    ],
    "major_milestones": [
        {{
            "name": "<milestone name>",
            "timeline": "<timeline>"
        }}
    ],
    "high_level_tasks": [
        {{
            "task_name": "<task name>",
            "description": "<description>",
            "dependencies": [],
            "estimated_duration": "<duration>"
        }}
    ]
}}

IMPORTANT:
1. Respond ONLY with valid JSON
2. Include 3-5 key features
3. Include 4-6 milestones
4. Include 5-8 tasks
5. NO placeholders - use real content based on the project details
6. NO text before or after the JSON
7. Ensure all JSON syntax is valid
"""
            
            plan_prompt = ChatPromptTemplate.from_template(prompt_template)

            # Create and execute the chain
            chain = plan_prompt | self.llm | self.output_parser
            
            logger.info("Generating project plan...")
            try:
                @tenacity.retry(
                    stop=tenacity.stop_after_attempt(3),
                    wait=tenacity.wait_exponential(multiplier=1, min=4, max=60),
                    retry=tenacity.retry_if_exception_type((RateLimitError, APIError))
                )
                async def call_with_retry():
                    logger.info("Making API call to Azure OpenAI...")
                    result = await chain.ainvoke(context)
                    logger.info(f"Raw response from API: {result}")
                    return result
                
                response = await call_with_retry()
                logger.info(f"Response type: {type(response)}")
                logger.info(f"Response content: {response}")
                
                # Parse and validate the response
                try:
                    if not response or not isinstance(response, str):
                        raise ValueError(f"Invalid response format. Expected string, got {type(response)}")
                    
                    # Attempt to clean the response if it's not pure JSON
                    cleaned_response = response.strip()
                    if not cleaned_response.startswith('{'):
                        # Try to find the first '{' and last '}'
                        start = cleaned_response.find('{')
                        end = cleaned_response.rfind('}')
                        if start != -1 and end != -1:
                            cleaned_response = cleaned_response[start:end+1]
                    
                    plan_json = json.loads(cleaned_response)
                    logger.info("Successfully parsed JSON response")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response: {e}")
                    logger.error(f"Invalid JSON response: {response}")
                    raise ValueError(f"Invalid JSON response from LLM: {e}")

                # Validate required fields
                required_fields = [
                    "project_summary",
                    "key_features_deliverables",
                    "major_milestones",
                    "high_level_tasks"
                ]
                
                missing_fields = [field for field in required_fields if field not in plan_json]
                if missing_fields:
                    raise ValueError(f"Missing required fields in plan: {', '.join(missing_fields)}")

                # Store the plan in MongoDB
                project_id = str(project_details["_id"]) if isinstance(project_details, dict) else str(project_details)
                await MongoDB.store_project_plan(project_id, plan_json)
                
                logger.info(f"Successfully generated and stored plan for project {project_id}")
                return plan_json

            except Exception as e:
                logger.error(f"Error in plan generation: {str(e)}")
                return {
                    "error": str(e),
                    "message": "Failed to generate project plan."
                }
                
        except Exception as e:
            logger.error(f"Error in plan generation setup: {str(e)}")
            return {
                "error": str(e),
                "message": "Failed to set up project plan generation."
            }

    async def refine_project_tasks(self, project_id: str, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Refine high-level tasks into detailed subtasks."""
        try:
            # First check if project plan exists
            project_plan = await MongoDB.db.project_plans.find_one({"project_id": project_id})
            if not project_plan:
                logger.warning(f"No existing plan found for project {project_id}. Creating new plan.")
                project_plan = {
                    "project_id": project_id,
                    "high_level_tasks": tasks,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
            
            tasks_str = json.dumps(tasks, indent=2)

            refine_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a technical project management AI specializing in task breakdown and estimation.
                Your output must be VALID JSON ONLY with no additional text."""),
                ("user", """Given these high-level tasks:
                
                {tasks}

                Break them down into subtasks following these rules:
                1. Create 2-4 subtasks for each high-level task
                2. Each subtask must have:
                   - Descriptive name
                   - Detailed description
                   - Effort estimate in story points or days
                   - Specific technical requirements
                3. Preserve the original task information
                4. Return ONLY valid JSON array

                Return your response in this EXACT JSON structure:
                [
                    {{
                        "task_name": "name from original task",
                        "description": "description from original task",
                        "dependencies": ["dependencies from original task"],
                        "subtasks": [
                            {{
                                "name": "specific subtask name",
                                "description": "detailed subtask description",
                                "effort": "effort estimate",
                                "technical_requirements": ["specific requirement 1", "specific requirement 2"]
                            }}
                        ]
                    }}
                ]
                """)
            ])

            # Create the chain using the new LangChain syntax
            chain = refine_prompt | self.llm | self.output_parser

            # Execute the chain with retry logic
            @tenacity.retry(
                stop=tenacity.stop_after_attempt(3),
                wait=tenacity.wait_exponential(multiplier=1, min=4, max=60),
                retry=tenacity.retry_if_exception_type((RateLimitError, APIError))
            )
            async def call_with_retry():
                return await chain.ainvoke({"tasks": tasks_str})

            logger.info(f"Sending tasks to refine: {tasks_str}")
            response = await call_with_retry()
            logger.info(f"Received response: {response}")
            
            try:
                # Clean the response if needed
                response = response.strip()
                if not response.startswith('['):
                    start = response.find('[')
                    end = response.rfind(']')
                    if start != -1 and end != -1:
                        response = response[start:end+1]
                        
                logger.info(f"Cleaned response: {response}")
                refined_tasks = json.loads(response)
                
                # Update the project plan with refined tasks
                project_plan["high_level_tasks"] = refined_tasks
                project_plan["updated_at"] = datetime.utcnow()
                
                # Store the updated plan
                await MongoDB.db.project_plans.update_one(
                    {"project_id": project_id},
                    {"$set": project_plan},
                    upsert=True
                )
                
                return {
                    "project_id": project_id,
                    "refined_tasks": refined_tasks,
                    "original_tasks": tasks
                }

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse refined tasks JSON: {e}")
                raise ValueError(f"Invalid JSON response for refined tasks: {e}")

        except Exception as e:
            logger.error(f"Error refining project tasks: {e}")
            return {
                "error": str(e),
                "message": "Failed to refine project tasks."
            }

    async def _store_project_plan(self, project_id: str, plan: Dict[str, Any]) -> None:
        """Store the project plan in MongoDB."""
        try:
            # Add the project_id to the plan document
            plan_with_id = {
                "project_id": project_id,
                **plan
            }
            await MongoDB.db.project_plans.update_one(
                {"project_id": project_id},
                {"$set": plan_with_id},
                upsert=True
            )
            logger.info(f"Stored project plan for project ID: {project_id}")
        except Exception as e:
            logger.error(f"Error storing project plan: {e}")
            raise

    async def _update_project_plan(self, project_id: str, plan: Dict[str, Any]) -> None:
        """Update the project plan in MongoDB."""
        try:
            # Add the project_id to the plan document
            plan_with_id = {
                "project_id": project_id,
                **plan
            }
            result = await MongoDB.db.project_plans.update_one(
                {"project_id": project_id},
                {"$set": plan_with_id}
            )
            if result.modified_count == 0 and result.matched_count == 0:
                logger.error(f"No project plan found with ID: {project_id}")
                raise ValueError(f"Project plan not found with ID: {project_id}")
            logger.info(f"Updated project plan for project ID: {project_id}")
        except Exception as e:
            logger.error(f"Error updating project plan: {e}")
            raise
