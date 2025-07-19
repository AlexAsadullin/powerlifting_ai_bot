import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from database import Base
from aiogram.fsm.state import State, StatesGroup


class Student(Base):
    __tablename__ = 'students'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False)
    username = Column(String, nullable=True)
    name = Column(String, nullable=True)
    remaining_sessions = Column(Integer, default=0)
    payment_requests = relationship("PaymentRequest", back_populates="student")


class Trainer(Base):
    __tablename__ = 'trainers'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False)
    username = Column(String, nullable=True)
    name = Column(String, nullable=True)


class Group(Base):
    __tablename__ = 'groups'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    trainer_id = Column(Integer, ForeignKey('trainers.id'))
    schedule = Column(String, nullable=True)
    program_file = Column(String, nullable=True)
    trainer = relationship("Trainer")
    students = relationship("Student", secondary="group_students")


class GroupStudent(Base):
    __tablename__ = 'group_students'
    group_id = Column(Integer, ForeignKey('groups.id'), primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), primary_key=True)


class Schedule(Base):
    __tablename__ = 'schedules'
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey('groups.id'))
    content = Column(String, nullable=False)
    group = relationship("Group")


class PaymentRequest(Base):
    __tablename__ = 'payment_requests'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'))
    sessions_requested = Column(Integer, nullable=False)
    status = Column(String, default='pending')
    screenshot_file_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now)
    student = relationship("Student", back_populates="payment_requests")


# Добавляем поддержку типа 'nutrition' в модель Progress
class Progress(Base):
    __tablename__ = 'progress'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'))
    type = Column(String, nullable=False)  # 'training', 'photo' or 'nutrition'
    content = Column(String, nullable=True)  # for text messages
    file_path = Column(String, nullable=True)  # for files
    date = Column(DateTime, default=datetime.datetime.now)
    student = relationship("Student")


class KnowledgeBase(Base):
    __tablename__ = 'knowledge_base'
    id = Column(Integer, primary_key=True)
    type = Column(String, nullable=False)
    content = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)


class GroupCreation(StatesGroup):
    waiting_for_name = State()
    waiting_for_schedule = State()
    waiting_for_program_file = State()
    waiting_for_students = State()
