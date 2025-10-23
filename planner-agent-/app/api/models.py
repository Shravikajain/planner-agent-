from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from bson import ObjectId

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

class Resource(BaseModel):
    profile: str
    skills: List[str]
    experience: str
    description: str
    type: str
    avatar: Optional[str] = None
    username: Optional[str] = None
    name: Optional[str] = None
    user: Optional[str] = None

class Sprint(BaseModel):
    name: str
    progress: float
    status: str

class TimelineEvent(BaseModel):
    title: str
    description: str
    type: str
    date: datetime

class TeamMember(BaseModel):
    name: str
    avatar: str

class ProjectCreate(BaseModel):
    title: str
    description: str
    deadline: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)
    document: str
    status: str = Field(default="planning")
    tasks: List[str] = Field(default_factory=list)
    progress: float = Field(default=0)
    team: List[TeamMember] = Field(default_factory=list)
    sprints: List[Sprint] = Field(default_factory=list)
    timeline: List[TimelineEvent] = Field(default_factory=list)
    resources: List[Resource] = Field(default_factory=list)
    user: str = Field(description="User identifier - can be ObjectId or string")

class ProjectResponse(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    title: str
    description: str
    deadline: Optional[datetime] = None
    tags: List[str]
    document: str
    status: str
    tasks: List[str]
    progress: float
    team: List[TeamMember]
    sprints: List[Sprint]
    timeline: List[TimelineEvent]
    resources: List[Resource]
    user: str
    created_at: datetime
    updated_at: datetime

    class Config:
       validate_by_name = True  # <-- RENAMED
       json_encoders = {ObjectId: str}

class Milestone(BaseModel):
    name: str
    timeline: str

class Task(BaseModel):
    task_name: str
    description: str
    dependencies: List[str]

class SubTask(BaseModel):
    name: str
    description: str
    effort: str
    technical_requirements: List[str]

class RefinedTask(Task):
    subtasks: List[SubTask]

class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[datetime] = None
    tags: Optional[List[str]] = None
    document: Optional[str] = None
    status: Optional[str] = None
    tasks: Optional[List[str]] = None
    progress: Optional[float] = None
    team: Optional[List[TeamMember]] = None
    sprints: Optional[List[Sprint]] = None
    timeline: Optional[List[TimelineEvent]] = None
    resources: Optional[List[Resource]] = None
    class Config:
        # Allow extra fields to be ignored
        extra = "ignore"
