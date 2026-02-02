from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey, BigInteger, DateTime
from sqlalchemy.orm import relationship
from .db import Base
from datetime import datetime


class Store(Base):
    __tablename__ = "stores"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    address = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    receipts = relationship("Receipt", back_populates="store")


class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(String, primary_key=True)
    store_id = Column(String, ForeignKey("stores.id"), nullable=False)
    date = Column(Date)
    total_before_cents = Column(Integer)
    total_after_cents = Column(Integer)
    currency = Column(String, default="USD")
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("Store", back_populates="receipts")
    line_items = relationship("LineItem", back_populates="receipt")


class LineItem(Base):
    __tablename__ = "line_items"
    id = Column(String, primary_key=True)
    receipt_id = Column(String, ForeignKey("receipts.id"), nullable=False)
    product_upc = Column(String)
    description = Column(Text)
    quantity = Column(Integer, default=1)
    unit_price_cents = Column(Integer)
    total_price_cents = Column(Integer)
    category = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    receipt = relationship("Receipt", back_populates="line_items")


class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    owner = Column(String, nullable=False)
    sql_query = Column(Text, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_run_at = Column(DateTime)
