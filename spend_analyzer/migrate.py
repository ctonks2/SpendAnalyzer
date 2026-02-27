"""Migration helper: migrate JSON data to SQLite DB using SQLAlchemy"""
import os
import json
from datetime import datetime
from .db import get_engine, get_session, Base, reset_db
from .models import User, Location, Receipt, LineItem, UserHistory, Recommendation


def init_db(db_url="sqlite:///spend_data.db"):
    """Initialize the database and create all tables"""
    reset_db()  # Clear any cached engine/session
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)


def migrate_from_json(db_url="sqlite:///spend_data.db"):
    """
    Migrate all JSON data to SQLite database.
    
    Reads from:
    - data/normalized/users/*.json (transaction data)
    - data/normalized/usersHistory/*_uploads.json (upload history)
    - reports/*_Recommendations.json (saved recommendations)
    
    Returns counts of created records.
    """
    init_db(db_url)
    session = get_session(db_url)
    
    base_dir = os.getcwd()
    users_dir = os.path.join(base_dir, "data", "normalized", "users")
    history_dir = os.path.join(base_dir, "data", "normalized", "usersHistory")
    reports_dir = os.path.join(base_dir, "reports")
    
    counts = {
        "users": 0,
        "locations": 0,
        "receipts": 0,
        "line_items": 0,
        "upload_history": 0,
        "recommendations": 0
    }
    
    # Cache for locations (key: "store_number|source")
    location_cache = {}
    
    # Cache for receipts (key: "user_id|orderno")
    receipt_cache = {}
    
    # Process each user's JSON data file
    if os.path.exists(users_dir):
        for filename in os.listdir(users_dir):
            if not filename.endswith(".json"):
                continue
            
            username = filename.replace(".json", "")
            filepath = os.path.join(users_dir, filename)
            
            print(f"Processing user: {username}")
            
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    transactions = json.load(f)
            except Exception as e:
                print(f"  Error reading {filename}: {e}")
                continue
            
            if not isinstance(transactions, list):
                print(f"  Skipping {filename} - not a list")
                continue
            
            # Get or create user
            user = session.query(User).filter_by(username=username).first()
            if not user:
                user = User(username=username)
                user.set_password(username)  # Default password same as username (hashed)
                session.add(user)
                session.flush()  # Get the user ID
                counts["users"] += 1
                print(f"  Created user: {username}")
            
            # Group transactions by receipt (orderno or date+store combination)
            receipt_groups = {}
            
            for tx in transactions:
                if not isinstance(tx, dict):
                    continue
                
                # Skip RECEIPT_TOTAL items - they're already aggregated from line items
                if tx.get("item_name") == "RECEIPT_TOTAL":
                    continue
                
                store_number = str(tx.get("store") or "unknown")
                source = tx.get("source") or "Unknown"
                date_str = tx.get("date")
                orderno = tx.get("orderno")
                
                # Create location key
                loc_key = f"{store_number}|{source}"
                
                # Get or create location
                if loc_key not in location_cache:
                    location = session.query(Location).filter_by(
                        store_number=store_number,
                        store_name=source
                    ).first()
                    
                    if not location:
                        location = Location(
                            store_number=store_number,
                            store_name=source
                        )
                        session.add(location)
                        session.flush()
                        counts["locations"] += 1
                    
                    location_cache[loc_key] = location
                
                location = location_cache[loc_key]
                
                # Create receipt key (orderno if available, else date+store)
                if orderno:
                    receipt_key = f"{user.id}|{orderno}"
                else:
                    receipt_key = f"{user.id}|{date_str}|{store_number}"
                
                if receipt_key not in receipt_groups:
                    receipt_groups[receipt_key] = {
                        "location": location,
                        "date": date_str,
                        "orderno": orderno,
                        "items": []
                    }
                
                receipt_groups[receipt_key]["items"].append(tx)
            
            # Create receipts and line items
            for receipt_key, group in receipt_groups.items():
                # Check if receipt already exists
                if receipt_key in receipt_cache:
                    receipt = receipt_cache[receipt_key]
                else:
                    # Parse date
                    receipt_date = None
                    if group["date"]:
                        try:
                            receipt_date = datetime.strptime(str(group["date"])[:10], "%Y-%m-%d").date()
                        except:
                            try:
                                receipt_date = datetime.strptime(str(group["date"]), "%m/%d/%Y").date()
                            except:
                                pass
                    
                    # Calculate total from line items
                    total = 0.0
                    for item in group["items"]:
                        try:
                            total += float(item.get("total_price") or 0)
                        except:
                            pass
                    
                    receipt = Receipt(
                        user_id=user.id,
                        location_id=group["location"].id,
                        date=receipt_date,
                        order_number=group["orderno"],
                        total_amount=round(total, 2)
                    )
                    session.add(receipt)
                    session.flush()
                    counts["receipts"] += 1
                    receipt_cache[receipt_key] = receipt
                
                # Create line items
                for item in group["items"]:
                    line_item = LineItem(
                        receipt_id=receipt.id,
                        item_name=item.get("item_name") or "Unknown Item",
                        product_upc=str(item.get("product_upc")) if item.get("product_upc") else None,
                        quantity=float(item.get("quantity") or 1),
                        unit_price=float(item.get("unit_price")) if item.get("unit_price") else None,
                        total_price=float(item.get("total_price") or 0),
                        category=item.get("category")
                    )
                    session.add(line_item)
                    counts["line_items"] += 1
            
            # Process upload history
            history_file = os.path.join(history_dir, f"{username}_uploads.json")
            if os.path.exists(history_file):
                try:
                    with open(history_file, "r", encoding="utf-8") as f:
                        uploads = json.load(f)
                    
                    if isinstance(uploads, list):
                        for filename in uploads:
                            # Check if already exists
                            exists = session.query(UserHistory).filter_by(
                                user_id=user.id,
                                filename=filename
                            ).first()
                            
                            if not exists:
                                history = UserHistory(
                                    user_id=user.id,
                                    filename=filename
                                )
                                session.add(history)
                                counts["upload_history"] += 1
                except Exception as e:
                    print(f"  Error reading upload history: {e}")
            
            # Process recommendations
            rec_file = os.path.join(reports_dir, f"{username}_Recommendations.json")
            if os.path.exists(rec_file):
                try:
                    with open(rec_file, "r", encoding="utf-8") as f:
                        recs = json.load(f)
                    
                    if isinstance(recs, list):
                        for rec in recs:
                            if not isinstance(rec, dict):
                                continue
                            
                            saved_at = None
                            if rec.get("saved_at"):
                                try:
                                    saved_at = datetime.fromisoformat(rec["saved_at"])
                                except:
                                    pass
                            
                            recommendation = Recommendation(
                                user_id=user.id,
                                category=rec.get("category") or "Other",
                                question=rec.get("question") or "",
                                response=rec.get("response") or "",
                                saved_at=saved_at or datetime.utcnow()
                            )
                            session.add(recommendation)
                            counts["recommendations"] += 1
                except Exception as e:
                    print(f"  Error reading recommendations: {e}")
            
            # Commit after each user to avoid huge transactions
            session.commit()
            print(f"  Processed {len(transactions)} transactions")
    
    session.close()
    return counts


def get_user_transactions(session, user_id):
    """
    Get all transactions for a user in the old JSON format.
    This allows existing code to work with the new database.
    """
    user = session.query(User).filter_by(id=user_id).first()
    if not user:
        return []
    
    transactions = []
    
    for receipt in user.receipts:
        for item in receipt.line_items:
            tx = {
                "transaction_id": f"tx_{item.id}",
                "user_id": user.username,
                "date": receipt.date.isoformat() if receipt.date else None,
                "store": receipt.location.store_number,
                "item_name": item.item_name,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total_price": item.total_price,
                "category": item.category,
                "orderno": receipt.order_number,
                "product_upc": item.product_upc,
                "source": receipt.location.store_name
            }
            transactions.append(tx)
    
    return transactions


def get_user_transactions_by_username(session, username):
    """Get all transactions for a user by username"""
    user = session.query(User).filter_by(username=username).first()
    if not user:
        return []
    return get_user_transactions(session, user.id)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate JSON data to SQLite DB")
    parser.add_argument("--db", default="sqlite:///spend_analyzer.db", help="DB URL (default sqlite:///spend_analyzer.db)")
    args = parser.parse_args()

    print(f"Migrating JSON data to {args.db}")
    counts = migrate_from_json(db_url=args.db)
    print("\nMigration complete!")
    print("Created records:")
    for key, count in counts.items():
        print(f"  {key}: {count}")