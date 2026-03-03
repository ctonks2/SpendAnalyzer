from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey, Float, DateTime, Boolean
from sqlalchemy.orm import relationship
from werkzeug.security import generate_password_hash, check_password_hash
from .db import Base
from datetime import datetime


class User(Base):
    """User account for authentication and personalization"""
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)  # Hashed password
    theme = Column(String(50), default='default')
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)

    # Relationships
    receipts = relationship("Receipt", back_populates="user", cascade="all, delete-orphan")
    upload_history = relationship("UserHistory", back_populates="user", cascade="all, delete-orphan")
    recommendations = relationship("Recommendation", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password):
        """Hash and store the password"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify password against stored hash"""
        return check_password_hash(self.password_hash, password)


class Location(Base):
    """Store/Location information"""
    __tablename__ = "locations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    store_number = Column(String(50), nullable=False)
    store_name = Column(String(100), nullable=False)
    address = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    receipts = relationship("Receipt", back_populates="location")

    def __repr__(self):
        return f"<Location {self.store_name} #{self.store_number}>"


class Receipt(Base):
    """Receipt - aggregated details of items purchased at the same time"""
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    date = Column(Date, nullable=False)
    order_number = Column(String(100))  # orderno from data
    total_amount = Column(Float, default=0.0)
    currency = Column(String(10), default="USD")
    is_active = Column(Boolean, default=True)  # For soft deletes
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="receipts")
    location = relationship("Location", back_populates="receipts")
    line_items = relationship("LineItem", back_populates="receipt", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Receipt {self.id} - {self.date} at {self.location_id}>"


class LineItem(Base):
    """Individual items purchased - FK to Receipt"""
    __tablename__ = "line_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id"), nullable=False)
    item_name = Column(String(255), nullable=False)
    product_upc = Column(String(50))
    quantity = Column(Float, default=1.0)
    unit_price = Column(Float)
    total_price = Column(Float, nullable=False)
    category = Column(String(100))
    is_active = Column(Boolean, default=True)  # For soft deletes
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    receipt = relationship("Receipt", back_populates="line_items")

    def __repr__(self):
        return f"<LineItem {self.item_name} ${self.total_price}>"


class UserHistory(Base):
    """Tracks files already uploaded by users"""
    __tablename__ = "user_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="upload_history")

    def __repr__(self):
        return f"<UserHistory {self.filename}>"


class Recommendation(Base):
    """Saved LLM recommendations"""
    __tablename__ = "recommendations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(String(100), default="Other")
    question = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    saved_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="recommendations")

    def __repr__(self):
        return f"<Recommendation {self.category}: {self.question[:30]}...>"

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "user_id": self.user.username if self.user else None,
            "category": self.category,
            "question": self.question,
            "response": self.response,
            "date": self.saved_at.strftime("%Y-%m-%d") if self.saved_at else None,
            "saved_at": self.saved_at.isoformat() if self.saved_at else None
        }


class Report(Base):
    """Custom SQL reports"""
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    owner = Column(String(50), nullable=False)
    sql_query = Column(Text, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_run_at = Column(DateTime)
