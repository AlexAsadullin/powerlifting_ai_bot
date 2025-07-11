from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from aiogram.fsm.state import State, StatesGroup

class Student(Base):
    __tablename__ = 'students'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False)
    username = Column(String, nullable=True)
    name = Column(String, nullable=True)


class Trainer(Base):
    __tablename__ = 'trainers'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False)
    username = Column(String, nullable=True)
    name = Column(String, nullable=True)

# Group model for storing student groups
class Group(Base):
    __tablename__ = 'groups'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    trainer_id = Column(Integer, ForeignKey('trainers.id'))
    trainer = relationship("Trainer")
    students = relationship("Student", secondary="group_students")

# Junction table for group-student relationship
class GroupStudent(Base):
    __tablename__ = 'group_students'
    group_id = Column(Integer, ForeignKey('groups.id'), primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), primary_key=True)

# Schedule model
class Schedule(Base):
    __tablename__ = 'schedules'
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey('groups.id'))
    date = Column(String, nullable=False)
    time = Column(String, nullable=False)
    description = Column(String, nullable=True)
    group = relationship("Group")

# Определяем состояния для создания группы
class GroupCreation(StatesGroup):
    waiting_for_name = State()  # Ожидание названия группы
    waiting_for_students = State()  # Ожидание выбора учеников