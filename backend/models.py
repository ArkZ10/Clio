from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class Paper(BaseModel):
    id: Optional[int] = None
    title: str
    abstract: Optional[str] = None
    source: str
    authors: Optional[str] = None
    year: Optional[int] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
