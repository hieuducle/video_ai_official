from sqlalchemy import create_engine, Column, Integer, String, Boolean, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

import os
import sys

def get_runtime_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(get_runtime_path(), "app_data.db")
engine = create_engine(f'sqlite:///{DB_PATH}', connect_args={'check_same_thread': False})
Base = declarative_base()

class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    project_type = Column(String, default="image") # "image" or "text"
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    scenes = relationship("Scene", back_populates="project", cascade="all, delete-orphan")

class Scene(Base):
    __tablename__ = 'scenes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    order_index = Column(Integer, default=0)
    image_path = Column(String, nullable=False)
    prompt = Column(Text, nullable=True)
    duration = Column(Integer, default=7)
    status = Column(String, default="Pending") # Pending, Processing, Completed, Error
    video_url = Column(String, nullable=True) # Direct URL to FB CDN
    video_path = Column(String, nullable=True) # Local path after download
    remote_task_id = Column(String, nullable=True) # ID on remote server
    error_msg = Column(Text, nullable=True)
    
    project = relationship("Project", back_populates="scenes")

Base.metadata.create_all(engine)

# Auto-migrate: Add project_type column if it doesn't exist
from sqlalchemy import text
try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE projects ADD COLUMN project_type VARCHAR DEFAULT 'image'"))
except Exception as e:
    pass # Column likely already exists

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE scenes ADD COLUMN remote_task_id VARCHAR"))
except Exception as e:
    pass

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE scenes ADD COLUMN duration INTEGER DEFAULT 7"))
except Exception as e:
    pass

SessionLocal = sessionmaker(bind=engine)
